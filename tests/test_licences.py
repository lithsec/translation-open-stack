#!/usr/bin/env python3
"""Licence data (server/licences.py) and its enforcement by edition
(stack_config.apply_edition for `check`, EngineSet at runtime). No models, no
GPU: engines are built but never loaded.

    python3 tests/test_licences.py        (or python3 -m pytest tests/test_licences.py)
"""
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

import engines  # noqa: E402
import licences as L  # noqa: E402
import stack_config as c  # noqa: E402
from engines.base import Context, Voice  # noqa: E402
from engines.manager import EngineSet  # noqa: E402

VOICE_ENGINES = set(engines.registry("voice"))


def _write(text):
    fd, path = tempfile.mkstemp(suffix=".toml")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


def _items(entry):
    """Every (engine, value) a language table names as a voice, in both editions."""
    out = []
    for e in (entry, entry.get("commercial") or {}):
        for k, v in e.items():
            if k in VOICE_ENGINES:
                out.append((k, v))
        for n in e.get("voice") or []:
            out.append((n, e.get(n)))
    return out


def _is_classified(name, value):
    li = L.lookup(name, value if isinstance(value, str) else None, cls=engines.registry("voice").get(name))
    return "has no entry" not in li.reason


# ---------------------------------------------------------------- the data

def test_piper_links_follow_the_voices_lock():
    """The Piper model cards cited are the ones at the commit voices.lock downloads from."""
    lock = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "voices.lock")
    rev = next(l.split()[1] for l in open(lock) if l.startswith("revision "))
    assert L.PIPER_REVISION == rev, (L.PIPER_REVISION, rev)


def test_every_configured_item_is_classified():
    """A voice or model named in languages.toml or the defaults without an entry
    in licences.py fails here, so nothing new slips in unclassified."""
    shipped, _ = c.load(c.DEFAULT_FILE)
    for table in (c.DEFAULTS, shipped):
        for lang, entry in table.items():
            for name, value in _items(entry):
                assert _is_classified(name, value), f"[{lang}] {name} {value!r} has no licence entry"
            asr = entry.get("asr", "whisper").split(":")[0]
            assert "has no entry" not in L.lookup(asr).reason, asr
            assert "has no entry" not in L.lookup(entry.get("translator", "hymt")).reason
    for models in (c.MODEL_DEFAULTS, c.load_models(c.DEFAULT_FILE)[0]):
        for name, entry in models.items():
            li = L.model_lookup(name, entry)
            assert li.cls != L.UNCLEAR, (name, li.reason)
    # Every built-in engine: classified itself, or per item.
    for kind, reg in engines.registry().items():
        for name in reg:
            assert name in L.ENGINES or name in L.PER_ITEM, f"{kind} {name} has no licence entry"


def test_every_entry_is_well_formed():
    for engine, items in [("engine", L.ENGINES), ("model", L.MODELS)] + list(L.ITEMS.items()):
        for key, li in items.items():
            assert li.cls in L.CLASSES, (engine, key)
            assert li.licence and li.reason, (engine, key)
            if li.cls in (L.ATTRIBUTION, L.SHARE_ALIKE):
                assert li.obligation, f"{engine} {key}: attribution/share-alike needs its obligation"
            if engine != "engine" or key != "echo":
                assert li.url.startswith("https://"), (engine, key)
    for voice, li in L.ITEMS["piper"].items():
        assert li.dataset and li.base, voice
        assert li.url == L._card(voice), voice
        # A voice fine-tuned from lessac or ryan is never simply clean.
        if li.base.startswith(("lessac", "ryan")) and li.cls != L.NONCOMMERCIAL:
            assert li.cls == L.UNCLEAR, voice


