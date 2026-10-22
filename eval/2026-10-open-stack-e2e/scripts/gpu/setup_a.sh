#!/usr/bin/env bash
# Pod A: omni-stt's pins (constraints.txt), then 300M and 7B; then the stack translators (mt_pod.py's PINS).
set -x
cd /root/a
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq libsndfile1 build-essential cmake libboost-program-options-dev \
  libboost-system-dev libboost-thread-dev libboost-test-dev zlib1g-dev libbz2-dev liblzma-dev ffmpeg >/dev/null
python3 -m venv /root/venv
. /root/venv/bin/activate
pip install -q -c stack/constraints.txt torch==2.8.0 torchaudio==2.8.0
pip install -q -c stack/constraints.txt omnilingual-asr torchaudio==2.8.0 scipy==1.13.1 speechbrain huggingface_hub soundfile
python -c "import torch, omnilingual_asr; print('torch', torch.__version__, torch.cuda.is_available())"
echo SETUP_ASR_DONE
export STACK=/root/a/stack OMNI_MMAP=1 STT_MODELS=/root/models
for card in omniASR_LLM_300M omniASR_LLM_7B; do
  python -u asr_a.py --card $card --out /root/a/out 2>&1 | grep -v -i warning | tail -40
done
echo ASR_DONE
