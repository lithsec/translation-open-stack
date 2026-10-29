#!/usr/bin/env bash
# The round on the pod, phase by phase; each phase leaves work/PHASE_<name>.done.
#   nohup bash orchestrate.sh > /workspace/logs/orch.log 2>&1 &
# Expects: setup_pod.sh's three parts, the German clips in work/clips_a_{reg,irr} (build_clips.py of
# ../2026-10-de-ru-ro) and the unseen en/es/fr clips in work/unseen/clips_{reg,irr}.
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
# German turns: de->en, set a, both pause patterns, four turn settings
for C in G1 G3 G4 G5; do for P in reg irr; do
  [ -f "$W/PHASE_de_${C}_$P.done" ] || { bash live.sh $C "$W/clips_a_$P" "de_${C}_$P" en,de de-en && done_ "de_${C}_$P"; }
done; done
# Simultaneous mode on the stack: utterance mode, the clause rule and agree, en<->es and en<->fr
D4="en-es es-en en-fr fr-en"
for P in reg irr; do
  [ -f "$W/PHASE_st_U_$P.done" ] || { Q="" bash live.sh S "$W/unseen/clips_$P" "st_U_$P" en,es,fr $D4 && done_ "st_U_$P"; }
  [ -f "$W/PHASE_st_C_$P.done" ] || { Q="&stream=1&policy=clause" bash live.sh S "$W/unseen/clips_$P" "st_C_$P" en,es,fr $D4 && done_ "st_C_$P"; }
  [ -f "$W/PHASE_st_A_$P.done" ] || { Q="&stream=1&policy=agree" bash live.sh S "$W/unseen/clips_$P" "st_A_$P" en,es,fr $D4 && done_ "st_A_$P"; }
done
echo ALL_DONE
