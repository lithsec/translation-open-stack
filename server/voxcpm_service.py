"""VoxCPM2 as a local voice service for the stack.

VoxCPM2 (OpenBMB, Apache 2.0) gave the clearest Khmer and Lao of every voice
tested (docs/dev/model-evaluation.md), but it pins its own library versions, so it
runs in its own virtualenv (scripts/prepare-voices.sh) as this small HTTP service, and
server.py calls it over localhost. One model, one generation at a time (RTF
~0.28 on an A100: a five-second sentence takes ~1.4 s, so two to three
listeners stay in real time by taking turns).

It does not queue. A request that finds the model busy for more than
BUSY_WAIT_S (1 s) is answered 503 at once; the stack (engines/voxcpm.py) keeps
at most one sentence in flight per instance and does the waiting itself, where
every instance's free slot is visible. The 1 s covers the moment between the
previous stream's last chunk and the lock being released. Headers go out as
soon as the lock is held (never tens of seconds later, when the client has
given up and marked a healthy instance down), and a request whose client has
already gone is dropped before any GPU work. During a stream, a write to a
listener who hung up fails and stops the generation.

    POST /tts   {"text": "...", "lang": "km"}  ->  mono PCM16 at the rate in X-Sample-Rate
    POST /tts   {"text": "...", "stream": true}
                ->  chunked mono PCM16 at 24 kHz, sent as it is generated (the
                    first chunk comes ~40 ms after the request instead of after
                    the whole sentence, ~2.3 s for five seconds of speech)
                ->  503 "busy" when another generation holds the model > 1 s
    GET  /health                 ->  200 once the model is loaded

Each language speaks in ONE fixed voice, cloned from voices/voxcpm/<lang>.wav
on the volume. Without a reference VoxCPM2 invents a new speaker for every
call, and the stack voices each sentence separately — so one phrase could
switch voice, even from a man to a woman, halfway through.

    python server/voxcpm_service.py --port 8791
"""
import argparse, io, json, select, socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

MODEL_ID = "openbmb/VoxCPM2"

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8791)
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--repo", default=MODEL_ID, help="Hugging Face repo (languages.toml [models.voxcpm])")
ap.add_argument("--revision", default=None, help="pin a model revision (languages.toml [models.voxcpm])")
args = ap.parse_args()

from voxcpm import VoxCPM  # noqa: E402  (after argparse so --help is instant)
import os  # noqa: E402

REF_DIR = os.environ.get("VOXCPM_REF_DIR", "/workspace/voices/voxcpm")


def voice_for(lang):
    """The language's fixed reference voice, if one has been chosen."""
    p = os.path.join(REF_DIR, f"{lang}.wav") if lang and lang.isalpha() else ""
    return {"reference_wav_path": p} if p and os.path.exists(p) else {}

t0 = time.time()
# from_pretrained has no revision argument: resolve the pinned snapshot (from the
# local cache when it is there) and load it by path.
from huggingface_hub import snapshot_download  # noqa: E402
path = snapshot_download(args.repo, revision=args.revision) if args.revision else args.repo
model = VoxCPM.from_pretrained(path, load_denoiser=False)
RATE = int(model.tts_model.sample_rate)
lock = threading.Lock()
BUSY_WAIT_S = 1.0   # see the top: the stack queues, not this service
# Warm up: the first generation compiles kernels.
model.generate(text="Hello.", cfg_value=2.0, inference_timesteps=10)
print(f"[voxcpm] ready in {time.time() - t0:.0f}s at {RATE} Hz on {args.host}:{args.port}", flush=True)


# Streaming output: the model's 48 kHz halved to the stack's 24 kHz with a
# stateful low-pass, so chunk joins are seamless (resampling each chunk on its
# own rings at every edge). Level: a whole clip is peak-normalised, but a
# stream can't know its peak in advance, so it gets a fixed gain that puts
# typical VoxCPM2 speech at the same level, and a soft limiter for louder sentences.
from scipy.signal import firwin, lfilter, lfilter_zi  # noqa: E402
STREAM_RATE = 24000
_TAPS = firwin(63, 0.45) if RATE == 2 * STREAM_RATE else None
STREAM_GAIN = 1.5  # typical clip needs 2.15x to peak at 0.89 (median of 48); 1.8 clipped louder ones


