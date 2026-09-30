#!/usr/bin/env bash
# The GPL-3.0 duties of a PUBLISHED image, met inside the image itself: the
# licence text plus the corresponding source of every GPL program it ships,
# under /opt/stack/licences/ (docs/licences.md, section 8). Run by the
# Dockerfile after the packages are installed, so the versions are the ones in
# the image. A few tens of MB; a failed download fails the build rather than
# publishing an image without its source.
#
#   espeak-ng        the Ubuntu package (apt): its Ubuntu source package
#   piper-tts        its PyPI sdist (it also carries the espeak-ng it builds against)
#   phonemizer-fork  its PyPI sdist
set -euo pipefail
OUT="${1:-/opt/stack/licences}"
mkdir -p "$OUT/source"
cd "$OUT/source"

# espeak-ng: the exact Ubuntu version installed, via a deb-src entry added for this only.
ver=$(dpkg-query -W -f '${Version}' espeak-ng)
src=/etc/apt/sources.list.d/ubuntu.sources
cp "$src" /tmp/ubuntu.sources.bak
sed -i 's/^Types: deb$/Types: deb deb-src/' "$src"
apt-get update -qq
apt-get source --download-only "espeak-ng=$ver"
mv /tmp/ubuntu.sources.bak "$src"
rm -rf /var/lib/apt/lists/*

# The PyPI packages: the sdist of the version pip installed, checked against PyPI's sha256.
for pkg in piper-tts phonemizer-fork; do
  pv=$(python3 -c "import importlib.metadata as m; print(m.version('$pkg'))")
  python3 - "$pkg" "$pv" <<'PY'
import hashlib, json, sys, urllib.request
pkg, ver = sys.argv[1:]
info = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/{ver}/json", timeout=60))
sd = [u for u in info["urls"] if u["packagetype"] == "sdist"]
if not sd:
    sys.exit(f"{pkg} {ver}: no sdist on PyPI")
u = sd[0]
data = urllib.request.urlopen(u["url"], timeout=300).read()
if hashlib.sha256(data).hexdigest() != u["digests"]["sha256"]:
    sys.exit(f"{u['filename']}: sha256 mismatch")
open(u["filename"], "wb").write(data)
print("source:", u["filename"])
PY
done

cp /usr/share/common-licenses/GPL-3 "$OUT/GPL-3.0.txt"
cat > "$OUT/README.txt" <<EOF
Translation Open Stack image: third-party licences and GPL source.

The stack itself is Apache-2.0 (/opt/stack/LICENSE, /opt/stack/NOTICE).
Every licence, of models and libraries alike: /opt/stack/docs/licences.md,
or https://github.com/lithsec/translation-open-stack/blob/main/docs/licences.md

This image contains these GPL-3.0 programs. Their licence is GPL-3.0.txt here;
their complete corresponding source, for the versions in this image, is in
source/:

  espeak-ng        $ver (Ubuntu package)      source/espeak-ng_*
  piper-tts        $(python3 -c "import importlib.metadata as m; print(m.version('piper-tts'))")                     source/piper_tts-*.tar.gz
  phonemizer-fork  $(python3 -c "import importlib.metadata as m; print(m.version('phonemizer-fork'))")                     source/phonemizer_fork-*.tar.gz

The base image's Ubuntu packages come with their own copyright files under
/usr/share/doc/<package>/copyright; their source is at https://launchpad.net/ubuntu.
The model weights are NOT in this image: they are downloaded from their
publishers on first start, under each model's own licence.
EOF
ls -l "$OUT" "$OUT/source"
