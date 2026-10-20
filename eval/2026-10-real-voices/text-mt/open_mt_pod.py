# Pod controller for the ht->en eval: NLLB on :8000/nllb, and starts/switches
# a vLLM OpenAI server on :8001 via :8000/serve. Every request needs API_KEY.
# The RunPod tools can't copy files, so the pod gets it in its start command:
#   image vllm/vllm-openai:v0.30.0-cu129, ports 8000/http 8001/http, disk ~400 GB,
#   env API_KEY=<random>, entrypoint ["/bin/bash", "-c"],
#   cmd ["echo <base64 of this file> | base64 -d > /srv.py && exec python3 -u /srv.py"]
# 80 GB of GPU holds one 27-31B model in bf16; NLLB is dropped before vLLM starts.
import json, os, signal, subprocess, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

KEY = os.environ["API_KEY"]
S = {"vllm": None, "model": None, "nllb": None, "hf_token": None}
LOCK = threading.Lock()
LOG = "/tmp/vllm.log"


def nllb_load():
    import torch
    from transformers import AutoTokenizer
    # Imported directly: through the Auto classes transformers hides the real
    # import error (the vLLM image lacks some of M2M100's requirements).
    from transformers.models.m2m_100.modeling_m2m_100 import M2M100ForConditionalGeneration
    m = "facebook/nllb-200-3.3B"
    tok = AutoTokenizer.from_pretrained(m, src_lang="hat_Latn")
    model = M2M100ForConditionalGeneration.from_pretrained(m, dtype=torch.bfloat16).cuda().eval()
    S["nllb"] = (tok, model)


def nllb(text):
    import torch
    with LOCK:
        if S["nllb"] is None:
            nllb_load()
    tok, model = S["nllb"]
    t0 = time.time()
    enc = tok(text, return_tensors="pt").to("cuda")
    with torch.inference_mode():
        out = model.generate(**enc, forced_bos_token_id=tok.convert_tokens_to_ids("eng_Latn"),
                             num_beams=4, max_new_tokens=256)
    return tok.decode(out[0], skip_special_tokens=True), round(time.time() - t0, 3)


def stop():
    """Ends vLLM so its GPU memory is free (for NLLB)."""
    p = S["vllm"]
    if p and p.poll() is None:
        os.killpg(p.pid, signal.SIGTERM)
        try:
            p.wait(60)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
    S["model"] = None


def serve(model, args):
    with LOCK:
        if S["nllb"] is not None:
            import torch
            S["nllb"] = None
            torch.cuda.empty_cache()
        stop()
        env = {**os.environ, "VLLM_API_KEY": KEY}
        if S["hf_token"]:
            env["HF_TOKEN"] = S["hf_token"]
        S["vllm"] = subprocess.Popen(["vllm", "serve", model, "--host", "0.0.0.0", "--port", "8001"] + args,
                                     env=env, stdout=open(LOG, "w"), stderr=subprocess.STDOUT, start_new_session=True)
        S["model"] = model


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
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
        if not self._auth():
            return
        p = S["vllm"]
        tail = open(LOG).read()[-6000:] if os.path.exists(LOG) else ""
        self._send(200, {"model": S["model"], "vllm_alive": bool(p and p.poll() is None),
                         "nllb_loaded": S["nllb"] is not None, "log": tail})

    def do_POST(self):
        if not self._auth():
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if self.path == "/nllb":
                text, sec = nllb(body["text"])
                self._send(200, {"text": text, "gpu_s": sec})
            elif self.path == "/token":
                S["hf_token"] = body.get("hf_token") or None
                self._send(200, {"ok": True})
            elif self.path == "/pip":  # add a missing package to the image
                r = subprocess.run(["pip", "install", "-q"] + body["pkgs"], capture_output=True, text=True)
                self._send(200, {"rc": r.returncode, "out": (r.stdout + r.stderr)[-3000:]})
            elif self.path == "/stop":
                with LOCK:
                    stop()
                self._send(200, {"ok": True})
            elif self.path == "/serve":
                serve(body["model"], body.get("args", []))
                self._send(200, {"ok": True, "model": body["model"]})
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            import traceback
            self._send(500, {"error": traceback.format_exc()[-4000:]})

    def log_message(self, *a):
        pass


print("controller listening on 0.0.0.0:8000", flush=True)
ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
