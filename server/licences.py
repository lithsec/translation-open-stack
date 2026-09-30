"""Every model and voice the stack can load, with its licence class: the single
source of truth for what EDITION=commercial may load.

    permissive     ✅  MIT, Apache 2.0, BSD, CC0, public domain
    attribution    ⚠️  CC-BY: allowed commercially; credit the source
    share-alike    ⚠️  CC-BY-SA: allowed commercially; credit it, and pass the
                       licence on with anything you distribute that adapts it
    noncommercial  ⛔  CC-BY-NC(-SA), research-only data: never in commercial
    unclear        ❓  no licence, a dead link, or a voice fine-tuned from a
                       checkpoint whose data is not commercial: commercial only
                       after the operator's own review ([licence_review])

What is classified, and how an item is looked up (lookup()):

  ENGINES   one entry per engine whose weights have one licence (Whisper,
            Kokoro, MMS-TTS, ...). An engine not here may declare its own:
            `licence_class` (one of CLASSES) and `licence` on the class
            (engines/base.py). An engine that declares nothing is unclear.
  ITEMS     engines whose licence depends on the per-language value: Piper
            (one entry per voice) and Coqui (per checkpoint). An item not
            listed is unclear.
  MODELS    the [models.<name>] values (repos, model names): what
            stack_config.load_models() resolves. `revision`, where given, is
            the revision the licence was read at; any other revision is unclear
            until someone reads it again.

docs/licences.md is the prose; its per-language and Piper tables are generated
from this file (`python3 server/stack_config.py docs`), and
tests/test_licences.py fails when they drift, or when languages.toml names a
voice or model that has no entry here. Standard library only (stack_config.py
imports it on the macOS system Python).

Not legal advice: an engineering classification of what each upstream card
says, checked 2026-09-29.
"""
from collections import namedtuple

PERMISSIVE, ATTRIBUTION, SHARE_ALIKE, NONCOMMERCIAL, UNCLEAR = (
    "permissive", "attribution", "share-alike", "noncommercial", "unclear")
CLASSES = (PERMISSIVE, ATTRIBUTION, SHARE_ALIKE, NONCOMMERCIAL, UNCLEAR)
SYMBOL = {PERMISSIVE: "✅", ATTRIBUTION: "⚠️", SHARE_ALIKE: "⚠️", NONCOMMERCIAL: "⛔", UNCLEAR: "❓"}

EDITIONS = ("nonprofit", "commercial")

# licence: the licence as stated (short). reason: why this class. url: primary
# source. obligation: what commercial use must do (attribution / share-alike).
# dataset, base: Piper voices only (the MODEL_CARD's dataset licence and the
# checkpoint it was fine-tuned from). revision: MODELS only (see above).
Lic = namedtuple("Lic", "cls licence reason url obligation dataset base revision",
                 defaults=("", "", "", None))

# The model cards as read, at the commit voices.lock pins (tests/test_licences.py checks they agree).
PIPER_REVISION = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
_PIPER = f"https://huggingface.co/rhasspy/piper-voices/blob/{PIPER_REVISION}/"
_LESSAC = ("fine-tuned from the en_US lessac checkpoint, whose Blizzard 2013 data is research-only: "
           "whether that carries over is an open question")
_RYAN = ("fine-tuned from the en_US ryan checkpoint, whose RyanSpeech data is CC-BY-NC-SA: "
         "whether that carries over is an open question")


def _card(voice):
    """The MODEL_CARD link for a Piper voice name."""
    locale, speaker, quality = voice.split("-")
    return f"{_PIPER}{locale.split('_')[0]}/{locale}/{speaker}/{quality}/MODEL_CARD"


def _piper(voice, cls, dataset, base, reason, obligation=""):
    return voice, Lic(cls, dataset, reason, _card(voice), obligation, dataset, base)


# ------------------------------------------------------------------ engines

