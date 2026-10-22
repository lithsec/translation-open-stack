export HF_HOME=/root/hf HF_HUB_OFFLINE=1
exec vllm serve tencent/Hy-MT2-30B-A3B --revision d3ead4dba61c09aac60a261a96ad1df3e705febb --port 8000 --api-key "$(cat /root/apikey)" --max-model-len 4096 --gpu-memory-utilization 0.90 --max-num-seqs 32
