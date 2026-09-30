#!/usr/bin/env python3
"""The engine plug-ins: registry, languages.toml validation, and the routing
EngineSet does (recogniser, translator, voice chain). No GPU, no models, no
numpy: engines are stood in for by small fakes, and MADLAD's decode by a
function that echoes its prompt.

The routing tests compare EngineSet with REFERENCE copies of the code it
replaced (Pipeline.translate_batch and Pipeline.synthesise in server.py before
the engines refactor, 2026-09-29), so a change of behaviour shows up here, not
on a GPU.

    python3 tests/test_engines.py        (or python3 -m pytest tests/test_engines.py)
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

import engines  # noqa: E402
import stack_config as c  # noqa: E402
from engines.base import Context, Recognizer, Translator, Voice, AudioStream  # noqa: E402
from engines.common import split_sentences, NO_SPACE_JOIN  # noqa: E402
from engines.hymt import HyMT, HYMT_NAMES  # noqa: E402
from engines.madlad import Madlad  # noqa: E402
from engines.manager import EngineSet  # noqa: E402

FIXTURE = os.path.join(HERE, "engines_fixture")


def _write(text):
    fd, path = tempfile.mkstemp(suffix=".toml")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


# ---------------------------------------------------------------- registry

def test_builtin_engines_registered():
    reg = engines.registry()
    assert set(reg["recognizer"]) == {"whisper", "omni"}
    assert {"madlad", "hymt", "echo"} <= set(reg["translator"])
    assert set(reg["voice"]) == {"kokoro", "voxcpm", "coqui", "piper", "mms", "cosyvoice", "espeak"}
    for kind, r in reg.items():
        for name, cls in r.items():
            assert cls.kind == kind and cls.name == name
            assert engines.origin(kind, name).endswith(".py")


def test_builtin_keys_are_the_old_keys():
    """The per-language keys the built-in engines contribute are exactly the
    ones languages.toml always had (plus `voice`, the new chain list, and
    `commercial`, the [<lang>.commercial] voices, and `espeak`, which only
    ever takes the last-resort voice out with `espeak = false`)."""
    assert c.keys() == {"kokoro": str, "voxcpm": bool, "coqui": str, "piper": str, "mms": str, "asr": str,
                        "translator": str, "madlad": str, "voice": list, "commercial": dict, "espeak": bool}


def test_default_voice_order():
    """kokoro -> voxcpm -> coqui -> piper -> mms, as the chain always was."""
    reg = engines.registry("voice")
    order = sorted(["kokoro", "voxcpm", "coqui", "piper", "mms"], key=lambda n: reg[n].priority)
    assert order == ["kokoro", "voxcpm", "coqui", "piper", "mms"]
    assert reg["cosyvoice"].priority < reg["kokoro"].priority


def test_register_rejects_bad_engines():
    for bad in (type("X", (Translator,), {"name": "Bad-Name"}),
                type("X", (Translator,), {"name": "voice"}),         # a languages.toml key
                type("X", (Voice,), {"name": "madlad"}),             # already a translator
                type("X", (Translator,), {"name": "madlad"}),        # already registered
                type("X", (object,), {"name": "plain"})):
        try:
            engines.register(bad)
            assert False, bad.name
        except (TypeError, ValueError):
            pass
    try:
        engines.get("translator", "nllb")
        assert False
    except ValueError as e:
        assert "unknown translator 'nllb'" in str(e) and "madlad" in str(e)


def _run(code, extra_env=None):
    env = {**os.environ, **(extra_env or {})}
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                          cwd=os.path.join(ROOT, "server"))


def test_out_of_tree_engines_via_stack_engines_path():
    """STACK_ENGINES_PATH: a directory of engine files outside the tree."""
    code = ("import engines, stack_config as c\n"
            "print(sorted(engines.registry('translator')), sorted(engines.registry('voice')))\n"
            "print(engines.origin('translator', 'shout'))\n"
            "t, _ = c.load()\n"
            "print(t['de'])\n"
            "m, _ = c.load_models()\n"
            "print(m['shout'])\n")
    cfg = _write('[de]\npiper = "de_DE-thorsten-high"\nbeep = "880"\nvoice = ["beep", "piper"]\n'
                 'translator = "shout"\n[models.shout]\nrevision = "abc123"\n')
    out = _run(code, {"STACK_ENGINES_PATH": FIXTURE, "STACK_CONFIG": cfg})
    assert out.returncode == 0, out.stderr
    lines = out.stdout.splitlines()
    assert "'shout'" in lines[0] and "'beep'" in lines[0], lines
    assert lines[1].endswith("engines_fixture/shout.py")
    assert "'translator': 'shout'" in lines[2] and "'voice': ['beep', 'piper']" in lines[2]
    assert lines[3] == "{'repo': 'example/shout', 'revision': 'abc123'}"
    # Without the path, the same file is an error naming the unknown engine.
    out = _run(code, {"STACK_ENGINES_PATH": "", "STACK_CONFIG": cfg})
    assert out.returncode != 0 and "unknown key 'beep'" in out.stderr, out.stderr
    # The engine's own check of its per-language value.
    bad = _write('[de]\nbeep = "loud"\n')
    out = _run(code, {"STACK_ENGINES_PATH": FIXTURE, "STACK_CONFIG": bad})
    assert out.returncode != 0 and "beep must be a pitch" in out.stderr, out.stderr
    # A translator's declared languages are enforced like Hy-MT2's.
    bad = _write('[es]\ntranslator = "shout"\n')
    out = _run(code, {"STACK_ENGINES_PATH": FIXTURE, "STACK_CONFIG": bad})
    assert out.returncode != 0 and "does not support es" in out.stderr, out.stderr
    # A directory that is not there is an error, not an empty registry.
    out = _run(code, {"STACK_ENGINES_PATH": "/nonexistent/engines"})
    assert out.returncode != 0 and "not a directory" in out.stderr


def test_engines_cli():
    out = subprocess.run([sys.executable, os.path.join(ROOT, "server", "stack_config.py"), "engines"],
                         capture_output=True, text=True)
    assert out.returncode == 0 and "server/engines/echo.py" in out.stdout, out


# ---------------------------------------------------------------- validation

def test_validation_of_engine_names():
    ok = ['[de]\ntranslator = "echo"\n', '[de]\nvoice = ["piper"]\npiper = "de_DE-thorsten-high"\n',
          '[de]\nasr = "omni:deu_Latn"\n', '[de]\nasr = "whisper"\n']
    for text in ok:
        c.load(_write(text))
    bad = {
        '[de]\ntranslator = "nllb"\n': "unknown translator 'nllb'",
        '[de]\nasr = "qwen3"\n': "unknown recognizer 'qwen3'",
        '[de]\nasr = "omni"\n': 'asr must be "omni:<code>"',
        '[de]\nasr = "whisper:de"\n': 'asr must be "whisper"',
        '[de]\nvoice = ["piper", "myvoice"]\n': "unknown voice 'myvoice'",
        '[de]\nvoice = "piper"\n': "voice must be a list",
        '[sw]\ntranslator = "hymt"\n': "Hy-MT2 does not support sw",
    }
    for text, want in bad.items():
        try:
            c.load(_write(text))
            assert False, text
        except ValueError as e:
            assert want in str(e), (text, str(e))


def test_shipped_config_uses_only_builtin_engines():
    table, _ = c.load(c.DEFAULT_FILE)
    reg = engines.registry()
    for lang, e in table.items():
        assert e.get("translator", "hymt") in ("hymt", "madlad")
        assert e.get("asr", "whisper").split(":")[0] in reg["recognizer"]


# ---------------------------------------------------------------- fakes

class FakeMadlad(Madlad):
    """The real MADLAD engine, with the decode replaced by an echo of the prompt."""
    calls = None

    @classmethod
    def enabled(cls, ctx):
        return True

    def load(self):
        self.available = True
        self.calls = []

    def generate(self, prompts):
        self.calls.append(list(prompts))
        return [f"M({p})" for p in prompts]


class FakeHyMT(HyMT):
    """Hy-MT2's routing (supports / supports_source) with a fake decode. Targets
    in `fail` come back missing, as when the real one returns {} or ""."""
    fail = set()
    calls = None

    @classmethod
    def enabled(cls, ctx):
        return True

    def load(self):
        self.available = True
        self.calls = []

    def translate(self, sentences, src, targets, text=None):
        self.calls.append((list(sentences), src, list(targets)))
        return {lg: (" " if lg not in NO_SPACE_JOIN else "").join(f"H{lg}({x})" for x in sentences)
                for lg in targets if lg not in self.fail}


class FakeWhisper(Recognizer):
    name = "whisper"

    @classmethod
    def enabled(cls, ctx):
        return True

    def supports(self, lang):
        return True

    def transcribe(self, pcm16k, lang, want_segments=False):
        return f"whisper:{lang}"


class FakeOmni(Recognizer):
    name = "omni"
    arg = "required"
    ok = True

    @classmethod
    def enabled(cls, ctx):
        return True

    def load(self):
        self.available = self.ok

    def supports(self, lang):
        return self.available and lang in self.ctx.tables["OMNI_LANGS"]

    def transcribe(self, pcm16k, lang, want_segments=False):
        return f"omni:{self.ctx.tables['OMNI_LANGS'][lang]}"


def fake_voice(name, priority, langs, result=b"audio", streaming=False, log=None):
    def synthesise(self, text, lang):
        if log is not None:
            log.append((name, text))
        return result if result is None else f"{name}:{text}".encode()

    def stream(self, text, lang, fallback):
        if log is not None:
            log.append((name + "/stream", text))
        if result is None:
            out = fallback()
            if out:
                yield out
            return
        yield f"{name}~{text}".encode()

    return type(name.title(), (Voice,), {
        "name": name, "priority": priority, "streaming": streaming,
        "enabled": classmethod(lambda cls, ctx: True),
        "supports": lambda self, lang: lang in langs,
        "synthesise": synthesise, "stream": stream})


def make_set(table=None, translators=None, recognizers=None, voices=None, langs=("es",), srcs=("en",)):
    table = c.DEFAULTS if table is None else table
    ctx = Context(device="cpu", models=c.MODEL_DEFAULTS, table=table, tables=c.tables(table),
                  langs=langs, srcs=srcs, options={})
    classes = {"recognizer": recognizers or {"whisper": FakeWhisper, "omni": FakeOmni},
               "translator": translators or {"madlad": FakeMadlad, "hymt": FakeHyMT},
               "voice": voices or {}}
    es = EngineSet(ctx, classes=classes)
    es.load()
    return es


# ---------------------------------------------------------------- the old code, for reference

def reference_translate_batch(madlad, hymt_loaded, hymt_translate, text, langs, src=None):
    """Pipeline.translate_batch as it was before the engines refactor."""
    T = c.tables(c.DEFAULTS)
    LANG_TO_MADLAD, MADLAD_ONLY = T["LANG_TO_MADLAD"], T["MADLAD_ONLY"]
    _generate = madlad.generate
    sentences = split_sentences(text)
    src = src or "en"
    hy = [lg for lg in langs if lg in HYMT_NAMES and lg not in MADLAD_ONLY] if hymt_loaded else []
    mad = [lg for lg in langs if lg not in hy]
    out = {}
    if mad:
        if len(sentences) > 1:
            outs = _generate([f"<2{LANG_TO_MADLAD.get(lg, lg)}> {x}" for lg in mad for x in sentences])
            n = len(sentences)
            for i, lg in enumerate(mad):
                out[lg] = (" " if lg not in NO_SPACE_JOIN else "").join(o.strip() for o in outs[i * n:(i + 1) * n])
        else:
            out.update(zip(mad, _generate([f"<2{LANG_TO_MADLAD.get(lg, lg)}> {text}" for lg in mad])))
    if hy:
        pivot = sentences
        if src not in HYMT_NAMES:
            pivot = [o.strip() for o in _generate([f"<2en> {x}" for x in sentences])]
        got = hymt_translate(pivot, hy)
        for lg in hy:
            out[lg] = got.get(lg) or _generate([f"<2{LANG_TO_MADLAD.get(lg, lg)}> {text}"])[0]
    return [out[lg] for lg in langs]


TEXTS = ["Could you tell me where the train station is?",
         "  Yes.  ",
         "Could you tell me where the train station is? I need to catch the 5 o'clock train.",
         "Dr. Smith is here. Thank you. Amen."]
LANG_SETS = [["es"], ["es", "ja", "km", "lo", "tl", "sw", "fa", "ht", "ro"], ["ro", "ht"], ["zh", "ja", "pl"],
             ["en"], ["xx", "es"]]


def test_translation_matches_the_old_code():
    for hymt_on in (True, False):
        for fail in (set(), {"ja", "km"}):
            for src in ("en", "es", "ht", "ro", None):
                for text in TEXTS:
                    for langs in LANG_SETS:
                        es = make_set()
                        hy = es.engines["translator"]["hymt"]
                        hy.fail = fail
                        hy.available = hymt_on
                        ref_mad = FakeMadlad(es.ctx)
                        ref_mad.load()
                        ref_hy = FakeHyMT(es.ctx)
                        ref_hy.load()
                        ref_hy.fail = fail
                        want = reference_translate_batch(
                            ref_mad, hymt_on, lambda s, t: ref_hy.translate(s, None, t), text, langs, src)
                        got = es.translate_batch(text, langs, src)
                        assert got == want, (hymt_on, fail, src, text, langs, got, want)
                        # ...and the same decodes, in the same order and batches.
                        assert es.engines["translator"]["madlad"].calls == ref_mad.calls, (src, text, langs)


def test_pivot_goes_through_english():
    es = make_set()
    es.translate_batch("Bonjou tout moun. Mèsi anpil pou vini.", ["es"], "ht")
    hy = es.engines["translator"]["hymt"]
    assert hy.calls[0][1] == "en"                        # handed over as English
    assert all(s.startswith("M(<2en> ") for s in hy.calls[0][0])


def test_a_configured_translator_is_used():
    """Extension through config: [de] translator = "echo"."""
    table = dict(c.DEFAULTS)
    table["de"] = {"piper": "de_DE-thorsten-high", "translator": "echo"}
    es = make_set(table, translators={"madlad": FakeMadlad, "hymt": FakeHyMT,
                                      "echo": engines.get("translator", "echo")}, langs=("de", "es"))
    assert es.translator_for("de").name == "echo"
    assert es.translator_for("es").name == "hymt"
    assert es.translate_batch("Where is the station?", ["de", "es"]) == [
        "Where is the station?", "Hes(Where is the station?)"]


def test_the_template_works():
    """server/engines/_template.py, copied in as docs/dev/adding-an-engine.md says,
    registers, validates and translates (on the fake MADLAD)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("madlad_whole", os.path.join(ROOT, "server", "engines",
                                                                               "_template.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert engines.get("translator", "madlad_whole") is mod.MadladWhole
    c.load(_write('[ro]\ntranslator = "madlad_whole"\nmadlad = "ro"\n'))
    table = dict(c.DEFAULTS)
    table["ro"] = {"piper": "ro_RO-mihai-medium", "translator": "madlad_whole", "madlad": "ro"}
    es = make_set(table, translators={"madlad": FakeMadlad, "hymt": FakeHyMT, "madlad_whole": mod.MadladWhole},
                  langs=("ro", "es"))
    assert es.translator_for("ro").name == "madlad_whole"
    assert es.translate_batch("One sentence here. And another one.", ["ro", "es"]) == [
        "M(<2ro> One sentence here. And another one.)", "Hes(One sentence here.) Hes(And another one.)"]
    long = " ".join(["word"] * 70) + ". " + " ".join(["more"] * 5) + "."
    assert es.translate_batch(long, ["ro"])[0].count("M(<2ro>") == 2     # the stock per-sentence path


def test_an_engine_that_raises_falls_back_to_madlad():
    class Broken(Translator):
        name = "broken"
        enabled = classmethod(lambda cls, ctx: True)

        def translate(self, sentences, src, targets, text=None):
            raise RuntimeError("no")

    table = dict(c.DEFAULTS)
    table["de"] = {"translator": "broken"}
    es = make_set(table, translators={"madlad": FakeMadlad, "broken": Broken}, langs=("de",))
    assert es.translate_batch("Hello there, friend.", ["de"]) == ["M(<2de> Hello there, friend.)"]


def test_unavailable_translator_falls_back_to_madlad():
    table = dict(c.DEFAULTS)
    table["de"] = {"translator": "echo"}
    es = make_set(table, langs=("de",))        # echo not in the classes: not running
    assert es.translator_for("de").name == "madlad"


# ---------------------------------------------------------------- recognition

def test_recogniser_routing():
    es = make_set(srcs=("en", "km", "ht", "es"))
    assert es.transcribe(None, "km") == "omni:khm_Khmr"
    assert es.transcribe(None, "ht") == "omni:hat_Latn"
    assert es.transcribe(None, "es") == "whisper:es"
    assert es.transcribe(None, "en") == "whisper:en"
    FakeOmni.ok = False
    try:
        es = make_set(srcs=("km",))
        assert es.transcribe(None, "km") == "whisper:km"   # Omnilingual missing: Whisper, as before
    finally:
        FakeOmni.ok = True


# ---------------------------------------------------------------- voices

def reference_synthesise(avail, text, lang, voxcpm=True):
    """Pipeline.synthesise's order before the refactor: clone, kokoro, voxcpm,
    coqui, piper, and MMS only when there is no Piper voice."""
    if not text or not any(ch.isalnum() for ch in text):
        return None
    for name in ("cosyvoice", "kokoro", "voxcpm", "coqui"):
        if name == "voxcpm" and not voxcpm:
            continue
        if lang in avail.get(name, {}):
            out = avail[name][lang]
            if out is not None:
                return out
    if lang in avail.get("piper", {}):
        return avail["piper"][lang]
    if lang in avail.get("mms", {}):
        return avail["mms"][lang]
    return None


def test_voice_chain_matches_the_old_order():
    import itertools
    names = [("cosyvoice", -100), ("kokoro", 10), ("voxcpm", 20), ("coqui", 30), ("piper", 40), ("mms", 50)]
    lang = "xx"
    for mask in itertools.product((None, "ok", "fail"), repeat=len(names)):
        if mask[4] == "fail":
            continue      # Piper never returns None: it has audio or raises
        voices, avail = {}, {}
        for (name, prio), m in zip(names, mask):
            if m is None:
                continue
            res = None if m == "fail" else b"x"
            voices[name] = fake_voice(name, prio, {lang}, result=res)
            avail[name] = {lang: None if m == "fail" else f"{name}:Hello.".encode()}
        es = make_set(voices=voices, langs=(lang,))
        assert es.synthesise("Hello.", lang) == reference_synthesise(avail, "Hello.", lang), mask
        assert es.synthesise("...", lang) is None
        assert (es.synthesise("Hello.", lang, exclude=("voxcpm",))
                == reference_synthesise(avail, "Hello.", lang, voxcpm=False)), mask


def test_explicit_voice_list_orders_the_chain():
    table = {"de": {"piper": "de_DE-thorsten-high", "voice": ["piper", "kokoro"]}}
    voices = {"kokoro": fake_voice("kokoro", 10, {"de"}), "piper": fake_voice("piper", 40, {"de"})}
    es = make_set(table, voices=voices, langs=("de",))
    assert [e.name for e in es.chain("de")] == ["piper", "kokoro"]
    assert es.synthesise("Hallo.", "de") == b"piper:Hallo."


def test_new_voice_goes_first_by_default():
    voices = {"kokoro": fake_voice("kokoro", 10, {"es"}), "piper": fake_voice("piper", 40, {"es"}),
              "myvoice": fake_voice("myvoice", 0, {"es"})}
    es = make_set(voices=voices)
    assert [e.name for e in es.chain("es")] == ["myvoice", "kokoro", "piper"]


class _Pool:
    def submit(self, fn, *a):
        from concurrent.futures import Future
        f = Future()
        f.set_result(fn(*a))
        return f


def test_streaming_voice_and_its_fallback():
    log = []
    voices = {"voxcpm": fake_voice("voxcpm", 20, {"km"}, streaming=True, log=log),
              "mms": fake_voice("mms", 50, {"km"}, log=log)}
    es = make_set(voices=voices, langs=("km",))
    futs = es.synthesise_futures("One. Two.", "km", _Pool())
    streams = [f.result() for f in futs]
    assert all(isinstance(s, AudioStream) for s in streams)
    assert [b"".join(s.chunks) for s in streams] == [b"voxcpm~One.", b"voxcpm~Two."]
    # The service down: each sentence falls back to the rest of the chain (MMS), not to itself.
    voices["voxcpm"] = fake_voice("voxcpm", 20, {"km"}, result=None, streaming=True, log=log)
    es = make_set(voices=voices, langs=("km",))
    got = [b"".join(f.result().chunks) for f in es.synthesise_futures("One. Two.", "km", _Pool())]
    assert got == [b"mms:One.", b"mms:Two."]
    # No streaming voice: plain futures of bytes, one per sentence.
    es = make_set(voices={"piper": fake_voice("piper", 40, {"es"})})
    assert [f.result() for f in es.synthesise_futures("Uno. Dos; tres", "es", _Pool())] == [
        b"piper:Uno.", b"piper:Dos;", b"piper:tres"]


def test_voice_locks():
    es = make_set()
    assert es.voice_lock("es") is es.voice_lock("es")
    assert es.voice_lock("es") is not es.voice_lock("fr")
    es._serial_tts = True
    assert es.voice_lock("es") is es.voice_lock("fr")
    v = fake_voice("v", 0, {"es"})(es.ctx)
    assert v.lock("es") is es.voice_lock("es")
    v.lock_policy = "none"
    assert v.lock("es") is not es.voice_lock("es")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
