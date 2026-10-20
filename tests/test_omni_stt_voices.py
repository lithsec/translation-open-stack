#!/usr/bin/env python3
"""services/omni-stt's voices without their models: Haitian Creole numbers in
words (ht_numbers.py), the text cut for synthesis (voices.py), and the /speak
protocol driven by a fake socket and a fake voice.

    python3 tests/test_omni_stt_voices.py   (or python3 -m pytest tests/test_omni_stt_voices.py)

Needs numpy and scipy (server.py's imports), nothing else.
"""
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "omni-stt"))
import ht_numbers as hn  # noqa: E402
import server as stt  # noqa: E402
import voices as vc  # noqa: E402
# (server.py has put the stack's server/ on the path, behind omni-stt's own server.py.)


# ---------------------------------------------------------------- numbers

def test_units_and_teens():
    assert [hn.words(n) for n in range(20)] == [
        "zewo", "en", "de", "twa", "kat", "senk", "sis", "sèt", "uit", "nèf",
        "dis", "onz", "douz", "trèz", "katòz", "kenz", "sèz", "disèt", "dizuit", "diznèf"]


def test_tens():
    want = {20: "ven", 21: "venteyen", 22: "vennde", 23: "venntwa", 25: "vennsenk", 27: "vennsèt",
            28: "ventuit", 29: "ventnèf", 30: "trant", 31: "tranteyen", 33: "tranntwa", 38: "trantuit",
            40: "karant", 41: "karanteyen", 45: "karannsenk", 46: "karannsis", 50: "senkant",
            51: "senkanteyen", 59: "senkantnèf", 60: "swasant", 61: "swasanteyen", 62: "swasannde",
            69: "swasantnèf", 70: "swasanndis", 71: "swasanteyonz", 72: "swasanndouz", 77: "swasanndisèt",
            79: "swasanndiznèf", 80: "katreven", 81: "katrevenen", 82: "katrevende", 89: "katrevennèf",
            90: "katrevendis", 91: "katrevenonz", 95: "katrevenkenz", 99: "katrevendiznèf"}
    for n, w in want.items():
        assert hn.words(n) == w, (n, hn.words(n), w)


def test_hundreds_thousands_millions():
    want = {100: "san", 101: "san en", 121: "san venteyen", 200: "de san", 500: "sen san",
            600: "si san", 640: "si san karant", 800: "ui san", 999: "nèf san katrevendiznèf",
            1000: "mil", 1001: "mil en", 2000: "de mil", 5000: "sen mil", 6000: "si mil", 8000: "ui mil",
            10000: "di mil", 17000: "disèt mil", 21000: "venteyen mil", 100000: "san mil",
            600000: "si san mil", 999999: "nèf san katrevendiznèf mil nèf san katrevendiznèf",
            1000000: "yon milyon", 2500000: "de milyon sen san mil", 1000000000: "yon milya"}
    for n, w in want.items():
        assert hn.words(n) == w, (n, hn.words(n), w)
    for n in (-1, 10 ** 12):
        try:
            hn.words(n)
        except ValueError:
            continue
        raise AssertionError(n)


def test_every_number_to_a_million_is_words():
    """No digits left, no empty or doubled spaces, letters the voices know."""
    alphabet = set("abcdefghijklmnopqrstuvwxyzàèéëìíïòóü ")       # Coqui OpenBible's characters
    for n in list(range(0, 2000)) + list(range(2000, 1000000, 997)):
        w = hn.words(n)
        assert w and "  " not in w and w == w.strip() and set(w) <= alphabet, (n, w)


def test_years():
    assert hn.spell_numbers("ane 1804") == "ane mil ui san kat"
    assert hn.spell_numbers("an 2026") == "an de mil vennsis"


