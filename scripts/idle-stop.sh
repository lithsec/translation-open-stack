#!/usr/bin/env bash
# Stop the pod when nobody uses the stack: no client on :8790 for STACK_IDLE_MIN
# (15) minutes, counted from "ready" (GET /health), not from boot. Also a hard
# ceiling, STACK_MAX_UPTIME_H (8): a credential that keeps a connection open
# cannot keep a pod running (and billing) indefinitely.
#
# Stopping: through RunPod's API with the pod's own scoped key (runpodctl and
# RUNPOD_POD_ID / RUNPOD_API_KEY are in every pod's environment). Killing PID 1
# is NOT a stop: RunPod restarts the container on the same GPU and keeps
# billing (found 2026-09-29: a pod "stopped" every 15 min and billed for hours).
# PID 1 is killed only as a fallback, if the API call fails. For RunPod pods
# only — runpod/runpod-start.sh starts it on every boot. Don't run it in a Docker
# container you want to keep up.
#
# (Until 2026-09 provision-runpod.sh wrote this to /workspace/idle-stop.sh; it
# lives here now so a prebuilt image, which skips the provisioner, still stops.)
S=/tmp/stack-idle-since
stop_pod() {
  echo "$(date -u +%FT%TZ) $1 — stopping the pod"
  if [ -n "${RUNPOD_POD_ID:-}" ] && command -v runpodctl >/dev/null \
     && runpodctl stop pod "$RUNPOD_POD_ID"; then
    sleep 300   # the stop takes the container down; if it's still here, fall through
    echo "$(date -u +%FT%TZ) still running 5 min after the API stop"
  fi
  kill 1
}
MAX_S=$(( ${STACK_MAX_UPTIME_H:-8} * 3600 ))
BOOT=$(date +%s)   # this starts at pod boot; /proc/uptime would be the HOST's uptime
while sleep 60; do
  if [ $(( $(date +%s) - BOOT )) -gt "$MAX_S" ]; then
    stop_pod "pod up ${STACK_MAX_UPTIME_H:-8}h, regardless of use"
  fi
  # Still loading: not idle. The 15 minutes count from "ready", not from boot.
  curl -sf -m 5 http://127.0.0.1:8790/health >/dev/null 2>&1 || { rm -f "$S"; continue; }
  # -H: no header line. Without it the header alone matched "any output", so the
  # pod never looked idle and never stopped (found 2026-09-28: an idle pod kept billing).
  if ss -Htn state established '( sport = :8790 )' 2>/dev/null | grep -q . ; then rm -f "$S"; continue; fi
  [ -f "$S" ] || { date +%s > "$S"; continue; }
  if [ $(( $(date +%s) - $(cat "$S") )) -gt $(( ${STACK_IDLE_MIN:-15} * 60 )) ]; then
    stop_pod "stack idle ${STACK_IDLE_MIN:-15}m"
  fi
done
