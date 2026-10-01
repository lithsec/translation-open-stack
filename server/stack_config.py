"""Which model serves each language: voice, recogniser, translator.

The defaults below ARE the stack as deployed (the tables server.py used to hold
inline). languages.toml, at the repository root, restates them so an operator can
change a voice or a route without editing Python; tests/test_stack_config.py checks
the two stay equal. Point STACK_CONFIG at another file to use that instead.

A voice is a fallback chain, tried in this order, first one that works wins:

    kokoro -> voxcpm -> coqui -> piper -> mms

so a language may list several (English has Kokoro, with Piper behind it). An
engine only takes part when the server runs it: kokoro needs --kokoro, voxcpm
the voice service (--voxcpm), coqui --coqui (EDITION=commercial), mms --mms
(EDITION=nonprofit). A language with none of them is served as text.

Per-language keys (all optional):

    kokoro      "<lang_code>:<voice>"   Kokoro 82M, e.g. "a:am_michael"
    voxcpm      true                    VoxCPM2 via voxcpm_service.py
    coqui       "<hf repo>"             a Coqui VITS checkpoint
    piper       "<voice name>"          a Piper voice, e.g. "de_DE-thorsten-high"
                                        (scripts/fetch-voices.sh downloads it)
    mms         "<hf repo>"             Meta MMS-TTS (CC-BY-NC)
    asr         "whisper" | "omni:<code>"   the recogniser for this SOURCE language
    translator  "hymt" | "madlad"       Hy-MT2 only covers the languages in
                                        engines/hymt.py's HYMT_NAMES; others use MADLAD
    madlad      "<code>"                MADLAD's target tag, when it differs
    voice       ["<name>", ...]         the voice chain in this order, instead of
                                        the default order above
    [<lang>.commercial]                 the voice keys (and `voice`) to use INSTEAD
                                        with EDITION=commercial; asr, translator
                                        and madlad still come from [<lang>]

Editions (EDITION=nonprofit|commercial, scripts/run.sh): nonprofit loads
everything configured. commercial loads only what server/licences.py classifies
as permissive, attribution or share-alike: a non-commercial (⛔) voice or model
never loads, and an unclear (❓) one only when [licence_review] names it (or
COMMERCIAL_ALLOW_UNCLEAR=1). A language left without a voice is served as text.
apply_edition() does this for `check`; engines/manager.py applies the same
function again at runtime, so neither can be skipped.

    [licence_review]
    "de_DE-thorsten-high" = "reviewed 2026-10-01 by <org>: <why it is acceptable>"

Engines are plug-ins (server/engines/, docs/dev/adding-an-engine.md): asr,
translator and voice accept any registered engine's name, and a voice or
translator that takes a per-language setting is given it under its own name
(`piper = "..."` is Piper's). An unknown name is an error here, not a silent
text-only language.

The same file's [models] table names every model that is NOT chosen per
language, with its exact upstream revision: Whisper, Omnilingual, language ID,
Silero VAD, Hy-MT2, MADLAD 7B and 3B, Kokoro, VoxCPM2 (MODEL_DEFAULTS below).
Unlike a language, a [models.<name>] table is MERGED key by key over the
default, so `[models.hymt]` with only `revision = "..."` keeps the repo.

    python3 server/stack_config.py check            # load, validate, print the tables
    python3 server/stack_config.py check --edition commercial   # what commercial loads, with licences
    python3 server/stack_config.py docs [--write]   # docs/licences.md's generated tables
    python3 server/stack_config.py piper en,es,de   # "<lang> <piper voice>" per line
    python3 server/stack_config.py get models.hymt.revision   # one value, for scripts
    python3 server/stack_config.py engines          # the registered engines, and their files
    python3 server/stack_config.py voxcpm-plan --edition commercial   # "<gpu> <port>" per VoxCPM2 instance
    python3 server/stack_config.py profiles         # the hardware profiles in profiles/
    python3 server/stack_config.py profile cuda-32gb   # what a profile changes (default: $STACK_PROFILE)

A profile (profiles/<name>.toml, STACK_PROFILE=<name>) is the hardware half:
which device each model loads on ([devices]), smaller models, script defaults
([env]) and per-language route changes. See "Profiles and devices" below.
"""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)   # for `import engines` (server/engines/)
# languages.toml lives at the repository root (one level up from server/),
# where operators edit it. STACK_CONFIG overrides it.
DEFAULT_FILE = os.path.join(os.path.dirname(HERE), "languages.toml")

# Hy-MT2's languages as of the pinned revision; a source outside these pivots
# through English (server.py), a target outside them is translated by MADLAD.
HYMT_LANGS = {
    "en", "zh", "fr", "pt", "es", "ja", "tr", "ru", "ar", "ko", "th", "it", "de", "vi", "ms", "id", "tl",
    "hi", "pl", "cs", "nl", "km", "my", "fa", "gu", "ur", "te", "mr", "he", "bn", "ta", "uk", "bo", "kk",
    "mn", "ug", "yue",
}