def test_ordinals():
    want = {1: "premye", 2: "dezyèm", 3: "twazyèm", 4: "katriyèm", 5: "senkyèm", 6: "sizyèm",
            7: "setyèm", 8: "uityèm", 9: "nevyèm", 10: "dizyèm", 11: "onzyèm", 20: "ventyèm",
            100: "santyèm", 1000: "milyèm"}
    for n, w in want.items():
        assert hn.ordinal(n) == w, (n, hn.ordinal(n), w)
    assert hn.spell_numbers("1e fwa, 2yèm fwa, 3e jou, 1er janvye") == "premye fwa, dezyèm fwa, twazyèm jou, premye janvye"


def test_spell_numbers_in_text():
    s = hn.spell_numbers
    assert s("600 moun te la.") == "si san moun te la."
    assert s("Jan 3:16 di sa.") == "Jan twa, sèz di sa."
    assert s("Li te 8:00 nan maten, 10:30 aswè.") == "Li te uit nan maten, dis, trant aswè."
    assert s("3,500 goud; 3,5 kilo; 2.75 mèt") == "twa mil sen san goud; twa pwen senk kilo; de pwen swasannkenz mèt"
    assert s("1 000 moun, 1 000, 1 000, 1.000.000") == "mil moun, mil, mil, yon milyon"
    assert s("ane 2026 300 moun") == "ane de mil vennsis twa san moun"     # two numbers, not one
    assert s("10% ak $5 oswa 20 $") == "dis pousan ak senk dola oswa ven dola"
    assert s("Rele 0612.") == "Rele zewo sis en de."
    assert s("1234567890123") == "en de twa kat senk sis sèt uit nèf zewo en de twa"
    assert s("Sòm 23, vèsè 4") == "Sòm venntwa, vèsè kat"
    assert s("Pa gen chif isit.") == "Pa gen chif isit."
    assert s("A1 ak 4x4") == "A1 ak 4x4"      # inside a word: left alone


# ---------------------------------------------------------------- text for the voices

def test_pieces_split_sentences_and_long_ones():
    assert vc.pieces("Bonjou tout moun. Kijan nou ye? Mwen byen.") == ["Bonjou tout moun.", "Kijan nou ye?", "Mwen byen."]
    long = ", ".join(["mo sa a ak lòt mo yo"] * 20) + "."
    out = vc.pieces(long)
    assert len(out) > 1 and all(len(p) <= vc.MAX_PIECE_CHARS for p in out)
    assert " ".join(out) == long
    words = " ".join(["mo"] * 300)
    out = vc.pieces(words)
    assert all(len(p) <= vc.HARD_PIECE_CHARS for p in out) and " ".join(out) == words


def test_prepare_spells_numbers():
    assert vc.prepare("Nou gen 600 moun.") == ["Nou gen si san moun."]


def test_parse_voice():
    assert vc.parse_voice("", "coqui") == "coqui"
    assert vc.parse_voice(" MMS ", "coqui") == "mms"
    try:
        vc.parse_voice("gemini", "coqui")
    except ValueError:
        return
    raise AssertionError("gemini accepted")


def test_default_voice():
    assert stt.default_voice(["mms", "coqui"], {}) == "coqui"
    assert stt.default_voice(["mms", "coqui"], {"HT_VOICE": "mms"}) == "mms"
    assert stt.default_voice(["mms"], {"HT_VOICE": "coqui"}) == "mms"
    assert stt.served({}) == {"listen", "speak"}
    assert stt.served({"STT_SERVE": "speak"}) == {"speak"}


# ---------------------------------------------------------------- /speak protocol

class FakeVoices:
    """1 ms of PCM per character, so a test can tell which piece was spoken."""
    names = ["mms", "coqui"]

    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)

    def synthesise(self, name, piece):
        self.calls.append((name, piece))
        if piece in self.fail:
            return None
        return b"\x01\x00" * 24 * len(piece)


class FakeWS:
    def __init__(self, path, messages, headers=None):
        self.request = type("R", (), {"path": path, "headers": headers or {}})()
        self.messages = list(messages)
        self.sent = []
        self.closed = None

    async def send(self, data):
        self.sent.append(data if isinstance(data, bytes) else json.loads(data))

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self.messages:
            yield m
            await asyncio.sleep(0)


def _speak(**kw):
    return json.dumps({"type": "speak", **kw})


