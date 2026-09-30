"""python3 -m pytest tests/test_stack_config.py  (or just python3 tests/test_stack_config.py; needs Python 3.11+)"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
import stack_config as c  # noqa: E402

# The tables server.py held inline before languages.toml (2026-09-28). The
# defaults must reproduce them exactly: that is what the deployed stack runs.
BEFORE = {
    "KOKORO_VOICES": {"en": ("a", "am_michael"), "es": ("e", "ef_dora"), "it": ("i", "if_sara"),
                      "pt": ("p", "pf_dora"), "fr": ("f", "ff_siwis"), "ja": ("j", "jf_alpha"),
                      "zh": ("z", "zf_xiaobei"), "hi": ("h", "hf_alpha")},
    "VOXCPM_LANGS": {"km", "lo", "tl"},
    "COQUI_VOICES": {"ht": "multilingual-tts/VITS-OpenBible-Haitian-Creole"},
    "PIPER_VOICES": {
        "en": "en_US-lessac-medium", "es": "es_ES-davefx-medium", "fr": "fr_FR-siwis-medium",
        "pt": "pt_BR-faber-medium", "sw": "sw_CD-lanfrica-medium", "ru": "ru_RU-irina-medium",
        "uk": "uk_UA-ukrainian_tts-medium", "it": "it_IT-serena-high", "zh": "zh_CN-huayan-medium",
        "vi": "vi_VN-vais1000-medium", "ko": "ko_KR-kss-medium", "ar": "ar_JO-kareem-medium",
        "fa": "fa_IR-gyro-medium", "id": "id_ID-news_tts-medium", "tr": "tr_TR-dfki-medium",
        "bn": "bn_BD-google-medium", "ur": "ur_PK-aegis_female-medium", "hi": "hi_IN-rohan-medium",
        "de": "de_DE-thorsten-high", "ja": "ja_JP-hi_fi_captain-medium", "ro": "ro_RO-mihai-medium"},
    "MMS_VOICES": {"ht": "facebook/mms-tts-hat", "km": "facebook/mms-tts-khm", "lo": "facebook/mms-tts-lao",
                   "tl": "facebook/mms-tts-tgl"},
    "OMNI_LANGS": {"ht": "hat_Latn", "km": "khm_Khmr", "lo": "lao_Laoo", "sw": "swh_Latn",
                   "hi": "hin_Deva", "fa": "pes_Arab", "bn": "ben_Beng", "ur": "urd_Arab"},
    "LANG_TO_MADLAD": {
        "es": "es", "fr": "fr", "pt": "pt", "sw": "sw", "ht": "ht", "km": "km", "lo": "lo",
        "ru": "ru", "uk": "uk", "it": "it", "zh": "zh", "ja": "ja", "ko": "ko", "de": "de",
        "ar": "ar", "hi": "hi", "vi": "vi", "fa": "fa", "id": "id", "tr": "tr", "bn": "bn", "ur": "ur",
        "tl": "fil", "ro": "ro"},
    "MADLAD_ONLY": {"sw", "ht", "lo", "ro"},  # none of which Hy-MT2 supports: routing is unchanged
}


# The models the deployed stack ran before [models] existed (2026-09-29): run.sh's
# --asr-model, server.py's Omnilingual card and language ID, prepare-mt.sh's and
# prepare-voices.sh's pins. Whisper, language ID and Kokoro were unpinned then;
# these revisions are what their repos served (unchanged since 2023-11, 2024-11
# and 2025-04). Silero followed its master branch, which was v6.2.3 from
# 2026-09-23 until 2026-09-29 (after that: utility fixes the server doesn't
# call, same model file). Its ref is now tag v6.2.3's commit, the same code.
MODELS_BEFORE = {
    "whisper": {"model": "large-v3", "multi_model": "", "multi_revision": "",
                "revision": "edaa852ec7e145841d8ffdb056a99866b5f0a478"},
    "omnilingual": {"card": "omniASR_LLM_300M"},
    "lid": {"repo": "speechbrain/lang-id-voxlingua107-ecapa", "revision": "0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9"},
    "vad": {"repo": "snakers4/silero-vad", "ref": "5cd7945676eb32225748052e2e6a0580e4686a08"},  # tag v6.2.3
    "hymt": {"repo": "tencent/Hy-MT2-7B", "revision": "9b0eb4e8f001def3e5ff6469a0ac96fdb39ec223"},
    "madlad": {"repo": "google/madlad400-7b-mt", "revision": "1ff63ce7ddd571a69d45cad9672c553428419671"},
    "madlad3b": {"repo": "google/madlad400-3b-mt", "revision": "fa184c675da0b5c9e1c8694fccd4e12e2d422094"},
    "kokoro": {"repo": "hexgrad/Kokoro-82M", "revision": "f3ff3571791e39611d31c381e3a41a3af07b4987"},
    "voxcpm": {"repo": "openbmb/VoxCPM2", "revision": "32279effe8c19989596f05d353d1447f51d9e915"},
}
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _write(text):
    fd, path = tempfile.mkstemp(suffix=".toml")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


def test_defaults_are_the_deployed_tables():
    assert c.tables(c.DEFAULTS) == BEFORE


def test_shipped_file_equals_defaults():
    table, src = c.load(c.DEFAULT_FILE)
    assert src == c.DEFAULT_FILE
    assert table == c.DEFAULTS


def test_hymt_langs_match_server():
    import server
    assert c.HYMT_LANGS == set(server.HYMT_NAMES)
    assert not (BEFORE["MADLAD_ONLY"] & set(server.HYMT_NAMES))


def test_absent_file_means_defaults():
    os.environ.pop("STACK_CONFIG", None)
    shipped, c.DEFAULT_FILE = c.DEFAULT_FILE, "/nonexistent/languages.toml"
    try:
        table, src = c.load()
    finally:
        c.DEFAULT_FILE = shipped
    assert src == "built-in defaults" and c.tables(table) == BEFORE
    try:
        os.environ["STACK_CONFIG"] = "/nonexistent/languages.toml"
        c.load()
        assert False, "an explicit missing file must fail"
    except FileNotFoundError:
        pass
    finally:
        os.environ.pop("STACK_CONFIG", None)


def test_override_replaces_one_language():
    p = _write('[de]\nkokoro = "a:am_adam"\nasr = "whisper"\n[pl]\npiper = "pl_PL-gosia-medium"\n'
               'translator = "hymt"\n')
    table, _ = c.load(p)
    t = c.tables(table)
    assert "de" not in t["PIPER_VOICES"] and t["KOKORO_VOICES"]["de"] == ("a", "am_adam")
    assert t["PIPER_VOICES"]["pl"] == "pl_PL-gosia-medium"
    assert t["PIPER_VOICES"]["en"] == "en_US-lessac-medium"  # untouched languages keep defaults


def test_bad_entries_fail_loudly():
    for bad in ['[de]\npipr = "x"\n', '[de]\nasr = "omni"\n', '[de]\ntranslator = "gemini"\n',
                '[sw]\ntranslator = "hymt"\n', '[de]\nkokoro = "am_adam"\n', '[de]\nvoxcpm = "yes"\n']:
        try:
            c.load(_write(bad))
            assert False, bad
        except ValueError:
            pass


def test_model_defaults_are_the_deployed_models():
    assert c.MODEL_DEFAULTS == MODELS_BEFORE


def test_vad_is_pinned_to_a_commit():
    # torch.hub runs the repo's code (trust_repo=True): a tag or branch could move under us.
    import re
    assert re.fullmatch(r"[0-9a-f]{40}", c.MODEL_DEFAULTS["vad"]["ref"])


def test_shipped_models_equal_defaults():
    models, src = c.load_models(c.DEFAULT_FILE)
    assert src == c.DEFAULT_FILE
    assert models == c.MODEL_DEFAULTS


def test_models_absent_file_means_defaults():
    os.environ.pop("STACK_CONFIG", None)
    shipped, c.DEFAULT_FILE = c.DEFAULT_FILE, "/nonexistent/languages.toml"
    try:
        models, src = c.load_models()
    finally:
        c.DEFAULT_FILE = shipped
    assert src == "built-in defaults" and models == MODELS_BEFORE


def test_models_override_merges_per_key():
    p = _write('[models.hymt]\nrevision = "0123abcd"\n[models.whisper]\nmodel = "large-v3-turbo"\n'
               'revision = ""\n[de]\npiper = "de_DE-thorsten-high"\n')
    models, _ = c.load_models(p)
    assert models["hymt"] == {"repo": "tencent/Hy-MT2-7B", "revision": "0123abcd"}  # repo kept
    assert models["whisper"] == {"model": "large-v3-turbo", "multi_model": "", "multi_revision": "", "revision": ""}
    assert models["madlad"] == MODELS_BEFORE["madlad"]  # untouched models keep defaults
    # [models] is not a language
    table, _ = c.load(p)
    assert "models" not in table and table["de"] == {"piper": "de_DE-thorsten-high"}
    assert c.get(models, "models.hymt.revision") == "0123abcd"
    for bad in ("hymt.revision", "models.hymt", "models.nope.repo", "models.hymt.nope"):
        try:
            c.get(models, bad)
            assert False, bad
        except KeyError:
            pass


def test_bad_models_fail_loudly():
    for bad in ['[models.whisperr]\nmodel = "x"\n', '[models.hymt]\nrepoo = "x"\n',
                '[models.hymt]\nrevision = ""\n', '[models.voxcpm]\nrevision = ""\n',
                '[models.whisper]\nmodel = ""\n', '[models.vad]\nref = 6\n', 'models = "x"\n',
                '[models]\nhymt = "x"\n', '[models.lid]\nrevision = " abc"\n']:
        try:
            c.load_models(_write(bad))
            assert False, bad
        except ValueError:
            pass


def test_get_cli():
    import subprocess
    cfg = os.path.join(ROOT, "server", "stack_config.py")
    env = {**os.environ, "STACK_CONFIG": _write('[models.madlad]\nrevision = "feedbeef"\n')}
    out = subprocess.run([sys.executable, cfg, "get", "models.madlad.revision"], env=env,
                         capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout == "feedbeef\n", out
    out = subprocess.run([sys.executable, cfg, "get", "models.madlad.nope"], env=env, capture_output=True, text=True)
    assert out.returncode != 0 and not out.stdout


def test_scripts_do_not_hardcode_revisions():
    """The revisions live in languages.toml; a copy in a script would drift."""
    for d in ("scripts", os.path.join("scripts", "runpod")):
        for name in os.listdir(os.path.join(ROOT, d)):
            if name.endswith(".sh"):
                text = open(os.path.join(ROOT, d, name)).read()
                for m in MODELS_BEFORE.values():
                    rev = m.get("revision")
                    assert not rev or rev not in text, f"{d}/{name} hardcodes {rev}"


def test_piper_path():
    assert c.piper_path("en_US-lessac-medium") == "en/en_US/lessac/medium/en_US-lessac-medium"
    assert c.piper_path("ja_JP-hi_fi_captain-medium") == "ja/ja_JP/hi_fi_captain/medium/ja_JP-hi_fi_captain-medium"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