# Today's stack, one entry per language. Keep languages.toml equal to this.
# "commercial": the voices EDITION=commercial uses instead (docs/licences.md §3);
# a language without one keeps its own voices, minus any that licences.py does
# not allow commercially (pt zh ja hi keep Kokoro; fa and ro get eSpeak NG only).
DEFAULTS = {
    "en": {"kokoro": "a:am_michael", "piper": "en_US-lessac-medium", "asr": "whisper", "translator": "hymt",
           "commercial": {"kokoro": "a:am_michael", "piper": "en_US-norman-medium"}},
    "es": {"kokoro": "e:ef_dora", "piper": "es_ES-davefx-medium", "asr": "whisper", "translator": "hymt",
           "madlad": "es", "commercial": {"kokoro": "e:ef_dora", "piper": "es_ES-carlfm-x_low"}},
    "fr": {"kokoro": "f:ff_siwis", "piper": "fr_FR-siwis-medium", "asr": "whisper", "translator": "hymt",
           "madlad": "fr", "commercial": {"kokoro": "f:ff_siwis", "piper": "fr_FR-mls-medium"}},
    "pt": {"kokoro": "p:pf_dora", "piper": "pt_BR-faber-medium", "asr": "whisper", "translator": "hymt",
           "madlad": "pt"},
    "it": {"kokoro": "i:if_sara", "piper": "it_IT-serena-high", "asr": "whisper", "translator": "hymt",
           "madlad": "it"},
    "de": {"piper": "de_DE-thorsten-high", "asr": "whisper", "translator": "hymt", "madlad": "de",
           "commercial": {"piper": "de_DE-mls-medium"}},
    "ru": {"piper": "ru_RU-irina-medium", "asr": "whisper", "translator": "hymt", "madlad": "ru",
           "commercial": {"voxcpm": True}},
    "uk": {"piper": "uk_UA-ukrainian_tts-medium", "asr": "whisper", "translator": "hymt", "madlad": "uk"},
    "zh": {"kokoro": "z:zf_xiaobei", "piper": "zh_CN-huayan-medium", "asr": "whisper", "translator": "hymt",
           "madlad": "zh"},
    "ja": {"kokoro": "j:jf_alpha", "piper": "ja_JP-hi_fi_captain-medium", "asr": "whisper",
           "translator": "hymt", "madlad": "ja"},
    "ko": {"piper": "ko_KR-kss-medium", "asr": "whisper", "translator": "hymt", "madlad": "ko",
           "commercial": {"voxcpm": True}},
    "vi": {"piper": "vi_VN-vais1000-medium", "asr": "whisper", "translator": "hymt", "madlad": "vi",
           "commercial": {"voxcpm": True}},
    "ar": {"piper": "ar_JO-kareem-medium", "asr": "whisper", "translator": "hymt", "madlad": "ar",
           "commercial": {"voxcpm": True}},
    "fa": {"piper": "fa_IR-gyro-medium", "asr": "omni:pes_Arab", "translator": "hymt", "madlad": "fa"},
    "id": {"piper": "id_ID-news_tts-medium", "asr": "whisper", "translator": "hymt", "madlad": "id",
           "commercial": {"voxcpm": True}},
    "tr": {"piper": "tr_TR-dfki-medium", "asr": "whisper", "translator": "hymt", "madlad": "tr",
           "commercial": {"voxcpm": True}},
    "bn": {"piper": "bn_BD-google-medium", "asr": "omni:ben_Beng", "translator": "hymt", "madlad": "bn"},
    "ur": {"piper": "ur_PK-aegis_female-medium", "asr": "omni:urd_Arab", "translator": "hymt", "madlad": "ur"},
    "hi": {"kokoro": "h:hf_alpha", "piper": "hi_IN-rohan-medium", "asr": "omni:hin_Deva", "translator": "hymt",
           "madlad": "hi"},
    "sw": {"piper": "sw_CD-lanfrica-medium", "asr": "omni:swh_Latn", "translator": "madlad", "madlad": "sw",
           "commercial": {"voxcpm": True}},
    "ro": {"piper": "ro_RO-mihai-medium", "asr": "whisper", "translator": "madlad", "madlad": "ro"},
    "ht": {"coqui": "multilingual-tts/VITS-OpenBible-Haitian-Creole", "mms": "facebook/mms-tts-hat",
           "asr": "omni:hat_Latn", "translator": "madlad", "madlad": "ht"},
    "km": {"voxcpm": True, "mms": "facebook/mms-tts-khm", "asr": "omni:khm_Khmr", "translator": "hymt",
           "madlad": "km"},
    "lo": {"voxcpm": True, "mms": "facebook/mms-tts-lao", "asr": "omni:lao_Laoo", "translator": "madlad",
           "madlad": "lo"},
    # MADLAD's code for Tagalog is fil (<2tl> is not in its vocabulary).
    "tl": {"voxcpm": True, "mms": "facebook/mms-tts-tgl", "asr": "whisper", "translator": "hymt",
           "madlad": "fil"},
}

# Every model the stack loads that is not chosen per language, with its exact
# upstream revision: these ARE the deployed stack (docs/reference.md,
# "[models.<name>]"). languages.toml's [models] restates them; tests pin them.
# A revision of "" means "whatever upstream serves now" (no pin).
MODEL_DEFAULTS = {
    # faster-whisper, for every source Omnilingual doesn't take. run.sh passes
    # these as --asr-model/--asr-revision. multi_model is the model for
    # non-English sources (--asr-multi-model); "" = the same one, loaded once.
    # The revision belongs to `model`'s repo (large-v3 -> Systran/faster-whisper-large-v3).
    "whisper": {"model": "large-v3", "multi_model": "", "multi_revision": "",
                "revision": "edaa852ec7e145841d8ffdb056a99866b5f0a478"},
    # Meta Omnilingual ASR, for the languages with asr = "omni:<code>". A fairseq2
    # model card names one fixed checkpoint; there is no revision to pin.
    "omnilingual": {"card": "omniASR_LLM_300M"},
    # Spoken-language ID for src=auto (SpeechBrain).
    "lid": {"repo": "speechbrain/lang-id-voxlingua107-ecapa",
            "revision": "0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9"},
    # Silero VAD through torch.hub: a git tag, branch or commit of the repo. Pinned
    # to the commit of tag v6.2.3 (a tag can be moved; torch.hub accepts a commit
    # that is the head of a branch or tag).
    "vad": {"repo": "snakers4/silero-vad", "ref": "5cd7945676eb32225748052e2e6a0580e4686a08"},
    # Translators, built once by scripts/prepare-mt.sh (4-bit Hy-MT2, CTranslate2
    # int8 MADLAD). A new revision is rebuilt there; see its header.
    "hymt": {"repo": "tencent/Hy-MT2-7B", "revision": "9b0eb4e8f001def3e5ff6469a0ac96fdb39ec223"},
    "madlad": {"repo": "google/madlad400-7b-mt", "revision": "1ff63ce7ddd571a69d45cad9672c553428419671"},
    "madlad3b": {"repo": "google/madlad400-3b-mt", "revision": "fa184c675da0b5c9e1c8694fccd4e12e2d422094"},
    # Voices that are not per-language repos (those are in each language's table).
    "kokoro": {"repo": "hexgrad/Kokoro-82M", "revision": "f3ff3571791e39611d31c381e3a41a3af07b4987"},
    "voxcpm": {"repo": "openbmb/VoxCPM2", "revision": "32279effe8c19989596f05d353d1447f51d9e915"},
    # MLX builds for the Apple GPU: used instead of the two above when [devices]
    # puts whisper or hymt on "mps" (profiles/mac.toml). Downloaded at start.
    "whisper_mlx": {"repo": "mlx-community/whisper-large-v3-turbo",
                    "revision": "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"},
    "hymt_mlx": {"repo": "mlx-community/Hy-MT2-7B-4bit", "revision": "9b7204bdb161490a8ce49ce607c1310cc3fd03ad"},
}
# Built from a revision, so they need one: a floating "main" would change the
# model under a build stamped with it.
MODELS_PINNED = {"hymt", "madlad", "madlad3b", "voxcpm"}

# The keys a language table may use: these, plus every registered engine that
# takes a per-language value (keys()). The built-in engines give exactly the
# set this file always had: kokoro voxcpm coqui piper mms madlad.
BASE_KEYS = {"asr": str, "translator": str, "voice": list, "commercial": dict}


def _engines():
    import engines
    return engines


def keys():
    """{key: type} for a language table: BASE_KEYS and the engines' own keys."""
    out = dict(BASE_KEYS)
    for kind in ("voice", "translator", "recognizer"):
        for name, cls in _engines().registry(kind).items():
            if cls.lang_key is not None:
                out[name] = cls.lang_key
    return out


def model_defaults():
    """MODEL_DEFAULTS plus the [models.<name>] tables engines declare for themselves."""
    out = copy.deepcopy(MODEL_DEFAULTS)
    for kind, reg in _engines().registry().items():
        for name, cls in reg.items():
            if cls.models and name not in out:
                out[name] = dict(cls.models)
    return out


def _read_toml(path):
    try:
        import tomllib
    except ImportError:  # Python < 3.11
        import tomli as tomllib
    with open(path, "rb") as f:
        return tomllib.load(f)


