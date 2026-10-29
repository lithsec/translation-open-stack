#!/usr/bin/env bash
# The whole de/ru/ro round on the pod, phase by phase; each phase leaves work/PHASE_<name>.done.
#   nohup bash orchestrate.sh > /workspace/logs/orch.log 2>&1 &
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; W="$HERE/work"
done_() { touch "$W/PHASE_$1.done"; echo "== $(date -u +%T) phase $1 done"; }
until grep -q SETUP_VLLM_DONE /workspace/logs/setup_vllm.log 2>/dev/null; do sleep 20; done
if ! curl -s -m 3 127.0.0.1:8101/v1/models | grep -q gemma; then
  cd /workspace && PATH=/root/vllm/bin:$PATH VLLM_USE_FLASHINFER_SAMPLER=0 HF_HOME=/workspace/hf-cache HF_HUB_OFFLINE=1 \
    setsid nohup /root/vllm/bin/vllm serve google/gemma-4-31B-it-qat-w4a16-ct --port 8101 --host 127.0.0.1 \
    --gpu-memory-utilization 0.40 --max-model-len 8192 > /workspace/logs/gemma.log 2>&1 < /dev/null &
fi
until curl -s -m 3 127.0.0.1:8101/v1/models | grep -q gemma; do grep -q "Engine core initialization failed" /workspace/logs/gemma.log && { echo GEMMA_FAILED; exit 1; }; sleep 20; done
done_ gemma
until grep -q SETUP_STACK_DONE /workspace/logs/setup_stack.log 2>/dev/null; do sleep 20; done
done_ stack
cd "$HERE"
for s in hymt madlad gemma; do
  [ -s "$W/mt/$s.json" ] || STACK=/workspace/tos HF_HUB_OFFLINE=1 python3 mt.py "$W" $s || echo "MT FAIL $s"
done
done_ mt
D6="en-de de-en en-ru ru-en en-ro ro-en"
for C in C1 C2; do for ST in a b; do bash live.sh $C $ST reg $D6; done; done
done_ live_main
bash live.sh C1 a irr de-en en-de
bash live.sh C3 a reg de-en
bash live.sh C3 a irr de-en
done_ live_german
echo ALL_DONE
