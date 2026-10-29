#!/bin/bash
# run_ctc.sh and the CTC bench under the pod's real-time lock (see run_all.sh).
W=/workspace/stream
log() { echo "$(date +%T) $*"; }
until mkdir /workspace/REALTIME_LOCK.d 2>/dev/null; do log "lock held by $(cat /workspace/REALTIME_LOCK.d/owner 2>/dev/null)"; sleep 120; done
echo stream > /workspace/REALTIME_LOCK.d/owner
trap 'rm -rf /workspace/REALTIME_LOCK.d' EXIT
log "lock taken; load $(cut -d' ' -f1-3 /proc/loadavg)"
bash $W/run_ctc.sh > $W/logs/run_ctc.log 2>&1
log "ctc bench"
cd $W && PYTHONPATH=$W/omni-stt FAIRSEQ2_CACHE_DIR=$W/fairseq2 HF_HOME=$W/hf /root/venv-omni/bin/python bench_ctc.py $W/clips/clips_reg --out $W/work/ctc_bench.json > $W/logs/ctc_bench.log 2>&1
log "done; load $(cut -d' ' -f1-3 /proc/loadavg)"