ENGINES = {
    # Recognisers
    "whisper": Lic(PERMISSIVE, "MIT", "OpenAI: \"Whisper's code and model weights are released under the MIT "
                   "License\"; the CTranslate2 conversion (Systran) is MIT too",
                   "https://github.com/openai/whisper/blob/main/LICENSE"),
    "omni": Lic(PERMISSIVE, "Apache-2.0", "\"Omnilingual ASR code and models are released under the Apache 2.0\"",
                "https://github.com/facebookresearch/omnilingual-asr"),
    # Translators
    "hymt": Lic(PERMISSIVE, "Apache-2.0", "LICENSE.txt at the pinned revision is plain Apache 2.0 (not the "
                "Hunyuan Community Licence); see MODELS for the revision",
                "https://huggingface.co/tencent/Hy-MT2-7B/blob/9b0eb4e8f001def3e5ff6469a0ac96fdb39ec223/LICENSE.txt"),
    "madlad": Lic(PERMISSIVE, "Apache-2.0", "model card: apache-2.0",
                  "https://huggingface.co/google/madlad400-7b-mt"),
    "echo": Lic(PERMISSIVE, "none (no model)", "a test engine with no weights", ""),
    # Voices
    "kokoro": Lic(PERMISSIVE, "Apache-2.0", "\"trained exclusively on permissive/non-copyrighted audio data\"; "
                  "the card lists the CC-BY audio it used (e.g. SIWIS, Koniwa), which is good practice to credit",
                  "https://huggingface.co/hexgrad/Kokoro-82M"),
    "voxcpm": Lic(PERMISSIVE, "Apache-2.0", "\"Released under the Apache-2.0 license, free for commercial use\"; "
                  "the reference voices in voices/voxcpm/ were generated by VoxCPM2 itself",
                  "https://huggingface.co/openbmb/VoxCPM2"),
    "cosyvoice": Lic(PERMISSIVE, "Apache-2.0", "model card: apache-2.0 (the --clone reference clip is the "
                     "operator's own responsibility)", "https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B"),
    # The espeak-ng program and its voice data (espeak-ng-data: phoneme tables,
    # dictionaries, voices) are one GPL-3.0-or-later work. The stack runs it as
    # a separate process (engines/espeak.py), never linked; GPL-3.0 (not AGPL)
    # puts no duty on running it, even as a service, nor on the audio it
    # makes. Distributing the image or a volume that contains it does: the
    # same duty as piper-tts (LIBRARY_NOTE). Share-alike (copyleft), so allowed
    # in commercial; its duty is deployment-wide (GLOBAL_OBLIGATION), not per
    # language. MBROLA voices (mb-*) have their own licences and are never used.
    "espeak": Lic(SHARE_ALIKE, "GPL-3.0-or-later", "README: \"eSpeak NG Text-to-Speech is released under the "
                  "GPL version 3 or later license\" (the voice data ships in the same repository, under the "
                  "same licence); run as a separate process, so running it as a service and its audio "
                  "output carry no GPL duty", "https://github.com/espeak-ng/espeak-ng#license-information",
                  "GPL-3.0: nothing to do for running the stack or for the audio; if you distribute the "
                  "image or a volume, include espeak-ng's licence and its source (docs/licences.md §8)"),
    "mms": Lic(NONCOMMERCIAL, "CC-BY-NC-4.0", "\"The model is licensed as CC-BY-NC 4.0\" (every mms-tts-* repo)",
               "https://huggingface.co/facebook/mms-tts-hat"),
}

# Engines whose duty is the same for the whole deployment (not per language):
# `check` and the startup log say it once, not in every language's line.
GLOBAL_OBLIGATION = {"espeak"}

# Engines whose licence is per item (the per-language value): looked up in ITEMS.
PER_ITEM = {"piper", "coqui"}

# ------------------------------------------------------------------ per-item

