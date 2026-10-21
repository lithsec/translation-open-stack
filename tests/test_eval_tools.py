#!/usr/bin/env python3
"""eval/tools: the pacer's chunking and timing with a fake adapter, the
corrected per-piece lag (offsets against arrival, on a hand-built event log
with a backlogged voice), the Segmenter simulator against omni-stt's own
source, the pause statistics and the energy dips, on synthetic data.

    python3 tests/test_eval_tools.py      (or python3 -m pytest tests/test_eval_tools.py)

Needs numpy; no network, no websockets, no torch.
"""
import asyncio
import json
import os
import sys
import tempfile
import time
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "eval", "tools"))
import cutsim  # noqa: E402
import dips  # noqa: E402
import lag  # noqa: E402
import pace  # noqa: E402
import pauses  # noqa: E402


# ---------------------------------------------------------------- pace.py

def test_chunks_and_resample():
    pcm = bytes(2 * int(16000 * 1.05))           # 1.05 s of silence
    cs = pace.chunks(pcm)
    assert len(cs) == 11 and all(len(c) == 3200 for c in cs), [len(c) for c in cs]
    tone = (np.sin(np.arange(1600) * 2 * np.pi * 440 / 16000) * 8000).astype("<i2").tobytes()
    up = pace.resample(tone, 16000, 24000)
    assert len(up) == 2400 * 2
    assert pace.resample(tone, 16000, 16000) is tone
    x = np.frombuffer(up, dtype="<i2")
    assert 7000 < np.abs(x).max() <= 8000


def test_voiced_frames():
    assert pace.voiced(bytes(4800), 24000) is None
    x = np.zeros(2400, dtype=np.int16)             # 100 ms at 24 kHz
    x[720:1440] = 3000                              # frames 3, 4, 5 (30-60 ms)
    assert pace.voiced(x.tobytes(), 24000) == (30, 60)


def test_pacer_timing_fake_clock():
    now = [0.0]
    sent = []

    async def sleep(s):
        now[0] += s

    async def send(c):
        sent.append((now[0], len(c)))

    late = asyncio.run(pace.pace(send, [b"x" * 10] * 5, clock=lambda: now[0], sleep=sleep))
    assert [round(t, 3) for t, _ in sent] == [0.1, 0.2, 0.3, 0.4, 0.5], sent
    assert max(abs(v) for v in late) < 1e-6


def test_pacer_timing_real_clock():
    sent = []

    async def send(c):
        sent.append(time.monotonic())

    t0 = time.monotonic()
    late = asyncio.run(pace.pace(send, [b"x"] * 6))
    total = sent[-1] - t0
    assert 0.55 < total < 0.9, total                 # six 100 ms chunks, the last at 600 ms
    assert float(np.median(late)) < 40, late         # ms late; generous for a busy CI runner


class FakeAdapter(pace.Adapter):
    """A service that answers each chunk with a transcript and some audio."""
    name = "fake"
    rate = 24000

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.received = []
        self.queue = asyncio.Queue()

    async def connect(self):
        self.log("hello", rate=self.rate)

    async def send_chunk(self, pcm):
        self.received.append(len(pcm))
        await self.queue.put(len(self.received))

    async def receive(self):
        while True:
            n = await self.queue.get()
            if n is None:
                return
            if n % 2 == 0:
                self.log("input", text=f"piece {n}", start_ms=self.clip_ms((n - 2) * 100), end_ms=self.clip_ms(n * 100))
                self.log_usage({"prompt_tokens": 10, "completion_tokens": 4}, status=200, ms=12)
                self.log.audio(np.full(2400, 2000, dtype=np.int16).tobytes(), self.rate, piece=str(n))

    async def finish(self):
        await self.queue.put(None)

    async def close(self):
        pass


