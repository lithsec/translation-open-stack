#!/usr/bin/env bash
# Runs the directions one at a time through the stack; saves events, GPU samples and stage log lines.
#   bash run_all.sh <dir>  [directions...]
set -uo pipefail
D="$1"; shift
# Env: STACK_URL (the stack's wss:// address), STACK_TOKEN, SIDECAR_URL (sidecar.py, https://)
: "${STACK_URL:?}" "${STACK_TOKEN:?}" "${SIDECAR_URL:?}"
SC="$SIDECAR_URL"
H=(-H "Authorization: Bearer $STACK_TOKEN")
mkdir -p "$D/out/runs"
for dir in "$@"; do
  s=${dir%-*}; t=${dir#*-}
  [ -s "$D/out/runs/$dir.json" ] && { echo "skip $dir"; continue; }
  curl -s -m 20 "${H[@]}" -X POST "$SC/reset" >/dev/null
  date -u +%T
  node "$D/scripts/e2e_client.mjs" "$D/clips" "$s" "$t" "$D/out/runs/$dir.json"
  curl -s -m 30 "${H[@]}" "$SC/stats" > "$D/out/runs/$dir.gpu.json"
  curl -s -m 30 "${H[@]}" "$SC/log?n=400" > "$D/out/runs/$dir.log.json"
  sleep 3
done
