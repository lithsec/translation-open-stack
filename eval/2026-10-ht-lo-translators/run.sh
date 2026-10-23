#!/bin/bash
# On the pod (A100 80 GB, image vllm/vllm-openai:v0.31.0), after `python3 pod_run.py download`
# and a /root/mtv venv (torch 2.8.0, transformers 4.57.6, ctranslate2 4.8.2, sentencepiece):
# each model in ORDER, deleting its weights once it has run (400 GB disk).
cd /root/work
for n in nllb-200-3.3b madlad-7b-bf16 madlad-10b-bf16; do /root/mtv/bin/python pod_run.py seq $n && rm -rf /root/models/$n; done
for n in translategemma-27b milmmt-46-12b; do python3 pod_run.py llm $n && rm -rf /root/models/$n; done
for n in qwen3.5-122b-a10b-int4-80gb gemma-4-31b-it; do python3 pod_run.py llm $n timing && rm -rf /root/models/$n; done
echo ALL_DONE
