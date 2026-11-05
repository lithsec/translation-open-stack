"""VoxCPM2 as a local voice service for the stack, batched (nano-vllm-voxcpm).

VoxCPM2 (OpenBMB, Apache 2.0) gave the clearest Khmer and Lao of every voice
tested (docs/dev/model-evaluation.md), but it pins its own library versions, so it
runs in its own virtualenv (scripts/prepare-voices.sh) as this small HTTP service, and
server.py calls it over localhost.

The model runs under nano-vllm-voxcpm (MIT; github a710128/nanovllm-voxcpm): one
copy of the weights per GPU, and every sentence in flight is decoded in the same
batch. VoxCPM's own PyTorch implementation makes one voice at a time behind a lock
(RTF ~0.28 on an A100: two to three listeners per GPU); batched, one GPU makes
several voices at once. Measured for Live Translation (2026-11-05, reference-voice
cloning, real-time streams that keep up): the PyTorch package 1 per A100 and none on
an L4 (RTF 1.38); batched, 16 on an L4 (RTF 0.51) and 32 on an A100 (RTF 0.30, 48
fail). This service takes up to VOXCPM_BATCH (16) sentences at once and
says so on /health (X-Max-Inflight), so the stack sends it that many.

It does not queue past its batch. A request that finds every slot taken for more
than BUSY_WAIT_S (1 s) is answered 503 at once; the stack (engines/voxcpm.py) keeps
at most X-Max-Inflight sentences in flight per instance and does the waiting itself,
where every instance's free slot is visible. Headers go out as soon as a slot is
held, a request whose client has already gone is dropped before any GPU work, and
during a stream a write to a listener who hung up fails and cancels its generation
(the others in the batch go on).

    POST /tts   {"text": "...", "lang": "km"}  ->  mono PCM16 at the rate in X-Sample-Rate
    POST /tts   {"text": "...", "stream": true}
                ->  chunked mono PCM16 at 24 kHz, sent as it is generated
                ->  503 "busy" when every slot is taken for > 1 s
    GET  /health                 ->  200 "ok" once the model is loaded and warm,
                                     X-Max-Inflight: how many sentences it takes at once

Each language speaks in ONE fixed voice, cloned from voices/voxcpm/<lang>.wav
on the volume (encoded once, at start). Without a reference VoxCPM2 invents a new
speaker for every call, and the stack voices each sentence separately — so one
phrase could switch voice, even from a man to a woman, halfway through.

Memory. nano-vllm sizes its cache from gpu_memory_utilization of the WHOLE card and
does not see the other processes on it (the stack, Gemma's vLLM), so the cache is
fixed instead: VOXCPM_KV_BLOCKS (default: enough for VOXCPM_BATCH sentences of
VOXCPM_MAX_LEN tokens). VOXCPM_GPU_UTIL only bounds its own allocation.

    python server/voxcpm_service.py --port 8791
"""
import argparse, asyncio, json, os, queue, select, socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

# server/ is on sys.path (this script's directory); engines.common imports only
# the standard library at load time, so it is safe in VoxCPM2's own virtualenv.
from engines.common import float_to_pcm16

MODEL_ID = "openbmb/VoxCPM2"

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8791)
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--repo", default=MODEL_ID, help="Hugging Face repo (languages.toml [models.voxcpm])")
ap.add_argument("--revision", default=None, help="pin a model revision (languages.toml [models.voxcpm])")
args = ap.parse_args()

BATCH = int(os.environ.get("VOXCPM_BATCH", "16"))           # sentences decoded at once
MAX_LEN = int(os.environ.get("VOXCPM_MAX_LEN", "4096"))     # tokens per sentence (prompt + audio)
BLOCK = 256                                                  # nano-vllm's KV block, tokens
KV_BLOCKS = int(os.environ.get("VOXCPM_KV_BLOCKS", "0")) or -(-BATCH * MAX_LEN // BLOCK)
GPU_UTIL = float(os.environ.get("VOXCPM_GPU_UTIL", "0.9"))
TIMESTEPS = int(os.environ.get("VOXCPM_TIMESTEPS", "10"))   # as the PyTorch service ran it
CFG = 2.0
if BATCH < 1:
    raise SystemExit(f"VOXCPM_BATCH must be at least 1 (got {BATCH})")
# Read by nano-vllm when it sizes the cache (see Memory, above).
os.environ["NANOVLLM_SERVERPOOL_NUM_KVCACHE_BLOCKS"] = str(KV_BLOCKS)

REF_DIR = os.environ.get("VOXCPM_REF_DIR", "/workspace/voices/voxcpm")

from nanovllm_voxcpm import VoxCPM  # noqa: E402  (after argparse so --help is instant)
from huggingface_hub import snapshot_download  # noqa: E402

t0 = time.time()
# The pinned snapshot (from the local cache when it is there), loaded by path.
path = snapshot_download(args.repo, revision=args.revision) if args.revision else snapshot_download(args.repo)

# nano-vllm's pool is asyncio: it lives on a loop of its own, and the HTTP threads
# hand it work with run_coroutine_threadsafe.
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, name="voxcpm-loop", daemon=True).start()