ITEMS = {
    "coqui": {
        "multilingual-tts/VITS-OpenBible-Haitian-Creole": Lic(
            SHARE_ALIKE, "CC-BY-SA-4.0", "model card: cc-by-sa-4.0; trained on the Open Bible corpus",
            "https://huggingface.co/multilingual-tts/VITS-OpenBible-Haitian-Creole",
            "CC-BY-SA 4.0: credit multilingual-tts / Open Bible; share adaptations of the model under CC-BY-SA"),
    },
    # Piper: from each voice's MODEL_CARD (fetched 2026-09-29). The configured
    # voices, the commercial replacements, and the candidates rejected for them.
    "piper": dict([
        # --- English
        _piper("en_US-lessac-medium", NONCOMMERCIAL, "Blizzard 2013 Lessac licence (research only)",
               "trained from scratch", "the dataset licence excludes \"any commercial purpose, including the "
               "development [...] of voice synthesis [...] products or services\""),
        _piper("en_US-lessac-high", NONCOMMERCIAL, "Blizzard 2013 Lessac licence (research only)",
               "trained from scratch", "research-only dataset"),
        _piper("en_US-norman-medium", PERMISSIVE, "public domain (LibriVox)", "trained from scratch",
               "public-domain LibriVox recordings, trained from scratch (Bryce Beattie)"),
        _piper("en_US-ljspeech-high", PERMISSIVE, "public domain (LJ Speech)", "trained from scratch",
               "public-domain dataset, trained from scratch"),
        _piper("en_US-kristin-medium", PERMISSIVE, "public domain (LibriVox)", "trained from scratch",
               "public-domain LibriVox recordings, trained from scratch"),
        _piper("en_US-john-medium", PERMISSIVE, "public domain (LibriVox)", "kristin (public domain)",
               "public-domain data, fine-tuned from kristin, itself trained from scratch on public-domain data"),
        _piper("en_GB-cori-high", PERMISSIVE, "public domain (LibriVox)", "trained from scratch",
               "public-domain LibriVox recordings, trained from scratch"),
        _piper("en_US-libritts-high", ATTRIBUTION, "CC-BY 4.0 (LibriTTS)", "trained from scratch",
               "CC-BY dataset, trained from scratch", "CC-BY 4.0: credit LibriTTS (Zen et al., 2019)"),
        _piper("en_US-ryan-high", NONCOMMERCIAL, "CC-BY-NC-SA 4.0 (RyanSpeech)", "trained from scratch",
               "non-commercial dataset"),
        _piper("en_US-hfc_female-medium", NONCOMMERCIAL, "CC-BY-NC-SA 4.0 (Hi-Fi-CAPTAIN)", "lessac",
               "non-commercial dataset"),
        _piper("en_US-l2arctic-medium", NONCOMMERCIAL, "CC-BY-NC 4.0 (L2-ARCTIC)", "lessac",
               "non-commercial dataset"),
        _piper("en_US-joe-medium", UNCLEAR, "CC0", "lessac", _LESSAC),
        # --- Spanish
        _piper("es_ES-davefx-medium", UNCLEAR, "CC0", "lessac", _LESSAC),
        _piper("es_ES-carlfm-x_low", PERMISSIVE, "public domain", "trained from scratch",
               "public-domain dataset, trained from scratch (x_low: 16 kHz, the only clean Spanish Piper voice)"),
        _piper("es_ES-sharvard-medium", UNCLEAR, "CC-BY 3.0 (Sharvard)", "lessac", _LESSAC),
        _piper("es_MX-claude-high", UNCLEAR, "apache-2.0 (as stated)", "not stated",
               "training and base checkpoint not stated (\"See URL\", a Hugging Face Space)"),
        _piper("es_MX-ald-medium", UNCLEAR, "Unlicense", "davefx (lessac)", _LESSAC + " (via davefx)"),
        _piper("es_AR-daniela-high", UNCLEAR, "CC-BY-SA 4.0 (OpenSLR 61)", "lessac", _LESSAC),
        # --- French
        _piper("fr_FR-siwis-medium", UNCLEAR, "CC-BY 4.0 (SIWIS)", "lessac", _LESSAC,
               "CC-BY 4.0: credit SIWIS"),
        _piper("fr_FR-mls-medium", ATTRIBUTION, "CC-BY 4.0 (Multilingual LibriSpeech, OpenSLR 94)",
               "trained from scratch", "CC-BY dataset, trained from scratch",
               "CC-BY 4.0: credit Multilingual LibriSpeech (Pratap et al., 2020)"),
        _piper("fr_FR-upmc-medium", UNCLEAR, "CC-BY-SA 4.0 (UPMC Pierre)", "lessac", _LESSAC),
        _piper("fr_FR-gilles-low", UNCLEAR, "CC0", "ryan", _RYAN),
        _piper("fr_FR-tom-medium", UNCLEAR, "AGPLv3 (as stated, for a dataset)", "not stated",
               "an AGPL \"dataset\" licence and no stated base checkpoint"),
        # --- Portuguese
        _piper("pt_BR-faber-medium", UNCLEAR, "CC0", "lessac", _LESSAC),
        _piper("pt_BR-cadu-medium", UNCLEAR, "CC0", "lessac", _LESSAC),
        _piper("pt_BR-jeff-medium", UNCLEAR, "CC0", "lessac", _LESSAC),
        _piper("pt_PT-tugão-medium", UNCLEAR, "CC0", "lessac", _LESSAC),
        _piper("pt_BR-edresson-low", UNCLEAR, "CC-BY 4.0", "ryan", _RYAN),
        # --- Italian
        _piper("it_IT-serena-high", ATTRIBUTION, "CC-BY 4.0 (synthetic, serena-synthetic-it-27h)",
               "trained from scratch", "CC-BY dataset, trained from scratch",
               "CC-BY 4.0: credit the serena-synthetic-it-27h dataset (committa)"),
        _piper("it_IT-serena-medium", ATTRIBUTION, "CC-BY 4.0 (synthetic, serena-synthetic-it-27h)",
               "trained from scratch", "CC-BY dataset, trained from scratch",
               "CC-BY 4.0: credit the serena-synthetic-it-27h dataset (committa)"),
        _piper("it_IT-paola-medium", UNCLEAR, "\"See URL\"", "lessac", _LESSAC),
        # --- German
        _piper("de_DE-thorsten-high", UNCLEAR, "CC0 (Thorsten-Voice)", "lessac", _LESSAC),
        _piper("de_DE-thorsten-medium", UNCLEAR, "CC0 (Thorsten-Voice)", "lessac", _LESSAC),
        _piper("de_DE-mls-medium", ATTRIBUTION, "CC-BY 4.0 (Multilingual LibriSpeech, OpenSLR 94)",
               "trained from scratch", "CC-BY dataset, trained from scratch",
               "CC-BY 4.0: credit Multilingual LibriSpeech (Pratap et al., 2020)"),
        _piper("de_DE-pavoque-low", NONCOMMERCIAL, "CC-BY-NC-SA 4.0 (PAVOQUE)", "ryan", "non-commercial dataset"),
        _piper("de_DE-eva_k-x_low", UNCLEAR, "\"See URL\" (M-AILABS)", "trained from scratch",
               "the M-AILABS licence was not verified"),
        _piper("de_DE-kerstin-low", UNCLEAR, "CC0", "ryan", _RYAN),
        # --- Russian
        _piper("ru_RU-irina-medium", UNCLEAR, "\"Unknown\" (RHVoice)", "lessac", "dataset licence unknown; " + _LESSAC),
        _piper("ru_RU-denis-medium", UNCLEAR, "CC0", "lessac", _LESSAC),
        _piper("ru_RU-dmitri-medium", UNCLEAR, "CC0", "lessac", _LESSAC),
        _piper("ru_RU-ruslan-medium", NONCOMMERCIAL, "CC-BY-NC-SA 4.0 (RUSLAN)", "lessac", "non-commercial dataset"),
        # --- Ukrainian
        _piper("uk_UA-ukrainian_tts-medium", PERMISSIVE, "CC0", "trained from scratch",
               "CC0 dataset, trained from scratch"),
        _piper("uk_UA-lada-x_low", PERMISSIVE, "Apache 2.0", "trained from scratch",
               "Apache dataset, trained from scratch"),
        # --- Chinese
        _piper("zh_CN-huayan-medium", UNCLEAR, "\"Unknown\" (HuaYan_TTS, repository gone)", "lessac",
               "dataset licence unknown; " + _LESSAC),
        _piper("zh_CN-xiao_ya-medium", NONCOMMERCIAL, "non-commercial (DataBaker BZNSYP)", "trained from scratch",
               "non-commercial dataset"),
        _piper("zh_CN-chaowen-medium", UNCLEAR, "CC0", "xiao_ya (non-commercial data)",
               "fine-tuned from xiao_ya, whose data is non-commercial"),
        # --- Japanese, Korean
        _piper("ja_JP-hi_fi_captain-medium", NONCOMMERCIAL, "CC-BY-NC-SA 4.0 (Hi-Fi-CAPTAIN)", "LibriTTS-R",
               "non-commercial dataset"),
        _piper("ko_KR-kss-medium", NONCOMMERCIAL, "CC-BY-NC-SA 4.0 (KSS)", "LibriTTS-R", "non-commercial dataset"),
        # --- Vietnamese
        _piper("vi_VN-vais1000-medium", UNCLEAR, "CC-BY 4.0 (VAIS-1000)", "lessac", _LESSAC,
               "CC-BY 4.0: credit VAIS-1000"),
        _piper("vi_VN-vivos-x_low", NONCOMMERCIAL, "CC-BY-NC-SA 4.0 (VIVOS)", "trained from scratch",
               "non-commercial dataset"),
        _piper("vi_VN-25hours_single-low", UNCLEAR, "\"Unknown\" (InfoRe)", "ryan", "dataset licence unknown; " + _RYAN),
        # --- Arabic, Persian, Indonesian
        _piper("ar_JO-kareem-medium", UNCLEAR, "\"See URL\": arabicttstrain declares no licence", "lessac",
               "dataset has no licence; " + _LESSAC),
        _piper("fa_IR-gyro-medium", UNCLEAR, "\"See URL\" (a GitHub profile)", "a Persian VITS voice",
               "no dataset licence found"),
        _piper("fa_IR-amir-medium", UNCLEAR, "CC0", "lessac", _LESSAC),
        _piper("fa_IR-ganji-medium", UNCLEAR, "CC0", "amir (lessac)", _LESSAC + " (via amir)"),
        _piper("fa_IR-reza_ibrahim-medium", UNCLEAR, "CC0", "lessac", _LESSAC),
        _piper("id_ID-news_tts-medium", UNCLEAR, "\"See URL\": links a Malayalam corpus notebook", "lessac",
               "the card's dataset link is wrong; " + _LESSAC),
        # --- Turkish
        _piper("tr_TR-dfki-medium", NONCOMMERCIAL, "CC-BY-NC-SA 4.0 (dfki-ot-data)", "lessac",
               "non-commercial dataset"),
        # --- Bengali, Urdu, Hindi
        _piper("bn_BD-google-medium", SHARE_ALIKE, "CC-BY-SA 4.0 (OpenSLR 37) and the CMU licence", "LibriTTS-R",
               "share-alike dataset; LibriTTS-R base (CC-BY)",
               "CC-BY-SA 4.0: credit Google's OpenSLR 37 Bengali corpus and keep the CMU notice"),
        _piper("ur_PK-aegis_female-medium", PERMISSIVE, "MIT (the card's own licence; dataset not stated)",
               "not stated", "the voice is published under MIT; its card names no dataset (a thin card)"),
        _piper("ur_PK-fasih-medium", PERMISSIVE, "MIT (the card's own licence; dataset not stated)", "not stated",
               "the voice is published under MIT; its card names no dataset (a thin card)"),
        _piper("hi_IN-rohan-medium", UNCLEAR, "IIT Madras Indic TTS licence (unverified)", "lessac",
               "dataset licence could not be retrieved; " + _LESSAC),
        _piper("hi_IN-pratham-medium", NONCOMMERCIAL, "CC-BY-NC-SA 4.0", "not stated", "non-commercial dataset"),
        _piper("hi_IN-priyamvada-medium", NONCOMMERCIAL, "CC-BY-NC-SA 4.0", "not stated", "non-commercial dataset"),
        # --- Swahili, Romanian
        _piper("sw_CD-lanfrica-medium", UNCLEAR, "\"See URL\" (Lanfrica record, no licence shown)", "lessac",
               "no dataset licence found; " + _LESSAC),
        _piper("ro_RO-mihai-medium", UNCLEAR, "CC0", "lessac", _LESSAC),
    ]),
}