def test_the_audit_verdicts():
    """docs/licences.md's audit (2026-09-29), as data."""
    p = L.ITEMS["piper"]
    for v in ("ko_KR-kss-medium", "tr_TR-dfki-medium", "ja_JP-hi_fi_captain-medium", "en_US-lessac-medium"):
        assert p[v].cls == L.NONCOMMERCIAL, v
    for v in ("es_ES-davefx-medium", "fr_FR-siwis-medium", "pt_BR-faber-medium", "de_DE-thorsten-high",
              "ru_RU-irina-medium", "zh_CN-huayan-medium", "vi_VN-vais1000-medium", "ar_JO-kareem-medium",
              "fa_IR-gyro-medium", "id_ID-news_tts-medium", "hi_IN-rohan-medium", "sw_CD-lanfrica-medium",
              "ro_RO-mihai-medium"):
        assert p[v].cls == L.UNCLEAR, v
    lessac = [v for v, li in p.items() if li.base == "lessac" and v in {x for e in c.DEFAULTS.values()
                                                                        for k, x in e.items() if k == "piper"}]
    assert len(lessac) == 13, lessac          # "Thirteen of these voices were fine-tuned from lessac"
    assert L.ENGINES["mms"].cls == L.NONCOMMERCIAL
    # Recognisers and translators: all clean.
    for name in ("whisper", "omni", "hymt", "madlad", "kokoro", "voxcpm"):
        assert L.ENGINES[name].cls == L.PERMISSIVE, name
    for repo in ("speechbrain/lang-id-voxlingua107-ecapa", "snakers4/silero-vad", "tencent/Hy-MT2-7B",
                 "google/madlad400-7b-mt", "google/madlad400-3b-mt"):
        assert L.MODELS[repo].cls == L.PERMISSIVE, repo


def test_hymt_licence_is_tied_to_its_revision():
    good = {"repo": "tencent/Hy-MT2-7B", "revision": "9b0eb4e8f001def3e5ff6469a0ac96fdb39ec223"}
    assert L.model_lookup("hymt", good).cls == L.PERMISSIVE
    moved = dict(good, revision="0123456789abcdef")
    assert L.model_lookup("hymt", moved).cls == L.UNCLEAR
    assert L.model_lookup("hymt", {"repo": "tencent/Hunyuan-MT-7B", "revision": "x"}).cls == L.UNCLEAR
    assert c.commercial_problems({"hymt": moved}) and not c.commercial_problems({"hymt": good})
    assert not c.commercial_problems({"hymt": moved}, reviews={"tencent/Hy-MT2-7B": "reviewed 2026-10-01 by us: ok"})


# ---------------------------------------------------------------- apply_edition

def _chains(table, ed, reviews=None, unclear_ok=False):
    eff, rep = c.apply_edition(table, ed, reviews or {}, unclear_ok)
    return eff, rep


def test_commercial_never_yields_a_noncommercial_item():
    """Across all languages of the defaults, the shipped file, and hostile
    configs that name ⛔ voices in every way the config allows."""
    hostile = c.load(_write(
        '[ko]\npiper = "ko_KR-kss-medium"\nmms = "facebook/mms-tts-kor"\nvoice = ["mms", "piper"]\n'
        '[tr]\nvoice = ["piper"]\npiper = "tr_TR-dfki-medium"\n'
        '[en]\npiper = "en_US-lessac-medium"\nkokoro = "a:am_michael"\n'
        '[ja]\npiper = "ja_JP-hi_fi_captain-medium"\n'
        '[ht]\nmms = "facebook/mms-tts-hat"\nvoice = ["mms"]\n'))[0]
    for table in (c.DEFAULTS, c.load(c.DEFAULT_FILE)[0], hostile):
        for unclear_ok in (False, True):
            eff, rep = _chains(table, "commercial", unclear_ok=unclear_ok)
            for lang, r in rep.items():
                for n, v, li in r["voices"]:
                    assert li.cls != L.NONCOMMERCIAL, (lang, n, v)
                    assert unclear_ok or li.cls != L.UNCLEAR, (lang, n, v)
                for k, v in eff[lang].items():
                    if k in VOICE_ENGINES:
                        assert L.lookup(k, v if isinstance(v, str) else None).cls != L.NONCOMMERCIAL, (lang, k, v)
                assert "commercial" not in eff[lang]


def test_noncommercial_in_a_commercial_table_is_an_error():
    for text in ('[ko]\npiper = "x"\n[ko.commercial]\npiper = "ko_KR-kss-medium"\n',
                 '[ht]\n[ht.commercial]\nmms = "facebook/mms-tts-hat"\n'):
        table, _ = c.load(_write(text))
        try:
            c.apply_edition(table, "commercial", {}, True)
            assert False, text
        except ValueError as e:
            assert "never load" in str(e), e