def validate(table):
    """Raise ValueError naming the first bad entry. Loud on purpose: a typo in a
    voice name must not quietly turn a language into text only."""
    known = keys()
    eng = _engines()
    for lang, entry in table.items():
        if not isinstance(entry, dict):
            raise ValueError(f"[{lang}] must be a table of keys")
        for k, v in entry.items():
            if k not in known:
                raise ValueError(f"[{lang}] unknown key {k!r} (known: {', '.join(known)})")
            if not isinstance(v, known[k]):
                raise ValueError(f"[{lang}] {k} must be a {known[k].__name__}")
            if k not in BASE_KEYS:
                cls = next(c for r in eng.registry().values() for n, c in r.items() if n == k)
                why = cls.check_lang(lang, v)
                if why:
                    raise ValueError(f"[{lang}] {why}")
        asr = entry.get("asr", "whisper")
        name, _, arg = asr.partition(":")
        try:
            rec = eng.get("recognizer", name)
        except ValueError as e:
            raise ValueError(f"[{lang}] asr: {e}") from None
        if rec.arg == "required" and not arg:
            raise ValueError(f"[{lang}] asr must be \"{name}:<code>\" (got {asr!r})")
        if rec.arg == "none" and ":" in asr:
            raise ValueError(f"[{lang}] asr must be \"{name}\", without \":...\" (got {asr!r})")
        tr = entry.get("translator", "hymt")
        try:
            cls = eng.get("translator", tr)
        except ValueError as e:
            raise ValueError(f"[{lang}] translator: {e}") from None
        if "translator" in entry and cls.languages is not None and lang not in cls.languages:
            raise ValueError(f"[{lang}] {cls.title or tr} does not support {lang}; use translator = \"madlad\"")
        for v in entry.get("voice", []):
            if not isinstance(v, str):
                raise ValueError(f"[{lang}] voice must be a list of voice names")
            try:
                eng.get("voice", v)
            except ValueError as e:
                raise ValueError(f"[{lang}] voice: {e}") from None
        if "commercial" in entry:
            _validate_commercial(lang, entry["commercial"], known)
    return table


def _validate_commercial(lang, comm, known):
    """[<lang>.commercial]: voice keys and `voice` only (the language's own asr,
    translator and madlad apply in both editions)."""
    eng = _engines()
    voices = eng.registry("voice")
    for k, v in comm.items():
        if k != "voice" and (k not in voices or k not in known):
            raise ValueError(f"[{lang}.commercial] may only name voices (and `voice`); {k!r} is not a voice")
        if not isinstance(v, known[k]):
            raise ValueError(f"[{lang}.commercial] {k} must be a {known[k].__name__}")
        if k == "voice":
            for n in v:
                if not isinstance(n, str) or n not in voices:
                    raise ValueError(f"[{lang}.commercial] voice: unknown voice {n!r}")
        else:
            why = voices[k].check_lang(lang, v)
            if why:
                raise ValueError(f"[{lang}.commercial] {why}")


# ------------------------------------------------------------------ editions

EDITIONS = ("nonprofit", "commercial")
# Voice engines scripts/run.sh does NOT start in an edition (--mms is nonprofit
# only, --coqui commercial only). Licence enforcement is separate and stricter.
EDITION_OFF = {"nonprofit": {"coqui"}, "commercial": {"mms"}}


def _licences():
    import licences
    return licences


def edition(value=None):
    """The edition: `value`, else $EDITION, else nonprofit. Anything else is an error."""
    ed = value or os.environ.get("EDITION") or "nonprofit"
    if ed not in EDITIONS:
        raise ValueError(f"EDITION must be nonprofit or commercial (got {ed!r})")
    return ed


def allow_unclear():
    """COMMERCIAL_ALLOW_UNCLEAR=1: every ❓ item may load in commercial (loudly)."""
    return os.environ.get("COMMERCIAL_ALLOW_UNCLEAR", "") == "1"


def validate_reviews(reviews):
    """[licence_review]: "<voice, repo or engine>" = "<who reviewed it, when, why>".
    A review can never admit a non-commercial item."""
    lic = _licences()
    if not isinstance(reviews, dict):
        raise ValueError("[licence_review] must be a table of \"<item>\" = \"<who reviewed it, when, and why>\"")
    known = {}
    for engine, items in lic.ITEMS.items():
        known.update(items)
    known.update(lic.ENGINES)
    known.update(lic.MODELS)
    for k, v in reviews.items():
        if not isinstance(v, str) or len(v.strip()) < 8:
            raise ValueError(f"[licence_review] {k!r}: say who reviewed it, when, and why (a sentence, not {v!r})")
        if k in known and known[k].cls == lic.NONCOMMERCIAL:
            raise ValueError(f"[licence_review] {k!r} is non-commercial ({known[k].licence}): "
                             "there is no override for ⛔ items")
    return reviews


def load_reviews(path=None):
    """{item: note} from the file's [licence_review] table ({} when none)."""
    data, _ = _source(path)
    return validate_reviews(dict((data or {}).get("licence_review", {})))


def voice_order(entry, lang=None):
    """[(engine, value)] for a language's voices, in the order the chain tries
    them: the `voice` list if given, else by engine priority (manager.py).
    With `lang`, the last-resort voices (eSpeak NG) that speak it follow,
    named or not, unless the table says `<name> = false` (manager.py appends
    them the same way)."""
    voices = _engines().registry("voice")
    last = {n for n, cls in voices.items() if getattr(cls, "last_resort", False)}
    if entry.get("voice"):
        names = [n for n in entry["voice"] if n in voices and n not in last]
    else:
        names = sorted((k for k in entry if k in voices and k not in last), key=lambda n: (voices[n].priority, n))
    if lang is not None:
        names += sorted((n for n in last if entry.get(n) is not False and voices[n].covers(lang)),
                        key=lambda n: (voices[n].priority, n))
    return [(n, entry.get(n)) for n in names]


def apply_edition(table, ed, reviews=None, unclear_ok=None):
    """(effective table, report) for an edition.

    nonprofit: the table as written ([<lang>.commercial] is ignored).
    commercial: [<lang>.commercial] replaces the language's voices; then every
    voice, recogniser and translator is looked up in licences.py and only what
    licences.allowed() admits stays. A ⛔ item named in a [<lang>.commercial]
    table is a configuration error; one inherited from [<lang>] is dropped and
    reported. report = {lang: {"voices": [(engine, value, Lic)], "dropped":
    [(engine, value, Lic)], "text_only": bool}} where voices are the ones the
    edition runs (EDITION_OFF), in chain order."""
    lic = _licences()
    reviews = reviews or {}
    unclear_ok = allow_unclear() if unclear_ok is None else unclear_ok
    reg = _engines().registry()
    voice_names = set(reg["voice"])
    out, report = {}, {}
    for lang, entry in table.items():
        e = copy.deepcopy(entry)
        comm = e.pop("commercial", None)
        dropped = []
        if ed == "commercial":
            if comm is not None:
                for k in [k for k in e if k in voice_names or k == "voice"]:
                    del e[k]
                e.update(copy.deepcopy(comm))
            for kind, name in (("recognizer", e.get("asr", "whisper").split(":", 1)[0]),
                               ("translator", e.get("translator", "hymt"))):
                li = lic.lookup(name, cls=reg[kind].get(name))
                if not lic.allowed(li, ed, name in reviews, unclear_ok):
                    raise ValueError(f"[{lang}] {kind} {name} is {lic.SYMBOL[li.cls]} {li.cls} ({li.reason}): "
                                     "not allowed with EDITION=commercial")
            for name, value in voice_order(e, lang):
                li = lic.lookup(name, value if isinstance(value, str) else None, cls=reg["voice"].get(name))
                if lic.allowed(li, ed, lic.item_id(name, value) in reviews, unclear_ok):
                    continue
                if comm is not None and (name in comm or name in comm.get("voice", [])) \
                        and li.cls == lic.NONCOMMERCIAL:
                    raise ValueError(f"[{lang}.commercial] {name} {value if isinstance(value, str) else ''} is "
                                     f"⛔ non-commercial ({li.licence}): it can never load in commercial")
                dropped.append((name, value, li))
                e.pop(name, None)
                if "voice" in e:
                    e["voice"] = [n for n in e["voice"] if n != name]
        voices = [(n, v, lic.lookup(n, v if isinstance(v, str) else None, cls=reg["voice"].get(n)))
                  for n, v in voice_order(e, lang) if n not in EDITION_OFF[ed]]
        out[lang] = e
        report[lang] = {"voices": voices, "dropped": dropped, "text_only": not voices}
    return out, report


