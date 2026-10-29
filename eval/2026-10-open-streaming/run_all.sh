#!/bin/bash
# The recognition passes, one after another, holding the pod's real-time lock
# (/workspace/REALTIME_LOCK.d, shared with the live-stack runs on the CPU-capped pod),
# started only once no MADLAD conversion is running and the load is low.
#   bash run_all.sh   (on the pod)
W=/workspace/stream
log() { echo "$(date +%T) $*"; }
while pgrep -f ct2-transformers-converte[r] >/dev/null; do sleep 30; done
until mkdir /workspace/REALTIME_LOCK.d 2>/dev/null; do log "lock held by $(cat /workspace/REALTIME_LOCK.d/owner 2>/dev/null)"; sleep 120; done
echo stream > /workspace/REALTIME_LOCK.d/owner
trap 'rm -rf /workspace/REALTIME_LOCK.d' EXIT
log "lock taken; load $(cut -d' ' -f1-3 /proc/loadavg)"
log nemo; bash $W/run_nemo.sh > $W/logs/nemo.log 2>&1
log simul
cd $W && OMP_NUM_THREADS=8 /root/venv-simul/bin/python simul_run.py $W/SimulStreaming $W/clips $W/rec_raw \
  --vac --min-chunk-size 0.5 --model_path $W/models/large-v3.pt -l WARNING > $W/logs/simul_run.log 2>&1
for p in reg irr; do for l in en es fr; do
  /root/venv-simul/bin/python -I $W/simul_to_partials.py $W/rec_raw/simul_${p}_$l.jsonl $W/work/rec/simul_${p}_$l.json
done; done
log ctc; bash $W/run_ctc.sh > $W/logs/run_ctc.log 2>&1
log "ctc bench"
cd $W && PYTHONPATH=$W/omni-stt FAIRSEQ2_CACHE_DIR=$W/fairseq2 HF_HOME=$W/hf /root/venv-omni/bin/python bench_ctc.py $W/clips/clips_reg --out $W/work/ctc_bench.json > $W/logs/ctc_bench.log 2>&1
log "done; load $(cut -d' ' -f1-3 /proc/loadavg)"
