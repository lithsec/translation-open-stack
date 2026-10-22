export HF_HOME=/root/hf HF_HUB_OFFLINE=1
exec vllm serve Qwen/Qwen3.5-122B-A10B-GPTQ-Int4 --revision 30cd92cba9707a9aba09d1e490ed4b66b78e9606 --port 8000 --api-key "$(cat /root/apikey)" --language-model-only --quantization gptq_marlin --max-model-len 4096 --gpu-memory-utilization 0.94 --max-num-seqs 8 --speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'
