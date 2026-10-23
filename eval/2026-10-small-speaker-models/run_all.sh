set -x
cd /w
pip -q install "speechbrain==1.0.3" onnx onnxruntime soundfile scipy "huggingface_hub<0.26" "numpy<2.2" > pip.log 2>&1
apt-get -qq update >/dev/null 2>&1; apt-get -qq install -y sox >/dev/null 2>&1
(curl -sL https://nodejs.org/dist/v20.18.0/node-v20.18.0-linux-x64.tar.xz | tar xJ -C /opt; export PATH=/opt/node-v20.18.0-linux-x64/bin:$PATH; mkdir -p web; cd web; npm init -y >/dev/null; npm i -s onnxruntime-web@1.20.1 >/dev/null 2>&1; cp /w/bench_web.mjs .) &
FL_LANGS=en,es,fr,pt,ja python3 fetch_data.py /w/data > fetch.log 2>&1
python3 make_ctl.py /w/data/fleurs /w/sw
python3 bleed_clips.py /w/data/libri /w/data/cmu /w/sw /w/pa /w/bclips > bclips.log 2>&1
SKIPVL=1 python3 vl_feats.py /w/bclips /w/vl > vl.log 2>&1
python3 export.py /w/data/fleurs /w/export.json > export.log 2>&1
python3 export_static.py /w/data/fleurs /w/export.json /w/export2.json > export2.log 2>&1
echo EXPORTED > stage
export WINS=1.5 ORT_THREADS=4 TORCH_THREADS=4
python3 feats_models.py /w/bclips /w/vl /w/ft resnet34_qdq > f1.log 2>&1 &
python3 feats_models.py /w/bclips /w/vl /w/ft campplus_int8 > f2.log 2>&1 &
python3 feats_models.py /w/bclips /w/vl /w/ft sb_ecapa_fp32 > f3.log 2>&1 &
LIBRI_N=40 LIBRI_UTTS=10 ONLY=libri_en ORT_THREADS=4 python3 eer.py /w/data /w/eer_libri40.json resnet34_fp32 resnet34_qdq campplus_int8 sb_ecapa_fp32 > eer.log 2>&1 &
wait
echo FEATS > stage
for m in resnet34_qdq campplus_int8 sb_ecapa_fp32; do METHODS=abc BUF=0.75 WINS=1.5 python3 bleed_analyze.py /w/bclips /w/ft/$m /w/ana_$m.json > ana_$m.log 2>&1 & done
wait
export PATH=/opt/node-v20.18.0-linux-x64/bin:$PATH
cd web && THREADS=1 node bench_web.mjs /w/models resnet34_qdq campplus_int8 resnet34_fp32 sb_ecapa_fp32 > /w/web1.log 2>&1; THREADS=4 node bench_web.mjs /w/models resnet34_qdq campplus_int8 resnet34_fp32 sb_ecapa_fp32 > /w/web4.log 2>&1
echo ALLDONE > /w/stage