# ------------------------------------------------------------------ VoxCPM2 capacity

# One voxcpm_service.py makes one voice at a time: ~2-3 real-time voices per GPU
# (RTF 0.28 on an A100). scripts/run.sh starts the instances this plan names,
# on ports VOXCPM_PORT (8791), +1, ...; the server balances over all of them
# (engines/voxcpm.py) and sends what none can take to the next voice.
VOXCPM_PORT = 8791
# ~7 GB per instance (6.2-7.1 GB measured) plus room for activations. The main
# stack's GPU is not checked: it has always held one instance.
VOXCPM_MIN_GPU_MB = 10 * 1024
VOXCPM_MAX_INSTANCES = 4


def detect_gpus():
    """[(id, memory MB)] of the GPUs this process may use, main GPU first:
    nvidia-smi's list, narrowed and ordered by CUDA_VISIBLE_DEVICES when set.
    STACK_GPUS="0:81920,1:46068" stands in for nvidia-smi (tests, dry runs).
    [] when there is no NVIDIA GPU (or no nvidia-smi)."""
    fake = os.environ.get("STACK_GPUS")
    if fake is not None:
        out = []
        for part in [x for x in fake.split(",") if x.strip()]:
            gid, _, mb = part.strip().partition(":")
            out.append((gid, int(mb) if mb else None))
        return out
    import subprocess
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=index,uuid,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []
    rows = []
    for line in r.stdout.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) >= 3 and f[0].isdigit():
            rows.append((f[0], f[1], int(float(f[2])) if f[2].replace(".", "").isdigit() else None))
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible is None:
        return [(i, mb) for i, _, mb in rows]
    out = []
    for v in [x.strip() for x in visible.split(",") if x.strip()]:
        hit = next((row for row in rows if v in (row[0], row[1]) or (v.startswith("GPU-") and row[1].startswith(v))),
                   None)
        if hit is None:
            break           # CUDA stops at the first invalid entry, and so do we
        out.append((hit[0], hit[2]))
    return out


def voxcpm_plan(ed, gpus, instances=None, devices=None, max_instances=None, min_mb=VOXCPM_MIN_GPU_MB,
                port=VOXCPM_PORT):
    """Where VoxCPM2 runs: {"instances": [(gpu id or None, port)], "message": str, "notes": [str]}.

    gpus: detect_gpus(), the main GPU (the rest of the stack's) first.
    instances: VOXCPM_INSTANCES: "auto" | "<n>". Default: "auto" in
      commercial (it routes ten languages to VoxCPM2), "1" in nonprofit (today's
      single instance, which serves km lo tl).
      auto: one on the main GPU, plus one on each other GPU with at least
      min_mb of memory, up to max_instances (VOXCPM_MAX_INSTANCES, 4).
      <n>: the main GPU, then the other usable GPUs in order, n at most.
    devices: VOXCPM_GPUS, e.g. ["0", "1"] or ["0", "1", "1"] (two on GPU 1):
      exactly these GPUs, in this order (instances, if a number, takes the first n).
    Raises ValueError for a bad setting."""
    ed = edition(ed)
    raw = (instances or "").strip() or ("auto" if ed == "commercial" else "1")
    default = not (instances or "").strip()
    if raw != "auto" and not raw.isdigit():
        raise ValueError(f"VOXCPM_INSTANCES must be auto or a number (got {raw!r})")
    cap = max_instances or VOXCPM_MAX_INSTANCES
    notes = []
    ids = [g for g, _ in gpus]
    mem = dict(gpus)
    if raw == "0":
        return {"instances": [], "message": "VoxCPM2: off (VOXCPM_INSTANCES=0)", "notes": notes}
    if devices:
        for d in devices:
            if gpus and d not in ids:
                raise ValueError(f"VOXCPM_GPUS names GPU {d}, which is not visible (visible: {', '.join(ids)})")
        chosen = list(devices)
        if raw.isdigit() and not default:
            chosen = chosen[:int(raw)]
        why = "VOXCPM_GPUS"
    elif not gpus:
        chosen = [None]
        why = "no GPU detected"
    else:
        usable = [ids[0]]
        for g in ids[1:]:
            if mem.get(g) is not None and mem[g] < min_mb:
                notes.append(f"GPU {g} not used for VoxCPM2: {mem[g] / 1024:.0f} GB < {min_mb / 1024:.0f} GB")
            else:
                usable.append(g)
        want = min(len(usable), cap) if raw == "auto" else int(raw)
        if raw != "auto" and want > len(usable):
            notes.append(f"VOXCPM_INSTANCES={raw} but {len(usable)} usable GPU{'s' * (len(usable) > 1)}: "
                         f"{len(usable)} instance{'s' * (len(usable) > 1)} (VOXCPM_GPUS=0,1,1 puts two on one GPU)")
        if raw == "auto" and len(usable) > cap:
            notes.append(f"{len(usable)} usable GPUs, capped at VOXCPM_MAX_INSTANCES={cap}")
        chosen = usable[:want]
        why = (f"VOXCPM_INSTANCES={raw}" + (f", the {ed} default" if default else ""))
    plan = [(g, port + i) for i, g in enumerate(chosen)]
    k = len(plan)
    if k == 1:
        where = ("one GPU" if len(gpus) == 1 and not devices else
                 "no GPU detected" if chosen[0] is None else f"GPU {chosen[0]}; {why}")
        message = f"VoxCPM2: 1 instance ({where}); overflow → fallback voices"
    else:
        message = f"VoxCPM2: {k} instances ({', '.join(f'GPU {g}' for g in chosen)})"
    return {"instances": plan, "message": message, "notes": notes}


def voxcpm_plan_lines(ed, vox_langs):
    """What `check` says about VoxCPM2's instances (they depend on the GPUs at start)."""
    raw = os.environ.get("VOXCPM_INSTANCES", "")
    mode = raw or ("auto" if ed == "commercial" else "1")
    cap = os.environ.get("VOXCPM_MAX_INFLIGHT") or "1"
    lines = [f"VoxCPM2 speaks {len(vox_langs)} language{'s' * (len(vox_langs) != 1)}"
             f"{' (' + ', '.join(vox_langs) + ')' if vox_langs else ''}; one instance makes ~2-3 real-time "
             f"voices, and takes up to {cap} sentences at once (VOXCPM_MAX_INFLIGHT)"]
    if mode == "auto":
        lines.append(f"VoxCPM2 instances: auto{'' if raw else f' (the {ed} default)'}: one on the main GPU plus one on "
                     f"each other GPU with ≥ {VOXCPM_MIN_GPU_MB // 1024} GB, up to {VOXCPM_MAX_INSTANCES} — "
                     "depends on the GPUs at start (VOXCPM_INSTANCES, VOXCPM_GPUS)")
    else:
        lines.append(f"VoxCPM2 instances: {mode}{'' if raw else f' (the {ed} default)'} "
                     "(VOXCPM_INSTANCES=auto|<n>, VOXCPM_GPUS)")
    gpus = detect_gpus()
    if gpus:
        try:
            plan = voxcpm_plan(ed, gpus, raw or None,
                               [x for x in os.environ.get("VOXCPM_GPUS", "").split(",") if x.strip()] or None)
            lines.append(f"on this machine now: {plan['message']}")
            lines += [f"  {n}" for n in plan["notes"]]
        except ValueError as e:
            lines.append(f"on this machine now: {e}")
    return lines