def _json(ws):
    return [m for m in ws.sent if not isinstance(m, bytes)]


def test_speak_protocol():
    voices = FakeVoices()
    ws = FakeWS("/speak", [_speak(text="Nou gen 600 moun. Bondye beni nou.", id="a"),
                           _speak(text="Mèsi.", voice="mms", id=7)])
    asyncio.run(stt.handle_speak(ws, voices, env={"EDITION": "nonprofit"}))
    msgs = _json(ws)
    assert msgs[0] == {"type": "hello", "lang": "ht", "voices": ["mms", "coqui"], "voice": "coqui", "rate": 24000,
                       "edition": "nonprofit"}
    assert voices.calls == [("coqui", "Nou gen si san moun."), ("coqui", "Bondye beni nou."), ("mms", "Mèsi.")]
    first = ws.sent.index(msgs[1])
    assert msgs[1] == {"type": "sentence", "id": "a", "index": 0, "bytes": 48 * len("Nou gen si san moun.")}
    assert isinstance(ws.sent[first + 1], bytes)
    assert msgs[2] == {"type": "sentence", "id": "a", "index": 1, "bytes": 48 * len("Bondye beni nou.")}
    done = [m for m in msgs if m["type"] == "done"]
    assert [d["id"] for d in done] == ["a", "7"] and [d["voice"] for d in done] == ["coqui", "mms"]
    assert done[0]["sentences"] == 2 and done[0]["audio_ms"] == len("Nou gen si san moun.Bondye beni nou.")
    assert done[0]["first_audio_ms"] is not None


def test_speak_frames_are_at_most_a_second():
    voices = FakeVoices()
    text = "a" * 2000
    ws = FakeWS("/speak", [_speak(text=text)])
    asyncio.run(stt.handle_speak(ws, voices, env={}))
    frames = [m for m in ws.sent if isinstance(m, bytes)]
    assert sum(map(len, frames)) == 48 * 2000 and max(map(len, frames)) <= stt.SPEAK_FRAME_BYTES


def test_speak_voice_from_query_and_env():
    ws = FakeWS("/speak?voice=mms", [])
    asyncio.run(stt.handle_speak(ws, FakeVoices(), env={"HT_VOICE": "coqui", "EDITION": "nonprofit"}))
    assert ws.sent[0]["voice"] == "mms"
    ws = FakeWS("/speak", [])
    asyncio.run(stt.handle_speak(ws, FakeVoices(), env={"HT_VOICE": "mms", "EDITION": "nonprofit"}))
    assert ws.sent[0]["voice"] == "mms"
    ws = FakeWS("/speak?voice=gemini", [])
    asyncio.run(stt.handle_speak(ws, FakeVoices(), env={}))
    assert ws.sent[0]["type"] == "error" and ws.closed[0] == stt.CLOSE_BAD_REQUEST


def test_each_voice_has_its_own_thread():
    """Two slow Coqui requests (two sockets) must not hold up an MMS one."""
    import threading
    import time
    release = threading.Event()

    class Slow(FakeVoices):
        def synthesise(self, name, piece):
            if name == "coqui":
                release.wait(5)
            return super().synthesise(name, piece)
    voices = Slow()
    assert stt.voice_pool("mms") is stt.voice_pool("mms") is not stt.voice_pool("coqui")

    async def run():
        async def nothing(m):
            return None
        coqui = [asyncio.create_task(stt.speak_one(voices, "coqui", "Wi.", None, nothing)) for _ in range(2)]
        await asyncio.sleep(0.05)
        t0 = time.monotonic()
        said = await asyncio.wait_for(stt.speak_one(voices, "mms", "Mèsi.", None, nothing), 2)
        took = time.monotonic() - t0
        release.set()
        await asyncio.gather(*coqui)
        return said, took
    said, took = asyncio.run(run())
    assert said == (1, len("Mèsi.")) and took < 1.0, (said, took)


