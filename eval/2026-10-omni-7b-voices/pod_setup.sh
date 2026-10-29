#!/usr/bin/env bash
# The 7B image's file system rebuilt by hand on a GPU pod (runpod/pytorch,
# Ubuntu 24.04, Python 3.12): 7b/Dockerfile.base's installs (with the voices),
# Meta's 7B converted to bf16 (7b/to_bf16.py), the cards, and the models the
# server loads, at the paths the image uses. Run from the repository checkout.
#
#   bash eval/2026-10-omni-7b-voices/pod_setup.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SVC="$ROOT/services/omni-stt"
export STT_MODELS=/opt/models HF_HOME=/opt/models/hf TORCH_HOME=/opt/models/torch \
  FAIRSEQ2_CACHE_DIR=/opt/models/fairseq2 FAIRSEQ2_USER_ASSET_DIR=/opt/models/cards
mkdir -p /opt/models/cards /opt/models/7b
apt-get update -qq && apt-get install -y -qq libsndfile1 build-essential cmake libboost-program-options-dev \
  libboost-system-dev libboost-thread-dev libboost-test-dev zlib1g-dev libbz2-dev liblzma-dev >/dev/null

# The 7B checkpoint download runs beside the installs.
( cd /opt/models/7b && t=$(date +%s) \
  && curl -sSfL --retry 5 -o fp32.pt https://dl.fbaipublicfiles.com/mms/omniASR-LLM-7B.pt \
  && echo "7B fp32 downloaded in $(( $(date +%s) - t ))s" ) > /opt/ckpt.log 2>&1 &
ck=$!

python3 -m venv /opt/venv
. /opt/venv/bin/activate
cd "$ROOT"
pip install -q -c constraints.txt torch==2.8.0 torchaudio==2.8.0
pip install -q -c constraints.txt omnilingual-asr torchaudio==2.8.0 scipy==1.13.1 speechbrain websockets huggingface_hub soundfile
grep -vE '^(librosa|contourpy)==' constraints.txt > /tmp/voices-c.txt
pip install -q -c /tmp/voices-c.txt coqui-tts==0.27.5 numpy==1.26.4 scipy==1.13.1 torch==2.8.0 torchaudio==2.8.0
pip check
python -c "import TTS, transformers, numpy, omnilingual_asr, torch; print('coqui-tts', TTS.__version__, 'transformers', transformers.__version__, 'torch', torch.__version__, torch.cuda.is_available())"
cp "$SVC/7b/cards.yaml" /opt/models/cards/omni7b.yaml
cd "$SVC"
python -c "import server; server.load_vad(); server.load_lid('cpu'); \
from fairseq2.data.tokenizers.hub import load_tokenizer; load_tokenizer('omniASR_LLM_7B_bf16'); print('fetched')"
EDITION=both python -c "import server; from voices import Voices; Voices('cpu', server.voice_list())"
du -sh /opt/models/*
wait "$ck"; cat /opt/ckpt.log
python "$SVC/7b/to_bf16.py" /opt/models/7b/fp32.pt /opt/models/7b/omniASR_LLM_7B_bf16.pt
rm /opt/models/7b/fp32.pt
ls -l /opt/models/7b
echo "pod setup done"