# ------------------------------------------------------------------ [models]

# The value of [models.<name>] repo (or whisper's `model`, omnilingual's
# `card`) -> its licence.
MODELS = {
    "large-v3": ENGINES["whisper"],
    "Systran/faster-whisper-large-v3": ENGINES["whisper"],
    "distil-large-v3": Lic(PERMISSIVE, "MIT", "distil-whisper: MIT",
                           "https://huggingface.co/distil-whisper/distil-large-v3"),
    "omniASR_LLM_300M": ENGINES["omni"],
    "speechbrain/lang-id-voxlingua107-ecapa": Lic(
        PERMISSIVE, "Apache-2.0", "model card: apache-2.0 (its VoxLingua107 training data is CC-BY 4.0)",
        "https://huggingface.co/speechbrain/lang-id-voxlingua107-ecapa"),
    "snakers4/silero-vad": Lic(PERMISSIVE, "MIT", "MIT (code and model)",
                               "https://github.com/snakers4/silero-vad/blob/master/LICENSE"),
    "tencent/Hy-MT2-7B": ENGINES["hymt"]._replace(revision="9b0eb4e8f001def3e5ff6469a0ac96fdb39ec223"),
    "google/madlad400-7b-mt": ENGINES["madlad"],
    "google/madlad400-3b-mt": ENGINES["madlad"]._replace(url="https://huggingface.co/google/madlad400-3b-mt"),
    "hexgrad/Kokoro-82M": ENGINES["kokoro"],
    "openbmb/VoxCPM2": ENGINES["voxcpm"],
}
# Which key of a [models.<name>] table names the model.
MODEL_KEYS = ("repo", "model", "card")

