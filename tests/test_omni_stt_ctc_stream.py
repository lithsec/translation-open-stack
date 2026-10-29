#!/usr/bin/env python3
"""services/omni-stt's streaming track (ctc_stream.py), without models: the
query parameters, CTC's collapse, the commit rule, the script mask, one
connection's passes over a fake CTC model, and the /listen protocol with the
track off, asked for and on, through the fake socket of test_omni_stt.py and
a real websocket.

    python3 tests/test_omni_stt_ctc_stream.py   (or python3 -m pytest tests/test_omni_stt_ctc_stream.py)

Needs numpy and scipy (server.py's imports) and websockets.
"""
import asyncio
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "omni-stt"))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import ctc_stream as cs  # noqa: E402
import server as stt  # noqa: E402
from test_omni_stt import FakeModels, FakeWS, _fake_vad, _pcm  # noqa: E402

RATE = 16000


# ---------------------------------------------------------------- a fake CTC model

def labels_of(pcm):
    """One label per 20 ms frame: the frame's level in twentieths (0 below 0.1:
    the blank), so a test's audio spells its own tokens."""
    n = len(pcm) // cs.FRAME
    if not n:
        return np.zeros(0, dtype=np.int64)
    v = np.median(np.abs(pcm[: n * cs.FRAME].reshape(n, cs.FRAME)), axis=1)
    return np.where(v < 0.1, 0, np.round(v * 20)).astype(np.int64)


def detok(ids):
    """SentencePiece-like: each token is a word ("▁wN"); the leading space goes."""
    return "".join(f" w{i}" for i in ids).lstrip()


class FakeCTC:
    def __init__(self, delay=0):
        self.calls = []
        self.delay = delay

    def submit(self, pcm, lang):
        self.calls.append((len(pcm), lang))
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        out = labels_of(np.asarray(pcm))
        if self.delay:
            loop.call_later(self.delay, lambda: fut.done() or fut.set_result(out))
        else:
            loop.call_soon(lambda: fut.done() or fut.set_result(out))
        return fut

    detok = staticmethod(detok)


class CTCModels(FakeModels):
    def __init__(self):
        super().__init__()
        self.ctc = FakeCTC()


def words_audio(levels, word_s=0.3, gap_s=0.1, gap_level=0.06):
    """'Speech': each level for word_s, then a quiet-but-voiced gap (a blank to
    the fake CTC, speech to the fake VAD), as float32 at 16 kHz."""
    parts = []
    for lv in levels:
        parts.append(np.full(int(word_s * RATE), lv, np.float32))
        parts.append(np.full(int(gap_s * RATE), gap_level, np.float32))
    return np.concatenate(parts)


def as_messages(x, step_s=0.1):
    b = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
    step = int(RATE * step_s) * 2
    return [b[i:i + step] for i in range(0, len(b), step)]


LEVELS = [0.2, 0.35, 0.5, 0.25, 0.65, 0.4, 0.8, 0.3, 0.55, 0.45, 0.7, 0.15]
TRUTH = " ".join(f"w{round(lv * 20)}" for lv in LEVELS)


# ---------------------------------------------------------------- parameters

def q(s):
    from urllib.parse import parse_qs
    return parse_qs(s)


def test_parse_stream():
    assert cs.parse_stream(q("langs=km"), ["km"], True) is None                       # not asked: no track, no hello field
    assert cs.parse_stream(q("stream=ctc"), ["km"], True) == {"track": "ctc", "lang": "km", "lookahead_ms": cs.LOOKAHEAD_MS}
    assert cs.parse_stream(q("stream=ctc&lookahead=1"), ["lo"], True)["lookahead_ms"] == 1000
    assert cs.parse_stream(q("stream=CTC&lookahead=2"), ["lo"], True)["lookahead_ms"] == 2000
    for bad in ("stream=rnnt", "stream=ctc&lookahead=3", "stream=ctc&lookahead=x", "lookahead=1"):
        try:
            cs.parse_stream(q(bad), ["km"], True)
        except cs.BadParam:
            continue
        raise AssertionError(bad)
    # Asked for and not possible: said so in the hello, the connection goes on without it.
    assert cs.parse_stream(q("stream=ctc"), ["km"], False)["track"] is None
    assert cs.parse_stream(q("stream=ctc"), ["km", "en"], True)["track"] is None
    assert cs.parse_stream(q("stream=ctc"), ["ht"], True)["track"] is None
    assert "reason" in cs.parse_stream(q("stream=ctc"), ["ht"], True)
    if "STT_CTC_STREAM" not in os.environ and "STT_CTC_LOOKAHEAD_MS" not in os.environ:
        assert cs.ENABLED is False and cs.LOOKAHEAD_MS == 2000 and cs.CHUNK_MS == 500 and cs.LEFT_MS == 8000


