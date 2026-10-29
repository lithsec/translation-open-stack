#!/usr/bin/env bash
# The clips, rebuilt on the pod from FLEURS by the rounds that made them (their scripts from their branches):
#   German:   ../2026-10-de-ru-ro/build_clips.py, set a with regular and irregular pauses -> work/clips_a_{reg,irr}
#   en/es/fr: ../2026-10-open-streaming/build_unseen_subset.py, the unseen set           -> work/unseen/clips_{reg,irr}
#   bash clips.sh     (after setup_pod.sh has cloned the repo to /workspace/tos)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; W="$HERE/work"; mkdir -p "$W"
cd /workspace/tos
git fetch -q origin eval/de-ru-ro eval/open-streaming
git checkout -q origin/eval/de-ru-ro -- eval/2026-10-de-ru-ro
git checkout -q origin/eval/open-streaming -- eval/2026-10-open-streaming
cd eval/2026-10-de-ru-ro && python3 -I build_clips.py "$W/drr" ../2026-10-real-voices ""
ln -sfn "$W/drr/clips_a_reg" "$W/clips_a_reg"; ln -sfn "$W/drr/clips_a_irr" "$W/clips_a_irr"
cd ../2026-10-open-streaming && python3 -I build_unseen_subset.py "$W/unseen" ../2026-10-real-voices ../2026-10-unseen/results.json en es fr
echo CLIPS_DONE