def test_run_with_fake_adapter():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "run.jsonl")
        log = pace.EventLog(out)
        ad = FakeAdapter("ws://nowhere", "", {}, log)
        pcm = bytes(2 * 16000 // 2)                  # 0.5 s clip
        asyncio.run(pace.run(ad, pcm, log, preroll_s=0.2, quiet_end_s=0.3, tail_max_s=1.0))
        log.close()
        ev = [json.loads(line) for line in open(out, encoding="utf-8")]
    kinds = [e["kind"] for e in ev]
    assert kinds[0] == "hello" and ev[0]["t"] < 0
    assert "start" in kinds and kinds[-1] == "end"
    start = next(e for e in ev if e["kind"] == "start")
    assert start["rate"] == 24000 and start["clip_s"] == 0.5 and start["preroll_ms"] == 200
    assert all(n == 4800 for n in ad.received)       # 100 ms at 24 kHz, resampled
    assert len(ad.received) >= 2 + 5                 # preroll + clip (+ tail)
    audio = [e for e in ev if e["kind"] == "audio"]
    assert audio and audio[0]["offset"] == 0 and audio[0]["samples"] == 2400 and audio[0]["on"] == 0
    assert [a["offset"] for a in audio] == [2400 * i for i in range(len(audio))]
    usage = [e for e in ev if e["kind"] == "usage"]
    assert usage and usage[0]["prompt"] == 10 and usage[0]["completion"] == 4 and usage[0]["status"] == 200
    inputs = [e for e in ev if e["kind"] == "input"]
    assert inputs[0]["start_ms"] == -200                 # the pre-roll, on the clip's timeline
    assert next(e for e in ev if e["kind"] == "end")["late_ms_max"] < 200


# ---------------------------------------------------------------- lag.py

def backlog_log(markers=True, tag_audio=False):
    """Two pieces; the first piece's voice arrives in three 3 s chunks, the
    last of them after the second piece's transcript, and the second piece's
    voice arrives while the first is still playing."""
    R = 24000
    ev = [
        {"t": 0, "kind": "start", "rate": R},
        {"t": 4000, "kind": "input", "text": "one two three", "start_ms": 0, "end_ms": 3000},
        {"t": 4500, "kind": "translation", "text": "first piece"},
        {"t": 8000, "kind": "input", "text": "four five", "start_ms": 6000, "end_ms": 7500},
        {"t": 8500, "kind": "translation", "text": "second piece"},
    ]
    chunks = [(5000, 0, "1"), (7000, 72000, "1"), (9000, 144000, "1"), (12000, 216000, "2")]
    if markers:
        ev.append({"t": 4600, "kind": "marker", "label": "start", "piece": "1", "offset": 0})
        ev.append({"t": 8600, "kind": "marker", "label": "start", "piece": "2", "offset": 216000})
    for t, off, piece in chunks:
        a = {"t": t, "kind": "audio", "samples": 3 * R, "rate": R, "offset": off, "on": 0, "off": 3000}
        if tag_audio:
            a["piece"] = piece
        ev.append(a)
    return sorted(ev, key=lambda e: e["t"])


def test_lag_offsets_count_the_backlog():
    res, pieces = lag.analyse(backlog_log(markers=True), speech_start=0, speech_end=7500)
    assert res["attribution"] == "offsets"
    assert [p["lag_start"] for p in pieces] == [5000, 8000], pieces
    assert res["piece_lag_p50_s"] == 6.5 and res["piece_lag_p90_s"] == 7.7
    assert res["first_audio_s"] == 5.0 and res["final_lag_s"] == 9.5
    assert res["pieces"] == 2 and res["pieces_without_audio"] == 0
    assert res["piece_s_p50"] == 2.2 and res["piece_words_max"] == 3
    assert res["backlog_max_s"] == 2.0                   # C and D each wait 2 s behind the queue
    # Tagged audio, no markers: the same answer.
    res2, pieces2 = lag.analyse(backlog_log(markers=False, tag_audio=True), speech_start=0, speech_end=7500)
    assert res2["attribution"] == "offsets" and [p["lag_start"] for p in pieces2] == [5000, 8000]


def test_lag_arrival_under_reports():
    res, pieces = lag.analyse(backlog_log(markers=False), speech_start=0, speech_end=7500)
    assert res["attribution"] == "arrival"
    # The first piece's third chunk arrives after the second input and is
    # taken for the second piece's start: 5.0 s where the truth is 8.0 s.
    assert [p["lag_start"] for p in pieces] == [5000, 5000], pieces
    assert res["piece_lag_p90_s"] == 5.0
    assert res["first_audio_s"] == 5.0 and res["final_lag_s"] == 9.5     # unaffected
    assert "under-reported" in res["attribution_note"]


def test_lag_without_piece_times():
    ev = [e for e in backlog_log(markers=True) if e["kind"] != "input"]
    ev += [{"t": 4000, "kind": "input", "text": "one two three"}, {"t": 8000, "kind": "input", "text": "four five"}]
    res, pieces = lag.analyse(sorted(ev, key=lambda e: e["t"]), speech_start=0, speech_end=7500)
    assert res["piece_lag_p50_s"] is None and res["pieces_with_times"] == 0
    assert [p["lag_input"] for p in pieces] == [1000, 6000]
    assert res["input_to_audio_p50_s"] == 3.5 and "no piece times" in res["piece_lag_note"]


def test_lag_reads_a_file_and_usage():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "run.jsonl")
        ev = backlog_log() + [{"t": 4400, "kind": "usage", "status": 200, "ms": 500, "prompt": 100, "cached": 0,
                               "completion": 20, "reasoning": 0},
                              {"t": 8400, "kind": "usage", "status": 429, "ms": 900, "prompt": 110, "cached": 10,
                               "completion": 0, "reasoning": 0}]
        with open(path, "w", encoding="utf-8") as f:
            for e in ev:
                f.write(json.dumps(e) + "\n")
        res, _ = lag.analyse(lag.read_events(path), 0, 7500)
    assert res["usage"] == {"calls": 2, "non_200": 1, "prompt": 210, "cached": 10, "completion": 20, "reasoning": 0,
                            "ms_p50": 0.7, "ms_p90": 0.9}


