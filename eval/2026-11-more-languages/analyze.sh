#!/usr/bin/env bash
# Latency, CER, drops, per-sentence output: ../2026-10-unseen/analyze_e2e.py with ORDER = this round's 28
# directions, after ../2026-11-commercial-edition/trim_logs.py.   bash analyze.sh WORK
set -e
U="$(cd "$(dirname "$0")/../2026-10-unseen" && pwd)"
O='ORDER = ['; for l in zh uk vi ar fa tl sw it ko id tr bn ur hi; do O="$O\"en-$l\", \"$l-en\", "; done; O="${O%, }]"
sed "s/^ORDER = .*/$O/" "$U/analyze_e2e.py" > "$U/.analyze_more.py"
trap 'rm -f "$U/.analyze_more.py"' EXIT
python3 -I "$(dirname "$0")/../2026-11-commercial-edition/trim_logs.py" "$1"
for e in "$1"/e2e_*; do [ -d "$e/out/runs" ] && python3 "$U/.analyze_more.py" "$e"; done
