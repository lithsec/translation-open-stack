#!/usr/bin/env bash
# On the pod, after pod_setup.sh: start the four services (STT_OPEN=1; the pod exposes only SSH), wait until each answers
# /health, then stream every clip. Haitian Creole to :8085 (and :8084, partials on); Khmer and Lao to the 7B
# (:8082) and the streaming service (:8083, ?stream=ctc&lookahead=2) at once. One clip per language and pattern;
# the six clips of a pattern run at the same time (at most 4 sockets on a service).
set -uo pipefail
. /w/venv/bin/activate
cd /opt/stt
export STT_MODELS=/opt/models HF_HOME=/opt/models/hf TORCH_HOME=/opt/models/torch FAIRSEQ2_CACHE_DIR=/opt/models/fairseq2 \
  FAIRSEQ2_USER_ASSET_DIR=/opt/models/cards STT_OPEN=1 STT_SERVE=listen
PORT=8085 OMNI_CARD=omniASR_LLM_300M python server.py > /w/logs/s300.log 2>&1 &
PORT=8082 OMNI_CARD=omniASR_LLM_7B_bf16 OMNI_MMAP=1 STT_MAX_CONNECTIONS=6 python server.py > /w/logs/s7b.log 2>&1 &
PORT=8083 OMNI_CARD=omniASR_CTC_3B_bf16 STT_CTC_CARD=omniASR_CTC_3B_bf16 STT_CTC_STREAM=1 STT_MAX_CONNECTIONS=6 \
  python server.py > /w/logs/s3b.log 2>&1 &
PORT=8084 OMNI_CARD=omniASR_LLM_300M STT_PARTIALS=1 python server.py > /w/logs/s300p.log 2>&1 &
for p in 8085 8082 8083 8084; do
  for i in $(seq 600); do curl -sf "http://127.0.0.1:$p/health" >/dev/null && break; sleep 2; done
  echo "port $p up after ~$((i * 2)) s"
done
nvidia-smi --query-gpu=memory.used --format=csv,noheader
for pat in reg irr; do
  python /w/stream_omni.py /w/clips/clips_$pat/ht.wav /w/out/o3_${pat}_ht.json "ws://127.0.0.1:8085/listen?langs=ht" &
  python /w/stream_omni.py /w/clips/clips_$pat/ht.wav /w/out/o3p_${pat}_ht.json "ws://127.0.0.1:8084/listen?langs=ht" &
  for l in km lo; do
    python /w/stream_omni.py /w/clips/clips_$pat/$l.wav /w/out/o7c_${pat}_$l.json "ws://127.0.0.1:8082/listen?langs=$l" \
      "ws://127.0.0.1:8083/listen?langs=$l&stream=ctc&lookahead=2" &
  done
  wait $(jobs -p | tail -4)
done
echo RUN-DONE
