# TranslateGemma (4B / 12B) on the benchmark: en<->10 languages, plus Lao (incl. Lao from the stack's own transcripts).
#   python3 tg.py 4b|12b
import json, sys, time, torch
from transformers import AutoModelForImageTextToText, AutoProcessor
size = sys.argv[1]
repo = f"google/translategemma-{size}-it"
rev = {"4b": "10042cb0e6e7fdce748996a71dc3dc432a4e0c89", "12b": "d1b225e1caa17f1ddc7e62065d8637d0923f34e2"}[size]
t0 = time.time()
proc = AutoProcessor.from_pretrained(repo, revision=rev); tok = proc.tokenizer; tok.padding_side = "left"
model = AutoModelForImageTextToText.from_pretrained(repo, revision=rev, dtype=torch.bfloat16, device_map="cuda").eval()
load_s = time.time() - t0
LANGS = ["es","fr","de","pt","ru","uk","zh","ja","km","ht"]
def translate(texts, src, tgt):
    try:
        prompts = [proc.apply_chat_template([{"role": "user", "content": [{"type": "text", "source_lang_code": src,
                   "target_lang_code": tgt, "text": t}]}], tokenize=False, add_generation_prompt=True) for t in texts]
    except Exception as e:
        return [f"[unsupported: {e}]"] * len(texts)
    inp = tok(prompts, return_tensors="pt", padding=True, add_special_tokens=False).to("cuda")
    with torch.inference_mode():
        g = model.generate(**inp, max_new_tokens=400, do_sample=False)
    return [tok.decode(x[inp["input_ids"].shape[1]:], skip_special_tokens=True).strip() for x in g]
EN = json.load(open("en.json")); out, times = {}, {}
translate(["Hello."], "en", "es")
t = time.time()
for s in EN[:6]: translate([s], "en", "es")
torch.cuda.synchronize(); single_ms = (time.time() - t) / 6 * 1000
for L in LANGS + ["lo"]:
    t = time.time(); out[f"en-{L}"] = translate(EN, "en", L); times[f"en-{L}"] = round(time.time() - t, 2)
    t = time.time(); out[f"{L}-en"] = translate(json.load(open(f"src_{L}.json")), L, "en"); times[f"{L}-en"] = round(time.time() - t, 2)
out["lo-en-heard"] = translate(json.load(open("asr_lo.json"))["omni/voxcpm"]["hyps"], "lo", "en")
print(json.dumps({"model": f"tg{size}", "revision": rev, "load_s": round(load_s, 1), "single_sentence_ms": round(single_ms),
                  "vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 1), "times": times, "out": out}, ensure_ascii=False))
