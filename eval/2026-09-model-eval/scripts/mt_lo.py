# Translators into and out of Lao: en->lo, lo->en from the text, and lo->en from what Omnilingual heard (the stack's path).
import json, sys, time, torch
EN = json.load(open("en.json")); LO = json.load(open("src_lo.json"))
HEARD = json.load(open("asr_lo.json"))["omni/voxcpm"]["hyps"]
which = sys.argv[1]
if which.startswith("madlad"):
    import ctranslate2
    from transformers import T5Tokenizer
    path = {"madlad3b": "/workspace/madlad-ct2", "madlad7b": "/workspace/mt/madlad7b-ct2"}[which]
    tok = T5Tokenizer.from_pretrained(path); tr = ctranslate2.Translator(path, device="cuda", compute_type="int8_float16")
    def T(texts, src, tgt):
        r = tr.translate_batch([tok.convert_ids_to_tokens(tok.encode(f"<2{tgt}> {t}")) for t in texts], beam_size=4, max_decoding_length=256)
        return [tok.decode(tok.convert_tokens_to_ids(x.hypotheses[0]), skip_special_tokens=True) for x in r]
elif which == "nllb3b":
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    C = {"en": "eng_Latn", "lo": "lao_Laoo"}
    tok = AutoTokenizer.from_pretrained("facebook/nllb-200-3.3B"); m = AutoModelForSeq2SeqLM.from_pretrained("facebook/nllb-200-3.3B", torch_dtype=torch.bfloat16).to("cuda").eval()
    def T(texts, src, tgt):
        tok.src_lang = C[src]; inp = tok(texts, return_tensors="pt", padding=True).to("cuda")
        with torch.inference_mode(): g = m.generate(**inp, forced_bos_token_id=tok.convert_tokens_to_ids(C[tgt]), num_beams=4, max_new_tokens=256)
        return tok.batch_decode(g, skip_special_tokens=True)
else:  # Hy-MT2 (no Lao in its list; measured anyway)
    from transformers import AutoModelForCausalLM, AutoTokenizer
    p = "/workspace/mt/hymt2-7b-nf4"; tok = AutoTokenizer.from_pretrained(p); tok.padding_side = "left"
    m = AutoModelForCausalLM.from_pretrained(p, device_map="cuda").eval(); N = {"en": "English", "lo": "Lao"}
    def T(texts, src, tgt):
        pr = [tok.apply_chat_template([{"role": "user", "content": f"Translate the following text into {N[tgt]}. Note that you should only output the translated result without any additional explanation:\n\n{t}"}], tokenize=False, add_generation_prompt=True) for t in texts]
        inp = tok(pr, return_tensors="pt", padding=True, add_special_tokens=False).to("cuda"); inp.pop("token_type_ids", None)
        with torch.inference_mode(): g = m.generate(**inp, max_new_tokens=400, do_sample=False, repetition_penalty=1.05)
        return [tok.decode(x[inp["input_ids"].shape[1]:], skip_special_tokens=True).strip() for x in g]
print(json.dumps({"model": which, "out": {"en-lo": T(EN, "en", "lo"), "lo-en": T(LO, "lo", "en"), "lo-en-heard": T(HEARD, "lo", "en")}}, ensure_ascii=False))
