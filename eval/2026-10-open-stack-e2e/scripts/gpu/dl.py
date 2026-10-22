import os, time
from huggingface_hub import snapshot_download
for repo, rev, pat in [("Qwen/Qwen3.5-122B-A10B-GPTQ-Int4", "30cd92cba9707a9aba09d1e490ed4b66b78e9606", None),
                       ("tencent/Hy-MT2-30B-A3B", "d3ead4dba61c09aac60a261a96ad1df3e705febb", None),
                       ("google/metricx-24-hybrid-xl-v2p6", "f6e7f99a655582f28cb998dd3e6ca86b4217430d", None),
                       ("google/mt5-xl", None, ["*.json", "spiece.model"])]:
    t = time.time()
    p = snapshot_download(repo, revision=rev, allow_patterns=pat, max_workers=16)
    print("DONE", repo, p, round(time.time() - t), "s", flush=True)
