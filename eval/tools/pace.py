#!/usr/bin/env python3
"""Stream a WAV at real time to a live speech service and log what comes back.

    python3 pace.py --service stack --url ws://localhost:8790 --lang es --src en clip.wav
    python3 pace.py --service omni --url ws://localhost:8080 --langs ht,en clip.wav
    python3 pace.py --service my_adapter.py:MyAdapter --url wss://... clip.wav

The clip (16 kHz mono PCM16 WAV) is sent in 100 ms chunks, each when it ends,
as a microphone would deliver it; the service's own rate is honoured (the
stack wants 24 kHz: the chunk is resampled first). Every message back is one
line of the event log (README.md, "Event log"): a JSON object with `t`, the
milliseconds since the clip's first sample was sent, and `kind`. lag.py reads
that log. Tokens come from the environment (STACK_TOKEN, STT_TOKEN or --token)
and travel in the Authorization header; they are never written to the log.

Built-in adapters: `stack` (docs/dev/protocol.md) and `omni` (omni-stt's
/listen, services/omni-stt/README.md). To point this at another service,
subclass Adapter (below) in your own module and pass `--service
path/to/module.py:ClassName`. Needs numpy and websockets.
"""
import argparse
import asyncio
import importlib
import importlib.util
import json
import os
import sys
import time
import wave
from urllib.parse import urlencode

import numpy as np

CLIP_RATE = 16000
CHUNK_MS = 100
VOICED_RMS = 150          # 10 ms frames over this RMS (about -47 dBFS) are voiced
QUIET_END_S = 10.0        # after the clip: stop when nothing arrived for this long...
TAIL_MAX_S = 45.0         # ...or after this much trailing silence anyway
PACE_LOG_S = 10.0         # a `pace` event (timing drift) this often


# ---------------------------------------------------------------- audio helpers

def read_wav(path):
    """16 kHz mono PCM16 WAV -> bytes of PCM16."""
    with wave.open(path) as w:
        if w.getframerate() != CLIP_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit(f"{path}: need {CLIP_RATE} Hz mono PCM16 "
                             f"(ffmpeg -i in -ar {CLIP_RATE} -ac 1 -sample_fmt s16 out.wav)")
        return w.readframes(w.getnframes())


def chunks(pcm, rate=CLIP_RATE, chunk_ms=CHUNK_MS):
    """The clip as equal chunks of chunk_ms (the last one padded with silence)."""
    size = rate * chunk_ms // 1000 * 2
    out = []
    for i in range(0, len(pcm), size):
        c = pcm[i:i + size]
        out.append(c if len(c) == size else c + bytes(size - len(c)))
    return out


def resample(pcm, rate_in, rate_out):
    """PCM16 bytes at rate_in -> PCM16 bytes at rate_out, linear interpolation.
    Good enough for a speech recogniser's input; not a studio resampler."""
    if rate_in == rate_out:
        return pcm
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    n_out = int(round(len(x) * rate_out / rate_in))
    if len(x) < 2 or n_out < 1:
        return bytes(n_out * 2)
    pos = np.arange(n_out) * (len(x) - 1) / max(1, n_out - 1)
    y = np.interp(pos, np.arange(len(x)), x)
    return np.clip(np.round(y), -32768, 32767).astype("<i2").tobytes()


def voiced(pcm, rate):
    """Where speech is inside an output chunk: (on, off) in ms, the first and
    the end of the last 10 ms frame whose RMS is over VOICED_RMS, or None.
    Some services stream silence between sentences, so "first audio" means the
    first voiced frame, not the first byte."""
    f = max(1, round(rate / 100))
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    n = len(x) // f
    if n == 0:
        return None
    rms = np.sqrt((x[:n * f].reshape(n, f) ** 2).mean(axis=1))
    hot = np.nonzero(rms > VOICED_RMS)[0]
    if len(hot) == 0:
        return None
    return int(hot[0]) * 10, (int(hot[-1]) + 1) * 10


# ---------------------------------------------------------------- the event log

