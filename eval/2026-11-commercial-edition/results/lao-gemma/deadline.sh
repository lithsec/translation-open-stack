#!/usr/bin/env bash
# On-pod hard stop: at DEADLINE (epoch s) stop this pod with runpodctl, credentials from PID 1's environment.
DEADLINE="$1"
eval "$(tr '\0' '\n' < /proc/1/environ | grep -E '^(RUNPOD_POD_ID|RUNPOD_API_KEY)=' | sed 's/^/export /')"
while [ "$(date +%s)" -lt "$DEADLINE" ]; do sleep 20; done
echo "$(date -u +%T) deadline: stopping $RUNPOD_POD_ID"
runpodctl pod stop "$RUNPOD_POD_ID" || runpodctl stop pod "$RUNPOD_POD_ID"