def model_report(models, ed, reviews=None, unclear_ok=None):
    """[(name, Lic, allowed)] for every [models.<name>] table."""
    lic = _licences()
    reviews = reviews or {}
    unclear_ok = allow_unclear() if unclear_ok is None else unclear_ok
    out = []
    for name, entry in models.items():
        li = lic.model_lookup(name, entry)
        value = next((entry[k] for k in lic.MODEL_KEYS if entry.get(k)), name)
        out.append((name, li, lic.allowed(li, ed, value in reviews or name in reviews, unclear_ok)))
    return out


def commercial_problems(models, reviews=None, unclear_ok=None):
    """What stops EDITION=commercial from starting: [models] it may not load."""
    return [f"[models.{n}] {li.licence}: {li.reason}" for n, li, ok in model_report(models, "commercial", reviews,
                                                                                    unclear_ok) if not ok]


def validate_models(models):
    """Raise ValueError naming the first bad [models] entry (after merging over
    the defaults)."""
    defaults = model_defaults()
    for name, entry in models.items():
        if name not in defaults:
            raise ValueError(f"[models.{name}] unknown model (known: {', '.join(defaults)})")
        if not isinstance(entry, dict):
            raise ValueError(f"[models.{name}] must be a table of keys")
        for k, v in entry.items():
            if k not in defaults[name]:
                raise ValueError(f"[models.{name}] unknown key {k!r} (known: {', '.join(defaults[name])})")
            if not isinstance(v, str):
                raise ValueError(f"[models.{name}] {k} must be a string")
            if v != v.strip():
                raise ValueError(f"[models.{name}] {k} has surrounding spaces")
        for k in ("model", "repo", "card"):
            if k in entry and not entry[k]:
                raise ValueError(f"[models.{name}] {k} must not be empty")
        if name in MODELS_PINNED and not entry.get("revision"):
            raise ValueError(f"[models.{name}] needs a revision (a commit hash): it is built from one")
    return models


def _source(path):
    """(data or None, source). data is None when the built-in defaults apply."""
    path = path or os.environ.get("STACK_CONFIG") or ""
    explicit = bool(path)
    path = path or DEFAULT_FILE
    if not os.path.exists(path):
        if explicit:
            raise FileNotFoundError(f"STACK_CONFIG={path} does not exist")
        return None, "built-in defaults"
    try:
        return _read_toml(path), path
    except ImportError:
        if explicit:
            raise
        # macOS's python3 is 3.9: no tomllib. The shipped file equals the defaults.
        print(f"[stack] can't read {path} on Python {sys.version.split()[0]} (needs 3.11+) — built-in defaults",
              file=sys.stderr)
        return None, "built-in defaults"


# Top-level tables of languages.toml that are not languages.
NOT_LANGUAGES = ("models", "licence_review", "devices")


def load(path=None, profile=None):
    """(table, source). Per language, the file REPLACES the default entry: a
    [de] section without piper means German has no Piper voice. Languages the
    file does not mention keep their defaults. ([models] is load_models().)
    Then the profile's [languages.<lang>] tables, merged key by key."""
    table = copy.deepcopy(DEFAULTS)
    data, src = _source(path)
    if data is not None:
        table.update(validate({k: dict(v) if isinstance(v, dict) else v for k, v in data.items()
                               if k not in NOT_LANGUAGES}))
    prof = load_profile(profile)
    if prof.get("languages"):
        for lang, over in prof["languages"].items():
            table[lang] = {**table.get(lang, {}), **over}
        validate(table)
        src = f"{src} + profile {prof['name']}"
    return table, src


def _merge_models(models, given, where):
    if not isinstance(given, dict):
        raise ValueError(f"{where}[models] must be a table of [models.<name>] tables")
    for name, entry in given.items():
        if name not in models:
            raise ValueError(f"{where}[models.{name}] unknown model (known: {', '.join(models)})")
        if not isinstance(entry, dict):
            raise ValueError(f"{where}[models.{name}] must be a table of keys")
        models[name].update(entry)


def load_models(path=None, profile=None):
    """(models, source): MODEL_DEFAULTS (and any engine's own [models.<name>]
    defaults) with the file's [models.<name>] tables merged over them key by
    key, then the profile's the same way."""
    models = model_defaults()
    data, src = _source(path)
    if data is not None:
        _merge_models(models, data.get("models", {}), "")
    prof = load_profile(profile)
    if prof.get("models"):
        _merge_models(models, prof["models"], f"profile {prof['name']}: ")
        src = f"{src} + profile {prof['name']}"
    return validate_models(models), src


# ---- Profiles and devices ------------------------------------------------------
# A profile is the hardware half of a deployment, kept apart from the languages
# and the edition: profiles/<name>.toml, chosen with STACK_PROFILE=<name> (or a
# path). It may hold
#
#   description = "..."          one line, for `stack_config.py profiles`
#   [env]                        defaults for the scripts' variables (MADLAD,
#                                VOXCPM_GPUS, LANGS, ...); the environment wins
#   [devices]                    which device each model loads on (below)
#   [models.<name>]              merged over languages.toml's, key by key
#   [languages.<lang>]           merged over that language's table, key by key
#                                (e.g. asr = "whisper" where Omnilingual can't run)
#
# and wins over languages.toml, so one line switches the whole setup:
# `STACK_PROFILE=cuda-32gb`. `stack_config.py profile` prints what it changes.
#
# [devices] (in languages.toml, a profile, or STACK_DEVICES="whisper=cuda:1,hymt=cuda:0"):
# "default" and any engine name (whisper, omni, hymt, madlad, kokoro, coqui,
# mms, cosyvoice), plus "lid" (language ID). Values: "auto" (the first GPU, or
# the CPU), "cpu", "cuda", "cuda:<n>", "mps". AMD cards under ROCm are "cuda"
# too. VoxCPM2 runs in its own processes: its GPUs are VOXCPM_GPUS.

PROFILES_DIR = os.path.join(os.path.dirname(HERE), "profiles")
PROFILE_KEYS = {"description", "env", "devices", "models", "languages"}
DEVICE_PSEUDO = {"default", "lid"}


def _valid_device(v):
    import re
    return isinstance(v, str) and re.fullmatch(r"auto|cpu|mps|cuda(:\d+)?", v) is not None


def profile_path(name):
    """profiles/<name>.toml, or `name` itself when it is a path."""
    import re
    if os.sep in name or name.endswith(".toml"):
        return name
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", name):
        raise ValueError(f"STACK_PROFILE={name!r}: a profile name is letters, digits and . _ + -")
    return os.path.join(PROFILES_DIR, f"{name}.toml")