class EventLog:
    """One JSON object per line. `t` is milliseconds on the clip's timeline:
    0 when the first clip chunk starts to be sent (events before that, such
    as the hello, have a negative t)."""

    def __init__(self, path, clock=time.monotonic):
        self.f = open(path, "w", encoding="utf-8")
        self.clock = clock
        self.origin = None              # set by begin(); events before it wait
        self.pending = []
        self.last_event = clock()
        self.audio_samples = 0          # output audio received so far, in samples
        self.count = 0

    def begin(self):
        """The clip starts now: t = 0. Events logged before (the hello, the
        pre-roll) are written now with their negative t."""
        self.origin = self.clock()
        for at, rec in self.pending:
            self._write(at, rec)
        self.pending = []

    def _write(self, at, rec):
        rec["t"] = round((at - self.origin) * 1000, 1)
        self.f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.f.flush()
        self.count += 1

    def __call__(self, kind, **fields):
        now = self.clock()
        self.last_event = now
        rec = {"t": None, "kind": kind}
        rec.update(fields)
        if self.origin is None:
            self.pending.append((now, rec))
        else:
            self._write(now, rec)

    def audio(self, pcm, rate, **fields):
        """An audio chunk: sample count, rate, offset (output samples before
        it), voiced on/off, plus whatever the adapter knows (piece, bytes)."""
        n = len(pcm) // 2
        v = voiced(pcm, rate)
        rec = {"samples": n, "rate": rate, "offset": self.audio_samples}
        if v:
            rec["on"], rec["off"] = v
        rec.update(fields)
        self("audio", **rec)
        self.audio_samples += n

    def close(self):
        if self.origin is None:         # the run never reached the clip: keep what there is
            self.begin()
        self.f.close()


# ---------------------------------------------------------------- adapters

class Adapter:
    """How pace.py talks to one kind of service. Subclass it:

      name          a short label written to the `start` event
      rate          the sample rate the service wants its audio at; pace.py
                    resamples the clip to it (set it in connect() from the hello)
      connect()     open the connection and wait for whatever the service sends
                    first; self.url, self.token and self.options (the
                    --option key=value pairs) are set
      send_chunk(pcm)  send one chunk of PCM16 at self.rate
      on_message(msg)  one message from the service (bytes or str): turn it
                    into event-log lines with self.log(kind, **fields) and
                    self.log.audio(pcm, rate, **fields)
      finish()      the clip is over (send a flush, if the service has one)
      close()       close the connection

    The default connect/send_chunk/close use a `websockets` connection in
    self.ws and the default receive loop iterates it, so a WebSocket service
    only needs on_message (and a connect() that opens self.ws with
    self.open(url) and reads the hello). Anything else: override receive()
    too. Token counts: when the service reports any, call
    self.log_usage(obj, ...) with its usage object; the fields match the
    earlier run logs (prompt, cached, completion, reasoning)."""

    name = "generic"
    rate = CLIP_RATE
    token_env = ""

    def __init__(self, url, token, options, log):
        self.url = url.rstrip("/")
        self.token = token
        self.options = options
        self.log = log
        self.ws = None
        self.preroll_ms = 0     # silence sent before the clip; set by run()

    async def open(self, url, headers=None):
        import websockets
        headers = dict(headers or {})
        if self.token and "Authorization" not in headers:
            headers["Authorization"] = "Bearer " + self.token
        try:    # websockets >= 14
            self.ws = await websockets.connect(url, max_size=2 ** 24, additional_headers=headers)
        except TypeError:
            self.ws = await websockets.connect(url, max_size=2 ** 24, extra_headers=headers)
        return self.ws

    async def connect(self):
        raise NotImplementedError

    async def send_chunk(self, pcm):
        await self.ws.send(pcm)

    async def receive(self):
        async for msg in self.ws:
            await self.on_message(msg)

    async def on_message(self, msg):
        raise NotImplementedError

    async def finish(self):
        pass

    async def close(self):
        if self.ws is not None:
            await self.ws.close()

    def clip_ms(self, service_ms):
        """A time the service counts from its first sample -> the clip's timeline."""
        return None if service_ms is None else service_ms - self.preroll_ms

    def log_usage(self, usage, **extra):
        """Token counts as the earlier run logs recorded them: prompt, cached,
        completion, reasoning (+ status, ms, totalMs, stream when known).
        Accepts OpenAI-style `usage` and Gemini-style `usageMetadata`."""
        u = usage or {}
        pd = u.get("prompt_tokens_details") or {}
        cd = u.get("completion_tokens_details") or {}
        rec = {
            "prompt": u.get("prompt_tokens", u.get("promptTokenCount")),
            "cached": pd.get("cached_tokens", u.get("cachedContentTokenCount", 0)),
            "completion": u.get("completion_tokens", u.get("candidatesTokenCount")),
            "reasoning": cd.get("reasoning_tokens", u.get("thoughtsTokenCount", 0)),
        }
        rec.update(extra)
        self.log("usage", **rec)

    def log_json(self, d):
        """Common message shapes, for adapters to fall back on."""
        if "usage" in d or "usageMetadata" in d:
            self.log_usage(d.get("usage") or d.get("usageMetadata"))
        else:
            self.log("other", data=d)