# Libraries: never blocked (they matter when you DISTRIBUTE the image or a
# volume, not when you run the stack). Printed by `check` in commercial.
LIBRARY_NOTE = ("libraries: espeak-ng, piper-tts and phonemizer-fork are GPL-3.0, coqui-tts MPL-2.0 — no duty "
                "for running the stack as a service; if you distribute the image or a volume, follow GPL-3.0 "
                "for them (docs/licences.md §8)")


def _unclear(reason, url=""):
    return Lic(UNCLEAR, "unknown", reason, url)


def lookup(engine, item=None, cls=None):
    """The Lic of one voice/recogniser/translator (`item` = its per-language
    value, e.g. a Piper voice name) — unclear when nothing classifies it.
    `cls` is the engine class, for engines that declare their own licence."""
    if engine in PER_ITEM:
        if isinstance(item, str) and item in ITEMS.get(engine, {}):
            return ITEMS[engine][item]
        return _unclear(f"{engine} {item!r} has no entry in server/licences.py")
    if engine in ENGINES:
        return ENGINES[engine]
    declared = getattr(cls, "licence_class", None) if cls is not None else None
    if declared in CLASSES:
        return Lic(declared, getattr(cls, "licence", "") or declared, "declared by the engine",
                   getattr(cls, "licence_url", ""), getattr(cls, "licence_obligation", ""))
    return _unclear(f"engine {engine!r} has no entry in server/licences.py and declares no licence_class")


def model_lookup(name, entry):
    """The Lic of one [models.<name>] table (as load_models() resolved it)."""
    value = next((entry[k] for k in MODEL_KEYS if entry.get(k)), None)
    lic = MODELS.get(value)
    if lic is None:
        return _unclear(f"[models.{name}] {value!r} has no entry in server/licences.py")
    if lic.revision and entry.get("revision") and entry["revision"] != lic.revision:
        return _unclear(f"{value}: the licence was read at revision {lic.revision[:12]}, not "
                        f"{entry['revision'][:12]}; read it again", lic.url)
    return lic


def item_id(engine, item=None):
    """What a [licence_review] key names: the item (a voice, a repo), or the engine."""
    return item if isinstance(item, str) and item else engine


def allowed(lic, edition, reviewed=False, allow_unclear=False):
    """May this item load in this edition?"""
    if edition != "commercial":
        return True
    if lic.cls == NONCOMMERCIAL:
        return False
    if lic.cls == UNCLEAR:
        return bool(reviewed or allow_unclear)
    return True


def describe(lic):
    """'✅ MIT' / '⚠️ CC-BY 4.0: credit ...'"""
    s = f"{SYMBOL[lic.cls]} {lic.licence}"
    return s
