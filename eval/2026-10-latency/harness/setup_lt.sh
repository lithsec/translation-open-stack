#!/bin/bash
# Prepares a scratch copy of Live Translation's provider code for the harness.
#
#   bash setup_lt.sh <live-translation git checkout> <commit> <scratch dir>
#
# Copies src/ at <commit> (git archive; the checkout itself is not touched),
# links the checkout's node_modules, adds the two passive __probe hooks
# (azure-probes.patch: they log each Azure / Omnilingual final with its audio
# span and change nothing else), replaces keys.ts / logger.ts with stubs that
# read keys from the environment and log to stderr, and copies the harness.
set -euo pipefail
repo=$1; commit=$2; dir=$3
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$dir"
git -C "$repo" archive --format=tar "$commit" src package.json | tar -x -C "$dir"
ln -sfn "$repo/node_modules" "$dir/node_modules"
(cd "$dir" && patch -p1 < "$here/azure-probes.patch")
cp "$here/stubs/keys.ts" "$here/stubs/logger.ts" "$dir/src/main/"
mkdir -p "$dir/harness"
cp "$here/run_route.ts" "$here/launch.sh" "$dir/harness/"
echo "ready: $dir (LT $(git -C "$repo" rev-parse --short "$commit"))"