def test_speak_bad_requests_keep_the_socket():
    voices = FakeVoices(fail={"Non."})
    ws = FakeWS("/speak", [b"\x00\x00", "not json", json.dumps({"type": "flush"}), _speak(text="  "),
                           _speak(text="x" * (stt.SPEAK_MAX_CHARS + 1)), _speak(text="Hi", voice="nope"),
                           _speak(text="Non.", id="f"), _speak(text="Wi.", id="ok")])
    asyncio.run(stt.handle_speak(ws, voices, env={}))
    msgs = _json(ws)[1:]
    errors = [m for m in msgs if m["type"] == "error"]
    assert len(errors) == 7, msgs
    assert errors[-1] == {"type": "error", "id": "f", "detail": "the voice could not say that"}
    done = [m for m in msgs if m["type"] == "done"]
    assert [(d["id"], d["sentences"]) for d in done] == [("f", 0), ("ok", 1)]
    assert ws.closed is None


def test_guarded_routes_speak():
    import stack_auth

    class M:
        serve = {"listen", "speak"}
        voices = FakeVoices()
        lid_index = {}

    stt.LIMITS = stack_auth.Limits(per_client=1, total=1)
    stt.SPEAK_LIMITS = stack_auth.Limits(per_client=1, total=1)
    old = dict(os.environ)
    try:
        os.environ.pop("STT_OPEN", None)
        os.environ["STT_TOKEN"] = "s3cret"
        os.environ.pop("HT_VOICE", None)
        ws = FakeWS("/speak", [])
        asyncio.run(stt.guarded(ws, M()))
        assert ws.closed[0] == stt.CLOSE_UNAUTHORIZED and not ws.sent
        ws = FakeWS("/speak", [_speak(text="Wi.")], {"Authorization": "Bearer s3cret"})
        asyncio.run(stt.guarded(ws, M()))
        assert ws.sent[0]["type"] == "hello" and _json(ws)[-1]["type"] == "done"
        assert stt.SPEAK_LIMITS.live == {} and stt.LIMITS.live == {}
        # Not served: refused like an unknown path.
        M.serve = {"listen"}
        ws = FakeWS("/speak", [], {"Authorization": "Bearer s3cret"})
        asyncio.run(stt.guarded(ws, M()))
        assert ws.closed[0] == stt.CLOSE_BAD_REQUEST
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_speak_waits_for_the_voices_and_refuses_without_them():
    import threading
    import stack_auth

    class M:
        serve = {"listen", "speak"}
        voices = None
        lid_index = {}

        def __init__(self):
            self.voices_ready = threading.Event()

    stt.SPEAK_LIMITS = stack_auth.Limits(per_client=1, total=1)
    old = dict(os.environ)
    try:
        os.environ.pop("STT_TOKEN", None)
        os.environ["STT_OPEN"] = "1"
        os.environ.pop("HT_VOICE", None)
        m = M()

        def loaded():
            m.voices = FakeVoices()
            m.voices_ready.set()
        threading.Timer(0.2, loaded).start()
        ws = FakeWS("/speak", [_speak(text="Wi.")])
        asyncio.run(stt.guarded(ws, m))
        assert ws.sent[0]["type"] == "hello" and _json(ws)[-1]["type"] == "done"
        m = M()
        m.voices_ready.set()          # loaded, and failed
        ws = FakeWS("/speak", [])
        asyncio.run(stt.guarded(ws, m))
        assert ws.sent[0]["type"] == "error" and ws.closed[0] == stt.CLOSE_UNAVAILABLE
        assert stt.SPEAK_LIMITS.live == {}
    finally:
        os.environ.clear()
        os.environ.update(old)


# ---------------------------------------------------------------- editions

KEY = "k" * 32


def test_editions_from_env():
    assert stt.service_editions({}) == ["commercial"]                  # safe by default
    assert stt.service_editions({"EDITION": "nonprofit"}) == ["nonprofit"]
    assert stt.service_editions({"EDITION": "both"}) == ["nonprofit", "commercial"]
    try:
        stt.service_editions({"EDITION": "everything"})
    except SystemExit:
        return
    raise AssertionError("a bad EDITION accepted")


