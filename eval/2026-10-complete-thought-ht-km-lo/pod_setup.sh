#!/usr/bin/env bash
# On a short-lived GPU pod (one 48 GB card): omni-stt from the public repo's main, Meta's stock checkpoints
# (no fine-tuned weights), three /listen services on 127.0.0.1 only (STT_OPEN=1, no port exposed):
#   :8085  omniASR_LLM_300M, stock (production's Haitian Creole card is a private fine-tune of it)
#   :8082  omniASR_LLM_7B in bf16 (omni-stt-7b: the km and lo finals)
#   :8083  omniASR_CTC_3B in bf16 with the streaming track (omni-stt-3b-stream)
#   :8084  as :8085 with STT_PARTIALS=1 (the prototype partial passes, off in production)
# Endpointing: the service defaults (200 ms pause, 10 s cap, 1 s minimum speech, progressive cut from 4 s).
# Expects /w/stt.tgz (services/omni-stt staged as deploy.sh stages it). A watchdog stops the pod after 3 h.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
eval "$(tr '\0' '\n' < /proc/1/environ | grep -E '^RUNPOD_(API_KEY|POD_ID)=' | sed 's/^/export /')"
nohup bash -c 'sleep 10800; runpodctl stop pod "$RUNPOD_POD_ID"' > /w/watchdog.log 2>&1 &
apt-get update -qq
apt-get install -y -qq --no-install-recommends libsndfile1 ca-certificates curl procps \
  build-essential cmake libboost-program-options-dev libboost-system-dev libboost-thread-dev \
  libboost-test-dev zlib1g-dev libbz2-dev liblzma-dev python3-venv >/dev/null
mkdir -p /opt/models/7b /opt/models/ctc3b /opt/models/cards /dl /w/logs /w/out
( curl -sSfL --retry 5 -o /dl/7b.pt https://dl.fbaipublicfiles.com/mms/omniASR-LLM-7B.pt; echo 7b-dl-ok ) > /dl/7b.log 2>&1 &
d7=$!
( curl -sSfL --retry 5 -o /dl/3b.pt https://dl.fbaipublicfiles.com/mms/omniASR-CTC-3B.pt; echo 3b-dl-ok ) > /dl/3b.log 2>&1 &
d3=$!
mkdir -p /opt && tar xzf /w/stt.tgz -C /opt
cd /opt/stt
python3 -m venv /w/venv
. /w/venv/bin/activate
pip install -q -c constraints.txt torch==2.8.0 torchaudio==2.8.0
pip install -q -c constraints.txt omnilingual-asr torchaudio==2.8.0 scipy==1.13.1 speechbrain websockets huggingface_hub soundfile
export STT_MODELS=/opt/models HF_HOME=/opt/models/hf TORCH_HOME=/opt/models/torch FAIRSEQ2_CACHE_DIR=/opt/models/fairseq2 FAIRSEQ2_USER_ASSET_DIR=/opt/models/cards
cp 7b/cards.yaml /opt/models/cards/omni7b.yaml
cp duo/cards.yaml /opt/models/cards/ctc3b.yaml
python -c "import server; server.load_vad(); server.load_lid('cpu'); \
from fairseq2.data.tokenizers.hub import load_tokenizer; load_tokenizer('omniASR_LLM_7B_bf16'); load_tokenizer('omniASR_CTC_3B_bf16'); print('fetched')"
wait $d7 $d3 || true   # (a stalled download was resumed by hand with curl -C - in this run)
cat /dl/*.log
python 7b/to_bf16.py /dl/3b.pt /opt/models/ctc3b/omniASR_CTC_3B_bf16.pt && rm /dl/3b.pt
python 7b/to_bf16.py /dl/7b.pt /opt/models/7b/omniASR_LLM_7B_bf16.pt && rm /dl/7b.pt
du -sh /opt/models/*
echo SETUP-DONE