class StackAdapter(Adapter):
    """The open stack's /translate socket (docs/dev/protocol.md). Options:
    lang (required), src (default en), stream=1, room, priority=1, route=to,
    cands=en,es. Audio is resampled to the hello's rate (24 kHz)."""

    name = "stack"
    token_env = "STACK_TOKEN"

    async def connect(self):
        q = {k: v for k, v in self.options.items() if k in ("lang", "src", "stream", "room", "priority", "route", "cands")}
        if "lang" not in q:
            raise SystemExit("stack: --lang is required")
        await self.open(f"{self.url}/translate?{urlencode(q)}")
        hello = json.loads(await self.ws.recv())
        if hello.get("type") != "hello":
            raise SystemExit(f"stack: expected hello, got {hello}")
        self.rate = int(hello["rate"])
        self.log("hello", rate=self.rate, mode=hello.get("mode"), lang=hello.get("lang"), src=hello.get("src"),
                 edition=hello.get("edition"))

    async def on_message(self, msg):
        if isinstance(msg, (bytes, bytearray)):
            self.log.audio(bytes(msg), self.rate)
            return
        d = json.loads(msg)
        kind = d.get("type")
        if kind == "inputTranscript":
            self.log("input", text=d.get("text", ""))
        elif kind == "transcript":
            self.log("translation", text=d.get("delta", ""))
        elif kind == "route":
            self.log("lang", lang=d.get("src"))
        elif kind == "error":
            self.log("error", detail=d.get("detail", ""))
        else:
            self.log_json(d)


class OmniAdapter(Adapter):
    """omni-stt's /listen socket (services/omni-stt/README.md). Options:
    langs (default en), transcribe. Audio stays at 16 kHz. start_ms/end_ms
    are moved onto the clip's timeline (omni-stt counts from its first sample)."""

    name = "omni"
    token_env = "STT_TOKEN"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.flushed = asyncio.Event()

    async def connect(self):
        q = {"langs": self.options.get("langs", "en")}
        if self.options.get("transcribe"):
            q["transcribe"] = self.options["transcribe"]
        await self.open(f"{self.url}/listen?{urlencode(q)}")
        hello = json.loads(await self.ws.recv())
        if hello.get("type") != "hello":
            raise SystemExit(f"omni: expected hello, got {hello}")
        self.rate = int(hello.get("rate", CLIP_RATE))
        self.log("hello", rate=self.rate, langs=hello.get("langs"))

    async def on_message(self, msg):
        if isinstance(msg, (bytes, bytearray)):
            self.log.audio(bytes(msg), self.rate)
            return
        d = json.loads(msg)
        kind = d.get("type")
        if kind == "inputTranscript":
            self.log("input", text=d.get("text", ""), lang=d.get("lang"), confidence=d.get("confidence"),
                     start_ms=self.clip_ms(d.get("start_ms")), end_ms=self.clip_ms(d.get("end_ms")))
        elif kind == "language":
            self.log("lang", lang=d.get("lang"), confidence=d.get("confidence"),
                     start_ms=self.clip_ms(d.get("start_ms")), end_ms=self.clip_ms(d.get("end_ms")))
        elif kind == "flushed":
            self.log("flushed")
            self.flushed.set()
        elif kind == "error":
            self.log("error", detail=d.get("detail", ""))
        else:
            self.log_json(d)

    async def finish(self):
        await self.ws.send(json.dumps({"type": "flush"}))
        try:
            await asyncio.wait_for(self.flushed.wait(), 30)
        except asyncio.TimeoutError:
            self.log("error", detail="no flushed within 30 s")


ADAPTERS = {"stack": StackAdapter, "omni": OmniAdapter}


def load_adapter(spec):
    """`stack`, `omni`, `module:Class` or `path/to/file.py:Class`."""
    if spec in ADAPTERS:
        return ADAPTERS[spec]
    mod, _, cls = spec.partition(":")
    if not cls:
        raise SystemExit(f"--service {spec}: built-in names are {', '.join(ADAPTERS)}; "
                         "a custom adapter is module:Class or path.py:Class")
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:            # so the adapter can `import pace`, under python -I too
        sys.path.insert(0, here)
    if mod.endswith(".py"):
        s = importlib.util.spec_from_file_location("pace_adapter", mod)
        m = importlib.util.module_from_spec(s)
        s.loader.exec_module(m)
    else:
        m = importlib.import_module(mod)
    return getattr(m, cls)


# ---------------------------------------------------------------- pacing

async def pace(send, pcm_chunks, chunk_ms=CHUNK_MS, clock=time.monotonic, sleep=asyncio.sleep,
               on_tick=None):
    """Send each chunk when it ends: chunk k at origin + (k + 1) * chunk_ms.
    Returns the per-chunk lateness in ms (send time minus due time)."""
    origin = clock()
    late = []
    for k, c in enumerate(pcm_chunks):
        due = origin + (k + 1) * chunk_ms / 1000
        wait = due - clock()
        if wait > 0:
            await sleep(wait)
        late.append((clock() - due) * 1000)
        await send(c)
        if on_tick:
            on_tick(k, late[-1])
    return late


