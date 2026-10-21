#!/usr/bin/env bash
# Streams the continuous clips to an omni-stt URL (twice real time, one language
# per stream: no language ID) and scores them.
#
#   STT_URL=wss://<host> STT_TOKEN=... bash run.sh <name> ht en      # 300M
#   STT_URL=wss://<host> STT_TOKEN=... bash run.sh <name> km lo      # 7B
#
# Writes out/<name>.json (client.mjs) and prints score.py's table (PYTHON: one
# with rapidfuzz).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
name="$1"; shift
args=()
for lang in "$@"; do args+=("$HERE/audio/$lang.wav" "$lang"); done
mkdir -p "$HERE/out"
node "$HERE/../../services/omni-stt/client.mjs" "${args[@]}" --speed "${SPEED:-2}" --out "$HERE/out/$name.json" >/dev/null
"${PYTHON:-python3}" "$HERE/score.py" --audio "$HERE/audio" --refs "$HERE/../2026-10-real-voices/sentences" "$HERE/out/$name.json"