def test_licences_come_from_the_stack():
    import licences
    assert vc.licence("mms").cls == licences.NONCOMMERCIAL
    assert vc.licence("coqui").cls == licences.SHARE_ALIKE
    assert vc.permitted(["mms", "coqui"], "commercial") == ["coqui"]
    assert vc.permitted(["mms", "coqui"], "nonprofit") == ["mms", "coqui"]


def test_commercial_never_loads_mms():
    assert stt.voice_list({}) == ["coqui"]
    assert stt.voice_list({"EDITION": "commercial"}) == ["coqui"]
    assert stt.voice_list({"EDITION": "nonprofit"}) == ["mms", "coqui"]
    assert stt.voice_list({"EDITION": "both"}) == ["mms", "coqui"]
    assert stt.voice_list({"EDITION": "nonprofit", "STT_VOICES": "mms"}) == ["mms"]
    assert stt.voice_list({"STT_VOICES": "coqui"}) == ["coqui"]
    for env in ({"STT_VOICES": "mms"}, {"EDITION": "commercial", "STT_VOICES": "mms,coqui"}):
        try:
            stt.voice_list(env)
        except SystemExit as e:
            assert "mms" in str(e) and "commercial" in str(e)
            continue
        raise AssertionError(f"{env} loaded MMS")


def test_commercial_speak_offers_and_speaks_only_permitted_voices():
    voices = FakeVoices()
    env = {"EDITION": "both", "HT_VOICE": "mms"}           # HT_VOICE forbidden for this connection
    ws = FakeWS("/speak", [_speak(text="Wi.", voice="mms", id="x"), _speak(text="Non.", id="y")])
    asyncio.run(stt.handle_speak(ws, voices, env=env, edition="commercial"))
    msgs = _json(ws)
    assert msgs[0] == {"type": "hello", "lang": "ht", "voices": ["coqui"], "voice": "coqui", "rate": 24000,
                       "edition": "commercial"}
    assert msgs[1] == {"type": "error", "detail": "voice mms is not available in the commercial edition"}
    assert voices.calls == [("coqui", "Non.")]                # never MMS, and the socket carried on
    assert ws.closed is None
    # Asked for at connect: refused, not swapped for another voice.
    ws = FakeWS("/speak?voice=mms", [_speak(text="Wi.")])
    asyncio.run(stt.handle_speak(ws, FakeVoices(), env=env, edition="commercial"))
    assert ws.sent == [{"type": "error", "detail": "voice mms is not available in the commercial edition"}]
    assert ws.closed[0] == stt.CLOSE_BAD_REQUEST
    # No edition passed: as a token without a claim (commercial when served).
    ws = FakeWS("/speak", [])
    asyncio.run(stt.handle_speak(ws, FakeVoices(), env={"EDITION": "both"}))
    assert ws.sent[0]["voices"] == ["coqui"] and ws.sent[0]["edition"] == "commercial"


def test_no_permitted_voice_closes_with_4403():
    class OnlyMMS(FakeVoices):
        names = ["mms"]
    ws = FakeWS("/speak", [_speak(text="Wi.")])
    voices = OnlyMMS()
    asyncio.run(stt.handle_speak(ws, voices, env={}, edition="commercial"))
    assert ws.sent[0]["type"] == "error" and ws.closed[0] == stt.CLOSE_EDITION and voices.calls == []


def test_connection_edition_matches_the_stack():
    import stack_auth
    ce = stack_auth.connection_edition
    both = ["nonprofit", "commercial"]
    assert [ce(both, c) for c in (None, "nonprofit", "commercial")] == ["commercial", "nonprofit", "commercial"]
    assert [ce(["commercial"], c) for c in (None, "nonprofit", "commercial")] == ["commercial"] * 3
    assert [ce(["nonprofit"], c) for c in (None, "nonprofit", "commercial")] == ["nonprofit", "nonprofit", None]


