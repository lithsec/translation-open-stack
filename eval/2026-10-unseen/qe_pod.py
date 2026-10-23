# On the pod, stack stopped: translate each live English piece with MADLAD-400 7B (the stack's CT2 int8,
# beam 4, sentence by sentence as the engine does), then score both translators' output with
# MetricX-24 hybrid XL in reference-free QE mode (lower = better), as eval/2026-10-open-stack-e2e.
#   HF_HOME=... python3 qe_pod.py pieces.json out.json      pieces: [{"key","src","tgt","hy"}]
import json, sys, time
sys.path.insert(0, "/opt/stack/server")
from engines.common import split_sentences, join_sentences
import ctranslate2, torch
from transformers import T5Tokenizer, AutoTokenizer, MT5ForConditionalGeneration

P = json.load(open(sys.argv[1]))
D = "/workspace/mt/madlad7b-ct2"
tok = T5Tokenizer.from_pretrained(D)
tr = ctranslate2.Translator(D, device="cuda", compute_type="int8_float16")
t0 = time.time()
for p in P:
    sents = split_sentences(p["src"]) or [p["src"]]
    toks = [tok.convert_ids_to_tokens(tok.encode(f"<2{p['tgt']}> {s}")) for s in sents]
    res = tr.translate_batch(toks, beam_size=4, max_decoding_length=256)
    outs = [tok.decode(tok.convert_tokens_to_ids(r.hypotheses[0]), skip_special_tokens=True) for r in res]
    p["madlad"] = join_sentences(outs, p["tgt"])
print("madlad", len(P), round(time.time() - t0, 1), "s", flush=True)
del tr; torch.cuda.empty_cache()

CK = ("google/metricx-24-hybrid-xl-v2p6", "f6e7f99a655582f28cb998dd3e6ca86b4217430d")
mt5 = AutoTokenizer.from_pretrained("google/mt5-xl")
model = MT5ForConditionalGeneration.from_pretrained(CK[0], revision=CK[1], torch_dtype=torch.float32).cuda().eval()
pairs = [(i, k, p["src"], p[k]) for i, p in enumerate(P) for k in ("hy", "madlad")]
with torch.inference_mode():
    for b in range(0, len(pairs), 16):
        chunk = pairs[b:b + 16]
        enc = [mt5(f"source: {s} candidate: {h}", max_length=1536, truncation=True)["input_ids"][:-1] for _, _, s, h in chunk]
        L = max(len(e) for e in enc)
        ids = torch.zeros(len(enc), L, dtype=torch.long); mask = torch.zeros(len(enc), L, dtype=torch.long)
        for r, e in enumerate(enc):
            ids[r, :len(e)] = torch.tensor(e); mask[r, :len(e)] = 1
        out = model(input_ids=ids.cuda(), attention_mask=mask.cuda(), decoder_input_ids=torch.zeros(len(enc), 1, dtype=torch.long).cuda())
        for (i, k, _, _), v in zip(chunk, out.logits[:, 0, 250089].clamp(0, 25).float().cpu().tolist()):
            P[i]["qe_" + k] = round(v, 4)
json.dump(P, open(sys.argv[2], "w"), ensure_ascii=False, indent=0)
print("qe done", round(time.time() - t0, 1), "s", flush=True)
