#!/usr/bin/env python3
"""services/omni-stt/server.py without its models: request parsing, auth, the
constrained language choice, endpointing, and the /listen protocol driven by a
fake socket and fake models (several connections at once included).

    python3 tests/test_omni_stt.py      (or python3 -m pytest tests/test_omni_stt.py)

Needs numpy and scipy (the stack's AudioIn), nothing else.
"""
import asyncio
import json
import os
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "omni-stt"))
import server as stt  # noqa: E402
import numpy as np  # noqa: E402

LID = {"en", "fr", "ht", "km", "lo", "es"}


def _raises(fn, *args):
    try:
        fn(*args)
    except stt.BadRequest as e:
        return str(e)
    raise AssertionError(f"{fn.__name__}{args} did not refuse")


def test_parse_langs():
    assert stt.parse_langs("ht,en", LID) == ["ht", "en"]
    assert stt.parse_langs(" HT , ht,en,", LID) == ["ht", "en"]        # case, spaces, repeats
    assert "required" in _raises(stt.parse_langs, "", LID)
    assert "not served: xx" in _raises(stt.parse_langs, "ht,xx", LID)
    assert "at most" in _raises(stt.parse_langs, ",".join(list(stt.OMNI_CODES)[:9]), None)
    # A language the LID doesn't know: fine alone, refused in a mix it would have to pick from.
    assert stt.parse_langs("tl", LID) == ["tl"]
    assert "language ID cannot" in _raises(stt.parse_langs, "tl,en", LID)
    # A hostile value comes back bounded.
    assert len(_raises(stt.parse_langs, "x" * 500, LID)) < 300


def test_parse_rate():
    assert stt.parse_rate("") == 16000 and stt.parse_rate("24000") == 24000
    _raises(stt.parse_rate, "44100")
    _raises(stt.parse_rate, "abc")


def test_codes_match_languages_toml():
    # The stack's Omnilingual codes, except Persian (server.py, OMNI_CODES).
    with open(os.path.join(ROOT, "languages.toml"), "rb") as fh:
        cfg = tomllib.load(fh)
    stack = {lang: t["asr"].split(":", 1)[1] for lang, t in cfg.items()
             if isinstance(t, dict) and str(t.get("asr", "")).startswith("omni:")}
    assert stack, "no omni: languages found in languages.toml"
    for lang, code in stack.items():
        want = "fas_Arab" if lang == "fa" else code
        assert stt.OMNI_CODES.get(lang) == want, (lang, stt.OMNI_CODES.get(lang), code)
    for lang in ("en", "fr", "ht", "km", "lo"):
        assert lang in stt.OMNI_CODES


def test_auth():
    assert stt.auth_mode({}) is None
    assert stt.auth_mode({"STT_OPEN": "1"}) == "open"
    assert stt.auth_mode({"STT_TOKEN": "t", "STT_OPEN": "1"}) == "token"     # a token always wins
    env = {"STT_TOKEN": "s3cret"}
    assert stt.subject_for({"Authorization": "Bearer s3cret"}, {}, env) == "static"
    assert stt.subject_for({}, {"token": ["s3cret"]}, env) == "static"
    assert stt.subject_for({"Authorization": "Bearer nope"}, {}, env) is None
    assert stt.subject_for({}, {}, env) is None
    assert stt.subject_for({}, {}, {}) is None                                 # no credential, not open
    assert stt.subject_for({}, {}, {"STT_OPEN": "1"}) == "open"
    # The stack's signed tokens, with STT_SIGNING_KEY.
    sys.path.insert(0, os.path.join(ROOT, "server"))
    import stack_auth
    tok = stack_auth.sign("k", "talk:acct", 60)
    assert stt.subject_for({"Authorization": f"Bearer {tok}"}, {}, {"STT_SIGNING_KEY": "k"}) == "talk:acct"
    assert stt.subject_for({"Authorization": f"Bearer {tok}"}, {}, {"STT_SIGNING_KEY": "other"}) is None


def test_constrained_choice():
    labels = {"en": 0, "fr": 1, "ht": 2, "hi": 3}
    # Log-probabilities, as SpeechBrain returns them: Hindi scores best overall,
    # but the room speaks ht and en, so the choice stays between those.
    logp = np.log(np.array([0.10, 0.25, 0.15, 0.50]))
    lang, conf = stt.constrained_choice(logp, [("ht", 2), ("en", 0)])
    assert lang == "ht" and abs(conf - 0.6) < 1e-6
    lang, conf = stt.constrained_choice(logp, [("ht", 2), ("en", 0), ("fr", 1)])
    assert lang == "fr" and abs(conf - 0.5) < 1e-6
    # Plain probabilities are normalised as they are, not exponentiated.
    lang, conf = stt.constrained_choice(np.array([0.2, 0.0, 0.6, 0.2]), [("en", 0), ("ht", 2)])
    assert lang == "ht" and abs(conf - 0.75) < 1e-6
    assert stt.lid_label_index({"ht: Haitian": 37, "en: English": 20, "starting_index": 0}) == {"ht": 37, "en": 20}
    assert labels  # (the indices above)


