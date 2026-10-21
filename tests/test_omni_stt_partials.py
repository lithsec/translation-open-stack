#!/usr/bin/env python3
"""services/omni-stt's partial text (partials.py) and energy dips (dips.py),
without models: the stability rule, the pass scheduler, dips on synthetic
audio, and the /listen protocol with the flag off and on, driven by the fake
socket and fake models of test_omni_stt.py and through a real websocket.

    python3 tests/test_omni_stt_partials.py   (or python3 -m pytest tests/test_omni_stt_partials.py)

Needs numpy and scipy (server.py's imports) and websockets.
"""
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "omni-stt"))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import dips  # noqa: E402
import partials  # noqa: E402
import server as stt  # noqa: E402
from test_omni_stt import FakeModels, FakeWS, _fake_vad, _speech  # noqa: E402


# ---------------------------------------------------------------- the stability rule

def test_tracker_commits_what_two_passes_agree_on():
    t = partials.PartialTracker()
    assert t.feed("nou gen") == ("nou gen", None)                     # one pass: nothing stable yet
    assert t.feed("nou gen sis san") == ("nou gen sis san", "nou gen")
    assert t.stable == "nou gen"
    assert t.feed("nou gen sis san moun") == ("nou gen sis san moun", "sis san")
    assert t.stable == "nou gen sis san"
    # No new agreement: a partial, no stable.
    assert t.feed("nou gen sis san mou") == ("nou gen sis san mou", None)
    assert t.feed("nou gen sis san moun jodi") == ("nou gen sis san moun jodi", None)   # "mou" then "moun": not yet
    assert t.feed("nou gen sis san moun jodi a") == ("nou gen sis san moun jodi a", "moun jodi")
    assert t.passes == 6


def test_tracker_whole_words_only():
    t = partials.PartialTracker()
    t.feed("bonjou tout mou")
    # The last word is still being said: "mou" vs "moun" is no agreement.
    assert t.feed("bonjou tout moun") == ("bonjou tout moun", "bonjou tout")
    assert t.feed("bonjou  tout moun,  mèsi") == ("bonjou  tout moun,  mèsi", None)   # "moun" vs "moun,"
    assert t.feed("bonjou tout moun, mèsi anpil")[1] == "moun, mèsi"
    assert t.stable == "bonjou tout moun, mèsi"
    assert partials.PartialTracker().feed("   ") == ("", None)


def test_tracker_corrected_word_then_stabilises():
    t = partials.PartialTracker()
    t.feed("mwen te wè")
    assert t.feed("mwen te wè yo") == ("mwen te wè yo", "mwen te wè")
    # The next pass rewrites a committed word: nothing is retracted, and
    # nothing more is committed while the hypothesis disagrees with the stable text.
    assert t.feed("mwen pa wè yo") == ("mwen pa wè yo", None)
    assert t.stable == "mwen te wè"
    assert t.feed("mwen pa wè yo ale") == ("mwen pa wè yo ale", None)
    assert t.stable == "mwen te wè"
    # It comes back to the committed prefix and grows: commits resume.
    t.feed("mwen te wè yo ale")
    assert t.feed("mwen te wè yo ale lakay") == ("mwen te wè yo ale lakay", "yo ale")
    assert t.stable == "mwen te wè yo ale"


def test_tracker_never_retracts():
    import random
    rng = random.Random(3)
    vocab = ["a", "b", "c", "d", "e"]
    for _ in range(200):
        t = partials.PartialTracker()
        stable = ""
        for _ in range(12):
            words = [rng.choice(vocab) for _ in range(rng.randint(0, 8))]
            partial, delta = t.feed(" ".join(words))
            assert partial == " ".join(words)
            new = t.stable
            assert new == stable or new.startswith(stable + " ") or (stable == "" and new), (stable, new)
            if delta is not None:
                assert new == (stable + " " + delta).strip() and delta
                assert partial.startswith(new)              # committed text is in the hypothesis it came from
            else:
                assert new == stable
            stable = new


