#!/usr/bin/env bash
# Rebuild the three clip sets this round needs (the clips aren't in the repository), on the pod:
#   set a  (../2026-10-unseen/build_clips.py, seed 2026; checked against ../2026-10-unseen/results.json fleurs_ids)
#   set b  (../2026-10-full-stack/build_clips_b.py, seed 2027, excluding set a)
#   de-ru-ro sets a and b (../2026-10-de-ru-ro/build_clips.py, seed 2027; checked against its results/ids.json)
#   bash build_clips.sh WORK
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; E="$HERE/.."; W="$1"
RV="$E/2026-10-real-voices"
mkdir -p "$W/empty" "$W/seta" "$W/setb" "$W/drr"
python3 -I "$E/2026-10-unseen/build_clips.py" "$W/seta" "$RV" "$W/empty" > "$W/seta/build.log" 2>&1 &
python3 -I "$E/2026-10-de-ru-ro/build_clips.py" "$W/drr" "$RV" "" > "$W/drr/build.log" 2>&1 &
wait %1
python3 - "$W/seta/ids.json" "$E/2026-10-unseen/results.json" <<'PY'
import json, sys
a, r = json.load(open(sys.argv[1]))["ids"], json.load(open(sys.argv[2]))["fleurs_ids"]
print("set a ids match the unseen round:", a == r); sys.exit(a != r)
PY
python3 -I "$E/2026-10-full-stack/build_clips_b.py" "$W/setb" "$RV" "$W/seta/clips_reg" > "$W/setb/build.log" 2>&1
wait
python3 - "$W/drr/ids.json" "$E/2026-10-de-ru-ro/results/ids.json" <<'PY'
import json, sys
a, r = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
print("de-ru-ro ids match:", a == r); sys.exit(a != r)
PY
echo built
