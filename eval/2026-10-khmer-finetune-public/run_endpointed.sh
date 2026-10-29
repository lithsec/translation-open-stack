#!/bin/bash
# Export the picked checkpoint as a card, then the endpointed (omni-stt path) evals.
#   bash run3.sh <step>
set -x
export FAIRSEQ2_CACHE_DIR=/workspace/cache/fairseq2 HF_HOME=/workspace/cache/hf TORCH_HOME=/workspace/cache/torch PYTHONUNBUFFERED=1
U=/workspace/up; L=/workspace/logs; S=$1; CARD=omniASR_LLM_300M_km_public
W=$(ls -d /workspace/ft/km/ws_*/checkpoints/step_$S)/model/pp_00/tp_00/sdp_00.pt
# (the checkpoint was exported to a bf16 fairseq2 card here: a state dict cast to bf16 plus a card
#  "name: $CARD / base: omniASR_LLM_300M / checkpoint: file://...pt"; not part of this folder)
cp /workspace/cards/$CARD/$CARD.yaml /root/.config/fairseq2/assets/
export PYTHONPATH=/workspace/stack/services/omni-stt:/workspace/stack/server
cd /workspace/stack/eval/2026-10-omni-sizes
for card in omniASR_LLM_300M omniASR_LLM_7B $CARD; do
  for set in rv unseen; do
    STACK=/workspace/stack python3 endpoint_sweep.py --card $card --audio $U/assets/$set --out /workspace/ep/$set \
      --langs km --settings 700:15 --level 2000 > $L/ep_${card}_$set.log 2>&1
  done
done
cd $U && python3 ep_score.py /workspace/eval/endpointed.json \
  $(for c in omniASR_LLM_300M omniASR_LLM_7B $CARD; do for s in rv unseen; do echo -n "$s:/workspace/ep/$s/${c}_level.json "; done; done) > $L/ep_score.log 2>&1
echo RUN3_DONE > $L/stage3
