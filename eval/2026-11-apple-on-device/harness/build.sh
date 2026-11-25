#!/usr/bin/env bash
# Builds applehear. FastPhrases.swift (the Talk app's phrase and boundary cutters, pure Swift) is compiled in from the
# app's checkout, not copied here: FASTPHRASES=<path to FastPhrases.swift> bash build.sh [out]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${FASTPHRASES:?set FASTPHRASES to the path of FastPhrases.swift}"
swiftc -O -parse-as-library -swift-version 5 "$here/Main.swift" "$here/Hear.swift" "$here/Cut.swift" "$FASTPHRASES" -o "${1:-$here/applehear}"
