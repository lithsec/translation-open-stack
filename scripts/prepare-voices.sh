#!/usr/bin/env bash
# Install VoxCPM2 (OpenBMB, Apache 2.0) ONCE into the network volume: its own
# virtualenv (it pins library versions the stack must not inherit) plus the
# model weights. run.sh then starts server/voxcpm_service.py from it (km lo tl; with
# EDITION=commercial also ko tr ru ar id sw vi).
#
#   bash scripts/prepare-voices.sh        # -> /workspace/venv_voxcpm, weights in $HF_HOME
#
# The stack's Docker image already has the venv (VOXCPM_VENV=/opt/venv_voxcpm),
# so there this only fetches the weights and the reference voices.
set -euo pipefail
# STACK_HOME: where models, voices and caches live (a pod's volume; a folder on a Mac).
W="${STACK_HOME:-/workspace}"
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"   # the repository: voices/voxcpm/ lives there
VENV="${VOXCPM_VENV:-$W/venv_voxcpm}"
export HF_HOME="${HF_HOME:-$W/hf-cache}"
if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c "import voxcpm" 2>/dev/null; then
  echo "== VoxCPM2 venv -> $VENV"
  # --system-site-packages: reuse the pod's CUDA torch instead of downloading another.
  python3 -m venv --system-site-packages "$VENV"
  # 2.0.3: the release the volume's venv was built from (current since 2026-05).
  # Its dependencies pinned too: constraints-voxcpm.txt, the venv's own packages
  # from a real build (everything else it reuses from the stack's, already pinned).
  "$VENV/bin/pip" -q install -c "$ROOT/constraints-voxcpm.txt" voxcpm==2.0.3 soundfile
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
"$VENV/bin/python" -c "import voxcpm, torch; print('voxcpm ok, cuda', torch.cuda.is_available())"

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
