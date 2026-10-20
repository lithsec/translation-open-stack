# Open-weight reasoning LLMs on one GPU pod, served by vLLM, one sentence per
# request. Every request needs API_KEY.
#   image vllm/vllm-openai:v0.31.0, port 8000/http, container disk ~250 GB,
#   env API_KEY=<random>,
#   entrypoint ["bash", "-c"],
#   cmd: "echo <base64 of this file> | base64 -d > /srv.py && exec python3 -u /srv.py"
# The RunPod tools can't copy files, hence the base64 start command.
# At start the models below download one after another into /models (public
# repos, no token), at pinned revisions. POST /load {"name"} (re)starts
# `vllm serve` on 127.0.0.1:8001 for that model; GET / shows the stage.
# POST /chat {chat-completions body without "model"} -> {"text", "gpu_s",
#   "finish", "usage", "reasoning_chars"}: the request is forwarded to vLLM;
#   "text" is the final answer with the reasoning stripped (vLLM's reasoning
#   parser puts the reasoning in a separate field; any leftover <think>…</think>
#   is cut too). gpu_s = time inside the pod for the request.
import json, os, re, subprocess, threading, time, traceback, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

KEY = os.environ["API_KEY"]
IGNORE = ["original/*", "metal/*", "*.md", "LICENSE", "USAGE_POLICY"]
MODELS = {  # name -> (repo, revision, extra vllm args)
    "gpt-oss-120b": ("openai/gpt-oss-120b", "b5c939de8f754692c1647ca79fbf85e8c1e70f8a",
                     ["--reasoning-parser", "openai_gptoss"]),
    "qwen3.8-27b-fp8": ("Qwen/Qwen3.8-27B-FP8", "017b9c7af6b5689d5dd426a76e0bc077eb5ca20a",
                        ["--reasoning-parser", "qwen3", "--limit-mm-per-prompt", '{"image":0,"video":0}',
                         "--speculative-config", '{"method":"mtp","num_speculative_tokens":3}',
                         "--max-num-seqs", "64"]),  # vLLM's 1024 default exceeds its Mamba cache blocks
                                                    # (on the run this went in as /load's "extra")
    "gpt-oss-20b": ("openai/gpt-oss-20b", "6cee5e81ee83917806bbde320786a8fb61efebee",
                    ["--reasoning-parser", "openai_gptoss"]),
    "deepseek-r1-0528-qwen3-8b": ("deepseek-ai/DeepSeek-R1-0528-Qwen3-8B", "6e8885a6ff5c1dc5201574c8fd700323f23c25fa",
                                  ["--reasoning-parser", "deepseek_r1"]),
}
S = {"stage": "starting", "log": [], "downloaded": [], "serving": None, "proc": None}


def log(m):
    S["log"].append(f"{time.strftime('%H:%M:%S')} {m}")
    print(m, flush=True)


def path(name):
    return f"/models/{name}"


def download_all():
    try:
        from huggingface_hub import snapshot_download
        for name, (repo, rev, _) in MODELS.items():
            t0 = time.time()
            snapshot_download(repo, revision=rev, local_dir=path(name), ignore_patterns=IGNORE, max_workers=16)
            S["downloaded"].append(name)
            log(f"downloaded {name} in {time.time() - t0:.0f}s")
    except Exception:
        log("download failed " + traceback.format_exc()[-2000:])


def stop():
    p = S["proc"]
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(60)
        except subprocess.TimeoutExpired:
            p.kill()
    S["proc"], S["serving"] = None, None


def load(name, extra):
    try:
        stop()
        S["stage"] = f"waiting for {name} download"
        while name not in S["downloaded"]:
            time.sleep(5)
        S["stage"] = f"starting vllm {name}"
        args = ["vllm", "serve", path(name), "--served-model-name", "m", "--host", "127.0.0.1", "--port", "8001",
                "--max-model-len", "16384", "--gpu-memory-utilization", "0.90"] + MODELS[name][2] + (extra or [])
        log("cmd: " + " ".join(args))
        S["proc"] = subprocess.Popen(args, stdout=open("/vllm.log", "a"), stderr=subprocess.STDOUT)
        t0 = time.time()
        while True:
            if S["proc"].poll() is not None:
                S["stage"] = f"vllm {name} exited {S['proc'].returncode}"
                log(S["stage"])
                return
            try:
                urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=5)
                break
            except Exception:
                time.sleep(5)
        S["serving"] = name
        S["stage"] = f"ready {name}"
        log(f"vllm {name} ready in {time.time() - t0:.0f}s")
    except Exception:
        S["stage"] = "load failed"
        log(traceback.format_exc()[-2000:])


def chat(body):
    body = dict(body, model="m")
    req = urllib.request.Request("http://127.0.0.1:8001/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    j = json.load(urllib.request.urlopen(req, timeout=600))
    sec = round(time.time() - t0, 3)
    msg = j["choices"][0]["message"]
    text = msg.get("content") or ""
    text = re.sub(r"(?s)^.*</think>", "", text).strip()  # if any reasoning leaked into the content
    reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    return {"text": text, "gpu_s": sec, "finish": j["choices"][0].get("finish_reason"),
            "usage": j.get("usage"), "reasoning_chars": len(reasoning)}


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
        if not self._auth():
            return
        if self.path == "/vllm_log":
            try:
                tail = open("/vllm.log", errors="replace").read()[-6000:]
            except OSError:
                tail = ""
            self._send(200, {"tail": tail})
        else:
            du = subprocess.run(["du", "-sh", "/models"], capture_output=True, text=True).stdout.strip()
            self._send(200, {"stage": S["stage"], "serving": S["serving"], "downloaded": S["downloaded"],
                             "disk": du, "log": S["log"][-20:]})

    def do_POST(self):
        if not self._auth():
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if self.path == "/chat":
                self._send(200, chat(body))
            elif self.path == "/load":
                threading.Thread(target=load, args=(body["name"], body.get("extra")), daemon=True).start()
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "not found"})
        except urllib.error.HTTPError as e:
            self._send(502, {"error": f"vllm {e.code}: {e.read().decode(errors='replace')[:2000]}"})
        except Exception:
            self._send(500, {"error": traceback.format_exc()[-3000:]})

    def log_message(self, *a):
        pass


os.makedirs("/models", exist_ok=True)
threading.Thread(target=download_all, daemon=True).start()
threading.Thread(target=load, args=("gpt-oss-120b", None), daemon=True).start()
print("controller listening on 0.0.0.0:8000", flush=True)
ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
