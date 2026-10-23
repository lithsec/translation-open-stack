#!/bin/bash
# Khmer public fine-tune, end to end on one GPU pod. Logs in /workspace/logs.
set -x
export FAIRSEQ2_CACHE_DIR=/workspace/cache/fairseq2 HF_HOME=/workspace/cache/hf TORCH_HOME=/workspace/cache/torch
export HF_HUB_ENABLE_HF_TRANSFER=1 PYTHONUNBUFFERED=1 OMNI_REPO=/workspace/omnilingual-asr
U=/workspace/up; L=/workspace/logs; E=/workspace/eval; D=/workspace/data/km_public
mkdir -p $L $E /root/.config/fairseq2/assets

# 1. Setup
if [ ! -f /workspace/.setup_done ]; then
  apt-get update -qq && apt-get install -y -qq sox libsndfile1 > $L/apt.log 2>&1
  pip install -q --break-system-packages omnilingual-asr==0.1.0 soxr huggingface_hub hf_transfer num2words websockets "pyarrow==19.0.1" soundfile unidecode tensorboard > $L/pip.log 2>&1
  git clone -q https://github.com/facebookresearch/omnilingual-asr $OMNI_REPO && (cd $OMNI_REPO && git checkout -q 81f51e2)
  python3 -c "import omnilingual_asr, fairseq2, torch; print(torch.__version__, fairseq2.__version__)" > $L/versions.log 2>&1
  touch /workspace/.setup_done
fi
cat $L/versions.log

# 2. Data prep (CPU) in the background; baselines on the GPU meanwhile.
(python3 $U/prep.py --out $D > $L/prep.log 2>&1; echo PREP_EXIT $? >> $L/prep.log) &
PREP=$!
cd $U
python3 eval_km.py --card omniASR_LLM_300M --name base300 --out $E > $L/eval_base300.log 2>&1
python3 eval_km.py --card omniASR_LLM_7B --name base7b --out $E > $L/eval_base7b.log 2>&1
wait $PREP
grep -q "PREP_EXIT 0" $L/prep.log || { echo PREP FAILED; exit 1; }
python3 eval_km.py --card omniASR_LLM_300M --name base300dev --sets "" --dev $D --out $E > $L/eval_base300dev.log 2>&1

# 3. Train
cp $D/km_public.yaml /root/.config/fairseq2/assets/
cd $OMNI_REPO && export PYTHONPATH=$OMNI_REPO/src:$OMNI_REPO
python3 -m workflows.recipes.wav2vec2.asr /workspace/ft/km --config-file $U/llm-finetune-km-public.yaml > $L/train.log 2>&1
echo TRAIN_EXIT $? >> $L/train.log
unset PYTHONPATH

# 4. Checkpoints: the sets and dev CER each
cd $U
for c in $(ls -d /workspace/ft/km/ws_*/checkpoints/step_* | sort -t_ -k3 -n); do
  s=$(basename $c | sed 's/step_//')
  w=$c/model/pp_00/tp_00/sdp_00.pt
  [ -f $w ] && python3 eval_km.py --card omniASR_LLM_300M --name ft_s$s --weights $w --dev $D --out $E > $L/eval_ft_s$s.log 2>&1
done
echo EVALS_DONE > $L/stage
