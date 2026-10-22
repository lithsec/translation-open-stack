"""Experiment A, step 2 on the pod: the stack translators (mt_pod.py's exact setup and decoding:
Hy-MT2 7B NF4 for km->en, MADLAD-400 7B CT2 int8 for lo->en) over every transcript variant.
  python3 mt_a.py /root/a/variants.json /root/a/out/mt_a.json
variants.json: {name: {"lang": "km"|"lo", "texts": [...]}}
"""
import json, os, subprocess, sys, time
import torch
from huggingface_hub import snapshot_download
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, T5Tokenizer
import ctranslate2

HYMT = ("tencent/Hy-MT2-7B", "9b0eb4e8f001def3e5ff6469a0ac96fdb39ec223")
MADLAD = ("google/madlad400-7b-mt", "1ff63ce7ddd571a69d45cad9672c553428419671")
V = json.load(open(sys.argv[1]))

src = snapshot_download(HYMT[0], revision=HYMT[1])
tok = AutoTokenizer.from_pretrained(src); tok.padding_side = "left"
q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                       bnb_4bit_use_double_quant=True)
hy = AutoModelForCausalLM.from_pretrained(src, quantization_config=q, device_map="cuda").eval()
msrc = snapshot_download(MADLAD[0], revision=MADLAD[1], allow_patterns=["*.json", "*.safetensors", "spiece.model"])
ct = "/root/madlad7b-ct2"
if not os.path.exists(os.path.join(ct, "model.bin")):
    subprocess.run(["ct2-transformers-converter", "--model", msrc, "--quantization", "int8", "--output_dir", ct,
                    "--low_cpu_mem_usage", "--force"], check=True)
mtok = T5Tokenizer.from_pretrained(msrc)
mad = ctranslate2.Translator(ct, device="cuda", compute_type="int8_float16")


def translate(text, src_lang):
    with torch.inference_mode():
        torch.cuda.synchronize(); t0 = time.time()
        if src_lang == "km":  # Hy-MT2 (mt_pod.py translate("hymt"))
            p = tok.apply_chat_template([{"role": "user", "content":
                "Translate the following text into English. Note that you should only output "
                f"the translated result without any additional explanation:\n\n{text}"}], tokenize=False, add_generation_prompt=True)
            inp = tok([p], return_tensors="pt", add_special_tokens=False).to("cuda")
            inp.pop("token_type_ids", None)
            n = len(tok.encode(text, add_special_tokens=False))
            g = hy.generate(**inp, max_new_tokens=min(1024, n * 10 + 64), do_sample=False, repetition_penalty=1.05)
            out = tok.decode(g[0][inp["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        else:  # MADLAD (mt_pod.py translate("madlad"))
            ids = mtok.encode(f"<2en> {text}")
            r = mad.translate_batch([mtok.convert_ids_to_tokens(ids)], max_decoding_length=min(160, len(ids) * 2 + 24),
                                    beam_size=4, replace_unknowns=False)
            out = mtok.decode(mtok.convert_tokens_to_ids(r[0].hypotheses[0]), skip_special_tokens=True).strip()
        torch.cuda.synchronize()
        return out, round(time.time() - t0, 3)


res = {}
for name, v in V.items():
    outs, secs = [], []
    for x in v["texts"]:
        if not x.strip():
            outs.append(""); secs.append(None); continue
        o, s = translate(x, v["lang"]); outs.append(o); secs.append(s)
    res[name] = {"out": outs, "gpu_s": secs}
    print(name, "done", flush=True)
json.dump(res, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
print("MT_DONE", flush=True)
