#!/usr/bin/env bash
# Phase 2, after the commercial runs (live.sh ... C): swap Gemma 4 for MiLMMT-46 12B on the same card
# (stop Gemma's vLLM, start MiLMMT on :8102 with ../../scripts/start-llmmt.sh), then the nonprofit edition
# for en->lo and lo->en on both clip sets.
#   bash lao_nonprofit.sh      -> W/e2e_N_{a,b}/out/runs/{lo-en,en-lo}.json
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; W=/workspace/work; ROOT=/workspace/tos-commercial
until grep -q "done C\|died" "$W/live_C.log"; do sleep 10; done
grep -q "died" "$W/live_C.log" && { echo "commercial phase died; not starting"; exit 1; }
# Gemma's vLLM: by PID (pkill -f would match this shell's own command line)
for p in $(pgrep -f "vllm serve google/gemma-4"); do kill "$p"; done
for i in $(seq 1 60); do pgrep -f "vllm serve google/gemma-4" >/dev/null || break; sleep 2; done
sleep 5; nvidia-smi --query-gpu=memory.used --format=csv,noheader
. /workspace/env.sh
( cd "$ROOT" && EDITION=nonprofit LLMMT=milmmt GEMMA_GB=39 LLMMT_LOG=/workspace/llmmt.log bash scripts/start-llmmt.sh )
for i in $(seq 1 180); do curl -sf -m 5 127.0.0.1:8102/v1/models >/dev/null && break; sleep 5; done
echo "$(date -u +%T) MiLMMT answering after ~$((i*5)) s"
bash "$HERE/live.sh" nonprofit N a:$W/seta/clips_reg:lo-en,en-lo b:$W/setb/clips_reg:lo-en,en-lo
