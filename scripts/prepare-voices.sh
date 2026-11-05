#!/usr/bin/env bash
# Install VoxCPM2 (OpenBMB, Apache 2.0) ONCE into the network volume: its own
# virtualenv (its engine, nano-vllm-voxcpm, pins library versions the stack must not
# inherit) plus the model weights. run.sh then starts server/voxcpm_service.py from it (km lo tl; with
# EDITION=commercial also ko tr ru ar id sw vi).
#
#   bash scripts/prepare-voices.sh        # -> /workspace/venv_voxcpm, weights in $HF_HOME
#
# The stack's Docker image already has the venv (VOXCPM_VENV=/opt/venv_voxcpm),
# so there this only fetches the weights and the reference voices.
set -euo pipefail
# STACK_HOME: where models, voices and caches live (a pod's volume, /workspace by default;
# any folder on your own machine).
W="${STACK_HOME:-/workspace}"
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"   # the repository: voices/voxcpm/ lives there
VENV="${VOXCPM_VENV:-$W/venv_voxcpm}"
export HF_HOME="${HF_HOME:-$W/hf-cache}"
# The engine: nano-vllm-voxcpm (MIT), VoxCPM2 batched on one GPU (server/voxcpm_service.py).
# A venv from before it (OpenBMB's `voxcpm` package, one voice at a time) is rebuilt.
NANO_VLLM_VOXCPM=2.0.5
# flash-attn, which it imports: the prebuilt wheel for this torch (2.8, CUDA 12, Python 3.12),
# pinned by hash; the one matching torch's C++ ABI is picked below.
FA_URL=https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3.post2
FA_WHL_TRUE="flash_attn-2.8.3.post2+cu12torch2.8cxx11abiTRUE-cp312-cp312-linux_x86_64.whl"
FA_SHA_TRUE=61ab39b7038d6a05cb97664f3481a92ced300d11aa14529ae3b675300a99f5e6
FA_WHL_FALSE="flash_attn-2.8.3.post2+cu12torch2.8cxx11abiFALSE-cp312-cp312-linux_x86_64.whl"
FA_SHA_FALSE=48e4f062cc517b5528ba674fa95e17ee8e5735e28a972c60578ff0576ed80d54
if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c "import nanovllm_voxcpm" 2>/dev/null; then
  echo "== VoxCPM2 venv (nano-vllm-voxcpm $NANO_VLLM_VOXCPM) -> $VENV"
  # --system-site-packages: reuse the pod's CUDA torch instead of downloading another.
  # --clear: an old venv's voxcpm and its transformers 5 would shadow the stack's.
  python3 -m venv --clear --system-site-packages "$VENV"
  ABI="$("$VENV/bin/python" -c "import torch; print('TRUE' if torch._C._GLIBCXX_USE_CXX11_ABI else 'FALSE')")"
  if [ "$ABI" = TRUE ]; then WHL="$FA_WHL_TRUE" SHA="$FA_SHA_TRUE"; else WHL="$FA_WHL_FALSE" SHA="$FA_SHA_FALSE"; fi
  TMPD="$(mktemp -d)"
  curl -fsSL -o "$TMPD/$WHL" "$FA_URL/${WHL//+/%2B}"
  echo "$SHA  $TMPD/$WHL" | sha256sum -c - >/dev/null
  # Its dependencies pinned too: constraints-voxcpm.txt, the venv's own packages
  # from a real build (everything else it reuses from the stack's, already pinned).
  "$VENV/bin/pip" -q install -c "$ROOT/constraints-voxcpm.txt" "$TMPD/$WHL" \
    "nano-vllm-voxcpm==$NANO_VLLM_VOXCPM" soundfile
  rm -rf "$TMPD"
fi
[ "${VOXCPM_VENV_ONLY:-0}" = 1 ] && exit 0   # the image build: no weights in the image
# Which weights: languages.toml [models.voxcpm] (pinned: change deliberately; Apache 2.0).
# VOXCPM_REV in the environment wins over the file's revision.
VOXCPM_REPO="$(python3 "$ROOT/server/stack_config.py" get models.voxcpm.repo)"
VOXCPM_REV="${VOXCPM_REV:-$(python3 "$ROOT/server/stack_config.py" get models.voxcpm.revision)}"
echo "== VoxCPM2 weights ($VOXCPM_REPO @ $VOXCPM_REV)"
# Values reach Python through the environment, never spliced into its source.
REPO="$VOXCPM_REPO" REV="$VOXCPM_REV" "$VENV/bin/python" -c \
  "import os; from huggingface_hub import snapshot_download as s; print(s(os.environ['REPO'], revision=os.environ['REV']))"
"$VENV/bin/python" -c "import nanovllm_voxcpm, torch; print('nano-vllm-voxcpm', nanovllm_voxcpm.__version__, 'ok, cuda', torch.cuda.is_available())"

# The fixed voice each VoxCPM2 language speaks in (server/voxcpm_service.py clones
# <lang>.wav). Copied from the repo only where the volume has none, so a
# reference chosen on the volume is never overwritten.
REF_DIR="${VOXCPM_REF_DIR:-$W/voices/voxcpm}"
if compgen -G "$ROOT/voices/voxcpm/*.wav" >/dev/null; then
  mkdir -p "$REF_DIR"
  for f in "$ROOT"/voices/voxcpm/*.wav; do
    [ -e "$REF_DIR/$(basename "$f")" ] || { cp "$f" "$REF_DIR/"; echo "  reference voice $(basename "$f")"; }
  done
fi
# The languages VoxCPM2 speaks in this edition (commercial routes more to it).
for l in $(tr , " " <<< "${VOXCPM_LANGS:-$(python3 "$ROOT/server/stack_config.py" uses voxcpm)}"); do
  [ -e "$REF_DIR/$l.wav" ] || echo "  note: no $REF_DIR/$l.wav — VoxCPM2 picks a new speaker per sentence for $l"
done