def test_commercial_table_validation():
    for bad, want in {'[de]\n[de.commercial]\nasr = "whisper"\n': "may only name voices",
                      '[de]\n[de.commercial]\npiper = 3\n': "must be a str",
                      '[de]\n[de.commercial]\nvoice = ["nope"]\n': "unknown voice",
                      '[de]\n[de.commercial]\nkokoro = "am_adam"\n': "kokoro must be",
                      '[de]\ncommercial = "yes"\n': "commercial must be a dict"}.items():
        try:
            c.load(_write(bad))
            assert False, bad
        except ValueError as e:
            assert want in str(e), (bad, str(e))


def test_unclear_needs_a_review():
    table = c.DEFAULTS
    _, rep = _chains(table, "commercial")
    # Without the review, only the last resort (eSpeak NG) speaks Romanian.
    assert _names(rep["ro"]) == ["espeak"] and [x[1] for x in rep["ro"]["dropped"]] == ["ro_RO-mihai-medium"]
    reviews = {"ro_RO-mihai-medium": "reviewed 2026-10-01 by Example Org: CC0 data, we accept the lessac base"}
    eff, rep = _chains(table, "commercial", reviews)
    assert eff["ro"]["piper"] == "ro_RO-mihai-medium" and _names(rep["ro"]) == ["piper", "espeak"]
    assert _names(rep["fa"]) == ["espeak"]              # a review is per item
    eff, rep = _chains(table, "commercial", unclear_ok=True)
    assert eff["ro"]["piper"] == "ro_RO-mihai-medium" and eff["fa"]["piper"] == "fa_IR-gyro-medium"
    assert "ja" in eff and "piper" not in eff["ja"]     # ...but never a ⛔ one


def test_reviews_are_validated():
    for bad in ({"ko_KR-kss-medium": "reviewed 2026-10-01 by us: we like it"},   # no override for ⛔
                {"mms": "reviewed 2026-10-01 by us: it's fine"},
                {"ro_RO-mihai-medium": "ok"},                                   # say who, when, why
                {"ro_RO-mihai-medium": 1}):
        try:
            c.validate_reviews(bad)
            assert False, bad
        except ValueError:
            pass
    p = _write('[licence_review]\n"ro_RO-mihai-medium" = "reviewed 2026-10-01 by Example Org: CC0 data"\n')
    assert c.load_reviews(p) == {"ro_RO-mihai-medium": "reviewed 2026-10-01 by Example Org: CC0 data"}
    assert "licence_review" not in c.load(p)[0]
    try:
        c.load_reviews(_write('[licence_review]\n"tr_TR-dfki-medium" = "reviewed 2026-10-01 by us: fine"\n'))
        assert False
    except ValueError as e:
        assert "no override" in str(e)


def test_attribution_is_allowed_and_reported():
    models = c.MODEL_DEFAULTS
    lines = c.check_lines(c.DEFAULTS, "commercial", {}, models, False)
    text = "\n".join(lines)
    assert "fr voice piper fr_FR-mls-medium: CC-BY 4.0: credit Multilingual LibriSpeech" in text
    assert "ht voice coqui multilingual-tts/VITS-OpenBible-Haitian-Creole: CC-BY-SA 4.0" in text
    assert "it voice piper it_IT-serena-high: CC-BY 4.0" in text
    assert re.search(r"^  it .*piper it_IT-serena-high ⚠️", text, re.M)


def _names(r):
    return [n for n, _, _ in r["voices"]]


