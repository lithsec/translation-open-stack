#!/usr/bin/env bash
# One configuration live: start the stack with configs/<C>.toml serving LANGS, stream each direction through it one
# at a time in real time, stop the stack. Gemma must already be serving on :8101.
#   Q="&stream=1&policy=agree" bash live.sh <C> <clips dir> <run name> <langs> <src-tgt>...
#     -> work/e2e_<run name>/out/runs/<src-tgt>.json, work/e2e_<run name>/stack.log
set -uo pipefail
C="$1" CLIPS="$2" NAME="$3" LANGS="$4"; shift 4
HERE="$(cd "$(dirname "$0")" && pwd)"
E="$HERE/work/e2e_$NAME"
mkdir -p "$E/out/runs"
ln -sfn "$CLIPS" "$E/clips"
echo "${Q:-}" > "$E/query"
export STACK_CONFIG="$HERE/configs/$C.toml" STACK_PROFILE=cuda-80gb MADLAD=3b   # MADLAD: the fallback only
unset STACK_TOKEN   # localhost only (no public port on the pod)
cd /workspace/tos
bash scripts/run.sh "$LANGS" "$LANGS" > "$E/stack.log" 2>&1 &
PID=$!
for i in $(seq 1 180); do
  grep -q "\[stack\] ready on" "$E/stack.log" 2>/dev/null && break
  kill -0 $PID 2>/dev/null || { echo "STACK_FAIL $NAME"; tail -5 "$E/stack.log"; exit 1; }
  sleep 5
done
sleep 10
echo "stack up after ~$((i*5)) s ($NAME)"
for d in "$@"; do
  s=${d%-*}; t=${d#*-}
  [ -s "$E/out/runs/$d.json" ] && { echo "skip $d"; continue; }
  date -u +%T
  STACK_URL=ws://127.0.0.1:8790 STACK_TOKEN=evaltoken NODE_PATH="$HERE/node/node_modules" \
    node "$HERE/e2e_client.mjs" "$E/clips" "$s" "$t" "$E/out/runs/$d.json"
  sleep 3
done
kill $PID; sleep 5
for p in $(pgrep -f "server/server.py"); do kill "$p" 2>/dev/null; done; sleep 5
echo "done $NAME"
