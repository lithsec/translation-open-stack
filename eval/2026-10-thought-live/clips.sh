#!/usr/bin/env bash
# The clips, rebuilt on the pod from FLEURS by ../2026-10-de-ru-ro/build_clips.py (from its branch): sets a and b of
# 20 sentences shared by en and de, set a with regular and irregular pauses, set b with regular -> work/drr/clips_*
#   bash clips.sh     (after setup_pod.sh has cloned the repo to /workspace/tos)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; W="$HERE/work"; mkdir -p "$W"
cd /workspace/tos
git fetch -q origin eval/de-ru-ro
git checkout -q origin/eval/de-ru-ro -- eval/2026-10-de-ru-ro
cd eval/2026-10-de-ru-ro && python3 -I build_clips.py "$W/drr" ../2026-10-real-voices ""
echo CLIPS_DONE
