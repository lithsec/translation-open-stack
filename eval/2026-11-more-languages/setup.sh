#!/usr/bin/env bash
# Pod side: Gemma 4 via start-llmmt.sh (LLMMT=gemma), sox and Node 22 for the client, the 15 languages' voices
# and translators, the clips, and the two configs.   bash setup.sh > /workspace/work/setup.log 2>&1
set -uo pipefail
ROOT=/workspace/tos; W=/workspace/work; H="$ROOT/eval/2026-11-more-languages"
mkdir -p "$W"
cat > /workspace/env.sh <<'ENV'
export STACK_PROFILE=cuda-80gb HF_HOME=/workspace/hf-cache TORCH_HOME=/workspace/torch-cache
export FAIRSEQ2_CACHE_DIR=/workspace/fairseq2-cache HF_HUB_ENABLE_HF_TRANSFER=0 MADLAD=3b EDITION=nonprofit
export LANGS=en,zh,uk,vi,ar,fa,tl,sw,it,ko,id,tr,bn,ur,hi SRCS=en,zh,uk,vi,ar,fa,tl,sw,it,ko,id,tr,bn,ur,hi
ENV
. /workspace/env.sh
cd "$ROOT"
echo "== $(date -u +%T) start-llmmt"
( . scripts/profile-env.sh; LLMMT=gemma LLMMT_LOG=/workspace/llmmt.log bash scripts/start-llmmt.sh )
echo "== $(date -u +%T) apt + node 22"
( apt-get update -qq && apt-get install -y -qq sox ffmpeg >/dev/null
  node -e 'if (typeof WebSocket === "undefined") process.exit(1)' 2>/dev/null || {
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1 && apt-get install -y -qq nodejs >/dev/null; } ) 2>&1 | tail -n 3
node --version
echo "== $(date -u +%T) clips (background)"
python3 -I "$H/build_clips.py" "$W" "$ROOT/eval/2026-10-real-voices" "$ROOT/eval" > "$W/build.log" 2>&1 &
CL=$!
python3 -I "$H/make_config.py" "$ROOT/languages.toml" "$H/configs"
for c in A B; do STACK_CONFIG="$H/configs/$c.toml" python3 server/stack_config.py check > "$H/configs/check-$c.txt" 2>&1; done
echo "== $(date -u +%T) fetch-voices"
VOICES_DIR=/workspace/voices bash scripts/fetch-voices.sh "$LANGS" 2>&1 | tail -n 3
echo "== $(date -u +%T) prepare-mt (MADLAD=3b)"
bash scripts/prepare-mt.sh 2>&1 | grep -v "it/s\]" | tail -n 5
echo "== $(date -u +%T) prepare-voices"
bash scripts/prepare-voices.sh 2>&1 | grep -v "it/s\]" | tail -n 5
wait $CL; echo "clips exit $?"; tail -n 3 "$W/build.log"
echo "== $(date -u +%T) setup done"
