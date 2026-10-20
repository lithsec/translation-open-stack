# The open stack's translators on one GPU pod, one sentence per request (the
# live pipeline's single-stream latency). Every request needs API_KEY.
#   image runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404 (the stack's base),
#   port 8000/http, container disk ~150 GB, env API_KEY=<random>,
#   cmd: bash -c "echo <base64 of this file> | base64 -d > /srv.py && exec python3 -u /srv.py"
# The RunPod tools can't copy files, hence the base64 start command.
# Setup runs in the background (GET / shows the stage): the stack's pinned
# packages, then
#   hymt   tencent/Hy-MT2-7B @ the stack's revision, 4-bit NF4 (bitsandbytes),
#          the stack's prompt and decoding (server/engines/hymt.py)
#   madlad google/madlad400-7b-mt @ the stack's revision -> CTranslate2 int8,
#          int8_float16 on the GPU, beam 4 (server/engines/madlad.py)
#   tgemma google/translategemma-12b-it, bf16, its own prompt (gated: POST
#          /token {"hf_token"} first, never written to the pod's env)
# POST /translate {"model", "text", "src", "tgt"} -> {"text", "gpu_s"}
import json, os, subprocess, threading, time, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

KEY = os.environ["API_KEY"]
HYMT = ("tencent/Hy-MT2-7B", "9b0eb4e8f001def3e5ff6469a0ac96fdb39ec223")
MADLAD = ("google/madlad400-7b-mt", "1ff63ce7ddd571a69d45cad9672c553428419671")
TGEMMA = "google/translategemma-12b-it"
PINS = ["bitsandbytes==0.50.2", "accelerate==1.15.0", "ctranslate2==4.8.2", "transformers==4.57.6",
        "sentencepiece==0.2.2", "huggingface_hub==0.36.2", "hf-xet==1.6.0", "tokenizers==0.22.2",
        "safetensors==0.8.0", "protobuf==7.36.2"]
NAMES = {"en": "English", "zh": "Chinese", "fr": "French", "es": "Spanish", "ja": "Japanese", "ru": "Russian",
         "de": "German", "uk": "Ukrainian", "km": "Khmer", "lo": "Lao", "ht": "Haitian Creole"}
S = {"stage": "starting", "log": [], "hymt": None, "madlad": None, "tgemma": None, "hf_token": None}
GPU = threading.Lock()


def log(m):
    S["log"].append(f"{time.strftime('%H:%M:%S')} {m}")
    print(m, flush=True)


def setup():
    try:
        S["stage"] = "pip"
        r = subprocess.run(["pip", "install", "-q", "--break-system-packages"] + PINS, capture_output=True, text=True)
        log(f"pip rc={r.returncode} {(r.stdout + r.stderr)[-800:]}")
        import torch
        from huggingface_hub import snapshot_download
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, T5Tokenizer
        import ctranslate2
        S["stage"] = "hymt"
        src = snapshot_download(HYMT[0], revision=HYMT[1])
        tok = AutoTokenizer.from_pretrained(src)
        tok.padding_side = "left"
        q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
        S["hymt"] = (tok, AutoModelForCausalLM.from_pretrained(src, quantization_config=q, device_map="cuda").eval())
        log(f"hymt loaded, {torch.cuda.memory_allocated() / 1e9:.1f} GB")
        S["stage"] = "madlad"
        src = snapshot_download(MADLAD[0], revision=MADLAD[1], allow_patterns=["*.json", "*.safetensors", "spiece.model"])
        out = "/workspace/madlad7b-ct2"
        if not os.path.exists(os.path.join(out, "model.bin")):
            r = subprocess.run(["ct2-transformers-converter", "--model", src, "--quantization", "int8",
                                "--output_dir", out, "--low_cpu_mem_usage", "--force"], capture_output=True, text=True)
            log(f"ct2 rc={r.returncode} {(r.stdout + r.stderr)[-800:]}")
        S["madlad"] = (T5Tokenizer.from_pretrained(src),
                       ctranslate2.Translator(out, device="cuda", compute_type="int8_float16"))
        log(f"madlad loaded, {torch.cuda.memory_allocated() / 1e9:.1f} GB (torch only)")
        S["stage"] = "ready (tgemma needs /token then /load_tgemma)"
    except Exception:
        S["stage"] = "setup failed"
        log(traceback.format_exc()[-3000:])