def test_tracker_keys_and_reset():
    t = partials.PartialTracker()
    t.feed("hello there", key="en")
    assert t.feed("hello there friend", key="ht") == ("hello there friend", None)   # another language's pass: no agreement
    assert t.feed("hello there friend", key="ht")[1] == "hello there friend"
    t.reset()
    assert t.stable == "" and t.prev is None and t.passes == 0
    assert t.feed("x y")[1] is None


# ---------------------------------------------------------------- the scheduler

def test_scheduler_timing():
    now = [0.0]
    s = partials.PassScheduler(interval_ms=1500, min_gap_ms=0, clock=lambda: now[0])
    assert not s.due(1000)
    assert s.due(1500) and s.due(2000)              # due until started
    s.started(1500)
    assert not s.due(3000)                          # one in flight
    s.finished()
    assert not s.due(2900) and s.due(3000)          # 1500 of new audio since the last pass
    assert not s.due(3000, busy=True)               # the GPU has work waiting: not now
    assert s.due(3000)                              # ... but not forgotten
    s.reset()
    assert not s.due(1000) and s.due(1500)
    # A wall-clock gap too (faster-than-real-time input).
    s = partials.PassScheduler(interval_ms=1000, min_gap_ms=500, clock=lambda: now[0])
    s.started(1000)
    s.finished()
    now[0] = 100
    assert not s.due(5000)
    now[0] = 600
    assert s.due(5000)
    # Defaults from the environment: off, 1500 ms.
    if "STT_PARTIALS" not in os.environ and "STT_PARTIAL_MS" not in os.environ:
        assert partials.ENABLED is False and partials.INTERVAL_MS == 1500


def test_queue_busy():
    class B:
        queues = {"lid": [], "asr": []}
    assert not partials.queue_busy(B())
    B.queues["asr"].append(1)
    assert partials.queue_busy(B())
    assert not partials.queue_busy(object())


# ---------------------------------------------------------------- dips

def _tone(seconds, amp=0.3, hz=220.0, rate=16000):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def test_dips_tone_with_a_gap():
    x = _tone(3.0)
    a, b = int(1.2 * 16000), int(1.5 * 16000)                     # a 300 ms gap at 1200 ms
    x[a:b] = 0.0
    found = dips.find_dips(x)
    assert len(found) == 1, found
    d = found[0]
    assert abs(d.start_ms - 1200) <= dips.FRAME_MS, d
    assert abs(d.end_ms - 1500) <= dips.FRAME_MS, d
    assert d.depth_db >= 12
    # The gap off the frame grid: the start is still within a frame.
    x = _tone(3.0)
    a = int(1.21 * 16000)
    x[a:a + 4800] = 0.0
    d = dips.find_dips(x)[0]
    assert abs(d.start_ms - 1210) <= dips.FRAME_MS, d


def test_dips_none_on_a_steady_tone_or_a_shallow_dip():
    assert dips.find_dips(_tone(3.0)) == []
    x = _tone(3.0)
    a, b = int(1.2 * 16000), int(1.5 * 16000)
    x[a:b] *= 0.5                                                  # 6 dB down: not a dip
    assert dips.find_dips(x) == []
    x[a:b] = _tone(0.3)[: b - a] * (10 ** (-14 / 20))             # 14 dB down: a dip
    assert len(dips.find_dips(x)) == 1
    # Too short: 40 ms under the level is not a dip (min 60 ms).
    x = _tone(3.0)
    x[a:a + 640] = 0.0
    assert dips.find_dips(x) == []
    assert dips.find_dips(x, min_ms=40) and dips.find_dips(np.zeros(0, np.float32)) == []
    # Silence stops counting once the running level has sunk to it.
    x = np.concatenate([_tone(2.0), np.zeros(4 * 16000, np.float32)])
    found = dips.find_dips(x)
    assert len(found) == 1 and abs(found[0].start_ms - 2000) <= dips.FRAME_MS and found[0].end_ms < 6000, found