def test_credentials_carry_the_edition_claim():
    import stack_auth
    env = {"STT_SIGNING_KEY": KEY, "STT_TOKEN": "s3cret"}
    for ed in ("nonprofit", "commercial", None):
        tok = stack_auth.sign(KEY, "lt:room", 600, ed=ed)
        assert stt.credentials_for({"Authorization": f"Bearer {tok}"}, {}, env) == ("lt:room", ed)
    assert stt.credentials_for({"Authorization": "Bearer s3cret"}, {}, env) == ("static", None)
    assert stt.credentials_for({}, {}, {"STT_OPEN": "1"}) == ("open", None)
    bad = stack_auth.sign(KEY, "x", 600)[:-2] + "AA"
    assert stt.credentials_for({"Authorization": f"Bearer {bad}"}, {}, env) == (None, None)


def test_nonprofit_static_token():
    import stack_auth
    env = {"STT_SIGNING_KEY": KEY, "STT_TOKEN": "s3cret", "STT_TOKEN_NONPROFIT": "np-s3cret"}
    np_sub = stt.NONPROFIT_SUBJECT
    assert stt.credentials_for({"Authorization": "Bearer np-s3cret"}, {}, env) == (np_sub, "nonprofit")
    assert stt.credentials_for({}, {"token": ["np-s3cret"]}, env) == (np_sub, "nonprofit")
    # The others are unchanged beside it: the old static token is still served, without an edition.
    assert stt.credentials_for({"Authorization": "Bearer s3cret"}, {}, env) == ("static", None)
    tok = stack_auth.sign(KEY, "talk:worker", 600, ed="commercial")
    assert stt.credentials_for({"Authorization": f"Bearer {tok}"}, {}, env) == ("talk:worker", "commercial")
    for wrong in ("np-s3cre", "np-s3cretx", "NP-S3CRET", ""):
        assert stt.credentials_for({"Authorization": f"Bearer {wrong}"}, {}, env) == (None, None), wrong
    # It alone is a credential (the server starts, and is not open).
    only = {"STT_TOKEN_NONPROFIT": "np-s3cret"}
    assert stt.auth_mode(only) == "token" and stt.auth_mode({"STT_TOKEN_NONPROFIT": "  "}) is None
    assert stt.credentials_for({"Authorization": "Bearer np-s3cret"}, {}, only) == (np_sub, "nonprofit")
    assert stt.credentials_for({"Authorization": "Bearer s3cret"}, {}, only) == (None, None)
    # One token for both editions is refused at startup.
    stt.check_credentials(env)
    stt.check_credentials({"STT_TOKEN_NONPROFIT": "x"})
    try:
        stt.check_credentials({"STT_TOKEN": "same", "STT_TOKEN_NONPROFIT": " same"})
    except SystemExit as e:
        assert "must differ" in str(e)
    else:
        raise AssertionError("the same static token for both editions was accepted")


def _hello(edition_env, token):
    """guarded() on /speak with FakeVoices (both loaded): the first message, and the close."""
    import stack_auth

    class M:
        serve = {"listen", "speak"}
        voices = FakeVoices()
        lid_index = {}

    stt.SPEAK_LIMITS = stack_auth.Limits(per_client=2, total=2)
    old = dict(os.environ)
    try:
        for k in ("STT_OPEN", "HT_VOICE", "STT_VOICES", "EDITION"):
            os.environ.pop(k, None)
        os.environ.update({"STT_SIGNING_KEY": KEY, "STT_TOKEN": "s3cret"})
        if edition_env:
            os.environ["EDITION"] = edition_env
        ws = FakeWS("/speak", [], {"Authorization": f"Bearer {token}"})
        asyncio.run(stt.guarded(ws, M()))
        assert stt.SPEAK_LIMITS.live == {}
        return (ws.sent[0] if ws.sent else None), ws.closed
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_guarded_serves_each_token_in_its_edition():
    import stack_auth
    tok = lambda ed: stack_auth.sign(KEY, "talk:acct", 600, ed=ed)       # noqa: E731
    # EDITION=both: the claim decides; none (or the static token): commercial.
    assert _hello("both", tok("nonprofit"))[0]["voices"] == ["mms", "coqui"]
    assert _hello("both", tok("commercial"))[0]["voices"] == ["coqui"]
    assert _hello("both", tok(None))[0]["voices"] == ["coqui"]
    assert _hello("both", "s3cret")[0]["voices"] == ["coqui"]
    # Unset EDITION is commercial: a non-profit token gets the stricter voices.
    hello, _ = _hello(None, tok("nonprofit"))
    assert hello["voices"] == ["coqui"] and hello["edition"] == "commercial"
    # A non-profit-only server: a commercial token is refused, and so is one
    # without a claim (the static STT_TOKEN, a signed token naming none): those
    # are commercial, never upgraded to MMS.
    hello, closed = _hello("nonprofit", tok("commercial"))
    assert hello is None and closed[0] == stt.CLOSE_EDITION
    for claimless in ("s3cret", tok(None)):
        hello, closed = _hello("nonprofit", claimless)
        assert hello is None and closed[0] == stt.CLOSE_EDITION, claimless
    assert _hello("nonprofit", tok("nonprofit"))[0]["voices"] == ["mms", "coqui"]


