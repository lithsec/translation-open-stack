#!/bin/bash
# Runs several harness sessions at once on the same clip set and waits.
#   launch.sh <clipDir> <outDir> <tag> "route src tgt [model]" ...
# Needs the keys in the environment (see env.example).
clip=$1; out=$2; tag=$3; shift 3
cd "$(dirname "$0")/.."
for spec in "$@"; do
  set -- $spec
  name="$tag-$1-$2-$3${4:+-$4}"
  npx tsx harness/run_route.ts $1 $2 $3 "$clip" "$out/$name.json" $4 > "$out/$name.log" 2>&1 &
done
wait
