"""python3 tests/test_editions.py  (needs Python 3.11+; no GPU, no models)

EDITION=both: one server for Lithos Talk (commercial) and Live Translation
(non-profit). Each connection gets the voice set of the edition its token
names; recognisers and translators are shared; a voice configured identically
in both editions is one engine; and a commercial connection can never reach a
non-commercial voice."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engines  # noqa: E402
import licences  # noqa: E402
import stack_auth  # noqa: E402
import stack_config as c  # noqa: E402
from engines.base import Context  # noqa: E402
from engines.manager import EngineSet  # noqa: E402
from test_engines import FakeHyMT, FakeMadlad, FakeOmni, FakeWhisper  # noqa: E402

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
    # server.py imports heavy libraries at start-up; read the function alone.
    src = open(os.path.join(os.path.dirname(c.__file__), "server.py"), encoding="utf-8").read()
    start = src.index("def connection_edition(")
    end = src.index("\n\n\n", start)
    ns = {}
    exec(src[start:end], ns)
    ce = ns["connection_edition"]
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
    assert c_set.engines["translator"] is np_set.engines["translator"]
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


def test_both_edition_in_the_cli_and_plan():
    assert c.editions_of("both") == ["nonprofit", "commercial"]
    assert c.editions_of("commercial") == ["commercial"]
    assert c.edition("both") == "both"
    plan = c.voxcpm_plan("both", [("0", 49000), ("1", 24000)])
    assert len(plan["instances"]) == 2                 # sized as commercial: auto


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
