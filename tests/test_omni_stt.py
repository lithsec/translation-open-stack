#!/usr/bin/env python3
"""services/omni-stt/server.py without its models: request parsing, auth, the
constrained language choice, endpointing, and the /listen protocol driven by a
fake socket and fake models (several connections at once included).

    python3 tests/test_omni_stt.py      (or python3 -m pytest tests/test_omni_stt.py)

Needs numpy and scipy (the stack's AudioIn), and websockets for the handshake test.
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
    # Cape Verdean Creole: served alone; the language ID has no label for it.
    assert stt.parse_langs("kea", LID) == ["kea"] and stt.OMNI_CODES["kea"] == "kea_Latn"
    assert "language ID cannot" in _raises(stt.parse_langs, "kea,en", LID)
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



def test_token_in_a_subprotocol():
    """A browser cannot set Authorization on a WebSocket: mic.html offers
    "omni-stt" and "bearer.<token>" instead of putting the token in the URL."""
    sys.path.insert(0, os.path.join(ROOT, "server"))
    import stack_auth
    env = {"STT_TOKEN": "s3cret", "STT_SIGNING_KEY": "k"}
    proto = {"Sec-WebSocket-Protocol": "omni-stt, bearer.s3cret"}
    assert stt.presented_token_via(proto, {}) == ("s3cret", "protocol")
    assert stt.subject_for(proto, {}, env) == "static"
    tok = stack_auth.sign("k", "lt:room", 60, ed="nonprofit")          # base64url and a dot: a valid subprotocol
    assert stt.credentials_for({"Sec-WebSocket-Protocol": f"omni-stt, bearer.{tok}"}, {}, env) == ("lt:room", "nonprofit")
    # The header wins over both; the subprotocol over ?token=; ?token= still works (deprecated).
    assert stt.presented_token_via({"Authorization": "Bearer a", **proto}, {"token": ["c"]}) == ("a", "header")
    assert stt.presented_token_via(proto, {"token": ["c"]}) == ("s3cret", "protocol")
    assert stt.presented_token_via({}, {"token": ["c"]}) == ("c", "query")
    assert stt.presented_token_via({}, {}) == ("", "none")
    assert stt.presented_token_via({"Sec-WebSocket-Protocol": "omni-stt, bearer."}, {}) == ("", "none")
    assert stt.subject_for({"Sec-WebSocket-Protocol": "omni-stt, bearer.nope"}, {}, env) is None
    # Every header line counts (websockets' Headers keeps them apart).
    import websockets.datastructures as wsd
    h = wsd.Headers()
    h["Sec-WebSocket-Protocol"] = "omni-stt"
    h["Sec-WebSocket-Protocol"] = "bearer.s3cret"
    assert stt.offered_protocols(h) == ["omni-stt", "bearer.s3cret"]
    assert stt.subject_for(h, {}, env) == "static"
    # The server picks "omni-stt", never the token.
    assert stt.select_subprotocol(None, ["omni-stt", "bearer.s3cret"]) == "omni-stt"
    assert stt.select_subprotocol(None, ["bearer.s3cret"]) is None
    assert stt.select_subprotocol(None, []) is None
    # mic.html sends it that way, and the URL only as a fallback.
    page = open(os.path.join(ROOT, "services", "omni-stt", "mic.html"), encoding="utf-8").read()
    assert 'new WebSocket(url, protocols)' in page and '"bearer." + token' in page
    assert page.count('searchParams.set("token"') == 1 and page.index("catch (e)") < page.index('searchParams.set("token"')


def test_subprotocol_handshake():
    """Through a real websockets server and client: the handshake succeeds,
    the client sees "omni-stt" chosen, the server reads the token from the
    offer; and a client offering nothing still connects."""
    import websockets

    seen = []

    async def handler(ws):
        seen.append((stt.presented_token_via(ws.request.headers, {}), ws.subprotocol))
        await ws.send("hi")

    async def run():
        async with websockets.serve(handler, "127.0.0.1", 0, select_subprotocol=stt.select_subprotocol) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(f"ws://127.0.0.1:{port}/listen",
                                          subprotocols=["omni-stt", "bearer.abc.DEF-_1"]) as c:
                assert await c.recv() == "hi"
                chosen = c.subprotocol
            async with websockets.connect(f"ws://127.0.0.1:{port}/listen") as c:
                assert await c.recv() == "hi"
                assert c.subprotocol is None
        return chosen
    assert asyncio.run(run()) == "omni-stt"
    assert seen == [(("abc.DEF-_1", "protocol"), "omni-stt"), (("", "none"), None)], seen

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


def test_segmenter_defaults():
    # The values Live Translation's latency depends on (README, Endpointing).
    # (200 ms / 10 s / 1 s: eval/2026-10-continuous-ht, the 'breath' run.)
    if not any(k in os.environ for k in ("ENDPOINT_MS", "MAX_UTTERANCE_S", "MIN_SPEECH_MS")):
        assert (stt.ENDPOINT_MS, stt.MAX_UTTERANCE_S, stt.MIN_SPEECH_MS) == (200, 10.0, 1000)
    seg = stt.Segmenter(endpoint_ms=200, max_s=10.0, min_speech_ms=1000)
    assert seg.short_endpoint_ms == 700
    assert seg.cut_window_s == 10.0 / 3                    # a third of the cap, under CUT_WINDOW_S


def test_segmenter_endpoint():
    seg = stt.Segmenter(endpoint_ms=300, max_s=6.0, min_speech_ms=400)
    blocks = _blocks(2.0, 0.0) + _blocks(2.0, 0.3) + _blocks(1.5, 0.0)
    out, ended_at = [], None
    for i, b in enumerate(blocks):
        got = seg.feed(b, 1.0 if b[0] > 0.05 else 0.0)
        if got and ended_at is None:
            ended_at = (i + 1) * 1536 * 1000 // 16000
        out += got
    assert len(out) == 1
    pcm, start_ms, end_ms = out[0]
    # Half a second of pre-roll before the speech, the speech, and at most a
    # short tail of the pause.
    assert 1400 <= start_ms <= 1600, start_ms
    assert 3900 <= end_ms <= 4300, end_ms
    assert len(pcm) == (end_ms - start_ms) * 16
    # Sent ~300 ms after the speech stopped (at ~3.94 s; 96 ms blocks), not 700.
    assert ended_at <= 3940 + 300 + 96, ended_at
    # The next turn's times continue from the stream, not from zero.
    utts = _run(seg, _blocks(1.5, 0.3) + _blocks(1.0, 0.0))
    assert len(utts) == 1 and utts[0][1] >= end_ms


def test_segmenter_clause_pauses_split():
    # Talk with 400 ms breaths between clauses: each clause is its own utterance
    # (the old 700 ms endpoint ran them together until the 9 s cut).
    seg = stt.Segmenter(endpoint_ms=300, max_s=6.0, min_speech_ms=400)
    clause = _blocks(1.5, 0.3) + _blocks(0.4, 0.0)
    utts = _run(seg, _blocks(1.0, 0.0) + clause * 4)
    assert len(utts) == 4, [(u[1], u[2]) for u in utts]


def test_segmenter_forced_cut_and_flush():
    seg = stt.Segmenter(endpoint_ms=300, max_s=6.0, min_speech_ms=400)
    talk = _blocks(20.0, 0.3)
    utts = _run(seg, talk)
    assert len(utts) >= 3                                  # cut by 6 s each time
    assert all(len(u[0]) <= 6.0 * 16000 for u in utts)
    assert all(len(u[0]) >= 3.9 * 16000 for u in utts)     # within the last 2 s, not the live 300 ms
    for a, b in zip(utts, utts[1:]):
        assert b[1] == a[2]                                # contiguous: nothing lost at a cut
    rest = seg.flush()
    assert len(rest) == 1 and rest[0][1] == utts[-1][2]
    assert seg.flush() == []                               # nothing left
    # A flush during silence sends nothing.
    seg2 = stt.Segmenter()
    _run(seg2, _blocks(1.0, 0.0))
    assert seg2.flush() == []


def test_segmenter_forced_cut_at_quietest():
    # No pause the VAD calls quiet, but one softer block at ~4.8 s (a gap
    # between words): the forced cut lands there, not at 6 s mid-word.
    seg = stt.Segmenter(endpoint_ms=300, max_s=6.0, min_speech_ms=400)
    talk = _blocks(7.0, 0.3)
    talk[50] = np.full(1536, 0.1, dtype=np.float32)        # samples 76800..78336
    utts = _run(seg, talk)
    assert len(utts) == 1
    assert 76800 <= len(utts[0][0]) < 78336, len(utts[0][0])


def test_segmenter_short_turn_waits_and_merges():
    seg = stt.Segmenter(endpoint_ms=300, max_s=6.0, min_speech_ms=400)
    # ~0.2 s of speech then 0.5 s of quiet: too little for language ID, so no
    # utterance yet...
    assert _run(seg, _blocks(1.0, 0.0) + _blocks(0.2, 0.3) + _blocks(0.5, 0.0)) == []
    # ...and the speech that follows joins it: one utterance spanning both.
    utts = _run(seg, _blocks(1.5, 0.3) + _blocks(0.5, 0.0))
    assert len(utts) == 1
    pcm, start_ms, end_ms = utts[0]
    assert start_ms <= 600 and end_ms >= 3000, (start_ms, end_ms)
    # A lone short word still goes out, ~700 ms after it ends.
    seg = stt.Segmenter(endpoint_ms=300, max_s=6.0, min_speech_ms=400)
    assert _run(seg, _blocks(1.0, 0.0) + _blocks(0.2, 0.3) + _blocks(0.5, 0.0)) == []
    utts = _run(seg, _blocks(0.3, 0.0))
    assert len(utts) == 1 and len(utts[0][0]) < 16000


# Forced cuts at a pause (pause_cut): synthetic speech probabilities, one per
# 32 ms VAD window (three a 96 ms block), as vad_windows gives the Segmenter.

W = 512                                   # samples per VAD window


def _probs(seconds, dips=(), base=0.95):
    """Window probabilities over `seconds`: base, with (start_s, length_ms, p) dips."""
    p = np.full(int(seconds * 16000) // W, base)
    for start_s, length_ms, low in dips:
        a = int(start_s * 16000) // W
        p[a:a + max(1, round(length_ms * 16 / W))] = low
    return p


def _feed(seg, probs, level=0.3, quiet_level=0.001):
    """Blocks whose samples are loud where the VAD says speech, near-silent in a dip."""
    out, blocks = [], []
    for b in range(len(probs) // 3):
        ps = probs[b * 3:b * 3 + 3]
        block = np.concatenate([np.full(W, level if q > 0.5 else quiet_level, dtype=np.float32) for q in ps])
        blocks.append(block)
        out += seg.feed(block, list(ps))
    return out, np.concatenate(blocks)


def _spans(start_sample, probs):
    return [(start_sample + i * W, start_sample + (i + 1) * W, float(q)) for i, q in enumerate(probs)]


def test_cut_defaults():
    if not any(k in os.environ for k in ("CUT_WINDOW_S", "CUT_DIP_PROB", "CUT_DIP_MS", "CUT_ENDPOINT_MS", "CUT_EARLY_S")):
        assert (stt.CUT_WINDOW_S, stt.CUT_DIP_PROB, stt.CUT_DIP_MS, stt.CUT_ENDPOINT_MS, stt.CUT_EARLY_S) == (3.5, 0.5, 96, 200, 4.0)
    # The window is at most a third of the cap (6 s: the old rule's 2 s).
    assert stt.Segmenter(max_s=15, cut_window_s=3.5).cut_window_s == 3.5
    assert stt.Segmenter(max_s=6, cut_window_s=3.5).cut_window_s == 2.0


def test_pause_cut_longest_dip_in_the_window():
    probs = _probs(15.0, dips=[(10.0, 640, 0.05),         # longest, but before the 3.5 s window
                               (12.0, 160, 0.10),         # the winner: 5 windows
                               (13.5, 96, 0.01),          # deeper but shorter
                               (14.5, 64, 0.0)])          # under CUT_DIP_MS: not a pause
    buf = np.where(np.repeat(probs, W) > 0.5, 0.3, 0.001).astype(np.float32)
    cut = stt.pause_cut(buf, 0, _spans(0, probs), 3.5, 0.5, 96)
    a = int(12.0 * 16000) // W * W
    assert a - 64 * 16 <= cut <= a + 5 * W, (cut, a)
    assert buf[cut] < 0.01                                 # in the quiet, not in a word
    # A stream offset (buf_start) changes nothing but the numbering.
    assert stt.pause_cut(buf, 160000, _spans(160000, probs), 3.5, 0.5, 96) == cut


def test_pause_cut_ties_and_none():
    # Two dips of one length: the lower one wins; equal too: the later one.
    probs = _probs(15.0, dips=[(12.0, 96, 0.2), (13.0, 96, 0.1)])
    buf = np.full(len(probs) * W, 0.3, dtype=np.float32)
    cut = stt.pause_cut(buf, 0, _spans(0, probs), 3.5, 0.5, 96)
    assert 13.0 * 16000 - 2 * W <= cut <= 13.0 * 16000 + 3 * W, cut
    probs = _probs(15.0, dips=[(12.0, 96, 0.1), (13.0, 96, 0.1)])
    cut = stt.pause_cut(buf, 0, _spans(0, probs), 3.5, 0.5, 96)
    assert cut > 12.5 * 16000, cut
    # No window under the threshold for long enough: None (the caller falls back).
    probs = _probs(15.0, dips=[(13.0, 64, 0.1)], base=0.9)
    assert stt.pause_cut(buf, 0, _spans(0, probs), 3.5, 0.5, 96) is None
    soft = _probs(15.0, dips=[(13.0, 160, 0.6)])          # a sag, not under 0.5
    assert stt.pause_cut(buf, 0, _spans(0, soft), 3.5, 0.5, 96) is None
    # A lower threshold or a shorter minimum finds what the defaults would not.
    probs = _probs(15.0, dips=[(13.0, 64, 0.1)])
    assert stt.pause_cut(buf, 0, _spans(0, probs), 3.5, 0.5, 64) is not None
    assert stt.pause_cut(buf, 0, _spans(0, soft), 3.5, 0.7, 96) is not None


def test_pause_cut_never_the_leading_quiet():
    # A buffer that starts with its pre-roll: that quiet is not a pause to cut
    # at (it would send a sliver of silence as an utterance).
    probs = np.concatenate([np.full(15, 0.02), _probs(3.0)])
    buf = np.full(len(probs) * W, 0.3, dtype=np.float32)
    assert stt.pause_cut(buf, 0, _spans(0, probs), 3.5, 0.5, 96) is None


def test_pause_cut_quietest_frame_in_the_dip():
    # The probability lags the audio: the cut is the dip's quietest 20 ms,
    # searched from VAD_LAG_MS before its first low window.
    probs = _probs(15.0, dips=[(13.0, 192, 0.05)])
    buf = np.full(len(probs) * W, 0.3, dtype=np.float32)
    a = int(13.0 * 16000) // W * W
    buf[a - 1024:a - 704] = 0.0                            # the real gap (20 ms), just before the low windows
    buf[a:a + 6 * W] = 0.05
    cut = stt.pause_cut(buf, 0, _spans(0, probs), 3.5, 0.5, 96)
    assert a - 1024 <= cut < a - 704, (cut, a)


def test_segmenter_forced_cut_at_a_pause_keeps_the_rest():
    # 40 s of talk that never pauses for ENDPOINT_MS (700 ms, as live) but dips
    # for 160 ms every ~4 s: every forced cut lands in a dip, the utterances
    # tile the stream exactly (nothing lost, nothing twice), none over the cap.
    dips = [(t, 160, 0.05) for t in np.arange(2.3, 40, 4.1)]
    seg = stt.Segmenter(endpoint_ms=700, max_s=15.0, min_speech_ms=400, cut_endpoint_ms=0)
    probs = _probs(40.0, dips=dips)
    utts, audio = _feed(seg, probs)
    utts += seg.flush()
    assert len(utts) >= 3
    for u, start_ms, end_ms in utts[:-1]:
        assert len(u) <= 15.0 * 16000
        assert np.abs(u[-W // 2:]).max() < 0.01, end_ms   # ends in a dip
        assert any(abs(end_ms / 1000 - (t + 0.08)) < 0.2 for t, _, _ in dips), end_ms
    for (a, _, ae), (b, bs, _) in zip(utts, utts[1:]):
        assert bs == ae
    joined = np.concatenate([u for u, _, _ in utts])
    first = utts[0][1] * 16
    assert np.array_equal(joined, audio[first:first + len(joined)])
    assert first + len(joined) == len(audio)


def test_segmenter_forced_cut_without_a_pause_falls_back():
    # No dip at all: the old rule (the quietest 20 ms of the last 2 s).
    seg = stt.Segmenter(endpoint_ms=700, max_s=15.0, min_speech_ms=400)
    probs = _probs(16.0)
    blocks = [np.full(1536, 0.3, dtype=np.float32) for _ in range(len(probs) // 3)]
    blocks[150][:320] = 0.1                                # samples 230400..230720, at 14.4 s
    utts = []
    for i, b in enumerate(blocks):
        utts += seg.feed(b, list(probs[i * 3:i * 3 + 3]))
    assert len(utts) == 1 and 230400 - 320 < len(utts[0][0]) < 230720, len(utts[0][0])   # (20 ms frames)


def test_segmenter_near_the_cap_a_short_pause_cuts_at_once():
    # A 300 ms pause at 12.5 s (under the 700 ms endpoint, inside the last
    # 3.5 s): cut there right away, in the pause, not at 15 s.
    seg = stt.Segmenter(endpoint_ms=700, max_s=15.0, min_speech_ms=400)
    probs = _probs(20.0, dips=[(12.5, 300, 0.02)])
    out, emitted_at = [], None
    for b in range(len(probs) // 3):
        ps = probs[b * 3:b * 3 + 3]
        block = np.concatenate([np.full(W, 0.3 if q > 0.5 else 0.001, dtype=np.float32) for q in ps])
        got = seg.feed(block, list(ps))
        if got and emitted_at is None:
            emitted_at = seg.total / 16000
        out += got
    assert out and emitted_at < 13.0, emitted_at
    u, start_ms, end_ms = out[0]
    assert 12450 <= end_ms <= 12800, end_ms
    assert np.abs(u[-W // 2:]).max() < 0.01
    # Earlier in the turn the same pause does not end it (700 ms still rules).
    seg = stt.Segmenter(endpoint_ms=700, max_s=15.0, min_speech_ms=400)
    out, _ = _feed(seg, _probs(9.0, dips=[(6.0, 300, 0.02)]))
    assert out == []
    # CUT_ENDPOINT_MS=0: no early cut; the cap cuts back to the pause at 15 s.
    seg = stt.Segmenter(endpoint_ms=700, max_s=15.0, min_speech_ms=400, cut_endpoint_ms=0)
    out, _ = _feed(seg, _probs(15.5, dips=[(12.5, 300, 0.02)]))
    assert len(out) == 1 and 12450 <= out[0][2] <= 12800, out[0][2]


def test_segmenter_cut_window_zero_is_the_old_rule():
    # CUT_WINDOW_S=0: the dip is ignored; the quietest 20 ms of the last 2 s
    # (here a soft spot in a "word", the old rule's mid-word cut).
    probs = _probs(16.0, dips=[(13.9, 160, 0.05)])
    for window, lo, hi in ((0, 220000, 221000), (3.5, 13.8 * 16000, 14.2 * 16000)):
        seg = stt.Segmenter(endpoint_ms=700, max_s=15.0, min_speech_ms=400, cut_window_s=window, cut_endpoint_ms=0)
        blocks, utts = [], []
        for b in range(len(probs) // 3):
            ps = probs[b * 3:b * 3 + 3]
            block = np.full(1536, 0.3, dtype=np.float32)
            if b == 143:
                block[:500] = 0.0                          # samples 219648..220148: quieter than the dip
            utts += seg.feed(block, list(ps))
        assert len(utts) == 1
        n = len(utts[0][0])
        assert (219648 <= n < 220148) if window == 0 else (lo <= n <= hi), (window, n)


# The progressive pause cut (CUT_EARLY_S): past 4 s the quiet that ends a turn
# falls from ENDPOINT_MS to CUT_ENDPOINT_MS at the cap. 700 ms -> 200 ms over
# 4 s -> 15 s here, so a 640 ms pause (the Segmenter counts quiet in whole
# 96 ms blocks: six of them, 576 ms) ends the turn once the line is under
# 576 ms, from 6.7 s on, and never did before.

def _pause_ends_turn(at_s, cut_early_s, **kw):
    """Whether a 640 ms pause at at_s ends a 700 ms / 15 s turn, and where."""
    seg = stt.Segmenter(endpoint_ms=700, max_s=15.0, min_speech_ms=400, cut_early_s=cut_early_s, **kw)
    out, _ = _feed(seg, _probs(at_s + 1.5, dips=[(at_s, 640, 0.02)]))
    assert len(out) <= 1
    return out[0][2] if out else None


def test_progressive_need_ms_line():
    seg = stt.Segmenter(endpoint_ms=700, max_s=15.0, min_speech_ms=400, cut_early_s=4.0)
    seg.speech_ms = 1000
    for seconds, want in ((0, 700), (4.0, 700), (6.4, 700 - 500 * 2.4 / 11), (9.5, 450), (15.0, 200), (20.0, 200)):
        seg.buf = np.zeros(int(seconds * 16000), dtype=np.float32)
        assert abs(seg._need_ms() - want) < 1e-6, (seconds, seg._need_ms())
    seg.speech_ms = 100                                    # too little speech: the short-turn wait
    assert seg._need_ms() == 700


def test_progressive_no_effect_below_cut_early():
    # A 640 ms pause at 3 s (the piece is under 4 s): 700 ms still rules.
    assert _pause_ends_turn(3.0, 4.0) is None
    # And at 4.5 s the line has only just started down (~650 ms): no.
    assert _pause_ends_turn(4.5, 4.0) is None


def test_progressive_shorter_pause_ends_the_turn_before_the_cap():
    # The same pause at 8 s (the line is under 500 ms, the piece well short of
    # the near-cap window): the turn ends there, in the pause, with nothing
    # left over, as a normal end of turn.
    seg = stt.Segmenter(endpoint_ms=700, max_s=15.0, min_speech_ms=400, cut_early_s=4.0)
    out, _ = _feed(seg, _probs(9.5, dips=[(8.0, 640, 0.02)]))
    assert len(out) == 1
    u, start_ms, end_ms = out[0]
    assert 8200 <= end_ms <= 8600, end_ms
    assert np.abs(u[-W // 2:]).max() < 0.01                # ends in the pause
    # The speech after the pause is a new turn that starts right after it
    # (nothing kept back, as a forced cut would), ended here by a 1 s pause.
    more, _ = _feed(seg, _probs(3.5, dips=[(2.0, 1000, 0.02)]))
    assert len(more) == 1 and end_ms <= more[0][1] <= end_ms + 700, (end_ms, more[0][1])


def test_progressive_cap_still_cuts():
    # No pause the line ever reaches (160 ms dips only): the cap cuts at 15 s
    # as before, back to the best dip of the last 3.5 s.
    seg = stt.Segmenter(endpoint_ms=700, max_s=15.0, min_speech_ms=400, cut_early_s=4.0, cut_endpoint_ms=200)
    out, _ = _feed(seg, _probs(16.0, dips=[(13.0, 160, 0.05)]))
    assert len(out) == 1 and 12900 <= out[0][2] <= 13300, out[0][2]
    assert len(seg.buf) > 0                                # the rest starts the next utterance


def test_progressive_disabled():
    # CUT_EARLY_S=0: the 400 ms pause at 8 s does not end the turn...
    assert _pause_ends_turn(8.0, 0) is None
    # ...nor with CUT_ENDPOINT_MS=0 (no floor to fall to), nor when the
    # endpoint is already at the floor (the 200 ms default: nothing to fall from).
    assert _pause_ends_turn(8.0, 4.0, cut_endpoint_ms=0) is None
    seg = stt.Segmenter(endpoint_ms=200, max_s=10.0, min_speech_ms=1000, cut_early_s=4.0)
    seg.speech_ms, seg.buf = 2000, np.zeros(8 * 16000, dtype=np.float32)
    assert seg._need_ms() == 200


# ---------------------------------------------------------------- protocol, with fakes

class FakeModels:
    """Language: by the audio's level (0.3 = ht, 0.6 = en). Text: the level, so
    a test can tell whose audio was transcribed."""

    serve = {"listen"}
    voices = None

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
    # The server's per-window probabilities (vad_windows): three 32 ms windows a block.
    stt.vad_windows = lambda vad, block: [1.0 if np.abs(block).max() > 0.05 else 0.0] * 3


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
    assert stt.parse_transcribe("none", ["ht", "en"]) == set()
    assert stt.parse_transcribe(" None ", ["ht"]) == set()


def test_listen_language_id_only():
    # ?transcribe=none: every utterance gets its language and nothing else (a
    # client that hands Haitian Creole to another recogniser on detection).
    _fake_vad()
    ws = FakeWS("/listen?langs=ht,en&transcribe=none", _speech(0.6) + _speech(0.3) + [json.dumps({"type": "flush"})])
    asyncio.run(stt.handle(ws, FakeModels()))
    kinds = [m["type"] for m in ws.sent]
    assert kinds == ["hello", "language", "language", "flushed"], kinds
    assert [m["lang"] for m in ws.sent[1:3]] == ["en", "ht"]


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



def test_vad_loads_before_any_loader_thread():
    """torch.hub's local load edits sys.path for a moment; an import on another
    thread meanwhile could miss site-packages (ModuleNotFoundError: fairseq2 on
    the 7B service). So no loader thread may be running while VAD loads, with
    STT_PARALLEL_LOAD on (the default) or off."""
    try:
        import torch  # noqa: F401  (Models() imports it)
    except ImportError:
        print("skip: no torch")
        return
    import threading
    seen = []
    saved = {k: getattr(stt, k) for k in ("load_vad", "load_lid", "load_omni")}
    saved_voices = stt.Models._load_voices

    def vad():
        seen.append(("vad", sorted(t.name for t in threading.enumerate() if t.name.endswith("-load"))))
        return "vad"

    def lid(device):
        seen.append(("lid", None))
        return "lid", {"en": 0, "ht": 1}

    def omni(device, card):
        seen.append(("omni", threading.current_thread().name))
        return "omni"

    def voices(self, names):
        seen.append(("voices", None))
        self.voices_ready.set()
    old = os.environ.get("STT_PARALLEL_LOAD")
    try:
        stt.load_vad, stt.load_lid, stt.load_omni = vad, lid, omni
        stt.Models._load_voices = voices
        for parallel in ("1", "0"):
            seen.clear()
            os.environ["STT_PARALLEL_LOAD"] = parallel
            m = stt.Models(device="cpu", card="c", serve={"listen", "speak"}, voice_names=[])
            assert seen[0] == ("vad", []), seen                    # first, and alone
            assert (m.vad, m.lid, m.omni) == ("vad", "lid", "omni")
            assert ("omni", "omni-load" if parallel == "1" else "MainThread") in seen, seen
            m.voices_ready.wait(5)
    finally:
        for k, v in saved.items():
            setattr(stt, k, v)
        stt.Models._load_voices = saved_voices
        if old is None:
            os.environ.pop("STT_PARALLEL_LOAD", None)
        else:
            os.environ["STT_PARALLEL_LOAD"] = old


def test_voices_load_only_after_the_recogniser_is_built():
    """transformers builds a voice under init_empty_weights, which patches
    torch.nn.Module.register_parameter for every thread: a recogniser built at
    the same time came up with meta-device weights and the warm-up crashed
    (2026-10-21). So the voices thread starts only after the recogniser and
    language ID are built (and, with defer_voices, when main says: after warm-up)."""
    try:
        import torch  # noqa: F401  (Models() imports it)
    except ImportError:
        print("skip: no torch")
        return
    import threading
    import time
    saved = {k: getattr(stt, k) for k in ("load_vad", "load_lid", "load_omni")}
    saved_voices = stt.Models._load_voices
    done, at_voices = set(), []

    def lid(device):
        time.sleep(0.05)
        done.add("lid")
        return "lid", {"en": 0, "ht": 1}

    def omni(device, card):
        time.sleep(0.1)             # slower than language ID: the parallel load's last
        done.add("omni")
        return "omni"

    def voices(self, names):
        at_voices.append((set(done), sorted(t.name for t in threading.enumerate() if t.name == "omni-load")))
        self.voices_ready.set()
    old = os.environ.get("STT_PARALLEL_LOAD")
    try:
        stt.load_vad, stt.load_lid, stt.load_omni = (lambda: "vad"), lid, omni
        stt.Models._load_voices = voices
        for parallel in ("1", "0"):
            os.environ["STT_PARALLEL_LOAD"] = parallel
            done.clear(); at_voices.clear()
            m = stt.Models(device="cpu", card="c", serve={"listen", "speak"}, voice_names=[])
            assert m.voices_ready.wait(5)
            assert at_voices == [({"lid", "omni"}, [])], at_voices
            # Deferred (main: Models, warm-up, then start_voices): nothing until asked, once.
            done.clear(); at_voices.clear()
            m = stt.Models(device="cpu", card="c", serve={"listen", "speak"}, voice_names=[], defer_voices=True)
            time.sleep(0.05)
            assert at_voices == [] and not m.voices_ready.is_set()
            m.start_voices().join(5)
            assert at_voices == [({"lid", "omni"}, [])] and m.start_voices() is None
        # /speak only: no recogniser, the voices load at once (and Models waits for them).
        at_voices.clear()
        m = stt.Models(device="cpu", card="c", serve={"speak"}, voice_names=[])
        assert m.voices_ready.is_set() and len(at_voices) == 1
        # /listen only: no voices thread at all.
        at_voices.clear()
        m = stt.Models(device="cpu", card="c", serve={"listen"}, voice_names=[])
        assert m.voices_ready.is_set() and m.start_voices() is None and at_voices == []
    finally:
        for k, v in saved.items():
            setattr(stt, k, v)
        stt.Models._load_voices = saved_voices
        if old is None:
            os.environ.pop("STT_PARALLEL_LOAD", None)
        else:
            os.environ["STT_PARALLEL_LOAD"] = old


def test_backlog_drops_the_oldest_utterance_never_a_flush():
    def u(name):
        return (np.zeros(1600, dtype=np.float32), name, 0)

    def contents(q):
        out = [q.get_nowait() for _ in range(q.qsize())]
        return [x if isinstance(x, str) else x[1] for x in out]

    async def run(start, limit=3):
        q = asyncio.Queue()
        for x in start:
            q.put_nowait(x if x == "flush" else u(x))
        dropped = stt.push_bounded(q, u("new"), limit)
        return (None if dropped is None else dropped[1]), contents(q)
    # Room left: nothing dropped.
    assert asyncio.run(run(["a", "b"])) == (None, ["a", "b", "new"])
    # Full: the oldest utterance goes; the queue stays at the limit.
    assert asyncio.run(run(["a", "b", "c"])) == ("a", ["b", "c", "new"])
    # A flush at the head keeps its place (it was once re-queued behind newer
    # utterances, which made the queue outgrow the limit and "flushed" late).
    assert asyncio.run(run(["flush", "a", "b"])) == ("a", ["flush", "b", "new"])
    assert asyncio.run(run(["a", "flush", "b"])) == ("a", ["flush", "b", "new"])
    assert asyncio.run(run(["a", "b", "flush"])) == ("a", ["b", "flush", "new"])
    # Nothing but flushes: nothing to drop.
    assert asyncio.run(run(["flush"] * 3)) == (None, ["flush"] * 3 + ["new"])

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
