#!/usr/bin/env bash
# Pod setup for this round (from ../2026-10-de-ru-ro) (RunPod, stack image 2026.10.09.2, the voices volume at /models): sox, node + ws
# for the client, the repo with its models (install-deps, prepare-mt), and Gemma 4 in its own vLLM venv.
# The three parts run in parallel; orchestrate.sh waits on their DONE lines in /workspace/logs.
set -uo pipefail
mkdir -p /workspace/logs /workspace/al
export HF_HUB_ENABLE_HF_TRANSFER=0
( apt-get update -qq && apt-get install -y -qq sox ffmpeg >/dev/null
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1 && apt-get install -y -qq nodejs >/dev/null
  mkdir -p /workspace/al/node && cd /workspace/al/node && npm init -y >/dev/null && npm i -q ws >/dev/null 2>&1
  echo APT_DONE ) > /workspace/logs/apt.log 2>&1 &
( set -e; cd /workspace
  git clone -q https://github.com/lithsec/translation-open-stack.git tos
  cd tos && git checkout -q "${BRANCH:-main}" && git log --oneline -1
  if [ -d /models/voices ]; then cp -r /models/voices /workspace/voices; fi   # the voices volume, when mounted
  bash scripts/fetch-voices.sh en,de,es,fr
  bash scripts/install-deps.sh
  bash scripts/prepare-mt.sh
  echo SETUP_STACK_DONE ) > /workspace/logs/setup_stack.log 2>&1 &
( set -e; export HF_HOME=/workspace/hf-cache
  python3 -m venv /root/vllm
  /root/vllm/bin/pip install -q "vllm==0.31.0" ninja
  /root/vllm/bin/hf download google/gemma-4-31B-it-qat-w4a16-ct >/dev/null
  echo SETUP_VLLM_DONE ) > /workspace/logs/setup_vllm.log 2>&1 &
wait
