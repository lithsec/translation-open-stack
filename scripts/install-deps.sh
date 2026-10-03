#!/usr/bin/env bash
# Every Python package the stack needs, on top of an image that already has
# CUDA torch 2.8 (the RunPod PyTorch template, or the Dockerfile's base).
# runpod/provision-runpod.sh runs this on every boot of a bare pod; the Dockerfile runs
# it once at build time, so both environments come from the same lines, in the
# same order (the order matters: see Coqui and Omnilingual below).
#
#   bash scripts/install-deps.sh            # warnings for the optional extras
#   STRICT=1 bash scripts/install-deps.sh   # any failure fails (the image build)
#   VERBOSE=1 bash scripts/install-deps.sh  # pip's full output and every command (troubleshooting)
#
# It ends with a check of every import the server makes; pip's three known
# conflict lines (librosa, contourpy and numpy 1.26.4) are expected: see
# constraints.txt's header.
set -euo pipefail
warn() { if [ "${STRICT:-0}" = 1 ]; then echo "ERROR: $*" >&2; exit 1; fi; echo "WARNING: $*"; }
step() { echo "== $*"; }
PIP_Q=(-q)
if [ "${VERBOSE:-0}" = 1 ]; then PIP_Q=(); set -x; fi

# eSpeak NG, the program: the last-resort voice (server/engines/espeak.py; VoxCPM2's overflow,
# fa and ro in commercial). The Dockerfile installs it with the other system packages; a bare
# RunPod PyTorch pod does not have it.
if ! command -v espeak-ng >/dev/null; then
  if command -v apt-get >/dev/null && [ "$(id -u)" = 0 ]; then
    { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends espeak-ng >/dev/null; } ||
      warn "espeak-ng failed to install — no last-resort voice"
  else
    warn "espeak-ng missing (apt-get install espeak-ng) — no last-resort voice"
  fi
fi

# The PyTorch template already has torch + CUDA; add only what is missing.
#
# --break-system-packages: the image's Python is externally managed (PEP 668)
# and refuses a bare install. A venv is the usual answer and the wrong one here
# — it would either hide the preinstalled torch+CUDA or need
# --system-site-packages to see it, and re-downloading torch on a metered GPU
# is minutes of money for nothing. This is a disposable container; there is no
# system to protect.
#
# PINNED: every install goes through constraints.txt (the repository root),
# the exact version of every package the stack's image holds, recorded from a
# real build. It pins without forcing anything in: a package only lands if a
# line below asks for it (or for something that needs it). How it was made, and
# how to refresh it: its header.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONSTRAINTS="${CONSTRAINTS:-$ROOT/constraints.txt}"
[ -f "$CONSTRAINTS" ] || { echo "ERROR: $CONSTRAINTS missing: packages are only installed pinned" >&2; exit 1; }

# Python 3.10-3.12 only: the Kokoro voice's packages (kokoro, misaki) don't install on 3.13+, and several pins
# (numpy 1.26.4, fairseq2) have no wheels past 3.12, so pip falls back to building them from source and asks
# for compilers and system libraries (openblas, cairo, glib, ...). Stop here instead (issue #8).
python3 -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)' || {
  echo "ERROR: $(python3 -V 2>&1): the stack needs Python 3.10-3.12 (3.12 recommended; kokoro and misaki don't" >&2
  echo "install on 3.13+). E.g. 'uv venv --python 3.12', then activate it and run this again." >&2
  echo "docs/user-guide.md, \"Install without Docker\"." >&2
  exit 1
}

# A GPU build of PyTorch already installed that isn't the pinned CUDA 2.8 (ROCm, for AMD cards): keep it.
# constraints.txt is the CUDA image's lock (torch 2.8.0 with NVIDIA's packages); followed as it is, pip would try
# to replace your PyTorch. So: those lines out, your torch and torchaudio pinned as installed, and the steps
# that need CUDA torch 2.8 (bitsandbytes' 4-bit Hy-MT2, Omnilingual's fairseq2) skipped.
TORCH_VER="$(python3 -c 'import torch; print(torch.__version__)' 2>/dev/null || true)"
ROCM=0
case "$TORCH_VER" in *rocm*) ROCM=1 ;; esac
if [ "$ROCM" = 1 ]; then
  rocm_c="$(mktemp)"
  grep -vE '^(torch|torchaudio|torchvision|triton|pytorch-triton[a-z-]*|nvidia-[a-z0-9-]+)==' "$CONSTRAINTS" > "$rocm_c"
  echo "torch==$TORCH_VER" >> "$rocm_c"
  TA_VER="$(python3 -c 'import torchaudio; print(torchaudio.__version__)' 2>/dev/null || true)"
  [ -n "$TA_VER" ] && echo "torchaudio==$TA_VER" >> "$rocm_c"
  CONSTRAINTS="$rocm_c"
  echo "PyTorch $TORCH_VER (ROCm): kept; NVIDIA-only steps skipped (Hy-MT2 runs at full precision: HYMT_QUANT=bf16)"
