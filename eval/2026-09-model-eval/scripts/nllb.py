# NLLB-200 3.3B on the same 24 sentences, both directions (text benchmark format of bench2/mt2.py).
import json, time, torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
LANGS = ["es","fr","de","pt","ru","uk","zh","ja","km","ht"]
CODE = {"en":"eng_Latn","es":"spa_Latn","fr":"fra_Latn","de":"deu_Latn","pt":"por_Latn","ru":"rus_Cyrl","uk":"ukr_Cyrl",
        "zh":"zho_Hans","ja":"jpn_Jpan","km":"khm_Khmr","ht":"hat_Latn"}
name = "facebook/nllb-200-3.3B"
tok = AutoTokenizer.from_pretrained(name)
model = AutoModelForSeq2SeqLM.from_pretrained(name, torch_dtype=torch.bfloat16).to("cuda").eval()
def translate(texts, src, tgt):
    tok.src_lang = CODE[src]
    inp = tok(texts, return_tensors="pt", padding=True).to("cuda")
    with torch.inference_mode():
        g = model.generate(**inp, forced_bos_token_id=tok.convert_tokens_to_ids(CODE[tgt]), num_beams=4, max_new_tokens=256)
    return tok.batch_decode(g, skip_special_tokens=True)
EN = json.load(open("en.json")); out, times = {}, {}
for L in LANGS:
    t = time.time(); out[f"en-{L}"] = translate(EN, "en", L); times[f"en-{L}"] = round(time.time() - t, 2)
    t = time.time(); out[f"{L}-en"] = translate(json.load(open(f"src_{L}.json")), L, "en"); times[f"{L}-en"] = round(time.time() - t, 2)
print(json.dumps({"model": "nllb3b", "times": times, "vram_gb": round(torch.cuda.max_memory_allocated()/1e9,1), "out": out}, ensure_ascii=False))
