"""python -m pytest tests/test_editions.py  (needs Python 3.11+; no GPU, no models)

EDITION=both: one server for Lithos Talk (commercial) and Live Translation
(non-profit). Each connection gets the engine set of the edition its token
names: its voices and its translation routing. Recognisers are shared; a
translator or voice configured identically in both editions is one engine; and
a commercial connection can never reach a non-commercial voice or a served
model its edition left out (MiLMMT-46 for Lao)."""
import os
from concurrent.futures import ThreadPoolExecutor

import engines
import licences
import stack_auth
import stack_config as c
from engines import llmmt
from engines.base import Context
from engines.manager import EngineSet
import support
from test_engines import FakeHyMT, FakeMadlad, FakeOmni, FakeWhisper

KEY = "k" * 32
LANGS = ["en", "es", "ko", "ht", "km"]


def _sets(share=True):
    """(nonprofit set, commercial set) as server.py builds them for EDITION=both,
    from the real voice engines, without loading a model."""
    voxcpm_shared = {}
    reg = engines.registry()

    def ctx(ed):
        import copy
        table = copy.deepcopy(c.DEFAULTS)
        return Context(device="cpu", models=c.MODEL_DEFAULTS, table=table, tables=c.tables(table),
                       langs=LANGS, srcs=LANGS,
                       options={"edition": ed, "kokoro": True, "mms": True, "coqui": True, "espeak": True,
                                "voxcpm": "http://127.0.0.1:9", "voxcpm_shared": voxcpm_shared})
    classes = {"recognizer": {"whisper": FakeWhisper, "omni": FakeOmni},
               "translator": {"madlad": FakeMadlad, "hymt": FakeHyMT},
               "voice": dict(reg["voice"])}
    np_set = EngineSet(ctx("nonprofit"), classes=classes)
    commercial = c.apply_edition(c.DEFAULTS, "commercial")[0]
    names = np_set.shareable_voices(commercial) if share else []
    c_set = EngineSet(ctx("commercial"), classes=classes, share_from=np_set, share_voices=names)
    for vs in (np_set, c_set):
        for eng in vs.engines["voice"].values():
            eng.available = True                 # as if loaded
            if eng.name == "piper":
                eng.tts = {l: object() for l in eng.names}
            if eng.name == "espeak":
                eng.langs = set(LANGS)
    return np_set, c_set, names


def _voices(vs, lang):
    return [(e.name, e.setting(lang)) for e in vs.chain(lang)]


def test_tokens_carry_the_edition():
    for ed in ("commercial", "nonprofit", None):
        tok = stack_auth.sign(KEY, "talk:abc", 600, ed=ed)
        assert stack_auth.verify_claims(tok, KEY) == ("talk:abc", ed)
        assert stack_auth.verify(tok, KEY) == "talk:abc"
    # An edition the stack doesn't know makes the token invalid, not a default.
    assert stack_auth.verify_claims(stack_auth.sign(KEY, "x", 600, ed="enterprise"), KEY) == (None, None)
    assert stack_auth.verify_claims("static-secret", KEY, "static-secret") == ("static", None)


def test_connection_edition():
    # stack_auth's, which server.py and services/omni-stt both use. server.py
    # imports heavy libraries at start-up; read its function alone.
    src = open(os.path.join(os.path.dirname(c.__file__), "server.py"), encoding="utf-8").read()
    start = src.index("def connection_edition(")
    end = src.index("\n\n\n", start)
    ns = {}
    exec(src[start:end], ns)
    assert "stack_auth.connection_edition(served, claim)" in src[start:end]
    for ce in (stack_auth.connection_edition, ns["connection_edition"]):
        _check_connection_edition(ce)


def _check_connection_edition(ce):
    both = ["nonprofit", "commercial"]
    assert ce(both, None) == "commercial"            # no claim: the strict one
    assert ce(both, "nonprofit") == "nonprofit"
    assert ce(both, "commercial") == "commercial"
    assert ce(["commercial"], "nonprofit") == "commercial"   # only stricter
    assert ce(["commercial"], None) == "commercial"
    assert ce(["nonprofit"], None) == "nonprofit"     # a non-profit stack's own clients
    assert ce(["nonprofit"], "commercial") is None   # never served non-commercial voices