# ---------------------------------------------------------------- collapse and the commit rule

def test_collapse():
    assert cs.collapse([0, 3, 3, 0, 3, 4, 4, 0], -1) == ([3, 3, 4], 0)
    assert cs.collapse([3, 3, 5], 3) == ([5], 5)            # a run that began before the boundary
    assert cs.collapse([], 7) == ([], 7)


def _stream_commits(truth, step, lookahead_ms, left_ms, jitter=None):
    """Drive a Committer over a fixed label sequence (labels are a function
    of the absolute frame) with passes every `step` frames; optional jitter
    rewrites the uncommitted tail of a pass (an unsure model)."""
    c = cs.Committer(lookahead_ms, left_ms)
    committed, tails = [], []
    total = len(truth) * cs.FRAME
    now = 0
    while True:
        now = min(total, now + step * cs.FRAME)
        final = now >= total
        start, end = c.window(now)
        assert start % cs.FRAME == 0 and start <= c.edge and c.edge - start <= c.left
        labels = list(truth[start // cs.FRAME: end // cs.FRAME])
        if jitter and not final:
            k = max(0, (end - c.lookahead - start) // cs.FRAME)
            labels[k:] = jitter(labels[k:])
        before = c.edge
        new, tail = c.apply(labels, start, now, final)
        assert c.edge >= before                             # the edge never goes back
        committed += new
        tails.append(tail)
        if final:
            return committed, tails, c


def test_commits_add_up_to_the_offline_decode():
    rng = random.Random(5)
    for _ in range(200):
        truth = []
        for _ in range(rng.randint(0, 120)):
            truth += [rng.choice([0, 0, 1, 2, 3])] * rng.randint(1, 6)
        step = rng.choice([5, 25, 50])
        la = rng.choice([500, 1000, 2000])
        committed, _, c = _stream_commits(truth, step, la, rng.choice([2000, 8000]))
        assert committed == cs.collapse(truth, -1)[0], (truth, committed)
        assert c.last == 0


def test_a_revised_tail_never_reaches_committed_text():
    truth = [0, 3, 3, 0, 4, 0, 0, 5, 5, 0] * 20
    committed, _, _ = _stream_commits(truth, 25, 1000, 8000, jitter=lambda tail: [9] * len(tail))
    assert committed == cs.collapse(truth, -1)[0]          # only right-context frames were rewritten


def test_lookahead_holds_frames_back():
    c = cs.Committer(2000, 8000)
    labels = [3] * 50 + [0] * 50 + [4] * 50                # 3 s of frames
    new, tail = c.apply(labels, 0, 150 * cs.FRAME)
    assert new == [3] and tail == [4] and c.edge == 50 * cs.FRAME     # committed up to now - 2 s
    c2 = cs.Committer(1000, 8000)
    new, tail = c2.apply(labels, 0, 150 * cs.FRAME)
    assert new == [3] and tail == [4] and c2.edge == 100 * cs.FRAME
    # The left context is bounded.
    c3 = cs.Committer(1000, 2000)
    c3.edge = 20 * RATE
    assert c3.window(25 * RATE) == (18 * RATE, 25 * RATE)


def test_commits_never_split_a_grapheme_cluster():
    # Token 7 is a vowel sign (joins the token before it); 8 ends with a coeng
    # (the next token joins it). Pieces as the model's tokenizer gives them.
    pieces = ["", "ក", "ម", "ព", "ន", "ល", "ស", "ា", "ក\u17d2", "\u17bb"]
    joins = cs.joiner(pieces)
    assert joins(1, 7) and joins(8, 4) and joins(3, 9) and not joins(7, 2) and not joins(1, 2)
    c = cs.Committer(1000, 8000, joins=joins)
    labels = [1] * 10 + [0] * 5 + [2] * 10 + [7] * 10 + [0] * 25 + [3] * 50     # 2.2 s of frames
    # The edge (now - 1 s = frame 60) would fall after 7; it ends after 7: fine.
    new, tail = c.apply(labels, 0, 110 * cs.FRAME)
    assert new == [1, 2, 7] and tail == [3]
    # Now the edge would split 2 from its vowel sign 7: it moves back to 2's first frame.
    c = cs.Committer(1000, 8000, joins=joins)
    labels = [1] * 10 + [0] * 5 + [2] * 10 + [0] * 5 + [7] * 50 + [0] * 30
    new, tail = c.apply(labels[:78], 0, 78 * cs.FRAME)                 # edge at frame 28: between 2 and 7
    assert new == [1] and tail == [2, 7] and c.edge == 15 * cs.FRAME
    # The next pass, a little later, commits the cluster whole.
    start, now = c.window(150 * cs.FRAME)
    more = labels + [0] * 40
    new, tail = c.apply(more[start // cs.FRAME: now // cs.FRAME], start, now)
    assert new == [2, 7] and tail == []
    # A coeng chain (8 then 4, then a vowel 9 on 4) moves back over all of it.
    c = cs.Committer(1000, 8000, joins=joins)
    labels = [1] * 10 + [8] * 10 + [4] * 10 + [0] * 5 + [9] * 65
    new, tail = c.apply(labels[:80], 0, 80 * cs.FRAME)                 # edge at frame 30: inside it
    assert new == [1] and tail == [8, 4, 9] and c.edge == 10 * cs.FRAME, (new, tail)
    # Random streams with joins still add up to the offline decode.
    rng = random.Random(9)
    for _ in range(200):
        truth = []
        for _ in range(rng.randint(0, 100)):
            truth += [rng.choice([0, 0, 1, 2, 7, 8, 4, 9])] * rng.randint(1, 6)
        c = cs.Committer(rng.choice([500, 1000, 2000]), 8000, joins=joins)
        committed, total, now = [], len(truth) * cs.FRAME, 0
        while True:
            now = min(total, now + 25 * cs.FRAME)
            start, end = c.window(now)
            new, tail = c.apply(truth[start // cs.FRAME: end // cs.FRAME], start, now, now >= total)
            committed += new
            if new and tail and now < total:
                assert not joins(new[-1], tail[0]), (new, tail)
            if now >= total:
                break
        assert committed == cs.collapse(truth, -1)[0]


def test_delta_text():
    assert cs.delta_text(detok, [], [3, 4]) == "w3 w4"
    assert cs.delta_text(detok, [3], [4]) == " w4"           # the space a lone decode would drop
    assert cs.delta_text(detok, [3], []) == ""
    glued = lambda ids: "".join(f"k{i}" for i in ids)        # noqa: E731  a script written without spaces
    assert cs.delta_text(glued, [1], [2]) == "k2"


def test_script_mask():
    pieces = ["▁ក", "ា", "ລ", "ໍ", "a", "▁Pa", "12", "?", "", "е", "ไ", "日"]
    km = cs.script_mask(pieces, "km")
    lo = cs.script_mask(pieces, "lo")
    assert km == [True, True, False, False, True, True, True, True, True, False, False, False], km
    assert lo == [False, False, True, True, True, True, True, True, True, False, False, False], lo
    assert cs.script_mask(["᧠"], "km") == [True]              # Khmer Symbols


# ---------------------------------------------------------------- one connection

def _drive(levels, lookahead_ms=1000, block_s=0.096, pause_s=1.0, turn_end=True, delay=0, vad=None):
    """Feed audio to a CTCStream block by block, as the server does; returns the messages."""
    sent = []
    model = FakeCTC(delay)

    async def run():
        async def send(m):
            sent.append(dict(m, fed_ms=int(st.total * 1000 / RATE)))   # how much audio was in at the time
        st = cs.CTCStream("km", lookahead_ms, model.submit, send, detok)
        x = np.concatenate([np.zeros(int(0.5 * RATE), np.float32), words_audio(levels),
                            np.zeros(int(pause_s * RATE), np.float32)])
        n = int(block_s * RATE)
        for i in range(0, len(x), n):
            b = x[i:i + n]
            st.feed(b, vad(b) if vad else (1.0 if np.abs(b).max() > 0.05 else 0.0))
            for _ in range(3):
                await asyncio.sleep(delay / 3 if delay else 0)
        if turn_end:
            st.turn_ended()
        await st.drain()
        st.close()
        return st
    st = asyncio.run(run())
    return sent, st, model


def test_stream_partials_then_commits_that_add_up():
    sent, st, model = _drive(LEVELS)
    kinds = [m["type"] for m in sent]
    assert set(kinds) == {"partial", "committed"}, kinds
    assert kinds.index("partial") < kinds.index("committed")            # the tail shows first
    committed = [m for m in sent if m["type"] == "committed"]
    assert "".join(m["text"] for m in committed) == TRUTH               # append-only, nothing lost or doubled
    assert committed[-1]["end"] is True and all(not m["end"] for m in committed[:-1])
    for m in sent:
        assert m.pop("fed_ms") >= m["end_ms"]
        assert m["track"] == "ctc" and m["lang"] == "km" and m["start_ms"] <= m["end_ms"]
    # Spans join up: each commit starts where the previous one ended.
    for a, b in zip(committed, committed[1:]):
        assert b["start_ms"] == a["end_ms"], (a, b)
    # Every partial is the text after the commits so far, and the last one is cleared.
    done = ""
    for m in sent:
        if m["type"] == "committed":
            done += m["text"]
        elif m["text"]:
            assert TRUTH.startswith((done + " " + m["text"]).strip()), (done, m)
    assert [m for m in sent if m["type"] == "partial"][-1]["text"] == ""
    # A pass every ~500 ms of audio while there is speech, every QUIET_MS without.
    speech_s = len(LEVELS) * 0.4 + 0.4
    assert len(model.calls) <= speech_s / 0.5 + (0.5 + 1.0) / (cs.QUIET_MS / 1000) + 3, model.calls
    assert all(n <= (cs.LEFT_MS + 1000 + cs.CHUNK_MS + 200) * RATE / 1000 for n, _ in model.calls)


def test_stream_lookahead_two_commits_later_than_one():
    one, _, _ = _drive(LEVELS, 1000, turn_end=False, pause_s=3.0)
    two, _, _ = _drive(LEVELS, 2000, turn_end=False, pause_s=3.0)

    def first(sent, kind):
        return next(m["fed_ms"] for m in sent if m["type"] == kind and m["text"])
    assert first(one, "partial") == first(two, "partial") <= 500 + 300 + cs.CHUNK_MS + 100
    assert first(two, "committed") - first(one, "committed") >= 900
    # Without a turn end the commits still catch up once the speech is lookahead old.
    for sent in (one, two):
        assert "".join(m["text"] for m in sent if m["type"] == "committed") == TRUTH


def test_stream_decodes_speech_the_vad_missed():
    # The VAD hears nothing at all (a quiet, distant speaker): the words still
    # come through, at the quiet rhythm, and nothing is skipped undecoded.
    sent, st, model = _drive(LEVELS, 2000, vad=lambda b: 0.0, pause_s=3.0, turn_end=False)
    assert "".join(m["text"] for m in sent if m["type"] == "committed") == TRUTH
    audio_s = 0.5 + len(LEVELS) * 0.4 + 3.0
    assert len(model.calls) <= audio_s / (cs.QUIET_MS / 1000) + 2, model.calls       # the quiet rhythm


def test_stream_slow_model_never_queues_passes():
    sent, st, model = _drive(LEVELS, 2000, delay=0.15)
    assert "".join(m["text"] for m in sent if m["type"] == "committed") == TRUTH
    assert st.stats["passes"] == len(model.calls)


def test_stream_close_cancels_a_pass():
    async def run():
        sent = []
        loop = asyncio.get_running_loop()
        futs = []

        def submit(pcm, lang):
            futs.append(loop.create_future())
            return futs[-1]

        async def send(m):
            sent.append(m)
        st = cs.CTCStream("lo", 2000, submit, send, detok)
        for _ in range(8):
            st.feed(np.full(1536, 0.3, np.float32), 1.0)
        await asyncio.sleep(0)
        assert len(futs) == 1                       # one in flight, the rest wait
        st.close()
        await asyncio.sleep(0)
        assert st.task.done() and futs[0].cancelled() and sent == []   # the CTC worker drops it unrun
    asyncio.run(run())


# ---------------------------------------------------------------- the protocol

def _listen(path, models, x, flush=True):
    _fake_vad()
    msgs = as_messages(x) + ([json.dumps({"type": "flush"})] if flush else [])
    ws = FakeWS(path, msgs)
    asyncio.run(stt.handle(ws, models))
    return ws


def _turns():
    sil = np.zeros(int(0.5 * RATE), np.float32)
    return np.concatenate([sil, words_audio(LEVELS[:6]), np.zeros(int(1.2 * RATE), np.float32),
                           words_audio(LEVELS[6:]), np.zeros(int(1.2 * RATE), np.float32)])


def test_listen_without_the_track_is_unchanged():
    x = _turns()
    plain = _listen("/listen?langs=km", FakeModels(), x)
    on_server = _listen("/listen?langs=km", CTCModels(), x)        # the track loaded, not asked for
    assert plain.sent == on_server.sent
    assert plain.sent[0] == {"type": "hello", "langs": ["km"], "rate": 16000}
    assert {m["type"] for m in plain.sent} == {"hello", "language", "inputTranscript", "flushed"}


def test_listen_with_the_track():
    x = _turns()
    models = CTCModels()
    plain = _listen("/listen?langs=km", FakeModels(), x)
    ws = _listen("/listen?langs=km&stream=ctc&lookahead=1", models, x)
    assert ws.sent[0] == {"type": "hello", "langs": ["km"], "rate": 16000,
                          "stream": {"track": "ctc", "lookahead_ms": 1000, "chunk_ms": cs.CHUNK_MS, "left_ms": cs.LEFT_MS}}
    kinds = [m["type"] for m in ws.sent]
    assert kinds[-1] == "flushed" and "partial" in kinds and "committed" in kinds, kinds
    # The finals are exactly the plain connection's.
    finals = [m for m in ws.sent if m["type"] in ("language", "inputTranscript")]
    assert finals == [m for m in plain.sent if m["type"] in ("language", "inputTranscript")]
    committed = [m for m in ws.sent if m["type"] == "committed"]
    assert "".join(m["text"] for m in committed) == TRUTH
    # One commit closes each turn (the Segmenter's pause), before that turn's
    # final; the second turn's text starts with a space after the first's.
    ends = [i for i, m in enumerate(ws.sent) if m["type"] == "committed" and m["end"]]
    assert len(ends) == 2, [m for m in committed]
    finals_at = [i for i, m in enumerate(ws.sent) if m["type"] == "inputTranscript"]
    assert ends[0] < finals_at[1]
    assert all(models.ctc.calls[i][1] == "km" for i in range(len(models.ctc.calls)))


def test_listen_track_refused_or_unavailable():
    x = np.concatenate([np.zeros(RATE // 2, np.float32), words_audio(LEVELS[:3]), np.zeros(RATE, np.float32)])
    # Malformed: refused at connect.
    _fake_vad()
    ws = FakeWS("/listen?langs=km&stream=ctc&lookahead=5", [])
    asyncio.run(stt.handle(ws, CTCModels()))
    assert ws.closed[0] == stt.CLOSE_BAD_REQUEST and ws.sent[0]["type"] == "error"
    # Asked for where it cannot run: the hello says why, and the connection is the plain one.
    for path, models in (("/listen?langs=km,en&stream=ctc", CTCModels()), ("/listen?langs=km&stream=ctc", FakeModels())):
        got = _listen(path, models, x)
        assert got.sent[0]["stream"]["track"] is None and got.sent[0]["stream"]["reason"], got.sent[0]
        assert not {m["type"] for m in got.sent} & {"partial", "committed"}


def test_listen_track_through_a_real_socket():
    import websockets
    _fake_vad()
    models = CTCModels()
    msgs = as_messages(_turns()) + [json.dumps({"type": "flush"})]

    async def run():
        async with websockets.serve(lambda ws: stt.handle(ws, models), "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            got = []
            async with websockets.connect(f"ws://127.0.0.1:{port}/listen?langs=lo&stream=ctc") as c:
                for m in msgs:
                    await c.send(m)
                    await asyncio.sleep(0.002)
                while True:
                    m = json.loads(await asyncio.wait_for(c.recv(), 10))
                    got.append(m)
                    if m["type"] == "flushed":
                        break
            return got
    got = asyncio.run(run())
    assert got[0]["stream"]["lookahead_ms"] == cs.LOOKAHEAD_MS
    assert "".join(m["text"] for m in got if m["type"] == "committed") == TRUTH
    assert got[-1]["type"] == "flushed" and sum(1 for m in got if m["type"] == "inputTranscript") == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