def soft_limit(x, knee=0.9):
    """Untouched below the knee; above it, peaks bend smoothly towards 1.0
    instead of clipping. Per sample, so it can't add seams between chunks."""
    a = np.abs(x)
    over = a > knee
    if over.any():
        x = x.copy()
        x[over] = np.sign(x[over]) * (knee + (1 - knee) * np.tanh((a[over] - knee) / (1 - knee)))
    return x


class Halver:
    def __init__(self):
        self.zi = lfilter_zi(_TAPS, [1.0]) * 0.0 if _TAPS is not None else None
        self.phase = 0

    def __call__(self, x):
        if _TAPS is None:
            return x
        y, self.zi = lfilter(_TAPS, [1.0], x, zi=self.zi)
        out = y[self.phase::2]
        self.phase = (self.phase + len(y)) % 2
        return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # chunked transfer for streams

    def log_message(self, *a):  # quiet: the stack logs per utterance already
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"ok")
        else:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()

    def do_POST(self):
        if self.path != "/tts":
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            text = str(body.get("text", "")).strip()
            if not text:
                raise ValueError("empty text")
            voice = voice_for(str(body.get("lang", "")))
        except Exception as e:
            return self.plain(500, str(e))
        if not self.take():
            return
        if body.get("stream"):
            return self.stream(text, voice)
        try:
            t = time.time()
            try:
                wav = np.asarray(model.generate(text=text, cfg_value=2.0, inference_timesteps=10, **voice),
                                 dtype=np.float32)
            finally:
                lock.release()
            peak = float(np.abs(wav).max()) if wav.size else 0.0
            if peak > 1e-4:
                wav = wav * min(0.891 / peak, 4.0)   # same level as the stack's other voices
            pcm = (np.clip(wav, -1, 1) * 32767).astype("<i2").tobytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("X-Sample-Rate", str(RATE))
            self.send_header("X-Gen-Ms", str(int((time.time() - t) * 1000)))
            self.send_header("Content-Length", str(len(pcm)))
            self.end_headers()
            self.wfile.write(pcm)
        except Exception as e:
            self.plain(500, str(e))

    def plain(self, code, msg):
        msg = msg.encode()[:300]
        self.send_response(code); self.send_header("Content-Length", str(len(msg))); self.end_headers()
        self.wfile.write(msg)

    def client_gone(self):
        """The client closed its end (it gave up): readable with nothing to read.
        It sends nothing else before our answer, so readable means EOF."""
        try:
            r, _, _ = select.select([self.connection], [], [], 0)
            return bool(r) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except OSError:
            return True

    def take(self):
        """Hold the model lock, or answer 503 busy (after BUSY_WAIT_S) and return
        False. A client that has already gone is dropped before any GPU work."""
        if not lock.acquire(timeout=BUSY_WAIT_S):
            self.plain(503, "busy")
            return False
        if self.client_gone():
            lock.release()
            self.close_connection = True
            return False
        return True

    def stream(self, text, voice):
        """Called holding the lock (take()); releases it."""
        halve = Halver()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("X-Sample-Rate", str(STREAM_RATE if _TAPS is not None else RATE))
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for chunk in model.generate_streaming(text=text, cfg_value=2.0, inference_timesteps=10, **voice):
                x = halve(np.asarray(chunk, dtype=np.float32) * STREAM_GAIN)
                pcm = (soft_limit(x) * 32767).astype("<i2").tobytes()
                if pcm:
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(pcm), pcm))
                    self.wfile.flush()
        except Exception as e:
            # The listener hung up (the write failed: generation stops here, the generator is
            # dropped) or the model failed mid-sentence. Headers are out, so no 500: the stream
            # ends without its last chunk, which the client reads as a broken stream.
            if not isinstance(e, (BrokenPipeError, ConnectionResetError)):
                print(f"[voxcpm] stream failed: {e}", flush=True)
            self.close_connection = True
            return
        finally:
            lock.release()
        # The end marker after the lock is free: when the client sees it and sends the next
        # sentence, the model is already free for it.
        try:
            self.wfile.write(b"0\r\n\r\n")
        except OSError:
            self.close_connection = True


ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
