#!/usr/bin/env bash
# One stack start, then runs one at a time (as ../2026-10-de-ru-ro/live.sh), each clip streamed in real time
# by e2e_client.mjs (../2026-10-de-ru-ro's copy: ?context=1). After each run: the stack log so far
# (runs/<dir>.log.json, for analyze_e2e.py's drop count) and nvidia-smi samples (runs/<dir>.gpu.json).
#   bash live.sh <edition> <tag> <run>:<clips dir>:<src-tgt>,<src-tgt>... [more run specs]
#     -> W/e2e_<tag>_<run>/out/runs/<dir>.json
set -uo pipefail
EDN="$1" TAG="$2"; shift 2
HERE="$(cd "$(dirname "$0")" && pwd)"
W="${W:-/workspace/work}"; ROOT="${ROOT:-/workspace/tos-commercial}"
. /workspace/env.sh
export EDITION="$EDN"
unset STACK_TOKEN STACK_SIGNING_KEY
LOG="$W/stack_${TAG}.log"
cd "$ROOT"
bash scripts/run.sh "$LANGS" "$SRCS" > "$LOG" 2>&1 &
PID=$!
for i in $(seq 1 360); do
  grep -q "\[stack\] ready on" "$LOG" 2>/dev/null && break
  kill -0 $PID 2>/dev/null || { echo "stack died"; tail -n 30 "$LOG"; exit 1; }
  sleep 5
done
echo "$(date -u +%T) stack up after ~$((i*5)) s ($EDN)"
# llmmt directions: wait until the stack says its LLM server answers (it checks every 30 s)
for i in $(seq 1 40); do grep -qE "llmmt: .*\) answering —" "$LOG" && break; sleep 5; done
grep "llmmt:" "$LOG" | tail -n 3
sleep 5
for spec in "$@"; do
  IFS=: read -r RUN CL DIRS <<< "$spec"
  E="$W/e2e_${TAG}_${RUN}"; mkdir -p "$E/out/runs"; ln -sfn "$CL" "$E/clips"
  for d in ${DIRS//,/ }; do
    s=${d%-*}; t=${d#*-}
    [ -s "$E/out/runs/$d.json" ] && { echo "skip $RUN $d"; continue; }
    kill -0 $PID 2>/dev/null || { echo "stack died"; exit 1; }
    echo "$(date -u +%T) $RUN $d"
    ( while true; do nvidia-smi --query-gpu=timestamp,memory.used,memory.total,utilization.gpu,name --format=csv,noheader,nounits; sleep 2; done ) > "$E/out/runs/$d.gpu.csv" &
    SMI=$!
    STACK_URL=ws://127.0.0.1:8790 STACK_TOKEN=evaltoken node "$HERE/../2026-10-de-ru-ro/e2e_client.mjs" "$E/clips" "$s" "$t" "$E/out/runs/$d.json"
    kill $SMI 2>/dev/null
    python3 - "$LOG" "$E/out/runs/$d" <<'PY'
import json, sys
lines = open(sys.argv[1], errors="replace").read().splitlines()
json.dump({"lines": lines}, open(sys.argv[2] + ".log.json", "w"))
smp = []
for l in open(sys.argv[2] + ".gpu.csv"):
    p = [x.strip() for x in l.split(",")]
    if len(p) == 5:
        smp.append([p[0], int(p[1]), int(p[2]), int(p[3]), p[4]])
json.dump({"samples": smp}, open(sys.argv[2] + ".gpu.json", "w"))
PY
    sleep 3
  done
done
kill $PID; sleep 5
P=$(pgrep -f "tos-commercial/server/server.py" || true); [ -n "$P" ] && kill $P
echo "$(date -u +%T) done $TAG"
