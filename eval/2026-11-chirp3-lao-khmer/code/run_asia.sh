#!/bin/zsh
# The five-language pipeline: wait for the clips, hear (Chirp 3 + today's recogniser), translate (Gemma), grade.
set -u
R=/tmp/rs/chirp; LT=/Users/sstone/dev/live-translation
until [ -f $R/data/asia/hi/clip.json ]; do sleep 5; done
source /Users/sstone/dev/lt-into-en-eval-results/scripts/keys.sh >/dev/null 2>&1
export GCP_PROJECT=linen-cubist-509804-h6 GCP_TOKEN=$(gcloud auth print-access-token)
typeset -A LOC; LOC=(ja ja-JP vi vi-VN zh cmn-Hans-CN ko ko-KR hi hi-IN)
typeset -A BASE; BASE=(ja mai vi mai zh mai ko azure hi azure)
echo "== hearing $(date +%T)"
for l in ja vi zh ko hi; do
  (cd $LT && npx tsx $R/code/azure_stream.mts $l ${BASE[$l]} > $R/runs/asia_${l}_${BASE[$l]}.log 2>&1) &
done
wait
cat $R/runs/asia_*_chirp.log $R/runs/asia_*_mai.log $R/runs/asia_*_azure.log
python3 -I $R/code/asia_score.py ja vi zh ko hi
echo "== translating $(date +%T)"
for l in ja vi zh ko hi; do (cd $LT && npx tsx $R/code/asia_translate.mts $l $R/runs/mt_asia_$l.json > $R/runs/mt_asia_$l.log 2>&1) & done
wait
grep -h -c ERR $R/runs/mt_asia_*.log
echo "== grading $(date +%T)"
GEMINI_API_KEY=$(tr -d ' \n\r' < ~/.config/lithos/gemini.key) $R/venv/bin/python -I $R/code/asia_grade.py $R/runs/grade_asia.json ja vi zh ko hi
echo "== done $(date +%T)"
