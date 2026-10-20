#!/usr/bin/env bash
# Fail if the research site, its sources, or the data it is built from mention
# anything that must stay out of the public site.
#
#   bash site/check_private.sh            # after python3 site/build.py
#
# Scans, case-insensitively:
#   - every file under site/ (sources and the built site/_site/), text content,
#     binary files' printable strings (metadata included) and file names; and
#   - every repository file the build reads (python3 site/build.py --list-inputs),
#     because their text can end up on a page.
# This script is the only file not scanned: it has to spell the terms out.
# Nothing is allow-listed.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
self="$here/check_private.sh"

# Private model-card suffixes, private training repo, private organisation and
# event names, private data descriptions, any Google Cloud Storage bucket
# (gs://<anything>) or concrete Artifact Registry host (<region>-docker.pkg.dev
# as a placeholder is fine), Google Cloud project
# references and 12-digit project numbers, and secret formats (Google API keys,
# PEM blocks, OpenAI-style sk- keys, Hugging Face tokens).
pattern='_gc|300M_gc|_joint|lithos-training|intellectual[[:space:]_-]*reserve|general[[:space:]_-]*conference|(^|[^[:alnum:]])conferences?([^[:alnum:]]|$)|church|gospel|held[[:space:]_-]*out|talk[[:space:]_-]*clips?|gs://|[[:alnum:]]-docker\.pkg\.dev|\.pkg\.dev/[[:alnum:]]|projects/[a-z0-9-]{6,}|[a-z][a-z0-9-]{4,28}\.iam\.gserviceaccount\.com|(^|[^[:alnum:].])[0-9]{12}([^[:alnum:].]|$)|AIza[0-9A-Za-z_-]{20,}|-----BEGIN|(^|[^[:alnum:]])sk-[A-Za-z0-9_-]{16,}|(^|[^[:alnum:]])hf_[A-Za-z0-9]{20,}'

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
# Content of text files.
if hits=$(grep -I -n -i -E "$pattern" "${targets[@]}" 2>/dev/null); then
  echo "check_private: private terms found in file contents:" >&2
  echo "$hits" | cut -c1-240 >&2
  fail=1
fi
# Binary files (mp3, png, ...): their printable strings, which include ID3 tags,
# PNG text chunks and other embedded metadata.
nbin=0
for f in "${targets[@]}"; do
  if [ -s "$f" ] && ! grep -I -q '' "$f" 2>/dev/null; then
    nbin=$((nbin + 1))
    if bhits=$(LC_ALL=C strings -a -n 4 "$f" | grep -i -E "$pattern"); then
      echo "check_private: private terms found in binary file ${f#$root/}:" >&2
      echo "$bhits" | head -5 | cut -c1-240 >&2
      fail=1
    fi
  fi
done
# File names.
if names=$(printf '%s\n' "${targets[@]}" | sed "s|^$root/||" | grep -i -E "$pattern"); then
  echo "check_private: private terms found in file names:" >&2
  echo "$names" >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  exit 1
fi
echo "check_private: OK (${#targets[@]} files scanned, $nbin of them binary via strings; no private terms)"
