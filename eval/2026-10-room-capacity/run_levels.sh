#!/usr/bin/env bash
# The load levels, one after another, on the pod: each runs load.py with GPU memory sampled every 2 s and the stack's
# "pipeline behind, dropped" lines kept. Stops climbing once a level drops utterances.
#   bash run_levels.sh CLIP_DIR RUNS_DIR STACK_LOG
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; CLIP=$1 RUNS=$2 LOG=$3
mkdir -p "$RUNS"
level() {  # level <tag> <rooms> <langs>
  local tag=$1 rooms=$2 langs=$3
  [ -s "$RUNS/$tag.json" ] && return 0
  local before; before=$(wc -l < "$LOG")
  ( while :; do nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits; sleep 2; done ) > "$RUNS/$tag.gpu" &
  local smi=$!
  python3 "$HERE/load.py" --rooms "$rooms" --langs "$langs" --clip "$CLIP" --out "$RUNS/$tag.json"
  kill $smi
  tail -n +"$((before + 1))" "$LOG" | grep "pipeline behind, dropped" > "$RUNS/$tag.drops" || true
  echo "$tag: $(wc -l < "$RUNS/$tag.drops") dropped"
  sleep 20
}
FOUR=es,fr,de,ja                                   # Gemma 4 out of English (a typical room)
TWELVE=es,fr,pt,de,ru,ja,zh,ko,it,vi,ar,hi         # many languages in one room
level r1 1 $FOUR
for n in 4 8 12 16 24 32; do
  level "r$n" $n $FOUR
  [ "$(wc -l < "$RUNS/r$n.drops")" -gt 0 ] && break
done
level w1 1 $TWELVE
for n in 4 8; do
  level "w$n" $n $TWELVE
  [ "$(wc -l < "$RUNS/w$n.drops")" -gt 0 ] && break
done
echo LEVELS_DONE
