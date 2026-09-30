#!/usr/bin/env bash
# Provision the stack on a RunPod pod — same pipeline, no quota gate.
#
#   Pod      : RTX 4090 (24 GB) — community ~$0.34/hr, secure ~$0.59/hr
#   Template : "RunPod PyTorch" (any recent CUDA build)
#   Disk     : 60 GB volume
#   Ports    : expose HTTP 8790 (Edit Pod -> HTTP ports), NOT a TCP port: clients
#              connect through RunPod's HTTPS proxy, wss://<pod-id>-8790.proxy.runpod.net,
#              so the Bearer token only ever travels over TLS. A raw TCP port
#              would carry it in clear text.
#
# Usage, in the pod's web terminal or via ssh:
#   bash scripts/runpod/provision-runpod.sh es,fr,pt
#
# COST GUARD: prepaid credits are the real guard here — a pod cannot spend
# money you have not loaded. The idle stop below (scripts/idle-stop.sh) is a
# courtesy on top: it stops the pod through RunPod's API. Storage may bill
# separately while the pod exists; delete the pod when the experiment ends.
set -euo pipefail
LANGS="${1:-es,fr,pt}"

DIR="$(cd "$(dirname "$0")" && pwd)"          # scripts/runpod
SCRIPTS="$(cd "$DIR/.." && pwd)"               # scripts
ROOT="$(cd "$DIR/../.." && pwd)"               # the repository

# Python packages: scripts/install-deps.sh (shared with the Dockerfile, so a pod and the
# image are built from the same pins in the same order).
bash "$SCRIPTS/install-deps.sh"

# ---- MADLAD through CTranslate2 ----------------------------------------------
# MT was 60-75% of this pipeline's latency; CT2 int8 is what took it off the
# critical path. Converting is a one-off, and the output lands on /workspace so
# a network volume keeps it — the check below makes re-provisioning free.
#
# The server's own transformers (4.57.6) now satisfies the converter, so this
# no longer needs a throwaway venv — that dance existed only because the pin
# was stuck at 4.46.3, which rejects the converter's dtype= argument.
CFG="$ROOT/server/stack_config.py"   # languages.toml [models]: repos and pinned revisions
if [ ! -f /workspace/madlad-ct2/model.bin ]; then
  echo "converting MADLAD to CTranslate2 int8 (one-off, ~10 min)…"
  M3_REPO="$(python3 "$CFG" get models.madlad3b.repo)"; M3_REV="$(python3 "$CFG" get models.madlad3b.revision)"
  # Values reach Python through argv, never spliced into its source.
  { src=$(HF_HOME=/workspace/hf-cache python3 -c 'import sys; from huggingface_hub import snapshot_download as s
print(s(sys.argv[1], revision=sys.argv[2], allow_patterns=["*.json", "*.safetensors", "spiece.model"]))' "$M3_REPO" "$M3_REV") &&
    HF_HOME=/workspace/hf-cache ct2-transformers-converter \
      --model "$src" \
      --output_dir /workspace/madlad-ct2 --quantization int8 --force &&
    printf '%s @ %s\nApache 2.0. Converted with ct2-transformers-converter --quantization int8.\n' "$M3_REPO" "$M3_REV" \
      > /workspace/madlad-ct2/PROVENANCE.txt; } \
    || echo "WARNING: CT2 conversion failed — start without --mt-ct2 (slower MT)"
else
  echo "CTranslate2 MADLAD already present ($(du -sh /workspace/madlad-ct2 | cut -f1))"
fi

# ---- warm cache on the network volume ----------------------------------------
# Hugging Face defaults to /root/.cache/huggingface, which is the CONTAINER
# disk and dies with the pod — 16GB re-downloaded on every launch, ~15 minutes
# before the first word can be translated. /workspace is where a network
# volume mounts, so point the cache there: attach a network volume at pod
# creation and the second launch onward skips the download.
# Without a volume attached this is simply a directory, and nothing breaks.
export HF_HOME=/workspace/hf-cache
mkdir -p "$HF_HOME"
if ! grep -q "HF_HOME" /root/.bashrc 2>/dev/null; then
  echo 'export HF_HOME=/workspace/hf-cache' >> /root/.bashrc
fi
echo "HF cache: $HF_HOME ($(du -sh "$HF_HOME" 2>/dev/null | cut -f1) present)"

# ---- Piper voices ------------------------------------------------------------
# The voice each language uses is in languages.toml; fetch-voices.sh skips files
# already on the volume.
VOICES_DIR=/workspace/voices bash "$SCRIPTS/fetch-voices.sh" "$LANGS"
cd /workspace

# ---- warm the model caches ---------------------------------------------------
# The recogniser run.sh starts: languages.toml [models.whisper], at its pinned revision.
WHISPER="$(python3 "$CFG" get models.whisper.model)" WHISPER_REV="$(python3 "$CFG" get models.whisper.revision)" \
python3 - <<'EOF'
import os
from faster_whisper import WhisperModel
WhisperModel(os.environ["WHISPER"], device="cuda", compute_type="float16", revision=os.environ["WHISPER_REV"] or None)
# Translation models are NOT fetched here: prepare-mt.sh builds them (with their
# tokenizers) into /workspace/mt. Warming MADLAD 3B's full weights used to put
# 11 GB on a 50 GB volume for nothing.
print("models cached")
EOF

# ---- idle stop: idle-stop.sh (runpod-start.sh starts it too, for images that
# skip this provisioner). One copy only.
if ! pgrep -f "idle-stop[.]sh" >/dev/null; then nohup bash "$SCRIPTS/idle-stop.sh" >/workspace/idle-stop.log 2>&1 & fi

echo
echo "Provisioned. Run the server:"
# --voices-dir is not optional here: the server looks in the repository's
# voices/ by default, and this script puts the voices in /workspace/voices. Leaving it
# off starts a server that loads, says "ready", and is silently text-only.
echo "  python3 $ROOT/server/server.py --langs $LANGS \\"
echo "    --voices-dir /workspace/voices"
echo
echo "Reach it through RunPod's HTTPS proxy (port 8790 exposed as HTTP), with the token:"
echo "  wss://<pod-id>-8790.proxy.runpod.net    Authorization: Bearer <token>"
echo "Never expose 8790 as a TCP port: that path has no TLS and would carry the token in clear."
echo
echo "Prepaid credits cap the worst case; the idle stop is a courtesy on top."
echo "Delete the pod (not just stop) when the experiment ends — storage bills."
