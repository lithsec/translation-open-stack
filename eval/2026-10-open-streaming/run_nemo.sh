#!/bin/bash
# NeMo cache-aware streaming: Nemotron 3.5 ASR (multilingual) on en/es/fr, 0.56 s chunks.
#   bash run_nemo.sh   (on the pod; /workspace/stream layout)
W=/workspace/stream
mkdir -p $W/work/rec $W/logs
cd $W
export HF_HOME=$W/hf OMP_NUM_THREADS=8
MODEL=nvidia/nemotron-3.5-asr-streaming-0.6b REV=ea30d66debe3740a08b573244286791d423d6b3e ATT=56,6 TAG=nemo \
  /root/venv-nemo/bin/python nemo_stream.py $W/clips $W/work/rec
/root/venv-nemo/bin/python -I $W/evalrepo/2026-10-open-streaming/nemo_spans.py $W/work/rec/nemo_{reg,irr}_{en,es,fr}.json
echo done
