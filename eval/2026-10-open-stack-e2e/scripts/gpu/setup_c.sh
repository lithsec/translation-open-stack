cd /root
export HF_HOME=/root/hf
apt-get install -y -qq libsndfile1 ffmpeg >/dev/null 2>&1
(uv venv -q -p 3.12 /root/nemo && VIRTUAL_ENV=/root/nemo uv pip install -q "nemo_toolkit[asr]==3.0.0" peft faster-whisper==1.2.1 soundfile > nemo_pip.log 2>&1; echo NEMO_PIP_DONE >> nemo_pip.log) &
(uv venv -q -p 3.12 /root/mtv && VIRTUAL_ENV=/root/mtv uv pip install -q torch==2.8.0 bitsandbytes==0.50.2 accelerate==1.15.0 ctranslate2==4.8.2 transformers==4.57.6 sentencepiece==0.2.2 huggingface_hub==0.36.2 hf-xet==1.6.0 tokenizers==0.22.2 safetensors==0.8.0 protobuf==7.36.2 > mtv_pip.log 2>&1; echo MTV_PIP_DONE >> mtv_pip.log) &
wait
echo SETUP_C_DONE
