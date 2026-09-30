# Hy-MT2 7B at one precision, both directions for 10 languages (same sentences as the earlier bf16 benchmark).
#   python hymt_q.py nf4|fp8|bf16
import json, sys, time, torch
from transformers import AutoModelForCausalLM, AutoTokenizer
v = sys.argv[1]
path = {"nf4": "/workspace/mt/hymt2-7b-nf4", "fp8": "tencent/Hy-MT2-7B-FP8", "bf16": "tencent/Hy-MT2-7B"}[v]
rev = {"fp8": "883d09eb21d9be92058556cd0a4016d8a648c7db", "bf16": "9b0eb4e8f001def3e5ff6469a0ac96fdb39ec223"}.get(v)
LANGS = ["es","fr","de","pt","ru","uk","zh","ja","km","ht"]
NAMES = {"en":"English","es":"Spanish","fr":"French","de":"German","pt":"Portuguese","ru":"Russian","uk":"Ukrainian","zh":"Chinese","ja":"Japanese","km":"Khmer","ht":"Haitian Creole"}
kw = {"revision": rev} if rev else {}
tok = AutoTokenizer.from_pretrained(path, **kw); tok.padding_side = "left"
t0 = time.time()
model = AutoModelForCausalLM.from_pretrained(path, device_map="cuda", **({"dtype": torch.bfloat16} if v == "bf16" else {}), **kw).eval()
load_s = time.time() - t0
def translate(texts, tgt):
    pr = [tok.apply_chat_template([{"role": "user", "content": f"Translate the following text into {NAMES[tgt]}. Note that you should only output the translated result without any additional explanation:\n\n{t}"}], tokenize=False, add_generation_prompt=True) for t in texts]
    inp = tok(pr, return_tensors="pt", padding=True, add_special_tokens=False).to("cuda"); inp.pop("token_type_ids", None)
    with torch.inference_mode(): g = model.generate(**inp, max_new_tokens=400, do_sample=False, repetition_penalty=1.05)
    return [tok.decode(x[inp["input_ids"].shape[1]:], skip_special_tokens=True).strip() for x in g]
EN = json.load(open("en.json")); out, times = {}, {}
translate(["Hello."], "es")  # warm up
# single-sentence latency (what a live utterance costs)
t = time.time()
for s in EN[:6]: translate([s], "es")
torch.cuda.synchronize(); single_ms = (time.time() - t) / 6 * 1000
for L in LANGS:
    t = time.time(); out[f"en-{L}"] = translate(EN, L); times[f"en-{L}"] = round(time.time() - t, 2)
    t = time.time(); out[f"{L}-en"] = translate(json.load(open(f"src_{L}.json")), "en"); times[f"{L}-en"] = round(time.time() - t, 2)
print(json.dumps({"model": f"hymt_{v}", "load_s": round(load_s, 1), "single_sentence_ms": round(single_ms),
                  "vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 1), "times": times, "out": out}, ensure_ascii=False))