def list_profiles():
    """[(name, description)] of the shipped profiles."""
    out = []
    for f in sorted(os.listdir(PROFILES_DIR)) if os.path.isdir(PROFILES_DIR) else []:
        if f.endswith(".toml"):
            out.append((f[:-5], str(_read_toml(os.path.join(PROFILES_DIR, f)).get("description", ""))))
    return out


def load_profile(name=None):
    """The profile as a dict (with "name"), {} when none is chosen. Loud on any
    mistake: a typo in a profile must not quietly run the wrong hardware setup."""
    import re
    name = name if name is not None else os.environ.get("STACK_PROFILE", "")
    if not name:
        return {}
    path = profile_path(name)
    if not os.path.exists(path):
        have = ", ".join(n for n, _ in list_profiles()) or "none"
        raise FileNotFoundError(f"STACK_PROFILE={name}: no {path} (profiles: {have})")
    data = _read_toml(path)
    where = f"profile {name}"
    bad = set(data) - PROFILE_KEYS
    if bad:
        raise ValueError(f"{where}: unknown table(s) {', '.join(sorted(bad))} (known: {', '.join(sorted(PROFILE_KEYS))})")
    env = data.get("env", {})
    if not isinstance(env, dict):
        raise ValueError(f"{where}: [env] must be a table")
    for k, v in env.items():
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", k) or not isinstance(v, (str, int, bool)):
            raise ValueError(f"{where}: [env] {k} must be an UPPER_CASE name with a string or number")
    langs = data.get("languages", {})
    if not isinstance(langs, dict) or not all(isinstance(v, dict) for v in langs.values()):
        raise ValueError(f"{where}: [languages] must hold [languages.<lang>] tables")
    validate_devices(data.get("devices", {}), where)
    return {**data, "name": name, "path": path}


def validate_devices(devices, where="[devices]"):
    if not isinstance(devices, dict):
        raise ValueError(f"{where}: [devices] must be a table")
    names = set(DEVICE_PSEUDO)
    for reg in _engines().registry().values():
        names |= set(reg)
    for k, v in devices.items():
        if k not in names:
            raise ValueError(f"{where}: [devices] unknown {k!r} (known: {', '.join(sorted(names))})")
        if not _valid_device(v):
            raise ValueError(f"{where}: [devices] {k} = {v!r}: use auto, cpu, mps, cuda or cuda:<n>")
    return devices


def load_devices(path=None, profile=None):
    """{name: device spec} ("default" always present): languages.toml's
    [devices], then the profile's, then STACK_DEVICES. Specs are unresolved
    ("auto" stays "auto"); the server resolves them (engines.common.resolve_device)."""
    devices = {"default": "auto"}
    data, _ = _source(path)
    if data is not None:
        devices.update(validate_devices(data.get("devices", {}), "languages.toml"))
    devices.update(load_profile(profile).get("devices", {}))
    raw = os.environ.get("STACK_DEVICES", "")
    if raw.strip():
        env = {}
        for part in raw.split(","):
            k, sep, v = part.partition("=")
            if not sep:
                raise ValueError(f"STACK_DEVICES: {part!r} is not name=device")
            env[k.strip()] = v.strip()
        devices.update(validate_devices(env, "STACK_DEVICES"))
    return devices


def profile_env_lines(profile=None):
    """Shell lines that set the profile's [env] for every variable the
    environment leaves unset (scripts/profile-env.sh evals them)."""
    import shlex
    prof = load_profile(profile)
    out = []
    for k, v in prof.get("env", {}).items():
        v = ("1" if v else "0") if isinstance(v, bool) else str(v)
        if k not in os.environ:
            out.append(f"export {k}={shlex.quote(v)}")
    return out


def profile_lines(profile=None):
    """What a profile changes, for `stack_config.py profile [<name>]`."""
    prof = load_profile(profile)
    if not prof:
        return ["no profile (STACK_PROFILE unset): languages.toml as it is, every model on the default device"]
    lines = [f"profile {prof['name']}: {prof.get('description', '')}", f"  file: {prof['path']}"]
    for k, v in prof.get("env", {}).items():
        now = os.environ.get(k)
        tail = f"  (environment has {k}={now}, which wins)" if now is not None and now != str(v) else ""
        lines.append(f"  env      {k}={v}{tail}")
    devices = load_devices(profile=profile)
    for k, v in sorted(devices.items(), key=lambda kv: (kv[0] != "default", kv[0])):
        lines.append(f"  device   {k:10} {v}")
    defaults = model_defaults()
    models, _ = load_models(profile=profile)
    for name, entry in prof.get("models", {}).items():
        for key, val in entry.items():
            lines.append(f"  model    {name}.{key} = {val!r} (default {defaults.get(name, {}).get(key)!r})")
    for lang, over in prof.get("languages", {}).items():
        lines.append(f"  language {lang}: " + ", ".join(f"{k} = {v!r}" for k, v in over.items()))
    return lines


def get(models, dotted):
    """models.<name>.<key> -> its value (KeyError when there is no such key)."""
    parts = dotted.split(".")
    if len(parts) != 3 or parts[0] != "models" or parts[1] not in models or parts[2] not in models[parts[1]]:
        raise KeyError(dotted)
    return models[parts[1]][parts[2]]


def tables(table):
    """The lookup tables server.py uses, derived from a loaded table."""
    return {
        "KOKORO_VOICES": {l: tuple(e["kokoro"].split(":")) for l, e in table.items() if "kokoro" in e},
        "VOXCPM_LANGS": {l for l, e in table.items() if e.get("voxcpm")},
        "COQUI_VOICES": {l: e["coqui"] for l, e in table.items() if "coqui" in e},
        "PIPER_VOICES": {l: e["piper"] for l, e in table.items() if "piper" in e},
        "MMS_VOICES": {l: e["mms"] for l, e in table.items() if "mms" in e},
        "OMNI_LANGS": {l: e["asr"][5:] for l, e in table.items() if e.get("asr", "").startswith("omni:")},
        "LANG_TO_MADLAD": {l: e["madlad"] for l, e in table.items() if "madlad" in e},
        # Languages kept off Hy-MT2 even though it supports them.
        "MADLAD_ONLY": {l for l, e in table.items() if e.get("translator") == "madlad"},
    }


def piper_path(voice):
    """en_US-lessac-medium -> en/en_US/lessac/medium/en_US-lessac-medium (the piper-voices repo layout)."""
    locale, speaker, quality = voice.split("-")
    return f"{locale.split('_')[0]}/{locale}/{speaker}/{quality}/{voice}"


# ------------------------------------------------------------------ reports

TITLES = {"whisper": "Whisper", "omni": "Omnilingual", "hymt": "Hy-MT2", "madlad": "MADLAD",
          "kokoro": "Kokoro", "voxcpm": "VoxCPM2", "coqui": "Coqui", "piper": "Piper", "mms": "MMS",
          "espeak": "eSpeak NG"}


def _item(name, value):
    """piper en_US-lessac-medium / kokoro a:am_michael / voxcpm"""
    return f"{name} {value}" if isinstance(value, str) else name


def _short(name, value):
    """For the docs table: Piper `lessac`, Kokoro `am_michael`, Coqui `OpenBible`."""
    t = TITLES.get(name, name)
    if not isinstance(value, str):
        return t
    if name == "piper":
        return f"{t} `{value.split('-')[1]}`"
    if name == "kokoro":
        return f"{t} `{value.split(':')[-1]}`"
    if name in ("coqui", "mms"):
        return f"{t} `{value.split('/')[-1]}`"
    return f"{t} `{value}`"