fi
pipi() { pip "${PIP_Q[@]}" install --break-system-packages -c "$CONSTRAINTS" "$@"; }
# transformers is PINNED below 5. Reproduced on 2026-08-28 against 5.16.1:
# MADLAD generates degenerate output — "ll ll ll ll…", "ty u u e je je ij…" —
# the same failure first seen as "ue ue ue".
#
# v5 warns that it will not tie shared.weight to decoder.embed_tokens.weight
# because the checkpoint holds both with different values (they differ by up to
# 253). That warning is a symptom, not the whole cause: tying them by hand does
# NOT fix generation, it only changes which garbage comes out. Something deeper
# in v5's T5 load of this checkpoint is wrong.
#
# Two earlier explanations recorded here were WRONG and are corrected: it is
# not an fp16 overflow (bf16 is identical), and it is not the tokenizer —
# "<2es>" tokenizes identically on 4.46.3 and 4.57.6, slow and fast.
#
# Upgrading would also break Omnilingual: transformers 5 pulls
# huggingface_hub 1.x, and fairseq2 0.6 requires ~=0.32. That is Khmer, Lao,
# Haitian and Swahili as source languages.
#
# The upside is now small anyway — MADLAD's decode runs through CTranslate2
# (--mt-ct2), so transformers is off the hot path entirely.
#
# accelerate + bitsandbytes: the 4-bit Hy-MT2 translator (prepare-mt.sh).
step "core: speech recognition, translation runtime, Piper, language ID"
if [ "$ROCM" = 1 ]; then
  pipi faster-whisper 'transformers==4.57.6' sentencepiece websockets scipy numpy piper-tts speechbrain accelerate
else
  pipi faster-whisper 'transformers==4.57.6' sentencepiece websockets scipy numpy piper-tts speechbrain accelerate bitsandbytes
fi

# ---- Kokoro TTS (en/es/fr/it/pt) ---------------------------------------------
# 82M, Apache 2.0, and it emits 24kHz — the pipeline's own rate, so those
# languages skip the resample entirely. On the GPU it runs ~98x real time
# against Piper's ~30x on CPU (and only 2x on CPU, so this is a deliberate move
# of TTS onto the idle GPU). Piper stays for everything Kokoro does not cover.
# misaki's ja/zh extras are Kokoro's Japanese and Mandarin G2P; without them
# those two languages fall back to Piper.
step "Kokoro voices"
pipi kokoro 'misaki[ja,zh]'
# MeCab's dictionary: without it misaki[ja] (and Coqui, which imports the same
# tokenizer) fail at load with "Failed initializing MeCab". `python3 -m unidic
# download` would pick the URL from a JSON file on unidic-py's GitHub master at
# install time; this fetches the same UniDic 3.1.0 zip, checks its sha256, and
# unpacks it with unidic's own routine.
UNIDIC_URL=https://cotonoha-dic.s3-ap-northeast-1.amazonaws.com/unidic-3.1.0.zip
UNIDIC_SHA256=638718c4c63625ab300de4c92c67925d54c0e9e3830009eaa992f29819d59c43
unidic_zip="$(mktemp)"
curl -sL --fail "$UNIDIC_URL" -o "$unidic_zip"
echo "$UNIDIC_SHA256  $unidic_zip" | sha256sum -c --quiet - ||
  { echo "ERROR: $UNIDIC_URL does not match its pinned sha256" >&2; rm -f "$unidic_zip"; exit 1; }
python3 -c 'import sys, unidic.download as d; d.download_and_clean("3.1.0+2021-08-31", "file://" + sys.argv[1])' "$unidic_zip"
rm -f "$unidic_zip"
# Its English G2P pulls a spaCy model AT FIRST USE, via pip, inside the server
# process — which dies on PEP 668 and takes startup with it. Fetch it now: a
# service must not be installing packages while someone is speaking.
# The model is installed straight from its release wheel, pinned by sha256
# (pip checks the #sha256= fragment), not through `spacy download`, which
# picks a version at install time and shells out to a pip that hits PEP 668 on
# this image (that failed on a real pod, caught only because the warning below
# is loud).
SPACY_EN=https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
SPACY_EN_SHA256=1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85
step "spaCy English model (Kokoro English)"
pipi spacy && pipi "en_core_web_sm @ $SPACY_EN#sha256=$SPACY_EN_SHA256" || {
  warn "spaCy model missing — Kokoro English will fail at synthesis"
}

# ---- Coqui, for the Haitian Creole OpenBible VITS -----------------------------
# CC-BY-SA, which is what takes Haitian off MMS's non-commercial licence. Needs
# transformers >=4.49, satisfied since the pin moved to 4.57.6.
#
# It raises numpy 1.26 -> 2.5 and scipy 1.13 -> 1.18, contradicting fairseq2's
# declared numpy~=1.23. The old Dockerfile installed it LAST for that reason
# (verified on a live box that Omnilingual still TRANSCRIBES on that
# combination); the RunPod provisioner has always installed it BEFORE
# Omnilingual, whose pins then win. The pods are the measured deployment, so
# this keeps their order. Without Coqui the server starts, says "Coqui unavailable",
# and serves Haitian from MMS — which works, but is the licence we were trying
# to leave.
#
# Pinned, that order needs one exception: Coqui's librosa 1.0 and contourpy 1.4
# require numpy 2, so this step drops the numpy/scipy lines of constraints.txt
# and pins the versions it resolved to in the measured build; Omnilingual's
# step then settles numpy/scipy on the constrained 1.26.4/1.13.1.
coqui_c="$(mktemp)"
grep -vE '^(numpy|scipy)==' "$CONSTRAINTS" > "$coqui_c"
step "Coqui (the commercial Haitian Creole voice)"
pip "${PIP_Q[@]}" install --break-system-packages -c "$coqui_c" coqui-tts 'numpy==2.5.3' 'scipy==1.18.1' ||
  warn "coqui-tts missing — Haitian falls back to MMS (CC-BY-NC)"