def test_speech_bounds():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "clip.wav")
        x = np.zeros(16000 * 3, dtype=np.int16)
        x[16000:32000] = (np.sin(np.arange(16000) * 0.3) * 6000).astype(np.int16)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(x.tobytes())
        start, end = lag.speech_bounds(path)
    assert start == 1000 and end == 2000, (start, end)


# ---------------------------------------------------------------- cutsim.py

SYNTHETIC_SERVER = '''
import os
VAD_RATE = 16000
ENDPOINT_MS = int(os.environ.get("ENDPOINT_MS", "250"))
EXTRA_S = float(os.environ.get("EXTRA_S", "4.0"))      # a setting cutsim.py has never heard of
PLAIN = 256 * 1024
RATES = (16000, 24000)
LATER = 5


def quietest_cut(buf):
    """RATES and VAD_RATE in a docstring do not count."""
    return len(buf)


class Segmenter:
    def __init__(self, endpoint_ms=None):
        self.endpoint_ms = ENDPOINT_MS if endpoint_ms is None else endpoint_ms
        self.extra = EXTRA_S + PLAIN      # RATES in a comment does not count either


def vad_windows():
    return LATER
'''


def test_cutsim_discovers_constants():
    Segmenter, consts = cutsim.segmenter_from_source(SYNTHETIC_SERVER, "synthetic")
    assert consts == {"ENDPOINT_MS": 250, "EXTRA_S": 4.0, "PLAIN": 262144}, consts
    assert Segmenter().endpoint_ms == 250 and Segmenter(100).extra == 4.0 + 262144
    # A setting the section uses but server.py assigns in a form that is not evaluated: refused, not guessed.
    bad = SYNTHETIC_SERVER.replace("self.extra = EXTRA_S + PLAIN", "self.extra = EXTRA_S + RATES[0]")
    try:
        cutsim.segmenter_from_source(bad, "bad")
    except SystemExit as e:
        assert "RATES" in str(e)
    else:
        raise AssertionError("RATES was not refused")
    # The real server.py: every setting the segmenter reads is found there, none from the fallback.
    consts, missing = cutsim.constants_of(open(cutsim.SERVER, encoding="utf-8").read())
    assert not missing, missing
    assert {"ENDPOINT_MS", "MAX_UTTERANCE_S", "MIN_SPEECH_MS", "CUT_WINDOW_S", "VAD_LAG_MS"} <= set(consts)


