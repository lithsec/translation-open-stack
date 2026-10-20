#!/usr/bin/env bash
# Fail if the research site, its sources, or the data it is built from mention
# anything that must stay out of the public site.
#
#   bash site/check_private.sh            # after python3 site/build.py
#
# Scans, case-insensitively:
#   - every file under site/ (sources and the built site/_site/), text content
#     and file names; and
#   - every repository file the build reads (python3 site/build.py --list-inputs),
#     because their text can end up on a page.
# This script is the only file not scanned: it has to spell the terms out.
# Nothing is allow-listed.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
self="$here/check_private.sh"

# Private model-card suffix, private training repo, private organisation and
# event names, and any Google Cloud Storage bucket (gs://<anything>).
pattern='_gc|300M_gc|lithos-training|intellectual[[:space:]_-]*reserve|general[[:space:]_-]*conference|church|gs://'

if [ ! -d "$here/_site" ]; then
  echo "check_private: site/_site not found; run python3 site/build.py first" >&2
  exit 2
fi

targets=()
while IFS= read -r -d '' f; do
  [ "$f" = "$self" ] && continue
  targets+=("$f")
done < <(find "$here" -type f -not -path '*/__pycache__/*' -print0)
while IFS= read -r rel; do
  p="$root/$rel"
  if [ -d "$p" ]; then
    while IFS= read -r -d '' f; do targets+=("$f"); done < <(find "$p" -type f -print0)
  elif [ -f "$p" ]; then
    targets+=("$p")
  fi
done < <(python3 "$here/build.py" --list-inputs)

fail=0
# Content (text files; binary files such as mp3 are checked by name only).
if hits=$(grep -I -n -i -E "$pattern" "${targets[@]}" 2>/dev/null); then
  echo "check_private: private terms found in file contents:" >&2
  echo "$hits" | cut -c1-240 >&2
  fail=1
fi
# File names.
if names=$(printf '%s\n' "${targets[@]}" | sed "s|^$root/||" | grep -i -E "$pattern"); then
  echo "check_private: private terms found in file names:" >&2
  echo "$names" >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  exit 1
fi
echo "check_private: OK (${#targets[@]} files scanned, no private terms)"