def test_espeak_speaks_the_formerly_text_only_languages():
    """fa and ro have no commercially licensed voice but eSpeak NG (⚠️ GPL-3.0,
    a separate process): no longer text only, and said so."""
    lines = "\n".join(c.check_lines(c.DEFAULTS, "commercial", {}, c.MODEL_DEFAULTS, False))
    assert "TEXT ONLY" not in lines and "text only: none" in lines
    assert "eSpeak NG only (robotic, better than text): fa, ro" in lines
    assert re.search(r"^  fa .*voice: espeak ⚠️$", lines, re.M)
    assert re.search(r"^  ko .*voice: voxcpm ✅ > espeak ⚠️ \(last resort\)$", lines, re.M)
    assert "VoxCPM2 speaks 10 languages" in lines and "VoxCPM2 instances: auto (the commercial default)" in lines
    # The GPL duty is said once, not in 21 languages' lines.
    assert "deployment-wide, 21 languages: espeak: GPL-3.0" in lines
    assert "voice espeak" not in lines
    # `espeak = false` takes it out: Persian is text only again.
    table, _ = c.load(_write('[fa]\npiper = "fa_IR-gyro-medium"\nasr = "omni:pes_Arab"\nespeak = false\n'))
    lines = "\n".join(c.check_lines(table, "commercial", {}, c.MODEL_DEFAULTS, False))
    assert "fa: TEXT ONLY in commercial (no commercially licensed voice)" in lines and "text only: fa" in lines


def test_commercial_outcome_per_language():
    """The commercial chain the docs promise (docs/licences.md §3)."""
    _, rep = _chains(c.DEFAULTS, "commercial")
    got = {l: [(n, v) for n, v, _ in r["voices"]] for l, r in rep.items()}
    vox = [("voxcpm", True)]
    # eSpeak NG (the last resort) ends every chain of a language it speaks:
    # all but km lo tl (no eSpeak voice) and ja (it cannot read kanji).
    for lang, chain in got.items():
        if lang in ("km", "lo", "tl", "ja"):
            assert ("espeak", None) not in chain, lang
        else:
            assert chain[-1] == ("espeak", None), lang
            chain.pop()
    assert got == {
        "en": [("kokoro", "a:am_michael"), ("piper", "en_US-norman-medium")],
        "es": [("kokoro", "e:ef_dora"), ("piper", "es_ES-carlfm-x_low")],
        "fr": [("kokoro", "f:ff_siwis"), ("piper", "fr_FR-mls-medium")],
        "pt": [("kokoro", "p:pf_dora")],
        "it": [("kokoro", "i:if_sara"), ("piper", "it_IT-serena-high")],
        "de": [("piper", "de_DE-mls-medium")],
        "ru": vox, "uk": [("piper", "uk_UA-ukrainian_tts-medium")],
        "zh": [("kokoro", "z:zf_xiaobei")], "ja": [("kokoro", "j:jf_alpha")], "ko": vox, "vi": vox, "ar": vox,
        "fa": [], "id": vox, "tr": vox, "bn": [("piper", "bn_BD-google-medium")],
        "ur": [("piper", "ur_PK-aegis_female-medium")], "hi": [("kokoro", "h:hf_alpha")], "sw": vox, "ro": [],
        "ht": [("coqui", "multilingual-tts/VITS-OpenBible-Haitian-Creole")], "km": vox, "lo": vox, "tl": vox}


def test_nonprofit_is_unchanged():
    eff, rep = _chains(c.DEFAULTS, "nonprofit")
    stripped = {l: {k: v for k, v in e.items() if k != "commercial"} for l, e in c.DEFAULTS.items()}
    assert eff == stripped
    assert c.tables(eff) == c.tables(c.DEFAULTS)
    import test_stack_config
    assert c.tables(eff) == test_stack_config.BEFORE
    # [<lang>.commercial] is ignored in nonprofit, even when it is all a language has.
    table, _ = c.load(_write('[de]\n[de.commercial]\npiper = "de_DE-mls-medium"\n'))
    assert c.apply_edition(table, "nonprofit")[0]["de"] == {}


# ---------------------------------------------------------------- the runtime (EngineSet)

def _commercial_set(table=None, options=None, classes=None, langs=None):
    table = c.DEFAULTS if table is None else table
    langs = list(table) if langs is None else langs
    # Every voice flag ON, as a careless or hostile launcher might pass them.
    opts = dict(kokoro=True, voxcpm="http://127.0.0.1:1", mms=True, coqui=True, espeak=True, edition="commercial")
    opts.update(options or {})
    ctx = Context(device="cpu", models=c.MODEL_DEFAULTS, table=table, tables=c.tables(table),
                  langs=langs, srcs=["en"], options=opts)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        es = EngineSet(ctx, classes=classes)
    return es, out.getvalue()