def load_tgemma():
    try:
        import torch
        from transformers import AutoModelForImageTextToText, AutoTokenizer
        S["stage"] = "tgemma"
        kw = {"token": S["hf_token"]} if S["hf_token"] else {}
        S["tgemma"] = (AutoTokenizer.from_pretrained(TGEMMA, **kw),
                       AutoModelForImageTextToText.from_pretrained(TGEMMA, dtype=torch.bfloat16, device_map="cuda", **kw).eval())
        log(f"tgemma loaded, {torch.cuda.memory_allocated() / 1e9:.1f} GB")
        S["stage"] = "ready"
    except Exception:
        S["stage"] = "tgemma failed"
        log(traceback.format_exc()[-3000:])


def translate(model, text, src, tgt):
    import torch
    with GPU, torch.inference_mode():
        torch.cuda.synchronize()
        t0 = time.time()
        if model == "hymt":
            tok, m = S["hymt"]
            p = tok.apply_chat_template([{"role": "user", "content":
                f"Translate the following text into {NAMES[tgt]}. Note that you should only output "
                f"the translated result without any additional explanation:\n\n{text}"}],
                tokenize=False, add_generation_prompt=True)
            inp = tok([p], return_tensors="pt", add_special_tokens=False).to("cuda")
            inp.pop("token_type_ids", None)
            n = len(tok.encode(text, add_special_tokens=False))
            g = m.generate(**inp, max_new_tokens=min(1024, n * 10 + 64), do_sample=False, repetition_penalty=1.05)
            out = tok.decode(g[0][inp["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        elif model == "madlad":
            tok, ct2 = S["madlad"]
            pr = f"<2{tgt}> {text}"
            ids = tok.encode(pr)
            r = ct2.translate_batch([tok.convert_ids_to_tokens(ids)], max_decoding_length=min(160, len(ids) * 2 + 24),
                                    beam_size=4, replace_unknowns=False)
            out = tok.decode(tok.convert_tokens_to_ids(r[0].hypotheses[0]), skip_special_tokens=True).strip()
        elif model == "tgemma":
            tok, m = S["tgemma"]
            a, b = NAMES[src], NAMES[tgt]
            # The model card's chat template, rendered by hand (as text-mt/translate_ht.py does).
            p = (f"<bos><start_of_turn>user\nYou are a professional {a} ({src}) to {b} ({tgt}) translator. Your goal is to "
                 f"accurately convey the meaning and nuances of the original {a} text while adhering to {b} grammar, "
                 f"vocabulary, and cultural sensitivities.\nProduce only the {b} translation, without any additional "
                 f"explanations or commentary. Please translate the following {a} text into {b}:\n\n\n"
                 f"{text.strip()}<end_of_turn>\n<start_of_turn>model\n")
            inp = tok([p], return_tensors="pt", add_special_tokens=False).to("cuda")
            g = m.generate(**inp, max_new_tokens=512, do_sample=False)
            out = tok.decode(g[0][inp["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        else:
            raise ValueError(model)
        torch.cuda.synchronize()
        return out, round(time.time() - t0, 3)


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _auth(self):
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            self._send(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self):
        if self._auth():
            self._send(200, {"stage": S["stage"], "log": S["log"][-20:],
                             "loaded": [k for k in ("hymt", "madlad", "tgemma") if S[k]]})

    def do_POST(self):
        if not self._auth():
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if self.path == "/translate":
                t, sec = translate(body["model"], body["text"], body["src"], body["tgt"])
                self._send(200, {"text": t, "gpu_s": sec})
            elif self.path == "/token":
                S["hf_token"] = body.get("hf_token") or None
                self._send(200, {"ok": True})
            elif self.path == "/load_tgemma":
                threading.Thread(target=load_tgemma, daemon=True).start()
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "not found"})
        except Exception:
            self._send(500, {"error": traceback.format_exc()[-3000:]})

    def log_message(self, *a):
        pass


threading.Thread(target=setup, daemon=True).start()
print("controller listening on 0.0.0.0:8000", flush=True)
ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
