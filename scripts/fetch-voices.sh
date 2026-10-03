#!/usr/bin/env bash
# Download the Piper voice for each requested language into /workspace/voices.
# Idempotent — a mounted volume makes every start after the first free.
#
#   bash scripts/fetch-voices.sh en,es,de
#
# Which voice a language uses is set in languages.toml (`piper = "<voice>"`),
# read through server/stack_config.py, so the server and this script can't disagree.
# EDITION=commercial fetches only the voices that edition may load (never a
# non-commercial one; [<lang>.commercial] replacements instead).
# The catalogue of every voice and quality tier:
#   https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json
#
# PINNED: voices.lock (repository root) names the rhasspy/piper-voices commit
# to download from and the sha256 of every voice file. Every file, new or
# already on the volume, is checked against it; a mismatch (or a voice the lock
# does not list) is an error, and this script exits non-zero after trying the
# rest. A voice not yet locked: python3 scripts/lock-voices.py <voice>.
set -euo pipefail
# STACK_HOME: where models, voices and caches live (a pod's volume, /workspace by default;
# any folder on your own machine).
W="${STACK_HOME:-/workspace}"
DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER="$(cd "$DIR/../server" && pwd)"   # stack_config.py
LOCK="${VOICES_LOCK:-$DIR/../voices.lock}"
# The same default languages as run.sh, so every voice it loads is here.
LANGS="${1:-${LANGS:-en,es,fr,pt,de,ru,uk,zh,ja,km,lo,ht,ar,hi,vi,ko,tl,fa,id,tr,bn,ur,it,sw,ro}}"
DEST="${VOICES_DIR:-$W/voices}"
[ -f "$LOCK" ] || { echo "ERROR: $LOCK missing: voices are only fetched pinned" >&2; exit 1; }
REPO="$(awk '$1 == "repo" { print $2 }' "$LOCK")"
REV="$(awk '$1 == "revision" { print $2 }' "$LOCK")"
[[ "$REV" =~ ^[0-9a-f]{40}$ ]] || { echo "ERROR: $LOCK: no 40-hex revision" >&2; exit 1; }
BASE="https://huggingface.co/$REPO/resolve/$REV"
mkdir -p "$DEST"

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }
locked() { awk -v f="$1" '$1 !~ /^#/ && $2 == f { print $1 }' "$LOCK"; }

MAPPED="$(python3 "$SERVER/stack_config.py" piper "$LANGS")"
IFS=',' read -ra LL <<< "$LANGS"
for l in "${LL[@]}"; do
  grep -q "^$l " <<< "$MAPPED" || echo "  $l: no Piper voice configured — Kokoro, VoxCPM2, Coqui, MMS or text"
done
bad=0
while read -r l name; do
  [ -n "$name" ] || continue
  # Values reach Python through the environment, never spliced into its source.
  p="$(SERVER="$SERVER" VOICE="$name" python3 -c \
    "import os, sys; sys.path.insert(0, os.environ['SERVER']); import stack_config; print(stack_config.piper_path(os.environ['VOICE']))")"
  for ext in .onnx .onnx.json; do
    f="$DEST/${name}${ext}"
    want="$(locked "${name}${ext}")"
    if [ -z "$want" ]; then
      echo "  ERROR $l: ${name}${ext} is not in voices.lock; add it with: python3 scripts/lock-voices.py $name" >&2
      bad=1; continue
    fi
    # A file already here (an older unpinned download, or a damaged one) must
    # match too; if it doesn't, the pinned file replaces it.
    if [ -s "$f" ] && [ "$(sha256 "$f")" != "$want" ]; then
      echo "  $l: ${name}${ext} on disk does not match voices.lock; fetching the pinned file"
      rm -f "$f"
    fi
    # -s catches the truncated file a killed download leaves behind, which
    # otherwise loads and fails at synthesis time.
    if [ ! -s "$f" ]; then
      echo "  $l: fetching ${name}${ext} (@ ${REV:0:12})"
      if ! curl -sL --fail "$BASE/${p}${ext}" -o "$f.part"; then
        rm -f "$f.part"; echo "    FAILED"; continue
      fi
      got="$(sha256 "$f.part")"
      if [ "$got" != "$want" ]; then
        rm -f "$f.part"
        echo "  ERROR $l: ${name}${ext} has sha256 $got; voices.lock expects $want. Refused." >&2
        bad=1; continue
      fi
      mv "$f.part" "$f"
    fi
  done
done <<< "$MAPPED"
echo "voices in $DEST: $(find "$DEST" -maxdepth 1 -name '*.onnx' | wc -l | tr -d ' ')"
if [ "$bad" = 1 ]; then
  echo "ERROR: Piper voices failed verification against voices.lock (above)" >&2
  exit 1
fi
