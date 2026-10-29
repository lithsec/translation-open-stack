#!/bin/bash
# Grading, once a Gemini key is available (all Gemini calls; no GPU):
#   GEMINI_API_KEY="$(cat ~/.config/lithos/gemini.key)" bash grade.sh CLIPS_ROOT UO WORK
# 1. cut every system's spoken stream into the read sentences at verbatim anchors (as the phrase eval)
# 2. grading and "chunks wrong later" jobs from that cut
# 3. grade (blind, all six systems per direction and reference), count chunks wrong later
# 4. the tables (results.json here, then table.py)
set -e
H=$(cd "$(dirname "$0")" && pwd)
ROOT=$1; UO=$2; WORK=$3
python3 -I "$H/../2026-10-simultaneous-phrases/seg_all.py" "$ROOT" "$WORK"
python3 -I "$H/analyze_open.py" jobs "$ROOT" "$UO" "$WORK"
python3 -I "$H/../2026-10-es-pt-live-compare/grade.py" "$WORK/jobs.json" "$WORK/grades.json"
python3 -I "$H/../2026-10-simultaneous-phrases/contradictions.py" "$WORK/contra_jobs.json" "$WORK/contra.json"
python3 -I "$H/analyze_open.py" table "$ROOT" "$UO" "$WORK"
python3 -I "$H/table.py"