def _blocks(seconds, level):
    n = int(seconds * 16000) // 1536
    return [np.full(1536, level, dtype=np.float32) for _ in range(n)]


def _run(seg, blocks):
    out = []
    for b in blocks:
        out += seg.feed(b, 1.0 if b[0] > 0.05 else 0.0)
    return out


def test_segmenter_endpoint():
    seg = stt.Segmenter(endpoint_ms=700, long_s=5.0, long_endpoint_ms=280, max_s=9.0)
    utts = _run(seg, _blocks(2.0, 0.0) + _blocks(2.0, 0.3) + _blocks(1.5, 0.0))
    assert len(utts) == 1
    pcm, start_ms, end_ms = utts[0]
    # Half a second of pre-roll before the speech, the speech, and at most a
    # short tail of the pause.
    assert 1400 <= start_ms <= 1600, start_ms
    assert 3900 <= end_ms <= 4300, end_ms
    assert len(pcm) == (end_ms - start_ms) * 16
    # The next turn's times continue from the stream, not from zero.
    utts = _run(seg, _blocks(1.5, 0.3) + _blocks(1.0, 0.0))
    assert len(utts) == 1 and utts[0][1] >= end_ms


def test_segmenter_forced_cut_and_flush():
    seg = stt.Segmenter(endpoint_ms=700, long_s=5.0, long_endpoint_ms=280, max_s=9.0)
    talk = _blocks(20.0, 0.3)
    utts = _run(seg, talk)
    assert len(utts) == 2                                  # cut at ~9 s, twice
    assert all(len(u[0]) <= 9.1 * 16000 for u in utts)
    assert utts[1][1] == utts[0][2]                        # contiguous: nothing lost at a cut
    rest = seg.flush()
    assert len(rest) == 1 and rest[0][1] == utts[1][2]
    assert seg.flush() == []                               # nothing left
    # A flush during silence sends nothing.
    seg2 = stt.Segmenter()
    _run(seg2, _blocks(1.0, 0.0))
    assert seg2.flush() == []


# ---------------------------------------------------------------- protocol, with fakes

class FakeModels:
    """Language: by the audio's level (0.3 = ht, 0.6 = en). Text: the level, so
    a test can tell whose audio was transcribed."""

    def __init__(self):
        self.lid_index = {c: i for i, c in enumerate(sorted(LID))}
        self.vads = 0

    def new_vad(self):
        self.vads += 1
        return object()

    def identify(self, pcm, langs):
        guess = "ht" if pcm.max() < 0.45 else "en"
        return (guess if guess in langs else langs[0]), (1.0 if len(langs) == 1 else 0.9)

    def transcribe(self, pcm, lang):
        return f"{lang} level {pcm.max():.1f}"


class FakeWS:
    def __init__(self, path, messages, headers=None):
        self.request = type("R", (), {"path": path, "headers": headers or {}})()
        self.messages = list(messages)
        self.sent = []
        self.closed = None
        self.done = asyncio.Event()

    async def send(self, data):
        self.sent.append(json.loads(data))
        if self.sent[-1]["type"] == "flushed":
            self.done.set()

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)
        self.done.set()

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self.messages:
            yield m
            await asyncio.sleep(0)
        # A real client waits for "flushed" before it closes.
        if any(isinstance(m, str) for m in self.messages):
            await asyncio.wait_for(self.done.wait(), 10)


def _pcm(seconds, level, rate=16000):
    return (np.full(int(seconds * rate), level) * 32767).astype("<i2").tobytes()


def _speech(level, rate=16000):
    """A turn: silence, 2 s of 'speech', silence; in ~100 ms messages."""
    audio = _pcm(0.5, 0.0, rate) + _pcm(2.0, level, rate) + _pcm(1.2, 0.0, rate)
    step = rate // 10 * 2
    return [audio[i:i + step] for i in range(0, len(audio), step)]


def _fake_vad():
    import audio_in
    audio_in.vad_block = lambda vad, block: 1.0 if np.abs(block).max() > 0.05 else 0.0


def test_listen_protocol():
    _fake_vad()
    models = FakeModels()
    ws = FakeWS("/listen?langs=ht,en", _speech(0.3) + _speech(0.6) + [json.dumps({"type": "flush"})])
    asyncio.run(stt.handle(ws, models))
    kinds = [m["type"] for m in ws.sent]
    assert ws.sent[0] == {"type": "hello", "langs": ["ht", "en"], "rate": 16000}
    assert kinds == ["hello", "language", "inputTranscript", "language", "inputTranscript", "flushed"], kinds
    a, b = ws.sent[2], ws.sent[4]
    assert ws.sent[1] == {k: v for k, v in a.items() if k not in ("type", "text")} | {"type": "language"}
    assert (a["lang"], a["text"], a["confidence"]) == ("ht", "ht level 0.3", 0.9)
    assert (b["lang"], b["text"]) == ("en", "en level 0.6")
    assert 0 <= a["start_ms"] < a["end_ms"] < b["start_ms"] < b["end_ms"]