def test_speak_edition():
    both = ["nonprofit", "commercial"]
    se = stt.speak_edition
    # A claim: the stack's rule (stack_auth.connection_edition).
    assert [se(both, c) for c in ("nonprofit", "commercial")] == ["nonprofit", "commercial"]
    assert [se(["commercial"], c) for c in ("nonprofit", "commercial")] == ["commercial", "commercial"]
    assert [se(["nonprofit"], c) for c in ("nonprofit", "commercial")] == ["nonprofit", None]
    # No claim: commercial, wherever that is served; refused where it is not.
    assert se(both, None) == "commercial" and se(["commercial"], None) == "commercial"
    assert se(["nonprofit"], None) is None
    # An open server (no credential at all, a laptop test): as before.
    assert se(["nonprofit"], None, open_server=True) == "nonprofit"
    assert se(both, None, open_server=True) == "commercial"


def test_open_nonprofit_server_still_speaks_mms():
    import stack_auth

    class M:
        serve = {"listen", "speak"}
        voices = FakeVoices()
        lid_index = {}
    stt.SPEAK_LIMITS = stack_auth.Limits(per_client=1, total=1)
    old = dict(os.environ)
    try:
        for k in ("STT_TOKEN", "STT_TOKEN_NONPROFIT", "STT_SIGNING_KEY", "HT_VOICE", "STT_VOICES"):
            os.environ.pop(k, None)
        os.environ.update({"STT_OPEN": "1", "EDITION": "nonprofit"})
        ws = FakeWS("/speak", [])
        asyncio.run(stt.guarded(ws, M()))
        assert ws.sent[0]["voices"] == ["mms", "coqui"] and ws.sent[0]["edition"] == "nonprofit"
    finally:
        os.environ.clear()
        os.environ.update(old)



def test_guarded_serves_the_nonprofit_token_as_nonprofit():
    old = os.environ.get("STT_TOKEN_NONPROFIT")
    os.environ["STT_TOKEN_NONPROFIT"] = "np-s3cret"
    try:
        hello, _ = _hello("both", "np-s3cret")
        assert hello["voices"] == ["mms", "coqui"] and hello["edition"] == "nonprofit"
        # The old static token beside it stays commercial.
        hello, _ = _hello("both", "s3cret")
        assert hello["voices"] == ["coqui"] and hello["edition"] == "commercial"
        # A commercial-only server gives it the stricter voices, as for a signed non-profit token.
        hello, _ = _hello(None, "np-s3cret")
        assert hello["voices"] == ["coqui"] and hello["edition"] == "commercial"
        # A non-profit-only server serves it.
        assert _hello("nonprofit", "np-s3cret")[0]["edition"] == "nonprofit"
    finally:
        os.environ.pop("STT_TOKEN_NONPROFIT", None)
        if old is not None:
            os.environ["STT_TOKEN_NONPROFIT"] = old


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
