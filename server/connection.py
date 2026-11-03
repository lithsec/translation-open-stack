"""
What one connection may send, and how output reaches it: the frame and speed
limits and close codes (docs/dev/protocol.md, "Limits and close codes"),
clean() for anything a client chose before it reaches the log, and the send
helpers the solo and room handlers share (Fanout, send_json, send_speech,
speak_to). Part of the server (server/server.py is the entry point).
"""
import asyncio, json, re, time
from concurrent.futures import ThreadPoolExecutor

from engines.base import AudioStream, RATE


# What one connection may send (docs/dev/protocol.md, "Limits and close codes"). A 100 ms
# frame at 24 kHz PCM16 is 4.8 KB; a bigger WebSocket message is refused by the
# websockets library itself (close 1009). Audio faster than AUDIO_MAX_SPEED x
# real time, beyond AUDIO_BURST_S of it in hand (the backlog a client builds
# while the server is busy with an utterance and not reading), is not a
# microphone: close CLOSE_TOO_FAST. Before these a client could post 40 x 4 MB
# frames, a 58-minute "utterance", into one buffer.
MAX_FRAME_BYTES = 256 * 1024
AUDIO_MAX_SPEED = 2.0
AUDIO_BURST_S = 60.0
# Close codes this server uses besides 4401 (token), 4429 (connection limits)
# and 4408 (session time limit), which guarded() sends.
CLOSE_BAD_REQUEST = 4400   # a query parameter the server does not accept
CLOSE_TOO_FAST = 4413      # audio faster than AUDIO_MAX_SPEED x real time
# ?room= ids: a name, not free text (they reach the log).
ROOM_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
# ?cands=: at most this many conversation languages.
MAX_CANDS = 8


def clean(value, n=64):
    """Anything a client chose, made safe to print: at most n characters, no
    newlines or control characters (which could forge or hide log lines)."""
    return "".join(c if c.isprintable() else "?" for c in str(value)[:n])


class AudioMeter:
    """How fast one connection sends audio: a token bucket that refills at
    AUDIO_MAX_SPEED seconds of audio per second and holds AUDIO_BURST_S."""

    def __init__(self, speed=None, burst_s=None, clock=time.monotonic):
        self.speed = speed or AUDIO_MAX_SPEED
        self.burst = burst_s or AUDIO_BURST_S
        self.clock = clock
        self.credit = self.burst
        self.t = clock()

    def take(self, nbytes):
        """Account for a message of nbytes (PCM16 at RATE); False once over the limit."""
        t = self.clock()
        self.credit = min(self.burst, self.credit + (t - self.t) * self.speed)
        self.t = t
        self.credit -= nbytes / 2 / RATE
        return self.credit >= 0


async def too_fast(ws, who):
    print(f"[stack] {who}: audio faster than {AUDIO_MAX_SPEED:g}x real time, closing", flush=True)
    await ws.close(code=CLOSE_TOO_FAST, reason=f"audio faster than {AUDIO_MAX_SPEED:g}x real time")


class Fanout:
    """Everyone listening to one language as a single send() target, so a
    sentence is translated and synthesised once however many listen. A
    listener that has gone is dropped; with none left, send() raises and the
    caller stops making audio nobody will hear."""

    def __init__(self, targets):
        self.targets = list(targets)

    async def send(self, data):
        for w in list(self.targets):
            try:
                await w.send(data)
            except Exception:
                self.targets.remove(w)
        if not self.targets:
            raise ConnectionError("no listener left")


async def send_json(targets, obj):
    """One JSON message to each connection in targets, ignoring any that have gone."""
    data = json.dumps(obj)
    for w in targets:
        try:
            await w.send(data)
        except Exception:
            pass



async def send_speech(w, audio):
    """Send one sentence's audio: bytes, or an AudioStream chunk by chunk as it
    is generated (the listener hears the start while the rest is being made)."""
    if isinstance(audio, AudioStream):
        # On a thread of its own, NOT TTS_POOL: next() blocks (VoxCPM2 waits up to
        # VOXCPM_WAIT_S for a GPU slot, then for each chunk), and in the shared pool
        # the waiters starved every other language's voices (11 Khmer listeners,
        # 8 workers: a 15 s stall; 2026-09-30 audit). One worker also orders close()
        # after a next() still running, so the generator's finally always releases
        # the slot. Not awaited: a cancelled sender need not wait for it.
        loop = asyncio.get_running_loop()
        own = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stream")
        it = audio.chunks
        try:
            while (chunk := await loop.run_in_executor(own, next, it, None)) is not None:
                await w.send(chunk)
        finally:
            own.submit(it.close)
            own.shutdown(wait=False)
    elif audio:
        # In pieces: a long sentence's audio in one frame can exceed the client's
        # message limit (iOS URLSessionWebSocketTask: 1 MB, "Message too long").
        for i in range(0, len(audio), 1 << 16):
            await w.send(audio[i:i + (1 << 16)])


async def speak_to(ws, pipe, text, lang, edition=None):
    """One listener: each sentence's audio the moment it is ready, in order."""
    for fut in pipe.synthesise_futures(text, lang, edition):
        try:
            audio = await asyncio.wrap_future(fut)
        except Exception as e:
            print(f"[stack] tts failed ({lang}): {e}", flush=True)
            continue
        await send_speech(ws, audio)