def check_lines(table, ed, reviews, models, unclear_ok=None):
    """The `check` report for one edition, as lines (also used by tests)."""
    lic = _licences()
    unclear_ok = allow_unclear() if unclear_ok is None else unclear_ok
    reg = _engines().registry()
    eff, report = apply_edition(table, ed, reviews, unclear_ok)
    lines = [f"edition: {ed}"]
    if ed == "commercial" and unclear_ok:
        lines.append("!!! COMMERCIAL_ALLOW_UNCLEAR=1: every ❓ (unclear) voice and model may load. You are "
                     "asserting you reviewed each one yourself. ⛔ items stay blocked. !!!")
    obligations, text_only, global_ob = [], [], {}
    for lang in sorted(eff):
        e, r = eff[lang], report[lang]
        asr = e.get("asr", "whisper")
        a = lic.lookup(asr.split(":", 1)[0], cls=reg["recognizer"].get(asr.split(":", 1)[0]))
        tr = e.get("translator", "hymt")
        t = lic.lookup(tr, cls=reg["translator"].get(tr))
        chain = " > ".join(f"{_item(n, v)} {lic.SYMBOL[li.cls]}" + (" (last resort)" if _last(n) and len(r["voices"]) > 1
                                                                     else "") for n, v, li in r["voices"]) or "TEXT ONLY"
        lines.append(f"  {lang:3} asr={asr:14} {lic.SYMBOL[a.cls]}  mt={tr:6} {lic.SYMBOL[t.cls]}  voice: {chain}")
        for n, v, li in r["voices"]:
            if n in lic.GLOBAL_OBLIGATION:
                if li.cls in (lic.ATTRIBUTION, lic.SHARE_ALIKE):
                    global_ob.setdefault(f"{_item(n, v)}: {li.obligation or li.licence}", []).append(lang)
                continue
            if li.cls in (lic.ATTRIBUTION, lic.SHARE_ALIKE):
                ob = li.obligation or li.licence
                lines.append(f"        {lic.SYMBOL[li.cls]} {lang} voice {_item(n, v)}: {ob}")
                obligations.append(f"{lang} {_item(n, v)}: {ob}")
            elif li.cls == lic.UNCLEAR and ed == "commercial":
                why = f"reviewed: {reviews[lic.item_id(n, v)]}" if lic.item_id(n, v) in reviews \
                    else "COMMERCIAL_ALLOW_UNCLEAR=1"
                lines.append(f"        ❓ {lang} voice {_item(n, v)} ({li.reason}) — loaded because {why}")
        for n, v, li in r["dropped"]:
            hint = "" if li.cls == lic.NONCOMMERCIAL else (
                f"; to allow it after your own review: [licence_review] \"{lic.item_id(n, v)}\" = "
                "\"reviewed <date> by <org>: <why>\"")
            lines.append(f"        not loaded in commercial: {_item(n, v)} {lic.SYMBOL[li.cls]} {li.licence}{hint}")
        if r["text_only"] and ed == "commercial":
            lines.append(f"        {lang}: TEXT ONLY in commercial (no commercially licensed voice)")
            text_only.append(lang)
        elif r["text_only"]:
            lines.append(f"        {lang}: text only (no voice configured)")
    if ed == "nonprofit":
        nc = sorted({_item(n, v) for r in report.values() for n, v, li in r["voices"] if li.cls in (lic.NONCOMMERCIAL,
                                                                                                    lic.UNCLEAR)})
        lines.append(f"  nonprofit loads {len(nc)} ⛔/❓ voices: non-commercial use only "
                     "(`check --edition commercial` for what a commercial deployment gets)")
    lines.append("models:")
    for name, li, ok in model_report(models, ed, reviews, unclear_ok):
        e = models[name]
        vals = "  ".join(f"{k}={v or ('(same as model)' if k == 'multi_model' else '(none)')}" for k, v in e.items())
        lines.append(f"  {name:11} {lic.SYMBOL[li.cls]} {li.licence:14} {vals}"
                     + ("" if ok else "   <- NOT ALLOWED in commercial"))
    vox = [l for l in sorted(eff) if any(n == "voxcpm" for n, _, _ in report[l]["voices"])]
    lines.append("voices at capacity:")
    lines.append("  a chain is tried in order: when VoxCPM2 is at capacity (every instance at its limit) or down, "
                 "the sentence waits briefly (VOXCPM_QUEUE_S, 2 s) for a free instance, then goes to the next voice (languages with no voice after VoxCPM2 wait up to VOXCPM_WAIT_S, 15 s); eSpeak NG (last resort) ends "
                 "every chain it speaks, if espeak-ng is installed")
    lines += ["  " + x for x in voxcpm_plan_lines(ed, vox)]
    if ed == "commercial":
        lines.append("summary (commercial):")
        lines.append(f"  text only: {', '.join(text_only) or 'none'}")
        only_last = [l for l in sorted(eff) if report[l]["voices"] and all(_last(n) for n, _, _ in report[l]["voices"])]
        if only_last:
            lines.append(f"  eSpeak NG only (robotic, better than text): {', '.join(only_last)}")
        lines.append("  attribution / share-alike you must honour (e.g. on an About screen):")
        lines += [f"    - {o}" for o in obligations] or ["    - none"]
        for ob, langs in global_ob.items():
            lines.append(f"  deployment-wide, {len(langs)} languages: {ob}")
        lines.append("  " + lic.LIBRARY_NOTE)
    return lines


def _last(name):
    """Is this voice a last resort (eSpeak NG)?"""
    cls = _engines().registry("voice").get(name)
    return bool(getattr(cls, "last_resort", False))