def test_cutsim_runs_omni_stt_segmenter():
    Segmenter, consts = cutsim.load_segmenter(cutsim.SERVER)
    assert consts["VAD_RATE"] == 16000 and consts["CUT_DIP_MS"] == 96
    # 20 s of "speech" with a 600 ms gap every 4 s (VAD probability per 32 ms
    # window; a 96 ms block is quiet only when all three of its windows are).
    n_win = 20 * 1000 // 32
    p = np.full(n_win, 0.95, dtype=np.float32)
    for s in range(4000, 20000, 4000):
        p[s // 32:(s + 600) // 32] = 0.05
    rng = np.random.default_rng(1)
    x = (rng.standard_normal(n_win * 512) * 0.1).astype(np.float32)
    for s in range(4000, 20000, 4000):
        x[s * 16:(s + 600) * 16] = 0
    row = cutsim.simulate(Segmenter, x, p, {"endpoint_ms": 300, "max_s": 10}, ref_ends=[4.1, 8.1, 12.1, 16.1])
    assert row["pieces"] == 5, row
    assert row["cuts_at_cap"] == 0 and row["cuts_mid_speech"] == 0
    assert row["cuts_near_sentence_end"] == 4
    assert 3.3 <= row["len_p50_s"] <= 4.5
    capped = cutsim.simulate(Segmenter, x, p, {"endpoint_ms": 700, "max_s": 6})
    assert capped["pieces"] >= 4 and capped["cuts_at_cap"] + capped["cuts_near_cap"] >= 1, capped
    st = cutsim.parse_set("quick=endpoint_ms:200,max_s:8.5")
    assert st == {"name": "quick", "params": {"endpoint_ms": 200, "max_s": 8.5}}


# ---------------------------------------------------------------- pauses.py

def test_pause_statistics():
    p = np.concatenate([np.full(100, 0.9), np.full(10, 0.1), np.full(100, 0.9), np.full(20, 0.1), np.full(100, 0.9)])
    rows = pauses.stats(p, [0.5])
    r = rows[0]
    assert r["gaps"] == 2 and r["gaps_at_least_ms"]["300"] == 2 and r["gaps_at_least_ms"]["500"] == 1
    assert r["span_s"] == 11
    assert r["speech_between_gaps_at_least_ms"]["500"] == {"p50_s": 6.7, "p90_s": 6.7, "max_s": 6.7}
    assert r["speech_between_gaps_at_least_ms"]["300"]["p50_s"] == 3.2
    assert r["gaps_per_min_at_least_ms"]["300"] == 11.4            # 2 gaps in 330 windows (10.56 s)


# ---------------------------------------------------------------- dips.py

def test_energy_dips():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "clip.wav")
        x = (np.sin(np.arange(16000 * 4) * 0.4) * 8000).astype(np.int16)
        x[32000:32000 + 1600] = 0                        # 100 ms hole at 2.0 s
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(x.tobytes())
        db, lvl = dips.levels(path)
        found = dips.find_dips(db, lvl, 12, 60)
        assert len(found) == 1 and abs(found[0][0] - 2000) <= 20 and found[0][1] >= 80, found
        assert dips.near_share(found, [2050.0, 3000.0]) == 0.5
        assert dips.times_from("1.5,2") == [1500.0, 2000.0]


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"{len(tests)} tests passed")