def test_sentence_end_candidates():
    ds = [dips.Dip(1200, 1500, 30.0), dips.Dip(4000, 4100, 15.0)]
    ends = [900, 1250, 2000, 3800, 4200]
    got = dips.sentence_end_candidates(ds, ends)
    # 1250: a dip starts 50 ms before it (within -100); 3800: 200 ms after (within +250).
    assert [(c.word_end_ms, c.dip.start_ms) for c in got] == [(1250, 1200), (3800, 4000)], got
    assert dips.sentence_end_candidates(ds, [900]) == []            # 300 ms after the word end: not it
    assert dips.sentence_end_candidates(ds, [900], lag_ms=300)[0].dip.start_ms == 1200
    assert dips.dip_at(ds, 3900).start_ms == 4000 and dips.dip_at(ds, 3000) is None
    assert dips.sentence_end_candidates([], ends) == []


# ---------------------------------------------------------------- the protocol, with fakes

def _with_flag(enabled, interval_ms, fn):
    old = partials.ENABLED, partials.INTERVAL_MS
    partials.ENABLED, partials.INTERVAL_MS = enabled, interval_ms
    try:
        return fn()
    finally:
        partials.ENABLED, partials.INTERVAL_MS = old


def _run_fake(enabled, interval_ms=800):
    _fake_vad()
    models = FakeModels()
    ws = FakeWS("/listen?langs=ht,en", _speech(0.3) + _speech(0.6) + [json.dumps({"type": "flush"})])
    _with_flag(enabled, interval_ms, lambda: asyncio.run(stt.handle(ws, models)))
    return ws.sent


def test_flag_off_sends_no_partials():
    sent = _run_fake(False)
    kinds = [m["type"] for m in sent]
    assert kinds == ["hello", "language", "inputTranscript", "language", "inputTranscript", "flushed"], kinds


def test_flag_on_sends_partials_then_stable_before_the_final():
    off = _run_fake(False)
    sent = _run_fake(True, 800)
    kinds = [m["type"] for m in sent]
    assert kinds[0] == "hello" and kinds[-1] == "flushed"
    # The finals are exactly the flag-off run's.
    finals = [m for m in sent if m["type"] in ("language", "inputTranscript")]
    assert finals == [m for m in off if m["type"] in ("language", "inputTranscript")], finals
    # Each piece (keyed by start_ms, as a client keys them; a later piece's
    # partial may precede an earlier piece's final when the GPU is behind):
    # partials, a stable once two passes agreed, then language + inputTranscript.
    pieces = _pieces(sent)
    assert len(pieces) == 2, kinds
    for piece in pieces.values():
        k = [m["type"] for m in piece]
        assert k[-2:] == ["language", "inputTranscript"], k
        assert k.count("partial") >= 2 and k.count("stable") == 1, k
        assert k.index("stable") > k.index("partial") and k.index("stable") < k.index("language"), k
        final = piece[-1]
        for m in piece[:-2]:
            assert m["text"] == final["text"] and m["lang"] == final["lang"], (m, final)
            assert m["start_ms"] == final["start_ms"] and m["end_ms"] <= final["end_ms"], (m, final)
            assert set(m) >= {"type", "text", "lang", "confidence", "start_ms", "end_ms"}
        stable = next(m for m in piece if m["type"] == "stable")
        assert stable["delta"] == stable["text"] == final["text"]
        # Passes about every 800 ms of audio: not more often.
        ends = [m["end_ms"] for m in piece if m["type"] == "partial"]
        assert all(b - a >= 800 - 96 for a, b in zip(ends, ends[1:])), ends


def _pieces(sent):
    """The messages of each piece, by start_ms, in the order they were sent."""
    out = {}
    for m in sent:
        if "start_ms" in m:
            out.setdefault(m["start_ms"], []).append(m)
    return out