def docs_blocks(table=None):
    """{name: markdown} for the generated sections of docs/licences.md."""
    lic = _licences()
    table = DEFAULTS if table is None else table
    non, rn = apply_edition(table, "nonprofit", {}, False)
    _, rc = apply_edition(table, "commercial", {}, False)

    def chain(r):
        return " › ".join(f"{_short(n, v)} {lic.SYMBOL[li.cls]}" for n, v, li in r["voices"])

    rows = ["| Lang | Recognition | Translation into it | Voice, `nonprofit` | Voice, `commercial` | "
            "Commercial notes |", "|---|---|---|---|---|---|"]
    for lang in table:
        e = non[lang]
        asr = TITLES.get(e.get("asr", "whisper").split(":")[0], e.get("asr"))
        tr = TITLES.get(e.get("translator", "hymt"), e.get("translator"))
        notes = []
        for n, v, li in rc[lang]["voices"]:
            if li.cls in (lic.ATTRIBUTION, lic.SHARE_ALIKE) and n not in lic.GLOBAL_OBLIGATION:
                notes.append(f"⚠️ {li.obligation or li.licence}")
            if n == "voxcpm" and not any(x == "voxcpm" for x, _, _ in rn[lang]["voices"]):
                notes.append("new: VoxCPM2 (shared GPU capacity, §2)")
            if n == "piper" and (n, v) not in [(x, y) for x, y, _ in rn[lang]["voices"]]:
                notes.append(f"new: Piper `{v}` ({li.reason})")
        for n, v, li in rc[lang]["dropped"]:
            notes.append(f"not loaded: {_short(n, v)} {lic.SYMBOL[li.cls]}")
        replaced = [(n, v, li) for n, v, li in rn[lang]["voices"]
                    if (n, v) not in [(x, y) for x, y, _ in rc[lang]["voices"]]
                    and (n, v) not in [(x, y) for x, y, _ in rc[lang]["dropped"]]
                    and n not in EDITION_OFF["commercial"]]
        for n, v, li in replaced:
            notes.append(f"replaced: {_short(n, v)} {lic.SYMBOL[li.cls]}")
        if rc[lang]["voices"] and all(_last(n) for n, _, _ in rc[lang]["voices"]):
            notes.insert(0, "**eSpeak NG only** (robotic; was text only)")
        cv = "**TEXT ONLY**" if rc[lang]["text_only"] else chain(rc[lang])
        rows.append(f"| {lang} | {asr} | {tr} | {chain(rn[lang]) or 'text only'} | {cv} | "
                    f"{'; '.join(notes) or '✅ unchanged'} |")
    used_n = {v for r in rn.values() for n, v, _ in r["voices"] if n == "piper"}
    used_c = {v for r in rc.values() for n, v, _ in r["voices"] if n == "piper"}
    order = {l: i for i, l in enumerate(table)}
    prow = ["| Lang | Voice | Dataset licence (as the card states it) | Base | Class | Used in |",
            "|---|---|---|---|---|---|"]
    for voice, li in sorted(lic.ITEMS["piper"].items(),
                            key=lambda kv: (order.get(kv[0].split("_")[0], 99), kv[0])):
        used = " and ".join(x for x, s in (("nonprofit", used_n), ("commercial", used_c)) if voice in s)
        prow.append(f"| {voice.split('_')[0]} | [`{voice}`]({li.url}) | {li.dataset} | {li.base} | "
                    f"{lic.SYMBOL[li.cls]} | {used or 'candidate, not used'} |")
    return {"languages": "\n".join(rows), "piper": "\n".join(prow)}


if __name__ == "__main__":
    argv = sys.argv[1:]
    ed_arg = None
    if "--edition" in argv:
        i = argv.index("--edition")
        ed_arg = argv[i + 1] if i + 1 < len(argv) else ""
        del argv[i:i + 2]
    cmd = argv[0] if argv else "check"
    if cmd == "get":
        # For shell scripts: one value, nothing else on stdout; loud and non-zero when unknown.
        try:
            print(get(load_models()[0], argv[1] if len(argv) > 1 else ""))
        except KeyError as e:
            sys.exit(f"stack_config: no such setting {e} (e.g. models.hymt.revision; see languages.toml [models])")
        sys.exit(0)
    try:
        ed = edition(ed_arg)
    except ValueError as e:
        sys.exit(str(e))
    try:
        t, src = load()
        load_devices()
    except (ValueError, FileNotFoundError) as e:
        sys.exit(f"stack_config: {e}")
    reviews = load_reviews()
    if cmd == "piper":
        # What scripts/fetch-voices.sh downloads: the edition's voices only, so a
        # commercial install never even fetches a non-commercial one.
        eff, _ = apply_edition(t, ed, reviews)
        for lang in [l.strip() for l in (argv[1] if len(argv) > 1 else "").split(",") if l.strip()]:
            if eff.get(lang, {}).get("piper"):
                print(lang, eff[lang]["piper"])
    elif cmd == "uses":
        # The languages that name an engine in this edition, e.g. `uses voxcpm`
        # (scripts/run.sh and prepare-voices.sh: which services to start).
        name = argv[1] if len(argv) > 1 else ""
        eff, _ = apply_edition(t, ed, reviews)
        print(",".join(l for l in sorted(eff) if eff[l].get(name) or name in (eff[l].get("voice") or [])))
    elif cmd == "voxcpm-plan":
        # For scripts/run.sh: one "<gpu> <port>" line per VoxCPM2 instance to
        # start ("-" = no CUDA_VISIBLE_DEVICES), the summary on stderr.
        try:
            plan = voxcpm_plan(ed, detect_gpus(), os.environ.get("VOXCPM_INSTANCES"),
                               [x.strip() for x in os.environ.get("VOXCPM_GPUS", "").split(",") if x.strip()] or None,
                               int(os.environ.get("VOXCPM_MAX_INSTANCES") or VOXCPM_MAX_INSTANCES))
        except ValueError as e:
            sys.exit(f"stack_config: {e}")
        for gpu, port in plan["instances"]:
            print(gpu if gpu is not None else "-", port)
        for line in [plan["message"]] + plan["notes"]:
            print(line, file=sys.stderr)
    elif cmd == "profile-env":
        # For scripts/profile-env.sh: `export K=v` for each [env] value the environment lacks.
        try:
            print("\n".join(profile_env_lines()))
        except (ValueError, FileNotFoundError) as e:
            sys.exit(f"stack_config: {e}")
    elif cmd == "profiles":
        for name, desc in list_profiles():
            print(f"  {name:14} {desc}")
    elif cmd == "profile":
        try:
            print("\n".join(profile_lines(argv[1] if len(argv) > 1 else None)))
        except (ValueError, FileNotFoundError) as e:
            sys.exit(f"stack_config: {e}")
    elif cmd == "check":
        print(f"config: {src}")
        prof = load_profile()
        if prof:
            print(f"profile: {prof['name']} ({prof.get('description', '')}); details: stack_config.py profile")
        print("devices: " + ", ".join(f"{k}={v}" for k, v in load_devices().items()))
        models, _ = load_models()
        for line in check_lines(t, ed, reviews, models):
            print(line)
        print("engines: " + "; ".join(f"{k} {', '.join(sorted(r))}" for k, r in _engines().registry().items()))
        if ed == "commercial":
            bad = commercial_problems(models, reviews)
            if bad:
                sys.exit("not allowed with EDITION=commercial:\n  " + "\n  ".join(bad))
    elif cmd == "docs":
        # The tables docs/licences.md generates from licences.py; --write updates them in place.
        blocks = docs_blocks()
        if "--write" in argv:
            import re
            doc = os.path.join(os.path.dirname(HERE), "docs", "licences.md")
            text = open(doc, encoding="utf-8").read()
            for name, md in blocks.items():
                text, n = re.subn(rf"<!-- generated: {name} -->\n.*?<!-- end generated: {name} -->",
                                  lambda _: f"<!-- generated: {name} -->\n{md}\n<!-- end generated: {name} -->",
                                  text, flags=re.S)
                if n != 1:
                    sys.exit(f"{doc}: no generated block {name!r}")
            open(doc, "w", encoding="utf-8").write(text)
            print(f"updated {doc}")
        else:
            for name, md in blocks.items():
                print(f"<!-- generated: {name} -->\n{md}\n<!-- end generated: {name} -->\n")
    elif cmd == "engines":
        eng = _engines()
        lic = _licences()
        for kind, reg in eng.registry().items():
            for name, cls in sorted(reg.items()):
                where = os.path.relpath(eng.origin(kind, name) or "?", os.path.dirname(HERE))
                li = lic.lookup(name, cls=cls)
                cl = "per item" if name in lic.PER_ITEM else f"{lic.SYMBOL[li.cls]} {li.cls}"
                print(f"  {kind:10} {name:10} {cls.title or '':18} {cls.licence or '':12} {cl:16} {where}")
    else:
        sys.exit(f"usage: {sys.argv[0]} check | engines | docs | piper <langs> | uses <engine> | get models.<name>.<key>"
                 " | voxcpm-plan [--edition nonprofit|commercial] | profiles | profile [<name>] | profile-env")
