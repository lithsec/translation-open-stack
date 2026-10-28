#!/usr/bin/env bash
# Every service run of the README, one server at a time on the pod's L4
# (pod_setup.sh first; clips from prep_clips.py). Servers are open (STT_OPEN=1,
# localhost only) and EDITION=nonprofit, so both voices load.
#
#   bash run_all.sh OUTDIR
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-/opt/runs}"; mkdir -p "$OUT"
SVC="$HERE/../../services/omni-stt"
export STT_MODELS=/opt/models HF_HOME=/opt/models/hf TORCH_HOME=/opt/models/torch \
  FAIRSEQ2_CACHE_DIR=/opt/models/fairseq2 FAIRSEQ2_USER_ASSET_DIR=/opt/models/cards \
  HF_HUB_OFFLINE=1 STT_OPEN=1 EDITION=nonprofit PORT=8080
PY=/opt/venv/bin/python
CLIPS=/opt/clips

start() {  # name, env... : start the server, wait for the voices (or the port)
  local name="$1"; shift
  ( cd "$SVC" && env "$@" $PY server.py > "$OUT/$name.server.log" 2>&1 ) &
  SERVER=$!
  local want="ready on"; case " $* " in *speak*) want="voices ready" ;; esac
  for i in $(seq 1 300); do
    grep -q "$want" "$OUT/$name.server.log" 2>/dev/null && break
    kill -0 $SERVER 2>/dev/null || { echo "$name: server died"; tail -20 "$OUT/$name.server.log"; return 1; }
    sleep 1
  done
  sleep 3
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits > "$OUT/$name.idle_mib"
  local pid; pid=$(pgrep -f "python server.py" | head -1)
  ps -o rss= -p "$pid" > "$OUT/$name.idle_rss_kb"
  echo "$name: idle $(cat "$OUT/$name.idle_mib") MiB GPU, $(( $(cat "$OUT/$name.idle_rss_kb") / 1024 )) MiB RSS; $(grep -E 'ready on|voices ready' "$OUT/$name.server.log" | tr '\n' ' ')"
}
stop() {
  pkill -f "python server.py"; wait 2>/dev/null; sleep 3
}
bench() {  # name, args...
  local name="$1"; shift
  $PY "$HERE/bench.py" --clips "$CLIPS" --out "$OUT/$name.json" "$@" > "$OUT/$name.summary" 2>&1
  local pid; pid=$(pgrep -f "python server.py" | head -1)
  echo "$name: $($PY -c "import json,sys; s=json.load(open('$OUT/$name.json'))['summary']; print({k: s[k] for k in ('errors','language_msgs','language_lag_p50','language_lag_p90','transcripts','transcript_lag_p50','transcript_lag_p90','lid_through_service','sentences','voice_errors','first_audio_p50','first_audio_p90','per_voice','gpu_mem_peak_mib','gpu_util_mean')})" 2>&1) rss=$(( $(ps -o rss= -p "$pid") / 1024 ))MiB"
}

# The separate omni-stt service (300M card, voices beside it), as setup.sh deploys it.
start omni300 OMNI_CARD=omniASR_LLM_300M STT_SERVE=listen,speak STT_MAX_CONNECTIONS=4 STT_MAX_SPEAKERS=4 || exit 1
bench omni300-hear1   --listen 1 --speak 0 --langs ht,en --transcribe ht --seconds 90
bench omni300-speak1  --listen 0 --speak 1 --seconds 60
bench omni300-4h2s    --listen 4 --speak 2 --langs ht,en --transcribe ht --seconds 120
stop

# The 7B as setup.sh deploys it beside omni-stt: /listen only.
start b7listen OMNI_CARD=omniASR_LLM_7B_bf16 OMNI_MMAP=1 STT_SERVE=listen STT_MAX_CONNECTIONS=6 || exit 1
bench b7listen-hear1  --listen 1 --speak 0 --langs ht,en --transcribe ht --seconds 90
bench b7listen-4h     --listen 4 --speak 0 --langs ht,en --transcribe ht --seconds 120
stop

# The 7B-only layout: the 7B with the voices.
start b7voices OMNI_CARD=omniASR_LLM_7B_bf16 OMNI_MMAP=1 STT_SERVE=listen+speak STT_MAX_CONNECTIONS=6 STT_MAX_SPEAKERS=4 || exit 1
bench b7voices-hear1      --listen 1 --speak 0 --langs ht,en --transcribe ht --seconds 90
bench b7voices-speak1     --listen 0 --speak 1 --seconds 60
bench b7voices-4h2s       --listen 4 --speak 2 --langs ht,en --transcribe ht --seconds 120
bench b7voices-4h2s-lid   --listen 4 --speak 2 --langs ht,en,fr,es --transcribe none --seconds 120
bench b7voices-6h4s       --listen 6 --speak 4 --langs ht,en --transcribe ht --seconds 120
stop
echo "all done"
