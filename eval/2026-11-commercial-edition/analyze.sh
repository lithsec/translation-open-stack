#!/usr/bin/env bash
# Latency, CER, drops and per-sentence output of every live run: ../2026-10-unseen/analyze_e2e.py with its
# ORDER set to this round's 20 directions (the copy sits beside the original so its imports resolve), as
# ../2026-10-de-ru-ro/analyze_live.sh. Run on the pod (it reads the clips' audio).
#   bash analyze.sh WORK      -> WORK/e2e_*/out/{latency,sentences}.json
set -e
U="$(cd "$(dirname "$0")/../2026-10-unseen" && pwd)"
sed 's/^ORDER = .*/ORDER = ["en-es", "es-en", "en-ja", "ja-en", "en-fr", "fr-en", "en-km", "km-en", "ht-en", "en-ht", "lo-en", "en-lo", "en-pt", "pt-en", "en-de", "de-en", "en-ru", "ru-en", "en-ro", "ro-en"]/' "$U/analyze_e2e.py" > "$U/.analyze_commercial.py"
trap 'rm -f "$U/.analyze_commercial.py"' EXIT
python3 -I "$(dirname "$0")/trim_logs.py" "$1"
for e in "$1"/e2e_*; do [ -d "$e/out/runs" ] && python3 "$U/.analyze_commercial.py" "$e"; done
