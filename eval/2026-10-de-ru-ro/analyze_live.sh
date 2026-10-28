#!/usr/bin/env bash
# Latency and CER of every live run: eval/2026-10-unseen/analyze_e2e.py with its ORDER set to this
# round's six directions (the copy sits beside the original so its imports resolve).
#   bash analyze_live.sh WORK      -> WORK/e2e_*/out/{latency,sentences}.json
set -e
U="$(cd "$(dirname "$0")/../2026-10-unseen" && pwd)"
sed 's/^ORDER = .*/ORDER = ["en-de", "de-en", "en-ru", "ru-en", "en-ro", "ro-en"]/' "$U/analyze_e2e.py" > "$U/.analyze_drr.py"
trap 'rm -f "$U/.analyze_drr.py"' EXIT
for e in "$1"/e2e_*; do python3 "$U/.analyze_drr.py" "$e"; done