async def run(adapter, pcm16k, log, preroll_s=1.0, quiet_end_s=QUIET_END_S, tail_max_s=TAIL_MAX_S,
              save_audio=None):
    await adapter.connect()
    rate = adapter.rate
    clip = [resample(c, CLIP_RATE, rate) for c in chunks(pcm16k)]
    silence = bytes(len(clip[0]))
    n_pre = int(round(preroll_s * 1000 / CHUNK_MS))
    adapter.preroll_ms = n_pre * CHUNK_MS
    receiver = asyncio.create_task(adapter.receive())
    audio_out = []
    if save_audio:
        orig_audio = log.audio

        def keep(pcm, r, **fields):
            audio_out.append(pcm)
            orig_audio(pcm, r, **fields)
        log.audio = keep

    # Pre-roll: a room is open before anyone speaks.
    for _ in range(n_pre):
        await adapter.send_chunk(silence)
        await asyncio.sleep(CHUNK_MS / 1000)
    log.begin()
    log("start", service=adapter.name, rate=rate, clip_s=round(len(pcm16k) / 2 / CLIP_RATE, 2),
        chunk_ms=CHUNK_MS, preroll_ms=adapter.preroll_ms)
    last_pace = [log.origin]

    def tick(k, late_ms):
        if log.clock() - last_pace[0] >= PACE_LOG_S:
            last_pace[0] = log.clock()
            log("pace", sent_ms=(k + 1) * CHUNK_MS, late_ms=round(late_ms, 1))
    late = await pace(adapter.send_chunk, clip, on_tick=tick)
    clip_end = log.clock()
    # Room tone after the clip: keep the microphone open until output settles.
    k = len(clip)
    while True:
        due = log.origin + (k + 1) * CHUNK_MS / 1000
        wait = due - log.clock()
        if wait > 0:
            await asyncio.sleep(wait)
        await adapter.send_chunk(silence)
        k += 1
        now = log.clock()
        if receiver.done() or now - log.last_event > quiet_end_s or now - clip_end > tail_max_s:
            break
    await adapter.finish()
    await adapter.close()
    try:                    # whatever the service still had to say, then the end
        await asyncio.wait_for(receiver, 5)
    except Exception as e:                          # noqa: BLE001 - closed, cancelled or timed out
        if not isinstance(e, asyncio.TimeoutError):
            log("error", detail=f"receive: {e!r}"[:200])
    log("end", sent_ms=k * CHUNK_MS, late_ms_p50=round(float(np.median(late)), 1),
        late_ms_max=round(float(max(late)), 1))
    if save_audio and audio_out:
        with wave.open(save_audio, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"".join(audio_out))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("wav", help="16 kHz mono PCM16 WAV")
    ap.add_argument("--service", default="stack", help="stack | omni | module:Class | file.py:Class")
    ap.add_argument("--url", required=True, help="the service's base URL, e.g. ws://localhost:8790")
    ap.add_argument("--token", default=None, help="bearer token (default: the adapter's environment variable)")
    ap.add_argument("--lang", help="stack: target language")
    ap.add_argument("--src", help="stack: source language or auto")
    ap.add_argument("--langs", help="omni: candidate languages, e.g. ht,en")
    ap.add_argument("--option", action="append", default=[], metavar="KEY=VALUE",
                    help="any other adapter option (stack: stream=1, room=main; omni: transcribe=ht)")
    ap.add_argument("--out", help="event log path (default: <wav>.<service>.jsonl)")
    ap.add_argument("--save-audio", help="also write the received audio to this WAV")
    ap.add_argument("--preroll", type=float, default=1.0, help="seconds of silence before the clip")
    ap.add_argument("--quiet-end", type=float, default=QUIET_END_S, help="stop after this long without an event")
    ap.add_argument("--tail-max", type=float, default=TAIL_MAX_S, help="never send more trailing silence than this")
    args = ap.parse_args(argv)

    options = {}
    for k in ("lang", "src", "langs"):
        if getattr(args, k):
            options[k] = getattr(args, k)
    for o in args.option:
        k, _, v = o.partition("=")
        options[k] = v
    cls = load_adapter(args.service)
    token = args.token if args.token is not None else os.environ.get(cls.token_env, "")
    out = args.out or f"{os.path.splitext(args.wav)[0]}.{cls.name}.jsonl"
    pcm = read_wav(args.wav)
    if len(pcm) < 2:
        raise SystemExit(f"{args.wav}: no audio")
    log = EventLog(out)
    adapter = cls(args.url, token, options, log)
    try:
        asyncio.run(run(adapter, pcm, log, preroll_s=args.preroll, quiet_end_s=args.quiet_end,
                        tail_max_s=args.tail_max, save_audio=args.save_audio))
    finally:
        log.close()
    print(f"{out}: {log.count} events, {log.audio_samples / max(1, adapter.rate):.1f} s of audio back", file=sys.stderr)


if __name__ == "__main__":
    main()
