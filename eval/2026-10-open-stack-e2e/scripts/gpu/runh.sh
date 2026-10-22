cd /root
until grep -q -E "Application startup complete|Traceback" vllm_h.log; do sleep 5; done
grep -q Traceback vllm_h.log && { echo HFAIL; exit 1; }
python3 b_client.py tencent/Hy-MT2-30B-A3B hymt b_inputs.json h_direct.json
python3 b_client.py tencent/Hy-MT2-30B-A3B hymt lat_inputs.json hlat_direct.json --latency 6
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader > h_mem.txt
echo H_ALL_DONE
