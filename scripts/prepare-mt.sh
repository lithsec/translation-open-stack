#!/usr/bin/env bash
# Build the stack's translation models ONCE, into the network volume, from pinned
# upstream releases. Afterwards the server loads them from disk and never
# contacts Hugging Face for them.
#
#   bash scripts/prepare-mt.sh            # -> /workspace/mt/{hymt2-7b-nf4,madlad7b-ct2}
#   MADLAD=3b bash scripts/prepare-mt.sh  # MADLAD 3B instead of 7B (32 GB cards), -> /workspace/madlad-ct2
#
# Which repo and revision: languages.toml [models.hymt], [models.madlad] and
# [models.madlad3b]. Each build records its source in PROVENANCE.txt
# ("<repo> @ <revision>"); when the configured one differs, the next run
# rebuilds it beside the old one and swaps it in when done (the old build keeps
# serving until then). A build with no PROVENANCE.txt (older volumes' MADLAD 3B)
# is kept as it is; delete the directory to rebuild it at the pinned revision.
#
# Needs a GPU (for 4-bit quantization) and ~45 GB of scratch on the container
# disk for the full-precision downloads (they don't fit the network volume);
# the results are ~5 GB + ~8 GB.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
CFG="$DIR/../server/stack_config.py"
DEST="${MT_DIR:-/workspace/mt}"
SCRATCH="${MT_SCRATCH:-/root/mt-build}"
# Pinned upstream revisions (languages.toml [models]): change them deliberately, never float to "main".
HYMT_REPO="$(python3 "$CFG" get models.hymt.repo)";         HYMT_REV="$(python3 "$CFG" get models.hymt.revision)"
MADLAD_REPO="$(python3 "$CFG" get models.madlad.repo)";     MADLAD_REV="$(python3 "$CFG" get models.madlad.revision)"
MADLAD3_REPO="$(python3 "$CFG" get models.madlad3b.repo)";  MADLAD3_REV="$(python3 "$CFG" get models.madlad3b.revision)"

# True when $1 holds a finished build of repo $2 at revision $3. A build without
# PROVENANCE.txt predates the stamp: keep it rather than rebuild ~40 minutes of work.
built() {
  [ -f "$1/$4" ] || return 1
  [ -f "$1/PROVENANCE.txt" ] || { echo "note: $1 has no PROVENANCE.txt; kept as it is (delete it to rebuild from $2 @ $3)"; return 0; }
  if [ "$(head -1 "$1/PROVENANCE.txt")" = "$2 @ $3" ]; then return 0; fi
  echo "== $1 was built from '$(head -1 "$1/PROVENANCE.txt")'; languages.toml asks for '$2 @ $3': rebuilding"
  return 1
}
# Swap a finished build in: the old one served until now.
install_build() { rm -rf "$2.old"; [ -e "$2" ] && mv "$2" "$2.old"; mv "$1" "$2"; rm -rf "$2.old"; }
# The snapshot of repo $1 at revision $2 (weights, configs, tokenizer): its local path.
# Values reach Python through argv, never spliced into its source.
snapshot() {
  python3 -c 'import sys; from huggingface_hub import snapshot_download as s
print(s(sys.argv[1], revision=sys.argv[2], allow_patterns=["*.json", "*.safetensors", "spiece.model"]))' "$1" "$2"
}
mkdir -p "$DEST" "$SCRATCH"
export HF_HOME="$SCRATCH/hf"
# The Docker image already has these; a bare pod needs them.
python3 -c "import bitsandbytes, accelerate, ctranslate2, sentencepiece" 2>/dev/null ||
  pip -q install --break-system-packages -c "$DIR/../constraints.txt" bitsandbytes accelerate ctranslate2 "transformers==4.57.6" sentencepiece

# MADLAD=3b (run.sh): the smaller fallback translator, for a 32 GB card. Built
# where run.sh (and older pods, via provision-runpod.sh) keep it; the 7B is then
# not needed, which saves ~33 GB of download.
M3="${MADLAD3_DIR:-/workspace/madlad-ct2}"
if [ "${MADLAD:-7b}" = 3b ] && ! built "$M3" "$MADLAD3_REPO" "$MADLAD3_REV" model.bin; then
  echo "== MADLAD-400 3B -> CTranslate2 int8"
  src=$(snapshot "$MADLAD3_REPO" "$MADLAD3_REV")
  ct2-transformers-converter --model "$src" --quantization int8 --output_dir "$M3.tmp" \
    --copy_files spiece.model tokenizer_config.json special_tokens_map.json added_tokens.json --force
  printf '%s @ %s\nApache 2.0. Converted with ct2-transformers-converter --quantization int8.\n' "$MADLAD3_REPO" "$MADLAD3_REV" \
    > "$M3.tmp/PROVENANCE.txt"
  install_build "$M3.tmp" "$M3"
fi

if [ "${MADLAD:-7b}" != 3b ] && ! built "$DEST/madlad7b-ct2" "$MADLAD_REPO" "$MADLAD_REV" model.bin; then
  echo "== MADLAD-400 7B -> CTranslate2 int8"
  src=$(snapshot "$MADLAD_REPO" "$MADLAD_REV")
  ct2-transformers-converter --model "$src" --quantization int8 --output_dir "$DEST/madlad7b-ct2.tmp" \
    --copy_files spiece.model tokenizer_config.json special_tokens_map.json added_tokens.json --force
  printf '%s @ %s\nApache 2.0. Converted with ct2-transformers-converter --quantization int8.\n' "$MADLAD_REPO" "$MADLAD_REV" \
    > "$DEST/madlad7b-ct2.tmp/PROVENANCE.txt"
  install_build "$DEST/madlad7b-ct2.tmp" "$DEST/madlad7b-ct2"
fi

if ! built "$DEST/hymt2-7b-nf4" "$HYMT_REPO" "$HYMT_REV" config.json; then
  echo "== Hy-MT2 7B -> 4-bit NF4"
  # Quoted heredoc: the values come from the environment, not spliced into the source.
  HYMT_OUT="$DEST/hymt2-7b-nf4" HYMT_REPO="$HYMT_REPO" HYMT_REV="$HYMT_REV" python3 - <<'PY'
import os, shutil, torch
from huggingface_hub import snapshot_download
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
repo, rev = os.environ["HYMT_REPO"], os.environ["HYMT_REV"]
src = snapshot_download(repo, revision=rev)
out = os.environ["HYMT_OUT"] + ".tmp"
q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                       bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
AutoModelForCausalLM.from_pretrained(src, quantization_config=q, device_map="cuda").save_pretrained(out)
AutoTokenizer.from_pretrained(src).save_pretrained(out)
shutil.copy(os.path.join(src, "LICENSE.txt"), out)
open(os.path.join(out, "PROVENANCE.txt"), "w").write(
    f"{repo} @ {rev}\nApache 2.0 (LICENSE.txt). Modified: quantized to 4-bit NF4 with bitsandbytes.\n")
PY
  install_build "$DEST/hymt2-7b-nf4.tmp" "$DEST/hymt2-7b-nf4"
fi
du -sh "$DEST"/*
# The full-precision downloads (~45 GB) are only needed to build the two above.
rm -rf "$SCRATCH"
echo "Done."