def _pretend_loaded(es):
    """Mark every voice available as if load() had run, without loading a model."""
    for name, eng in es.engines["voice"].items():
        eng.available = True
        if name == "piper":
            eng.tts = {lang: object() for lang in eng.names}
        if name == "espeak":
            eng.langs = {lang for lang in eng.ctx.langs if eng.covers(lang)}


def test_engineset_commercial_never_loads_noncommercial():
    """The runtime enforces the edition on its own: the caller passes the RAW
    table (nonprofit voices, ⛔ included) and every voice flag, MMS too."""
    for table in (c.DEFAULTS, c.load(c.DEFAULT_FILE)[0]):
        es, log = _commercial_set(table)
        assert "mms" not in es.engines["voice"], "MMS-TTS was constructed in commercial"
        assert "NOT loading voice mms" in log
        piper = es.engines["voice"]["piper"]
        for lang, voice in piper.names.items():
            assert L.lookup("piper", voice).cls not in (L.NONCOMMERCIAL, L.UNCLEAR), (lang, voice)
        _pretend_loaded(es)
        for lang in table:
            for eng in es.chain(lang):
                li = L.lookup(eng.name, eng.setting(lang) if isinstance(eng.setting(lang), str) else None)
                assert li.cls not in (L.NONCOMMERCIAL, L.UNCLEAR), (lang, eng.name, eng.setting(lang))
        assert [e.name for e in es.chain("ko")] == ["voxcpm", "espeak"]
        assert [e.name for e in es.chain("fa")] == ["espeak"] and [e.name for e in es.chain("ro")] == ["espeak"]
        assert [e.name for e in es.chain("km")] == ["voxcpm"]


def test_engineset_env_and_option_tricks():
    """VOXCPM_LANGS-style overrides, COMMERCIAL_ALLOW_UNCLEAR and a hostile
    `voice = [...]` still never reach a ⛔ item."""
    hostile, _ = c.load(_write('[ko]\npiper = "ko_KR-kss-medium"\nmms = "facebook/mms-tts-kor"\n'
                               'voice = ["mms", "piper"]\n[tr]\npiper = "tr_TR-dfki-medium"\n'))
    os.environ["COMMERCIAL_ALLOW_UNCLEAR"] = "1"
    try:
        es, log = _commercial_set(hostile, options={"voxcpm_langs": ["ko", "tr", "ro"]})
    finally:
        del os.environ["COMMERCIAL_ALLOW_UNCLEAR"]
    _pretend_loaded(es)
    assert "ko" not in es.engines["voice"]["piper"].names and "tr" not in es.engines["voice"]["piper"].names
    assert [e.name for e in es.chain("ko")] == ["voxcpm", "espeak"]   # VoxCPM2 (Apache) may speak it
    assert es.engines["voice"]["piper"].names.get("ro") == "ro_RO-mihai-medium"   # ❓ admitted by the env
    for lang in hostile:
        for eng in es.chain(lang):
            assert L.lookup(eng.name, eng.setting(lang) if isinstance(eng.setting(lang), str)
                            else None).cls != L.NONCOMMERCIAL
    # A table smuggled in after construction is caught by the chain filter.
    es.ctx.table["ja"] = {"piper": "ja_JP-hi_fi_captain-medium"}
    es.engines["voice"]["piper"].tts["ja"] = object()
    es._chains.clear()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert "piper" not in [e.name for e in es.chain("ja")]
    assert "refusing piper" in out.getvalue()
    try:
        es._assert_clean()
        assert False
    except RuntimeError as e:
        assert "not allowed" in str(e)


