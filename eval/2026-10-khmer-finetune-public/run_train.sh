#!/bin/bash
set -x
export FAIRSEQ2_CACHE_DIR=/workspace/cache/fairseq2 HF_HOME=/workspace/cache/hf TORCH_HOME=/workspace/cache/torch
export HF_HUB_ENABLE_HF_TRANSFER=1 PYTHONUNBUFFERED=1 OMNI_REPO=/workspace/omnilingual-asr
U=/workspace/up; L=/workspace/logs; E=/workspace/eval; D=/workspace/data/km_public
mkdir -p $L $E /root/.config/fairseq2/assets
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