def test_both_sets_share_recognisers_translators_and_identical_voices():
    np_set, c_set, names = _sets()
    assert c_set.engines["recognizer"] is np_set.engines["recognizer"]
    for name, eng in np_set.engines["translator"].items():   # no llmmt here: every translator is shared
        assert c_set.engines["translator"][name] is eng, name
    assert "kokoro" in names and "espeak" in names
    assert "piper" not in names and "voxcpm" not in names and "mms" not in names
    assert c_set.engines["voice"]["kokoro"] is np_set.engines["voice"]["kokoro"]
    assert c_set.engines["voice"]["piper"] is not np_set.engines["voice"]["piper"]
    # A shared model is locked as one: the two sets share their voice locks.
    assert c_set.voice_lock("en") is np_set.voice_lock("en")
    # VoxCPM2: one engine per edition (different languages), the same services and slots.
    vn, vc = np_set.engines["voice"]["voxcpm"], c_set.engines["voice"]["voxcpm"]
    assert vn is not vc and vn.instances is vc.instances and vn._guard is vc._guard
    assert "ko" in vc.langs and "ko" not in vn.langs


def test_each_edition_hears_its_own_voices():
    np_set, c_set, _ = _sets()
    assert ("piper", "en_US-lessac-medium") in _voices(np_set, "en")
    assert ("piper", "en_US-norman-medium") in _voices(c_set, "en")
    assert ("piper", "en_US-lessac-medium") not in _voices(c_set, "en")
    assert any(n == "mms" for n, _ in _voices(np_set, "ht"))
    assert any(n == "coqui" for n, _ in _voices(c_set, "ht"))
    assert any(n == "voxcpm" for n, _ in _voices(c_set, "ko"))
    assert not any(n == "voxcpm" for n, _ in _voices(np_set, "ko"))


def test_no_commercial_chain_holds_a_noncommercial_voice():
    np_set, c_set, _ = _sets()
    for lang in LANGS:
        for eng in c_set.chain(lang):
            li = licences.lookup(eng.name, eng.setting(lang) if isinstance(eng.setting(lang), str) else None,
                                 cls=type(eng))
            assert li.cls != licences.NONCOMMERCIAL, (lang, eng.name, eng.setting(lang))
    assert "mms" not in c_set.engines["voice"]


def test_share_voices_cannot_smuggle_in_a_noncommercial_engine():
    np_set, _, _ = _sets()
    import copy
    table = copy.deepcopy(c.DEFAULTS)
    ctx = Context(device="cpu", models=c.MODEL_DEFAULTS, table=table, tables=c.tables(table), langs=LANGS,
                  srcs=LANGS, options={"edition": "commercial", "mms": True})
    classes = {"recognizer": {}, "translator": {}, "voice": dict(engines.registry()["voice"])}
    c_set = EngineSet(ctx, classes=classes, share_from=np_set, share_voices=["mms", "kokoro"])
    assert "mms" not in c_set.engines["voice"]


# ---------------------------------------------------------------- translation per edition

GEMMA = "google/gemma-4-31B-it-qat-w4a16-ct"
MILMMT = "xiaomi-research/MiLMMT-46-12B-v0.1"
T_LANGS = ["en", "es", "ht", "lo"]


class Loads:
    """Counts each translator's loads across both sets: a shared model loads once."""
    n = {}


def _counted(cls):
    class Counted(cls):
        def load(self):
            Loads.n[self.name] = Loads.n.get(self.name, 0) + 1
            super().load()
    Counted.__name__ = "Counted" + cls.__name__
    return Counted


class ServedLlm(llmmt.LlmMT):
    """The real llmmt engine (routing, server_for, the per-target batching) with every server up and the
    HTTP call replaced by a record of the model it went to."""
    sent = []

    def load(self):
        Loads.n[self.name] = Loads.n.get(self.name, 0) + 1
        self.pool = ThreadPoolExecutor(max_workers=4)
        self._servers = self._configured()
        self._checks = False
        self._up = {s: True for s in self._servers}
        self.available = True

    def call(self, server, sentence, src, tgt, context=None):
        ServedLlm.sent.append((self.ctx.options["edition"], server[2], src, tgt))
        return f"{server[2].split('/')[0]}({sentence})"

    def ask(self, src, tgt, prompt):
        server = self.server_for(src, tgt)
        ServedLlm.sent.append((self.ctx.options["edition"], server[2], src, tgt))
        return "agreed"


