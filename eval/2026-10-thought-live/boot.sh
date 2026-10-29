#!/usr/bin/env bash
# Everything on the pod, detached, and the pod stops itself at the end: STOP_GRACE_MIN minutes after the round
# ends (for the results to be copied off), or at DEADLINE_H hours whatever happens.
#   curl -fsSL <raw url of this file> | BRANCH=<branch> bash    (as root on the pod, over SSH)
set -uo pipefail
BRANCH=${BRANCH:-main} STOP_GRACE_MIN=${STOP_GRACE_MIN:-45} DEADLINE_H=${DEADLINE_H:-5}
mkdir -p /workspace/logs /workspace/tl
# The pod's own id and API key reach PID 1 only, not an SSH shell.
eval "$(tr '\0' '\n' < /proc/1/environ | grep -E '^RUNPOD_(POD_ID|API_KEY)=' | sed 's/^/export /')"
stop_pod() {
  echo "$(date -u +%T) stopping pod ${RUNPOD_POD_ID:-?}"
  if command -v runpodctl >/dev/null; then runpodctl pod stop "$RUNPOD_POD_ID" || runpodctl stop pod "$RUNPOD_POD_ID"
  else curl -s -X POST "https://rest.runpod.io/v2/pods/$RUNPOD_POD_ID/action" -H "Authorization: Bearer $RUNPOD_API_KEY" \
         -H "content-type: application/json" -d '{"action":"stop"}'; fi
}
( sleep $((DEADLINE_H * 3600)); echo DEADLINE; stop_pod ) > /workspace/logs/deadline.log 2>&1 &
cd /workspace
curl -fsSL "https://raw.githubusercontent.com/lithsec/translation-open-stack/$BRANCH/eval/2026-10-thought-live/setup_pod.sh" -o setup_pod.sh
BRANCH=$BRANCH bash setup_pod.sh
echo SETUP_RETURNED
if grep -q SETUP_STACK_DONE /workspace/logs/setup_stack.log; then
  cp -r /workspace/tos/eval/2026-10-thought-live/. /workspace/tl/
  if bash /workspace/tl/clips.sh > /workspace/logs/clips.log 2>&1; then
    bash /workspace/tl/orchestrate.sh > /workspace/logs/orch.log 2>&1
  else echo CLIPS_FAILED; fi
else echo SETUP_FAILED; fi
echo "BOOT_DONE $(date -u +%T)"
sleep $((STOP_GRACE_MIN * 60))
stop_pod
