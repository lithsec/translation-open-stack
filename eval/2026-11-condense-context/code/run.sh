#!/bin/zsh
# Translate + condense both languages, then grade.
R=/tmp/rs/cond; LT=/Users/sstone/dev/live-translation
source /Users/sstone/dev/lt-into-en-eval-results/scripts/keys.sh >/dev/null 2>&1
for l in pt es; do (cd $LT && npx tsx $R/code/condense_eval.mts $l > $R/runs/condense_$l.log 2>&1) & done
wait
tail -1 $R/runs/condense_pt.log $R/runs/condense_es.log
GEMINI_API_KEY=$(tr -d ' \n\r' < ~/.config/lithos/gemini.key) /tmp/rs/chirp/venv/bin/python -I $R/code/grade.py pt es