def test_flag_on_transcribe_subset_and_one_language():
    # The language the pass guesses is not one this connection transcribes: no partial for it.
    _fake_vad()
    ws = FakeWS("/listen?langs=ht,en&transcribe=ht", _speech(0.6) + _speech(0.3) + [json.dumps({"type": "flush"})])
    _with_flag(True, 800, lambda: asyncio.run(stt.handle(ws, FakeModels())))
    kinds = [m["type"] for m in ws.sent]
    assert kinds[0] == "hello" and kinds[-1] == "flushed" and kinds.count("inputTranscript") == 1, kinds
    en, ht = _pieces(ws.sent).values()
    assert [m["type"] for m in en] == ["language"] and en[0]["lang"] == "en", en     # no partial for en
    k = [m["type"] for m in ht]
    assert k.count("partial") >= 2 and k[-2:] == ["language", "inputTranscript"], k
    assert all(m["lang"] == "ht" for m in ht)
    # One language: no language ID in the pass, confidence 1.0.
    ws = FakeWS("/listen?langs=ht", _speech(0.3) + [json.dumps({"type": "flush"})])
    _with_flag(True, 800, lambda: asyncio.run(stt.handle(ws, FakeModels())))
    ps = [m for m in ws.sent if m["type"] == "partial"]
    assert ps and all(m["confidence"] == 1.0 and m["lang"] == "ht" for m in ps)


def test_flag_on_through_a_real_socket():
    """The same through websockets: messages arrive in order on the wire."""
    import websockets
    _fake_vad()
    models = FakeModels()
    msgs = _speech(0.3) + [json.dumps({"type": "flush"})]

    async def run():
        async with websockets.serve(lambda ws: stt.handle(ws, models), "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            got = []
            async with websockets.connect(f"ws://127.0.0.1:{port}/listen?langs=ht,en") as c:
                for m in msgs:
                    await c.send(m)
                    await asyncio.sleep(0.005)
                while True:
                    m = json.loads(await asyncio.wait_for(c.recv(), 10))
                    got.append(m)
                    if m["type"] == "flushed":
                        break
            return got
    got = _with_flag(True, 800, lambda: asyncio.run(run()))
    kinds = [m["type"] for m in got]
    assert kinds[0] == "hello" and kinds[-3:] == ["language", "inputTranscript", "flushed"], kinds
    assert kinds.count("partial") >= 2 and kinds.count("stable") == 1, kinds
    assert kinds.index("stable") < kinds.index("language")


def test_a_pass_in_flight_is_dropped_when_the_piece_ends():
    """A pass still waiting on the GPU when the piece ends is cancelled, so no
    partial follows the final; and the Batcher drops the cancelled job unrun."""
    sent = []

    async def run():
        loop = asyncio.get_running_loop()
        futs = []

        def submit(kind, pcm, arg):
            fut = loop.create_future()
            futs.append((kind, fut))
            return fut

        async def send(m):
            sent.append(m)
        ps = partials.PartialStream(["ht"], {"ht"}, submit, send, interval_ms=500)

        class Seg:
            speech_seen = True
            buf = np.zeros(16000, np.float32)
            buf_start = 8000
        ps.after_feed(Seg(), [])
        await asyncio.sleep(0)
        assert len(futs) == 1 and ps.scheduler.inflight
        ps.after_feed(Seg(), [])                     # one in flight: no second pass
        assert len(futs) == 1
        ps.piece_ended()                             # the final is on its way
        await asyncio.sleep(0)
        assert futs[0][1].cancelled() and ps.stats["dropped"] == 1
        # The next piece starts clean.
        ps.after_feed(Seg(), [])
        await asyncio.sleep(0)
        assert len(futs) == 2 and not futs[1][1].done()
        futs[1][1].set_result("wi")
        await asyncio.sleep(0.01)
        assert sent == [{"type": "partial", "text": "wi", "lang": "ht", "confidence": 1.0,
                         "start_ms": 500, "end_ms": 1500}], sent
        assert not ps.scheduler.inflight
        ps.close()
    asyncio.run(run())


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
