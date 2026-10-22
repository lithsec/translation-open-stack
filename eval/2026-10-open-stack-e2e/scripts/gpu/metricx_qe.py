"""MetricX-24 hybrid XL (v2p6), reference-free QE mode, as google-research/metricx (metricx24):
input "source: {src} candidate: {hyp}", tokenized with the mT5 tokenizer, EOS removed, max 1536 tokens;
decoder gets one 0 token, score = logits[:, 0, 250089] clamped to [0, 25] (lower = better).
  python3 metricx_qe.py <pairs.json> <out.json>   pairs: [{"key":..., "src":..., "hyp":...}]
"""
import json, sys, time
import torch
from transformers import AutoTokenizer, MT5ForConditionalGeneration

CK = ("google/metricx-24-hybrid-xl-v2p6", "f6e7f99a655582f28cb998dd3e6ca86b4217430d")
pairs = json.load(open(sys.argv[1]))
tok = AutoTokenizer.from_pretrained("google/mt5-xl")
model = MT5ForConditionalGeneration.from_pretrained(CK[0], revision=CK[1], torch_dtype=torch.float32).cuda().eval()
t = time.time()
scores = {}
order = sorted(range(len(pairs)), key=lambda i: len(pairs[i]["src"]) + len(pairs[i]["hyp"]))
B = 16
with torch.inference_mode():
    for k in range(0, len(order), B):
        idx = order[k:k + B]
        texts = [f"source: {pairs[i]['src']} candidate: {pairs[i]['hyp']}" for i in idx]
        enc = [tok(x, max_length=1536, truncation=True)["input_ids"][:-1] for x in texts]
        L = max(len(e) for e in enc)
        ids = torch.zeros(len(enc), L, dtype=torch.long)
        mask = torch.zeros(len(enc), L, dtype=torch.long)
        for r, e in enumerate(enc):
            ids[r, :len(e)] = torch.tensor(e); mask[r, :len(e)] = 1
        out = model(input_ids=ids.cuda(), attention_mask=mask.cuda(),
                    decoder_input_ids=torch.zeros(len(enc), 1, dtype=torch.long).cuda())
        pred = out.logits[:, 0, 250089].clamp(0, 25).float().cpu().tolist()
        for i, p in zip(idx, pred):
            scores[pairs[i]["key"]] = round(p, 4)
json.dump(scores, open(sys.argv[2], "w"), indent=0)
print("metricx done", len(scores), round(time.time() - t, 1), "s", flush=True)
