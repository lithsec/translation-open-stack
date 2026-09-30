#!/usr/bin/env bash
# Bring the whole stack up on a RunPod pod, unattended, from the network volume.
# Use it as the pod's start command so a fresh or restarted pod serves by itself:
#
#   bash -c 'bash /workspace/translation-open-stack/scripts/runpod/runpod-start.sh > /workspace/stack.log 2>&1 & exec /start.sh'
#
# Pod: 48 GB GPU (32 GB with MADLAD=3b or fewer languages), 80 GB container
# disk, network volume at /workspace, ports 22/tcp and 8790/http. Clients connect
# through RunPod's HTTPS proxy, with the token in an Authorization header:
#
#   wss://<pod-id>-8790.proxy.runpod.net      Authorization: Bearer <token>
#
# Setup, step by step: docs/user-guide.md, "Run on your own RunPod pod". The
# volume folder is /workspace/translation-open-stack by convention (a clone of this repository);
# the Lithos launcher's pods use that path.
#
# The stack has no accounts, so a credential is what keeps strangers off a public
# URL: STACK_SIGNING_KEY (the Lithos server issues short-lived tokens signed with
# it; server/stack_auth.py) and/or a static STACK_TOKEN — pod environment variables, else
# /workspace/.stack-signing-key and /workspace/.stack-token. Without either this
# script refuses to start. The container disk is wiped on every stop, so on the
# stock PyTorch image the Python packages are reinstalled each boot (~3 min);
# the stack's own image (Dockerfile) has them baked in and skips that. Models
# stay on the volume either way.
set -euo pipefail
# RunPod's PyTorch image sets HF_HUB_ENABLE_HF_TRANSFER=1 without the hf_transfer package,
# and then EVERY Hugging Face download fails ("hf_transfer ... not available"). That quietly
# disabled language ID on launcher-started pods: every source was served as English (2026-09-29).
python3 -c "import hf_transfer" 2>/dev/null || export HF_HUB_ENABLE_HF_TRANSFER=0
DIR="$(cd "$(dirname "$0")" && pwd)"          # scripts/runpod
SCRIPTS="$(cd "$DIR/.." && pwd)"               # scripts
ROOT="$(cd "$DIR/../.." && pwd)"               # the repository (/workspace/translation-open-stack)
STACK_SIGNING_KEY="${STACK_SIGNING_KEY:-$(cat /workspace/.stack-signing-key 2>/dev/null || true)}"
STACK_TOKEN="${STACK_TOKEN:-$(cat /workspace/.stack-token 2>/dev/null || true)}"
# No credential at all: make a random token once, keep it on the volume, and
# print it here (the pod's log, which only its owner sees). The RunPod template
# relies on this so a deploy needs no setup; the stack is never open.
if [ -z "$STACK_SIGNING_KEY" ] && [ -z "$STACK_TOKEN" ]; then
  if [ -n "${RUNPOD_POD_ID:-}" ] && [ -d /workspace ]; then
    STACK_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    (umask 077; printf '%s\n' "$STACK_TOKEN" > /workspace/.stack-token)
    echo "== no STACK_TOKEN set: made one, saved in /workspace/.stack-token (it's reused on every start)"
    MADE_TOKEN=1
  else
    echo "no STACK_SIGNING_KEY or STACK_TOKEN — refusing: the stack is reachable from the internet on RunPod" >&2
    exit 1
  fi
fi
if [ -n "${RUNPOD_POD_ID:-}" ]; then
  echo "== connect: wss://${RUNPOD_POD_ID}-8790.proxy.runpod.net"
  # Printed only the time it's made; later: cat /workspace/.stack-token in the pod's terminal.
  [ "${MADE_TOKEN:-0}" = 1 ] && echo "== access key: $STACK_TOKEN"
fi
export STACK_SIGNING_KEY STACK_TOKEN HF_HOME=/workspace/hf-cache
LANGS="${LANGS:-en,es,fr,pt,de,ru,uk,zh,ja,km,lo,ht,ar,hi,vi,ko,tl,fa,id,tr,bn,ur,it,sw,ro}"
SRCS="${SRCS:-en,es,fr,pt,de,ru,uk,it,zh,ja,ko,sw,km,lo,ht,ar,hi,vi,tl,fa,id,tr,bn,ur,ro}"
echo "== $(date -u) provisioning"
python3 -c "import faster_whisper, kokoro, piper" 2>/dev/null || bash "$DIR/provision-runpod.sh" "$LANGS"
# The idle stop runs whether or not the provisioner did (a prebuilt image skips it).
if ! pgrep -f "idle-stop[.]sh" >/dev/null; then nohup bash "$SCRIPTS/idle-stop.sh" >/workspace/idle-stop.log 2>&1 & fi
# Piper voices for LANGS; files already on the volume are kept.
VOICES_DIR=/workspace/voices bash "$SCRIPTS/fetch-voices.sh" "$LANGS"
bash "$SCRIPTS/prepare-mt.sh"
bash "$SCRIPTS/prepare-voices.sh"
# Report to the Lithos server once the models are loaded (or that the stack died
# first), so whoever asked for it gets a push. Only when STACK_REPORT_URL names
# where (the Lithos launcher sets it on the pods it creates; a pod created before
# that can use /workspace/.stack-report-url); unset or empty: no report, and
# nothing leaves the pod. Signed with the stack's own key, audience "report", so
# the stack itself refuses the token as a connection credential.
STACK_REPORT_URL="${STACK_REPORT_URL-$(cat /workspace/.stack-report-url 2>/dev/null || true)}"
report() {
  [ -n "$STACK_SIGNING_KEY" ] && [ -n "$STACK_REPORT_URL" ] || return 0
  tok=$(cd "$ROOT/server" && python3 -c "import os, stack_auth; print(stack_auth.sign(os.environ['STACK_SIGNING_KEY'], 'pod:' + os.environ.get('RUNPOD_POD_ID', '?'), 300, aud=stack_auth.AUD_REPORT))")
  curl -s -m 20 -X POST "$STACK_REPORT_URL" -H "Authorization: Bearer $tok" \
    -H "content-type: application/json" -d "{\"ok\": $1, \"detail\": \"$2\"}" >/dev/null || true
}
(
  for _ in $(seq 1 180); do   # up to 30 minutes
    sleep 10
    if curl -sf -m 5 http://127.0.0.1:8790/health >/dev/null; then report true ""; exit 0; fi
    if ! pgrep -f "$SCRIPTS/run[.]sh|$ROOT/server/server[.]py" >/dev/null; then report false "The stack stopped while starting."; exit 0; fi
  done
  report false "The stack didn't load within 30 minutes."
) &

echo "== $(date -u) starting stack (edition ${EDITION:-nonprofit})"
exec bash "$SCRIPTS/run.sh" "$LANGS" "$SRCS"
