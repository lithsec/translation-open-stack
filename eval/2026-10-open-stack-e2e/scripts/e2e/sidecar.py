# Sidecar on the stack pod (port 8000/http), same bearer as the stack (STACK_TOKEN).
# GET  /stats         GPU samples (nvidia-smi, 1 s) since the last reset + "[stack]" log lines
# POST /reset         clear samples
# GET  /log?n=200     tail of /workspace/stack.log, only lines starting with "[stack]"/"=="/"note"
# POST /mt_mode       stop the stack server and VoxCPM2, load the stack's own translators
#                     (EngineSet from server/, madlad + hymt, exactly as server.py builds them)
# POST /translate     {"text","src","tgt"} -> {"text","gpu_s"} via EngineSet.translate_batch
import copy, json, os, subprocess, sys, threading, time, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

KEY = os.environ["STACK_TOKEN"]
LOG = "/workspace/stack.log"
SAMPLES, S = [], {"mt": None, "stage": "stack", "err": ""}
LOCK = threading.Lock()


def sampler():
    while True:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,name",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
            used, total, util, name = [x.strip() for x in out.strip().split("\n")[0].split(",")]
            with LOCK:
                SAMPLES.append((round(time.time(), 1), int(used), int(total), int(util), name))
                del SAMPLES[:-20000]
        except Exception:
            pass
        time.sleep(1)


def log_lines(n):
    try:
        with open(LOG, errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []
    keep = [l.rstrip() for l in lines if l.startswith(("[stack]", "==", "note", "edition", "ready", "WARNING"))
            and "token" not in l.lower() and "key" not in l.lower()]
    return keep[-n:]


def mt_mode():
    try:
        S["stage"] = "stopping stack"
        subprocess.run(["pkill", "-f", "server/server[.]py"])
        subprocess.run(["pkill", "-f", "voxcpm_service[.]py"])
        time.sleep(15)
        S["stage"] = "loading translators"
        sys.path.insert(0, "/opt/stack/server")
        os.chdir("/opt/stack/server")
        import server as SV
        from engines.base import Context
        from engines.manager import EngineSet
        langs = os.environ.get("LANGS", "en").split(",")
        srcs = os.environ.get("SRCS", "en").split(",")
        opts = dict(xeng=True, clone_ref=None, omni=False, mms=False, asr_model="large-v3",
                    asr_multi_model="large-v3", asr_revision=None, asr_multi_revision=None,
                    mt_model="google/madlad400-3b-mt", mt_ct2="/workspace/mt/madlad7b-ct2", kokoro=False,
                    coqui=False, voices_dir=None, hymt="/workspace/mt/hymt2-7b-nf4", voxcpm=None,
                    voxcpm_langs=None, edition="nonprofit", voxcpm_max_inflight=None, espeak=False,
                    licence_review={}, voxcpm_shared={})
        ctx = Context(device="cuda", devices={}, models=SV.MODELS, table=copy.deepcopy(SV.LANG_CONFIG),
                      tables=SV._T, langs=langs, srcs=srcs, options=opts)
        es = EngineSet(ctx)
        es.load(["madlad", "hymt"])
        S["mt"] = es
        S["stage"] = "mt ready"
    except Exception:
        S["stage"] = "mt failed"
        S["err"] = traceback.format_exc()[-3000:]


GPU = threading.Lock()


def translate(text, src, tgt):
    import torch
    with GPU:
        torch.cuda.synchronize()
        t0 = time.time()
        out = S["mt"].translate_batch(text, [tgt], src)[0]
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
        if not self._auth():
            return
        if self.path.startswith("/stats"):
            with LOCK:
                s = list(SAMPLES)
            self._send(200, {"stage": S["stage"], "err": S["err"], "samples": s})
        elif self.path.startswith("/log"):
            n = int(self.path.split("n=")[-1]) if "n=" in self.path else 200
            self._send(200, {"stage": S["stage"], "lines": log_lines(n)})
        else:
            self._send(200, {"stage": S["stage"], "err": S["err"]})

    def do_POST(self):
        if not self._auth():
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if self.path == "/reset":
                with LOCK:
                    SAMPLES.clear()
                self._send(200, {"ok": True})
            elif self.path == "/mt_mode":
                threading.Thread(target=mt_mode, daemon=True).start()
                self._send(200, {"ok": True})
            elif self.path == "/translate":
                t, sec = translate(body["text"], body["src"], body["tgt"])
                self._send(200, {"text": t, "gpu_s": sec})
            else:
                self._send(404, {"error": "not found"})
        except Exception:
            self._send(500, {"error": traceback.format_exc()[-3000:]})

    def log_message(self, *a):
        pass


threading.Thread(target=sampler, daemon=True).start()
ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