def _translation_sets(reviews=None):
    """(nonprofit set, commercial set) as server.py builds them for EDITION=both, with fake decodes and
    the real llmmt routing; translators loaded the way Pipeline loads them (first set, then the second)."""
    import copy
    Loads.n, ServedLlm.sent = {}, []

    def ctx(ed):
        table = copy.deepcopy(c.DEFAULTS)
        return Context(device="cpu", models=c.MODEL_DEFAULTS, table=table, tables=c.tables(table),
                       langs=T_LANGS, srcs=T_LANGS, options={"edition": ed, "licence_review": reviews or {}})
    classes = {"recognizer": {"whisper": _counted(FakeWhisper), "omni": _counted(FakeOmni)},
               "translator": {"madlad": _counted(FakeMadlad), "hymt": _counted(FakeHyMT), "llmmt": ServedLlm},
               "voice": {}}
    np_set = EngineSet(ctx("nonprofit"), classes=classes)
    np_set.load(["whisper", "omni", "madlad", "hymt", "llmmt"])
    c_set = EngineSet(ctx("commercial"), classes=classes, share_from=np_set, share_voices=[])
    c_set.load(["whisper", "omni", "madlad", "hymt", "llmmt"])
    return np_set, c_set


def _served(vs, text, tgt, src):
    """(translation, [models the llmmt calls went to]) for src -> tgt in this set."""
    ServedLlm.sent = []
    out = vs.translate_batch(text, [tgt], src)[0]
    return out, [m for _, m, _, _ in ServedLlm.sent]


def test_each_edition_translates_by_its_own_table():
    np_set, c_set = _translation_sets()
    # Lao names two servers, MiLMMT-46 (❓) then Gemma 4 (✅). Nonprofit: MiLMMT both ways. Commercial leaves
    # MiLMMT's line out, so Lao's next line, Gemma, serves both ways (not MADLAD into Lao, Hy-MT2 into English).
    for ed_set in (np_set, c_set):
        assert ed_set.translator_for("lo", "en").name == "llmmt", ed_set.edition
        assert ed_set.translator_for("en", "lo").name == "llmmt", ed_set.edition
    assert _served(np_set, "Hello.", "lo", "en")[1] == [MILMMT]
    assert _served(np_set, "ສະບາຍດີ.", "en", "lo")[1] == [MILMMT]
    out, sent = _served(c_set, "Hello.", "lo", "en")
    assert sent == [GEMMA] and out.startswith("google("), out
    assert _served(c_set, "ສະບາຍດີ.", "en", "lo")[1] == [GEMMA]
    # A Lao speaker heard in a Gemma language: the pair goes to Lao's servers (the source side's), the first
    # its edition has and that answers: MiLMMT in nonprofit, Gemma in commercial.
    for tgt in ("es", "ht"):
        assert np_set.translator_for(tgt, "lo").name == "llmmt" and c_set.translator_for(tgt, "lo").name == "llmmt"
        assert _served(np_set, "ສະບາຍດີ.", tgt, "lo")[1] == [MILMMT], tgt
        assert _served(c_set, "ສະບາຍດີ.", tgt, "lo")[1] == [GEMMA], tgt
    # Into Lao from a Gemma language: the source's own line (Gemma) in both, as with one Lao line.
    for ed_set in (np_set, c_set):
        assert _served(ed_set, "Hola.", "lo", "es")[1] == [GEMMA], ed_set.edition
    # Gemma directions: llmmt in both editions.
    for ed_set in (np_set, c_set):
        for src, tgt in (("en", "es"), ("en", "ht"), ("ht", "en"), ("es", "ht")):
            assert ed_set.translator_for(tgt, src).name == "llmmt", (ed_set.edition, src, tgt)
            assert _served(ed_set, "Hello.", tgt, src)[1] == [GEMMA], (ed_set.edition, src, tgt)
    # Nothing commercial ever reached MiLMMT, through any path: its client does not even know the server.
    c_llm = c_set.engines["translator"]["llmmt"]
    assert not any(s[2] == MILMMT for a in T_LANGS for b in T_LANGS for s in c_llm.servers_for(a, b))
    assert c_llm.servers_for("lo", "en") == [llmmt.parse_server(c.GEMMA)]


def test_nonprofit_lao_uses_gemma_while_milmmt_is_down():
    """A nonprofit pod with Gemma only (start-llmmt.sh's auto): Lao's second server line serves, not MADLAD."""
    np_set, _ = _translation_sets()
    llm = np_set.engines["translator"]["llmmt"]
    llm._up[llmmt.parse_server(c.MILMMT)] = False
    for src, tgt in (("en", "lo"), ("lo", "en"), ("lo", "es")):
        assert np_set.translator_for(tgt, src).name == "llmmt", (src, tgt)
        assert _served(np_set, "Hello.", tgt, src)[1] == [GEMMA], (src, tgt)
    llm._up[llmmt.parse_server(c.GEMMA)] = False          # neither answers: the next translator
    assert np_set.translator_for("lo", "en").name == "madlad"
    assert np_set.translator_for("en", "lo").name == "hymt"


