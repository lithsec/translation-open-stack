#!/bin/zsh
# Final prompt: condense both languages on the original eval's runs, then grade A vs final B, and old B vs final B.
F=/Users/sstone/dev/translation-open-stack/eval/2026-11-condense-context-final; W=/Users/sstone/.t3/worktrees/live-translation/t3-763703d3
source /Users/sstone/dev/lt-into-en-eval-results/scripts/keys.sh >/dev/null 2>&1
for l in pt es; do (cd $W && npx tsx $F/code/condense_eval.mts $l > $F/runs/condense_$l.log 2>&1) & done
wait
tail -1 $F/runs/condense_pt.log $F/runs/condense_es.log
K=$(tr -d ' \n\r' < ~/.config/lithos/gemini.key)
GEMINI_API_KEY=$K PREFIX=condense_ /tmp/rs/chirp/venv/bin/python -I $F/code/grade.py pt es > $F/runs/summary_A_vs_final.txt
GEMINI_API_KEY=$K PREFIX=oldB_vs_final_ /tmp/rs/chirp/venv/bin/python -I $F/code/grade.py pt es > $F/runs/summary_oldB_vs_final.txt
cat $F/runs/summary_*.txt
