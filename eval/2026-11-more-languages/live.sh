#!/usr/bin/env bash
# One stack start with configs/<C>.toml, then each run spec's directions one at a time, each clip streamed at
# real time by ../2026-10-de-ru-ro/e2e_client.mjs (?context=1); as ../2026-11-commercial-edition/live.sh.
# PAR=1 runs the specs at the same time (one loop each, so two rooms at once): quality only, the latency and
# drop counts of those runs are under load and are not reported.
#   bash live.sh <C> <tag> <run>:<clips dir>:<src-tgt>,... [more specs]   -> W/e2e_<tag>_<run>/out/runs/<dir>.json
set -uo pipefail
C="$1" TAG="$2"; shift 2
HERE="$(cd "$(dirname "$0")" && pwd)"
W=/workspace/work; ROOT=/workspace/tos
. /workspace/env.sh
export STACK_CONFIG="$HERE/configs/$C.toml"
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
echo "$(date -u +%T) stack up after ~$((i*5)) s ($C)"
for i in $(seq 1 480); do grep -qE "llmmt: .*\) answering —" "$LOG" && break; sleep 5; done
grep "llmmt:" "$LOG" | tail -n 2
sleep 5
one() {
  IFS=: read -r RUN CL DIRS <<< "$1"
  E="$W/e2e_${TAG}_${RUN}"; mkdir -p "$E/out/runs"; ln -sfn "$CL" "$E/clips"
  for d in ${DIRS//,/ }; do
    s=${d%-*}; t=${d#*-}
    [ -s "$E/out/runs/$d.json" ] && { echo "skip $RUN $d"; continue; }
    kill -0 $PID 2>/dev/null || { echo "stack died"; return 1; }
    echo "$(date -u +%T) $TAG $RUN $d"
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
}
if [ "${PAR:-0}" = 1 ]; then
  # wait on the loops only: a bare wait would also wait on the stack, which never exits (it hung here once)
  L=(); for spec in "$@"; do one "$spec" & L+=($!); done; wait "${L[@]}"
else for spec in "$@"; do one "$spec"; done; fi
grep -cE "pipeline behind, dropped" "$LOG" | sed 's/^/drops in log: /'
grep -E "llmmt .*failed" "$LOG" | wc -l | sed 's/^/llmmt failures: /'
kill $PID; sleep 5
P=$(pgrep -f "/workspace/tos/server/server.py" || true); [ -n "$P" ] && kill $P
sleep 5
echo "$(date -u +%T) done $TAG"
