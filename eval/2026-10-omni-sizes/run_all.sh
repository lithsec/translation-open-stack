#!/usr/bin/env bash
# Runs sizes_eval.py for each card in turn on the GPU pod, one model at a time
# (the timings need the GPU to themselves). Checkpoints are fetched beforehand
# into /root/ckpt (aria2c, 16 connections; the cards' checkpoint: URLs are
# rewritten to file:///root/ckpt/ on the pod) and deleted after their run.
#   bash run_all.sh omniASR_LLM_300M omniASR_LLM_1B ...
set -uo pipefail
TEST=${TEST:-}
for card in "$@"; do
  [ -s "out/$card.json" ] && { echo "skip $card"; continue; }
  f=/root/ckpt/$(echo "$card" | sed 's/_/-/g').pt
  until [ -s "$f" ] && ! pgrep -f "aria2c.*$(basename "$f")" >/dev/null; do sleep 5; done
  python sizes_eval.py --card "$card" --clips clips --out out ${TEST:+--test "$TEST" --data /root/w/lt/data} 2>&1 \
    | grep -v -i "warning" > "logs/$card.log"
  tail -1 "logs/$card.log"
  [ "${KEEP:-0}" = 1 ] || rm -f "$f"
done
