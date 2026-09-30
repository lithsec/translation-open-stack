# Both directions (en->X, X->en) for one model. python3 mt2.py <madlad3b|madlad7b|hymt7b>
import json, sys, time, torch
which = sys.argv[1]
LANGS = ["es","fr","de","pt","ru","uk","zh","ja","km","ht"]
NAMES = {"en":"English","es":"Spanish","fr":"French","de":"German","pt":"Portuguese","ru":"Russian","uk":"Ukrainian","zh":"Chinese","ja":"Japanese","km":"Khmer","ht":"Haitian Creole"}
HEARD = {c: json.load(open(f"asr/{c}.json"))["heard"] for c in ["en"] + LANGS}
EN = HEARD["en"]; SRC = {l: HEARD[l] for l in LANGS}
if which.startswith("madlad"):
    import ctranslate2
    from huggingface_hub import snapshot_download
    from transformers import T5Tokenizer
    tok = T5Tokenizer.from_pretrained("google/madlad400-3b-mt")
    path = "/workspace/madlad-ct2" if which == "madlad3b" else snapshot_download("Heng666/madlad400-7b-mt-ct2-int8")
    tr = ctranslate2.Translator(path, device="cuda", compute_type="int8_float16")
    def translate(texts, src, tgt):
        srcs = [tok.convert_ids_to_tokens(tok.encode(f"<2{tgt}> {t}")) for t in texts]
        res = tr.translate_batch(srcs, beam_size=4, max_decoding_length=200)
        return [tok.decode(tok.convert_tokens_to_ids(r.hypotheses[0]), skip_special_tokens=True) for r in res]
else:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    name = "tencent/Hy-MT2-7B"
    tok = AutoTokenizer.from_pretrained(name); tok.padding_side = "left"
    model = AutoModelForCausalLM.from_pretrained(name, torch_dtype=torch.bfloat16).to("cuda").eval()
    def translate(texts, src, tgt):
        prompts = [tok.apply_chat_template([{"role": "user", "content": f"Translate the following text into {NAMES[tgt]}. Note that you should only output the translated result without any additional explanation:\n\n{t}"}],
                   tokenize=False, add_generation_prompt=True) for t in texts]
        inp = tok(prompts, return_tensors="pt", padding=True, add_special_tokens=False).to("cuda"); inp.pop("token_type_ids", None)
        with torch.inference_mode():
            g = model.generate(**inp, max_new_tokens=200, do_sample=False, repetition_penalty=1.05)
        return [tok.decode(x[inp["input_ids"].shape[1]:], skip_special_tokens=True).strip() for x in g]
out, times = {}, {}
for l in LANGS:
    t = time.time(); out[f"en-{l}"] = translate(EN, "en", l); times[f"en-{l}"] = round(time.time() - t, 2)
    t = time.time(); out[f"{l}-en"] = translate(SRC[l], l, "en"); times[f"{l}-en"] = round(time.time() - t, 2)
    print(which, l, file=sys.stderr, flush=True)
print(json.dumps({"model": which, "times": times, "out": out}, ensure_ascii=False))
