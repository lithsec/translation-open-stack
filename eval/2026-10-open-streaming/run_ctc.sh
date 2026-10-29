#!/bin/bash
# omni-stt's CTC 3B streaming service (eval/2026-10-ctc-stream "Reproduce"), with the
# track opened to en/es/fr for this test (STT_CTC_LANGS and ctc_stream_en_es_fr.patch:
# a Latin script mask), on port 8310, then the six clips streamed at real time, one
# connection per clip, the three languages of a pause pattern at once.
#   bash run_ctc.sh   (on the pod; /workspace/stream layout, omni-stt copied to $W/omni-stt and patched)
W=/workspace/stream
mkdir -p $W/rec_raw $W/work/rec $W/logs $W/fairseq2 $W/hf
cd $W/omni-stt
OMNI_CARD=omniASR_CTC_3B STT_CTC_STREAM=1 STT_CTC_LANGS=en,es,fr STT_OPEN=1 STT_SERVE=listen PORT=8310 \
  HF_HOME=$W/hf FAIRSEQ2_CACHE_DIR=$W/fairseq2 TORCH_HOME=$W/torch \
  nohup /root/venv-omni/bin/python server.py > $W/logs/ctc_server.log 2>&1 &
SRV=$!
for i in $(seq 1 120); do
  grep -q "ready on :8310" $W/logs/ctc_server.log && break
  sleep 10
done
sleep 5
(while kill -0 $SRV 2>/dev/null; do nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader | grep "^$SRV," >> $W/logs/ctc_mem.csv; sleep 1; done) &
for p in reg irr; do
  /root/venv-omni/bin/python $W/stream_ctc.py ws://127.0.0.1:8310/listen $W/clips/clips_$p $W/work/rec ctc_$p en es fr
done
cp $W/logs/ctc_server.log $W/logs/ctc_server_after.log
kill $SRV
echo done
