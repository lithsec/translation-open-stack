#!/usr/bin/env bash
# Pod side of the Lao-on-Gemma re-run (README, "Lao on Gemma 4"): env, Gemma via start-llmmt.sh as the
# template's start would (LLMMT=auto, profile cuda-80gb so OMNI_LARGE=1), the stack's models, clip sets a and b.
#   bash setup.sh      (ROOT=/workspace/tos-commercial, the rsynced working tree)
set -uo pipefail
ROOT=/workspace/tos-commercial; W=/workspace/work; E="$ROOT/eval"
mkdir -p "$W"
cat > /workspace/env.sh <<'ENV'
export STACK_PROFILE=cuda-80gb HF_HOME=/workspace/hf-cache TORCH_HOME=/workspace/torch-cache
export FAIRSEQ2_CACHE_DIR=/workspace/fairseq2-cache HF_HUB_ENABLE_HF_TRANSFER=0 MADLAD=3b
export LANGS=en,es,pt,fr,ja,km,lo,ht,de,ru,ro SRCS=en,es,pt,fr,ja,km,lo,ht,de,ru,ro
ENV
. /workspace/env.sh
cd "$ROOT"
echo "== $(date -u +%T) start-llmmt (LLMMT=${LLMMT:-auto}, as runpod-start.sh: profile-env first)"
( . scripts/profile-env.sh; echo "OMNI_LARGE=${OMNI_LARGE:-unset}"; EDITION=commercial LLMMT_LOG=/workspace/llmmt.log bash scripts/start-llmmt.sh )
echo "== $(date -u +%T) apt"
(apt-get update -qq && apt-get install -y -qq sox nodejs >/dev/null) 2>&1 | tail -n 3
echo "== $(date -u +%T) clips"
mkdir -p "$W/empty" "$W/seta" "$W/setb"
RV="$E/2026-10-real-voices"
python3 -I "$E/2026-10-unseen/build_clips.py" "$W/seta" "$RV" "$W/empty" > "$W/seta/build.log" 2>&1 &
CL=$!
echo "== $(date -u +%T) fetch-voices"
VOICES_DIR=/workspace/voices bash scripts/fetch-voices.sh "$LANGS" 2>&1 | tail -n 3
echo "== $(date -u +%T) prepare-mt (MADLAD=3b)"
bash scripts/prepare-mt.sh 2>&1 | grep -v "it/s\]" | tail -n 5
echo "== $(date -u +%T) prepare-voices"
bash scripts/prepare-voices.sh 2>&1 | grep -v "it/s\]" | tail -n 5
wait $CL; echo "set a build exit $?"
python3 -I "$E/2026-10-full-stack/build_clips_b.py" "$W/setb" "$RV" "$W/seta/clips_reg" > "$W/setb/build.log" 2>&1; echo "set b build exit $?"
echo "== $(date -u +%T) setup done"