def test_translators_and_recognisers_are_shared_not_loaded_twice():
    np_set, c_set = _translation_sets()
    assert c_set.engines["recognizer"] is np_set.engines["recognizer"]
    for name in ("madlad", "hymt"):
        assert c_set.engines["translator"][name] is np_set.engines["translator"][name], name
    # llmmt holds per-language server lines and the editions' differ (Lao's): its own client (no weights).
    assert c_set.engines["translator"]["llmmt"] is not np_set.engines["translator"]["llmmt"]
    assert Loads.n == {"whisper": 1, "omni": 1, "madlad": 1, "hymt": 1, "llmmt": 2}, Loads.n
    # The commercial client knows only the servers its table names.
    assert {s[2] for s in c_set.engines["translator"]["llmmt"]._servers} == {GEMMA}
    assert {s[2] for s in np_set.engines["translator"]["llmmt"]._servers} == {GEMMA, MILMMT}
    # A reviewed MiLMMT-46 makes the tables agree: one llmmt for both, and Lao on it in both.
    np_set, c_set = _translation_sets({"llmmt": "reviewed"})
    assert c_set.engines["translator"]["llmmt"] is np_set.engines["translator"]["llmmt"]
    assert Loads.n["llmmt"] == 1
    assert _served(c_set, "Hello.", "lo", "en")[1] == [MILMMT]


def test_recognition_is_the_same_in_both_editions():
    """What makes sharing the recognisers correct: no language's recognition differs by edition."""
    nonprofit = c.apply_edition(c.DEFAULTS, "nonprofit")[0]
    commercial = c.apply_edition(c.DEFAULTS, "commercial")[0]
    for lang in set(nonprofit) | set(commercial):
        a, b = nonprofit.get(lang, {}), commercial.get(lang, {})
        for key in ["asr"] + list(engines.registry()["recognizer"]):
            assert a.get(key) == b.get(key), (lang, key)


def _pipeline(np_set, c_set):
    """A Pipeline as EDITION=both builds it, without loading anything."""
    server = support.stack_server()
    pipe = server.Pipeline.__new__(server.Pipeline)
    pipe.edition, pipe.editions, pipe.default_edition = "both", ["nonprofit", "commercial"], "commercial"
    pipe.engines = np_set
    pipe.voice_sets = {"nonprofit": np_set, "commercial": c_set}
    return pipe


def test_the_pipeline_translates_in_the_connections_edition():
    pipe = _pipeline(*_translation_sets())
    ServedLlm.sent = []
    pipe.translate_batch("Hello.", ["lo", "es"], "en", None, "nonprofit")
    assert sorted(m for _, m, _, _ in ServedLlm.sent) == sorted([MILMMT, GEMMA])
    for edition in ("commercial", None):   # None: a token naming no edition, served as commercial
        ServedLlm.sent = []
        out = pipe.translate_batch("Hello.", ["lo", "es"], "en", None, edition)
        assert [m for _, m, _, _ in ServedLlm.sent] == [GEMMA, GEMMA] and out[0].startswith("google("), out
        ServedLlm.sent = []
        pipe.translate("ສະບາຍດີ.", "es", "lo", None, edition)
        assert [m for _, m, _, _ in ServedLlm.sent] == [GEMMA]
    # Simultaneous mode's agree policy asks the llmmt client of the connection's edition (en->es: Gemma,
    # a chat server, in both).
    for edition in ("nonprofit", "commercial"):
        ServedLlm.sent = []
        turn = pipe.agree_turn("en", "es", None, edition)
        assert turn is not None
        assert turn.ask("prompt") == "agreed" and ServedLlm.sent == [(edition, GEMMA, "en", "es")], edition


def test_both_edition_in_the_cli_and_plan():
    assert c.editions_of("both") == ["nonprofit", "commercial"]
    assert c.editions_of("commercial") == ["commercial"]
    assert c.edition("both") == "both"
    plan = c.voxcpm_plan("both", [("0", 49000), ("1", 24000)])
    assert len(plan["instances"]) == 2                 # sized as commercial: auto

