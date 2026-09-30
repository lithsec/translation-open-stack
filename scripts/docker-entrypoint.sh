#!/usr/bin/env bash
# The container's start: fill the model volume on the first run, then serve.
#
# Everything big lives on /workspace (the volume), never in the image. Each step
# skips what is already there, so the first start takes 30-60 minutes (~38 GB
# kept, plus ~48 GB of temporary download while the translators are built) and
# every start after it about three minutes (loading and warming the models).
#
# On RunPod the pod's start command runs runpod/runpod-start.sh instead of this (same
# steps, plus the idle stop and the ready report).
set -euo pipefail
# RunPod's PyTorch image sets HF_HUB_ENABLE_HF_TRANSFER=1 without the hf_transfer package,
# and then EVERY Hugging Face download fails ("hf_transfer ... not available"). That quietly
# disabled language ID on launcher-started pods: every source was served as English (2026-09-29).
python3 -c "import hf_transfer" 2>/dev/null || export HF_HUB_ENABLE_HF_TRANSFER=0
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"

if [ -z "${STACK_SIGNING_KEY:-}" ] && [ -z "${STACK_TOKEN:-}" ]; then
  if [ "${STACK_OPEN:-0}" != 1 ]; then
    echo "Set STACK_TOKEN (or STACK_SIGNING_KEY) so only your apps can connect." >&2
    echo "On a private LAN you may instead set STACK_OPEN=1 to run with no credential." >&2
    exit 1
  fi
  echo "WARNING: STACK_OPEN=1 — anyone who can reach port 8790 can use this stack. LAN only."
fi

export HF_HOME="${HF_HOME:-/workspace/hf-cache}"
# Caches that would otherwise land on the container disk and be fetched again on
# every new container: Silero VAD (torch hub) and Omnilingual's weights (fairseq2).
export TORCH_HOME="${TORCH_HOME:-/workspace/torch-cache}"
export FAIRSEQ2_CACHE_DIR="${FAIRSEQ2_CACHE_DIR:-/workspace/fairseq2-cache}"
# The translator build's full-precision downloads: on the volume here (deleted
# afterwards), so they don't grow the container's own layer.
export MT_SCRATCH="${MT_SCRATCH:-/workspace/.mt-build}"
LANGS="${LANGS:-en,es,fr,pt,de,ru,uk,zh,ja,km,lo,ht,ar,hi,vi,ko,tl,fa,id,tr,bn,ur,it,sw,ro}"
SRCS="${SRCS:-en,es,fr,pt,de,ru,uk,it,zh,ja,ko,sw,km,lo,ht,ar,hi,vi,tl,fa,id,tr,bn,ur,ro}"
mkdir -p /workspace "$HF_HOME"

if ! python3 -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"; then
  echo "No NVIDIA GPU visible in the container. Check that this works first (NVIDIA Container Toolkit):" >&2
  echo "  docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi" >&2
  exit 1
fi
python3 "$ROOT/server/stack_config.py" check | sed -n 1p   # fails here, not mid-start, on a bad languages.toml

echo "== $(date -u) Piper voices"
VOICES_DIR=/workspace/voices bash "$DIR/fetch-voices.sh" "$LANGS"
echo "== $(date -u) translators (first run: ~20-40 min)"
bash "$DIR/prepare-mt.sh"
echo "== $(date -u) VoxCPM2 weights and reference voices"
if [ "${VOXCPM:-1}" = 1 ]; then bash "$DIR/prepare-voices.sh"; fi

echo "== $(date -u) starting the stack (edition ${EDITION:-nonprofit}); ready when it logs 'ready on :8790'"
exec bash "$DIR/run.sh" "$LANGS" "$SRCS"