rm -f "$coqui_c"

# ---- Omnilingual ASR (the --omni sources) ------------------------------------
# Without this the server starts, prints "Omnilingual unavailable — ht/km/lo/sw
# fall back to whisper (poor)", and serves confident nonsense for those
# languages: a Khmer clip came back as "The 1000-year-old hill of the hill of
# the hill…". It degrades honestly in the log and invisibly in the room, so
# install it rather than rely on someone reading startup output.
#
# The pins are not optional. fairseq2 (which omnilingual-asr pulls) downgrades
# numpy, which strands scipy — "module 'numpy' has no attribute 'long'" at T5
# import — and repins torch, which breaks the torchaudio pairing. Install all
# three together so pip resolves them in one pass.
step "Omnilingual (rare languages' recogniser)"
# ROCm: fairseq2 is built for CUDA torch 2.8 only, so Omnilingual can't run; its languages use Whisper. Its
# scipy pin still matters (Coqui above brought scipy 1.18 for numpy 2).
[ "$ROCM" = 1 ] && echo "ROCm: skipping Omnilingual (no ROCm build of fairseq2); its languages use Whisper" &&
  pipi 'scipy==1.13.1' ||
pipi omnilingual-asr 'torchaudio==2.8.0' 'scipy==1.13.1' ||
  warn "omnilingual-asr failed to install — ht/km/lo/sw will fall back to whisper, which produces fluent nonsense for them."

# ---- Japanese Piper voice -----------------------------------------------------
# Japanese is phonemised by pyopenjtalk, not espeak-ng like every other Piper
# voice — without it the voice loads and then throws at synthesis time.
step "Japanese Piper voice"
pipi pyopenjtalk || warn "pyopenjtalk missing — the Japanese Piper voice can't speak"

# ---- Check ----------------------------------------------------------------------
# What a successful install looks like, stated, instead of a last line of pip
# output that may be the expected conflict warnings. Every import server.py makes
# (as the Dockerfile checks); Omnilingual and Coqui are optional (and Omnilingual
# absent on ROCm). pip's conflicts: the three known ones are expected (numpy
# 1.26.4 for fairseq2, below librosa's and contourpy's declared minimums; both
# work), anything else is reported.
{ set +x; } 2>/dev/null
step "check"
python3 - "$ROCM" <<'PY'
import importlib, sys
rocm = sys.argv[1] == "1"
need = ["torch", "torchaudio", "transformers", "faster_whisper", "ctranslate2", "onnxruntime", "speechbrain",
        "kokoro", "misaki", "piper", "numpy", "scipy", "websockets", "sentencepiece", "accelerate", "spacy"]
optional = {"TTS": "Coqui (commercial Haitian Creole voice)", "pyopenjtalk": "the Japanese Piper voice"}
if not rocm:
    optional["omnilingual_asr"] = "Omnilingual (ht km lo sw hi fa bn ur fall back to Whisper)"
    need.append("bitsandbytes")
bad = []
for m in need:
    try:
        importlib.import_module(m)
    except Exception as e:
        bad.append(f"{m}: {type(e).__name__}: {e}")
for m, what in optional.items():
    try:
        importlib.import_module(m)
    except Exception as e:
        print(f"  optional, not available: {what} ({m}: {type(e).__name__})")
try:
    import torch
    gpus = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())] if torch.cuda.is_available() else []
    print(f"  torch {torch.__version__}, GPUs: {', '.join(gpus) or 'none visible'}")
except Exception as e:
    print(f"  torch: {type(e).__name__}: {e}")
try:
    import ctranslate2
    print(f"  CTranslate2 {ctranslate2.__version__}, GPUs it sees: {ctranslate2.get_cuda_device_count()}")
except Exception as e:
    print(f"  CTranslate2: {e}")
if bad:
    print("FAILED: missing or broken imports:\n  " + "\n  ".join(bad))
    sys.exit(1)
print("  every required import works")
PY
known='^(librosa .* requires (numpy|scipy)|contourpy .* requires numpy)'
others="$(pip check 2>&1 | grep -vE "$known|^No broken requirements" || true)"
if [ -n "$others" ]; then
  echo "  pip check, beyond the three known conflicts (worth a look):"
  echo "$others" | sed 's/^/    /'
else
  echo "  pip check: only the known numpy/scipy conflicts (expected; constraints.txt's header)"
fi
echo "Done."
