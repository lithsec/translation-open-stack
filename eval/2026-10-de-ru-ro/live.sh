#!/usr/bin/env bash
# One configuration live: start the stack with configs/<C>.toml, run each direction through it one at a
# time on one clip set and pause pattern, stop the stack. Gemma must already be serving on :8101.
#   bash live.sh <C> <set a|b> <reg|irr> <src-tgt>...      -> work/e2e_<C>_<set>_<pat>/out/runs/<dir>.json
set -uo pipefail
C="$1" ST="$2" PAT="$3"; shift 3
HERE="$(cd "$(dirname "$0")" && pwd)"
E="$HERE/work/e2e_${C}_${ST}_${PAT}"
mkdir -p "$E/out/runs"
ln -sfn "$HERE/work/clips_${ST}_${PAT}" "$E/clips"
export STACK_CONFIG="$HERE/configs/$C.toml" STACK_PROFILE=cuda-80gb HF_HUB_OFFLINE=1
unset STACK_TOKEN   # localhost only (no public port on the pod)
# Real-time runs on this pod take turns (the streaming eval shares it): mkdir is the lock.
until mkdir /workspace/REALTIME_LOCK.d 2>/dev/null; do sleep 60; done
echo live > /workspace/REALTIME_LOCK.d/owner
trap 'rm -rf /workspace/REALTIME_LOCK.d' EXIT
cd /workspace/tos
bash scripts/run.sh en,de,ru,ro en,de,ru,ro > "$E/stack.log" 2>&1 &
PID=$!
for i in $(seq 1 180); do grep -q "\[stack\] ready on" "$E/stack.log" 2>/dev/null && break; sleep 5; done
sleep 10
echo "stack up after ~$((i*5)) s ($C)"
for d in "$@"; do
  s=${d%-*}; t=${d#*-}
  [ -s "$E/out/runs/$d.json" ] && { echo "skip $d"; continue; }
  date -u +%T
  STACK_URL=ws://127.0.0.1:8790 STACK_TOKEN=evaltoken NODE_PATH="$HERE/node/node_modules" node "$HERE/e2e_client.mjs" "$E/clips" "$s" "$t" "$E/out/runs/$d.json"
  sleep 3
done
kill $PID; sleep 5; pkill -f "server/server.py" || true; sleep 5
echo "done $C $ST $PAT"