def test_listen_transcribes_only_what_is_asked():
    _fake_vad()
    ws = FakeWS("/listen?langs=ht,en&transcribe=ht", _speech(0.6) + _speech(0.3) + [json.dumps({"type": "flush"})])
    asyncio.run(stt.handle(ws, FakeModels()))
    kinds = [m["type"] for m in ws.sent]
    assert kinds == ["hello", "language", "language", "inputTranscript", "flushed"], kinds
    assert ws.sent[1]["lang"] == "en" and "text" not in ws.sent[1]
    assert (ws.sent[3]["lang"], ws.sent[3]["text"]) == ("ht", "ht level 0.3")
    assert stt.parse_transcribe("", ["ht", "en"]) == {"ht", "en"}
    assert stt.parse_transcribe(" HT ", ["ht", "en"]) == {"ht"}
    assert "not in langs: fr" in _raises(stt.parse_transcribe, "ht,fr", ["ht", "en"])


def test_listen_24k_and_one_language():
    _fake_vad()
    ws = FakeWS("/listen?langs=ht&rate=24000", _speech(0.3, 24000) + [json.dumps({"type": "flush"})])
    asyncio.run(stt.handle(ws, FakeModels()))
    assert ws.sent[0]["rate"] == 24000
    t = [m for m in ws.sent if m["type"] == "inputTranscript"]
    assert len(t) == 1 and t[0]["lang"] == "ht" and t[0]["confidence"] == 1.0
    assert t[0]["start_ms"] <= 100 and 2300 <= t[0]["end_ms"] <= 2900, t[0]


def test_listen_bad_requests():
    for path, words in (("/listen", "required"), ("/listen?langs=ht,xx", "not served"),
                        ("/listen?langs=ht&rate=8000", "rate")):
        ws = FakeWS(path, [])
        asyncio.run(stt.handle(ws, FakeModels()))
        assert ws.sent[0]["type"] == "error" and words in ws.sent[0]["detail"], ws.sent
        assert ws.closed[0] == stt.CLOSE_BAD_REQUEST
    ws = FakeWS("/listen?langs=ht", ["not json", json.dumps({"type": "flush"})])
    asyncio.run(stt.handle(ws, FakeModels()))
    assert [m["type"] for m in ws.sent] == ["hello", "error", "flushed"]


def test_guarded_auth_and_path():
    sys.path.insert(0, os.path.join(ROOT, "server"))
    import stack_auth
    stt.LIMITS = stack_auth.Limits(per_client=1, total=1)
    old = dict(os.environ)
    try:
        os.environ.pop("STT_OPEN", None)
        os.environ["STT_TOKEN"] = "s3cret"
        ws = FakeWS("/listen?langs=ht", [])
        asyncio.run(stt.guarded(ws, FakeModels()))
        assert ws.closed[0] == stt.CLOSE_UNAUTHORIZED and not ws.sent
        ws = FakeWS("/other?langs=ht", [], {"Authorization": "Bearer s3cret"})
        asyncio.run(stt.guarded(ws, FakeModels()))
        assert ws.closed[0] == stt.CLOSE_BAD_REQUEST
        ws = FakeWS("/listen?langs=ht", [], {"Authorization": "Bearer s3cret"})
        asyncio.run(stt.guarded(ws, FakeModels()))
        assert ws.sent[0]["type"] == "hello" and stt.LIMITS.live == {}     # admitted, then released
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_streams_do_not_mix():
    # Three connections at once on one set of models: each has its own VAD and
    # hears only its own audio, in order.
    _fake_vad()
    models = FakeModels()
    flush = json.dumps({"type": "flush"})
    wss = [FakeWS("/listen?langs=ht,en", _speech(0.3) + _speech(0.6) + [flush]),
           FakeWS("/listen?langs=ht,en", _speech(0.6) + [flush]),
           FakeWS("/listen?langs=ht", _speech(0.3) + _speech(0.3) + _speech(0.3) + [flush])]

    async def all_at_once():
        await asyncio.gather(*(stt.handle(ws, models) for ws in wss))
    asyncio.run(all_at_once())
    assert models.vads == 3
    texts = [[m["text"] for m in ws.sent if m["type"] == "inputTranscript"] for ws in wss]
    assert texts == [["ht level 0.3", "en level 0.6"], ["en level 0.6"], ["ht level 0.3"] * 3], texts


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
