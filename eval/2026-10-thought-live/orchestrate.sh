#!/usr/bin/env bash
# The round on the pod; each run leaves work/PHASE_<name>.done. boot.sh stops the pod afterwards.
#   nohup bash orchestrate.sh > /workspace/logs/orch.log 2>&1 &
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; W="$HERE/work"
done_() { touch "$W/PHASE_$1.done"; echo "== $(date -u +%T) phase $1 done"; }
until grep -q SETUP_VLLM_DONE /workspace/logs/setup_vllm.log 2>/dev/null; do sleep 20; done
if ! curl -s -m 3 127.0.0.1:8101/v1/models | grep -q gemma; then
  cd /workspace && PATH=/root/vllm/bin:$PATH VLLM_USE_FLASHINFER_SAMPLER=0 HF_HOME=/workspace/hf-cache HF_HUB_OFFLINE=1 \
    setsid nohup /root/vllm/bin/vllm serve google/gemma-4-31B-it-qat-w4a16-ct --port 8101 --host 127.0.0.1 \
    --gpu-memory-utilization 0.40 --max-model-len 8192 --enable-prefix-caching > /workspace/logs/gemma.log 2>&1 < /dev/null &
fi
until curl -s -m 3 127.0.0.1:8101/v1/models | grep -q gemma; do grep -q "Engine core initialization failed" /workspace/logs/gemma.log && { echo GEMMA_FAILED; exit 1; }; sleep 20; done
done_ gemma
until grep -q SETUP_STACK_DONE /workspace/logs/setup_stack.log 2>/dev/null; do sleep 20; done
python3 -I "$HERE/make_configs.py" /workspace/tos/languages.toml "$HERE/configs"
done_ stack
cd "$HERE"
run() {  # run <name> <config> <clips> <query> <directions...>
  local name=$1 cfg=$2 clips=$3 q=$4; shift 4
  [ -f "$W/PHASE_$name.done" ] || { Q="$q" bash live.sh "$cfg" "$W/drr/$clips" "$name" en,de "$@" && done_ "$name"; }
}
for CL in a_reg a_irr b_reg; do
  run "U5_$CL" G5 "clips_$CL" "" en-de de-en                          # utterance mode, German long turns cut at 12 s
  run "U1_$CL" G1 "clips_$CL" "" de-en                                # utterance mode, default turns
  run "A_$CL" G5 "clips_$CL" "&stream=1&policy=agree" en-de           # agree (not offered for de->en)
  run "T_$CL" G5 "clips_$CL" "&stream=1&policy=thought" en-de de-en   # complete thought
done
echo ALL_DONE