def run(coro, timeout=None):
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)


async def _start():
    pool = VoxCPM.from_pretrained(model=path, inference_timesteps=TIMESTEPS, max_num_seqs=BATCH,
                                  max_num_batched_tokens=max(8192, MAX_LEN), max_model_len=MAX_LEN,
                                  gpu_memory_utilization=GPU_UTIL, devices=[0])
    await pool.wait_for_ready()
    return pool, await pool.get_model_info()

model, info = run(_start())
RATE = int(info["output_sample_rate"])

# The fixed voices, encoded once (reference mode: the voice, not a prefix to continue).
REFS = {}
if os.path.isdir(REF_DIR):
    for f in sorted(os.listdir(REF_DIR)):
        lang, ext = os.path.splitext(f)
        if ext == ".wav" and lang.isalpha():
            REFS[lang] = run(model.encode_latents(open(os.path.join(REF_DIR, f), "rb").read(), "wav"))


def voice_for(lang):
    """The language's fixed reference voice, if one has been chosen."""
    return {"ref_audio_latents": REFS[lang]} if lang in REFS else {}


async def _collect(text, voice):
    return [np.asarray(c, dtype=np.float32) async for c in
            model.generate(target_text=text, cfg_value=CFG, **voice)]

# Warm up: the first generation captures the CUDA graphs.
run(_collect("Hello.", {}))
slots = threading.BoundedSemaphore(BATCH)
BUSY_WAIT_S = 1.0   # see the top: the stack queues, not this service
print(f"[voxcpm] ready in {time.time() - t0:.0f}s at {RATE} Hz on {args.host}:{args.port}: batched "
      f"(nano-vllm-voxcpm), {BATCH} sentences at once, KV cache {KV_BLOCKS} blocks, voices "
      f"{','.join(sorted(REFS)) or 'none'}", flush=True)


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


_END = object()


def stream_chunks(text, voice):
    """The sentence's chunks as they are generated, on this (HTTP) thread. Closing the
    generator early (the listener went away) cancels the sentence in the batch."""
    q = queue.Queue()

    async def pump():
        try:
            async for c in model.generate(target_text=text, cfg_value=CFG, **voice):
                q.put(np.asarray(c, dtype=np.float32))
            q.put(_END)
        except BaseException as e:   # CancelledError included: nano-vllm cancels the sequence
            q.put(e)
            raise

    fut = asyncio.run_coroutine_threadsafe(pump(), loop)
    try:
        while True:
            item = q.get()
            if item is _END:
                return
            if isinstance(item, BaseException):
                raise RuntimeError(f"generation failed: {item!r}")
            yield item
    finally:
        if not fut.done():
            fut.cancel()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # chunked transfer for streams

    def log_message(self, *a):  # quiet: the stack logs per utterance already
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.send_header("Content-Length", "2")
            self.send_header("X-Max-Inflight", str(BATCH)); self.end_headers(); self.wfile.write(b"ok")
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
                parts = run(_collect(text, voice))
            finally:
                slots.release()
            wav = np.concatenate(parts) if parts else np.zeros(0, np.float32)
            peak = float(np.abs(wav).max()) if wav.size else 0.0
            if peak > 1e-4:
                wav = wav * min(0.891 / peak, 4.0)   # same level as the stack's other voices
            pcm = float_to_pcm16(wav)
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
        """Hold a batch slot, or answer 503 busy (after BUSY_WAIT_S) and return
        False. A client that has already gone is dropped before any GPU work."""
        if not slots.acquire(timeout=BUSY_WAIT_S):
            self.plain(503, "busy")
            return False
        if self.client_gone():
            slots.release()
            self.close_connection = True
            return False
        return True

    def stream(self, text, voice):
        """Called holding a slot (take()); releases it."""
        halve = Halver()
        gen = stream_chunks(text, voice)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("X-Sample-Rate", str(STREAM_RATE if _TAPS is not None else RATE))
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for chunk in gen:
                x = halve(chunk * STREAM_GAIN)
                pcm = (soft_limit(x) * 32767).astype("<i2").tobytes()
                if pcm:
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(pcm), pcm))
                    self.wfile.flush()
        except Exception as e:
            # The listener hung up (the write failed: the sentence is cancelled in the batch)
            # or the model failed mid-sentence. Headers are out, so no 500: the stream ends
            # without its last chunk, which the client reads as a broken stream.
            if not isinstance(e, (BrokenPipeError, ConnectionResetError)):
                print(f"[voxcpm] stream failed: {e}", flush=True)
            self.close_connection = True
            return
        finally:
            gen.close()
            slots.release()
        # The end marker after the slot is free: when the client sees it and sends the next
        # sentence, the slot is already free for it.
        try:
            self.wfile.write(b"0\r\n\r\n")
        except OSError:
            self.close_connection = True


ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
