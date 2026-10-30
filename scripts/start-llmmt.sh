#!/usr/bin/env bash
# Start the LLM translators languages.toml names with `llmmt` (Gemma 4 31B on :8101, MiLMMT-46 12B on :8102)
# in vLLM beside the stack, when the GPU has room for them. Without them the stack still serves: each llmmt
# direction uses its next translator (Hy-MT2 or MADLAD) and switches over by itself once the server answers
# (engines/llmmt.py checks every 30 s). So this runs in the background and the stack starts at once.
#
#   bash scripts/start-llmmt.sh            (scripts/runpod/runpod-start.sh runs it; logs to $LLMMT_LOG)
#
# LLMMT     auto (default): Gemma when one GPU has room for it beside the stack (below); gemma, milmmt or
#           gemma,milmmt: those, without the check; 0: none.
# EDITION=commercial starts none: commercial leaves llmmt out until [licence_review] names it.
#
# Room, for auto: the stack holds about 33 GB with all 25 languages (docs/user-guide.md, "GPUs and capacity"),
# 20 GB more with Omnilingual's 7B card (OMNI_LARGE=1), and Gemma 4 31B 4-bit takes GEMMA_GB (36) with an
# 8192-token context; 8 GB more stays free for activations. One GPU: total >= stack + Gemma + 8 (96 GB cards
# with the 7B, 80 GB cards without it). Several GPUs: Gemma goes on the last one, if it has GEMMA_GB + 4 (+ 16 with
# STACK_PROFILE=cuda-2gpu, which puts recognition and the voices there).
#
# First start: vLLM in its own venv on the volume (VLLM_VENV, ~10 GB, ~5 min), Gemma's weights (~20 GB to
# HF_HOME), and vLLM's first compile (~12 min); later starts reuse all three. vLLM needs ninja on PATH for
# FlashInfer, and its FlashInfer sampler off on these images (eval/2026-10-de-ru-ro).
set -uo pipefail
LLMMT="${LLMMT:-auto}"
LLMMT_LOG="${LLMMT_LOG:-/workspace/llmmt.log}"
VLLM_VENV="${VLLM_VENV:-/workspace/vllm-venv}"
VLLM_VERSION="${VLLM_VERSION:-0.31.0}"
GEMMA_GB="${GEMMA_GB:-36}"
GEMMA_MODEL="google/gemma-4-31B-it-qat-w4a16-ct"
MILMMT_MODEL="xiaomi-research/MiLMMT-46-12B-v0.1"
STACK_GB=33
[ "${OMNI_LARGE:-0}" = 1 ] && STACK_GB=53

if [ "$LLMMT" = 0 ]; then echo "== llmmt: off (LLMMT=0)"; exit 0; fi
if [ "${EDITION:-nonprofit}" = commercial ]; then
  echo "== llmmt: not started (EDITION=commercial leaves llmmt out; its directions use Hy-MT2 or MADLAD)"; exit 0
fi

# GPU totals in GB, one per line (LLMMT_GPUS_GB="96" or "48 48" stands in for nvidia-smi, for tests).
gpus=${LLMMT_GPUS_GB:-$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | awk '{printf "%d ", $1/1024}')}
read -r -a GB <<< "$gpus"
models=() gpu="" util=""
if [ "$LLMMT" = auto ]; then
  n=${#GB[@]}
  # profiles/cuda-2gpu puts recognition and the voices (~16 GB) on the last GPU too.
  shared=0; [ "${STACK_PROFILE:-}" = cuda-2gpu ] && shared=16
  if [ "$n" -ge 2 ] && [ "${GB[$((n - 1))]}" -ge $((GEMMA_GB + 4 + shared)) ]; then
    gpu=$((n - 1))
  elif [ "$n" -ge 1 ] && [ "${GB[0]}" -ge $((STACK_GB + GEMMA_GB + 8)) ]; then
    gpu=0
  else
    echo "== llmmt: no room for Gemma 4 31B (GPUs: ${gpus:-none} GB; it needs ${GEMMA_GB} GB beside the stack's" \
         "${STACK_GB} GB + 8): its directions use Hy-MT2 or MADLAD. LLMMT=gemma starts it anyway."
    exit 0
  fi
  models=(gemma)
else
  IFS=, read -r -a models <<< "$LLMMT"
  gpu=$(( ${#GB[@]} >= 2 ? ${#GB[@]} - 1 : 0 ))
fi
total=${GB[$gpu]:-96}
# vLLM's share of the card: GEMMA_GB of it, or most of a card of its own.
if [ "${#GB[@]}" -ge 2 ] && [ "${STACK_PROFILE:-}" != cuda-2gpu ]; then util=$([ "${#models[@]}" -ge 2 ] && echo 0.42 || echo 0.85)
else util=$(awk -v g="$GEMMA_GB" -v t="$total" 'BEGIN { printf "%.2f", g / t }'); fi
echo "== llmmt: ${models[*]} on GPU $gpu (${total} GB, vLLM share $util); log $LLMMT_LOG"
[ "${LLMMT_DRY_RUN:-0}" = 1 ] && exit 0

(
  set -e
  export HF_HOME="${HF_HOME:-/workspace/hf-cache}" VLLM_USE_FLASHINFER_SAMPLER=0 CUDA_VISIBLE_DEVICES="$gpu"
  export VLLM_CACHE_ROOT="${VLLM_CACHE_ROOT:-/workspace/vllm-cache}"
  if [ ! -x "$VLLM_VENV/bin/vllm" ] || ! "$VLLM_VENV/bin/python" -c "import vllm, sys; sys.exit(vllm.__version__ != '$VLLM_VERSION')"; then
    echo "== $(date -u +%T) installing vLLM $VLLM_VERSION in $VLLM_VENV"
    python3 -m venv "$VLLM_VENV"
    "$VLLM_VENV/bin/pip" install -q "vllm==$VLLM_VERSION" ninja
  fi
  export PATH="$VLLM_VENV/bin:$PATH"
  for m in "${models[@]}"; do
    case "$m" in
      gemma)  model=$GEMMA_MODEL port=8101 ;;
      milmmt) model=$MILMMT_MODEL port=8102 ;;
      *) echo "== llmmt: unknown model '$m' (gemma, milmmt)"; continue ;;
    esac
    echo "== $(date -u +%T) starting $model on :$port"
    nohup vllm serve "$model" --port "$port" --host 127.0.0.1 --gpu-memory-utilization "$util" \
      --max-model-len 8192 --enable-prefix-caching > "${LLMMT_LOG%.log}-$m.log" 2>&1 < /dev/null &
  done
) >> "$LLMMT_LOG" 2>&1 &
