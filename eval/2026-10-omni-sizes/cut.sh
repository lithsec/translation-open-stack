#!/usr/bin/env bash
# Cuts the real-voice clips into one 16 kHz mono wav per sentence, with ffmpeg,
# at the marks in audio/<lang>.json "sentences" [{i,start,end}]
# (start, and end - start as the duration).
#   bash cut.sh ../2026-10-real-voices clips
set -euo pipefail
src=$1 dst=$2
for lang in ht km lo en fr; do
  mkdir -p "$dst/$lang"
  python3 -c "import json,sys; [print(m['i'], m['start'], round(m['end'] - m['start'], 3)) for m in json.load(open(sys.argv[1]))['sentences']]" \
    "$src/audio/$lang.json" | while read -r i s d; do
    ffmpeg -nostdin -v error -y -ss "$s" -t "$d" -i "$src/audio/$lang.wav" -ac 1 -ar 16000 \
      "$dst/$lang/$(printf %02d "$i").wav"
  done
done