def test_engineset_unclassified_plugins():
    """An out-of-tree voice with no licence is refused in commercial, loads in
    nonprofit; one that declares a permissive licence loads in both."""
    def voice(name, **attrs):
        return type(name.title(), (Voice,), {"name": name, "priority": 0, "lang_key": str,
                                              "enabled": classmethod(lambda cls, ctx: True), **attrs})
    table = {"de": {"mystery": "x", "declared": "y"}}
    classes = {"recognizer": {}, "translator": {},
               "voice": {"mystery": voice("mystery"), "declared": voice("declared", licence_class="permissive",
                                                                          licence="MIT")}}
    es, log = _commercial_set(table, classes=classes, langs=["de"])
    assert set(es.engines["voice"]) == {"declared"} and "NOT loading voice mystery" in log
    es, _ = _commercial_set(table, options={"edition": "nonprofit"}, classes=classes, langs=["de"])
    assert set(es.engines["voice"]) == {"mystery", "declared"}


def test_engineset_logs_text_only_and_obligations():
    es, _ = _commercial_set()
    _pretend_loaded(es)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        es._licence_log()
    log = out.getvalue()
    assert "TEXT ONLY" not in log
    assert "[licence] fa: voice espeak ⚠️" in log and "[licence] ro: voice espeak ⚠️" in log
    assert "[licence] ko: voice voxcpm ✅ > espeak ⚠️" in log
    assert "[licence] voice espeak (21 languages): GPL-3.0" in log
    assert "[licence] fr voice piper fr_FR-mls-medium: CC-BY 4.0: credit Multilingual LibriSpeech" in log
    assert "[licence] ko: voice voxcpm ✅" in log
    for name in ("kss", "dfki", "hi_fi_captain", "lessac", "mms-tts"):
        assert name not in log, name   # replaced or left out, never named as loaded


def test_engineset_nonprofit_is_unchanged():
    es, _ = _commercial_set(options={"edition": "nonprofit"})
    assert "mms" in es.engines["voice"]
    assert es.engines["voice"]["piper"].names == c.tables(c.DEFAULTS)["PIPER_VOICES"]
    assert "commercial" not in es.ctx.table["en"]


# ---------------------------------------------------------------- CLI and docs

def _cli(*args, env=None):
    return subprocess.run([sys.executable, os.path.join(ROOT, "server", "stack_config.py"), *args],
                          capture_output=True, text=True, env={**os.environ, **(env or {})})


def test_check_cli_both_editions():
    out = _cli("check", "--edition", "commercial")
    assert out.returncode == 0, out.stderr
    assert "eSpeak NG only (robotic, better than text): fa, ro" in out.stdout
    assert "edition: commercial" in out.stdout
    out2 = _cli("check", env={"EDITION": "commercial"})
    assert out2.stdout == out.stdout                  # EDITION is honoured
    out = _cli("check")
    assert out.returncode == 0 and "edition: nonprofit" in out.stdout and "TEXT ONLY" not in out.stdout
    assert _cli("check", "--edition", "enterprise").returncode != 0
    moved = _write('[models.hymt]\nrevision = "0123abcd"\n')
    out = _cli("check", "--edition", "commercial", env={"STACK_CONFIG": moved})
    assert out.returncode != 0 and "models.hymt" in out.stderr


def test_piper_cli_never_fetches_noncommercial():
    allv = ",".join(c.DEFAULTS)
    out = _cli("piper", allv, env={"EDITION": "commercial"})
    assert out.returncode == 0
    for line in out.stdout.splitlines():
        lang, voice = line.split()
        assert L.lookup("piper", voice).cls not in (L.NONCOMMERCIAL, L.UNCLEAR), line
    assert "ko_KR-kss-medium" in _cli("piper", allv).stdout      # nonprofit fetches as before


def test_docs_tables_are_generated_from_the_data():
    """docs/licences.md's per-language and Piper tables are exactly what
    `python3 server/stack_config.py docs` generates."""
    doc = open(os.path.join(ROOT, "docs", "licences.md"), encoding="utf-8").read()
    for name, md in c.docs_blocks().items():
        m = re.search(rf"<!-- generated: {name} -->\n(.*?)\n<!-- end generated: {name} -->", doc, re.S)
        assert m, f"docs/licences.md has no generated block {name!r}"
        assert m.group(1) == md, (f"docs/licences.md's {name} table is stale: run "
                                  "python3 server/stack_config.py docs and paste the block")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
