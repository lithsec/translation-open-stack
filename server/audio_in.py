"""Client audio in: the same 16 kHz blocks whatever size of message a client sends.

Every /translate loop used to take each binary message on its own: resample it
24 -> 16 kHz with a fresh resample_poly, and score its newest 512 samples with
the VAD. That only worked for clients that send ~100 ms per message. A client
sending ~5 ms messages (a dsnoop capture with 5 ms periods, forwarded as read)
got a filter edge at both ends of every message, 190 times a second, and a VAD
fed 85 padded samples at a time: the stack found 0.8 s of "speech" in 42 s of
talking and Whisper transcribed the noise (issue #13).

AudioIn buffers per connection and hands out fixed blocks (BLOCK samples at 16
kHz, a whole number of the VAD's 512-sample windows), resampled by a polyphase
filter that keeps its history across blocks, so the result depends only on the
audio, never on how it was cut into messages. The remainder waits for the next
message. vad_block() scores every window of a block in order, so the VAD's own
state (Silero is recurrent) sees all of the audio.
"""
import numpy as np

IN_RATE = 24000
OUT_RATE = 16000
VAD_WINDOW = 512                 # Silero v5's frame at 16 kHz
BLOCK = 3 * VAD_WINDOW           # 1536 samples = 96 ms at 16 kHz
SMALL_MESSAGE_MS = 20            # under this on average, say so once per connection


class StreamResampler:
    """24 kHz -> 16 kHz (up 2, down 3) with the filter state carried between
    calls: the output of many small calls equals one call on the whole signal."""

    UP, DOWN = 2, 3

    def __init__(self):
        from scipy.signal import firwin
        # As scipy's resample_poly designs it: Kaiser window (beta 5), half-length 10 x max(up, down).
        half = 10 * max(self.UP, self.DOWN)
        taps = firwin(2 * half + 1, 1.0 / max(self.UP, self.DOWN), window=("kaiser", 5.0))
        self.h = (taps * self.UP).astype(np.float64)
        self.zi = np.zeros(len(self.h) - 1)
        self.phase = 0           # upsampled-sample index (mod DOWN) of the next output
        self.delay = half        # the filter's delay at the upsampled rate, dropped once at the start

    def process(self, x):
        from scipy.signal import lfilter
        if not len(x):
            return np.zeros(0, dtype=np.float32)
        up = np.zeros(len(x) * self.UP)
        up[::self.UP] = x
        y, self.zi = lfilter(self.h, 1.0, up, zi=self.zi)
        if self.delay:
            skip = min(self.delay, len(y))
            y, self.delay = y[skip:], self.delay - skip
        start = (-self.phase) % self.DOWN
        out = y[start::self.DOWN]
        self.phase = (self.phase + len(y)) % self.DOWN
        return out.astype(np.float32)


class AudioIn:
    """One connection's input. feed(bytes) -> list of 16 kHz float32 blocks of BLOCK samples."""

    def __init__(self, label=""):
        self.label = label
        self.rs = StreamResampler()
        self.odd = b""                     # a byte left over from an odd-length message
        self.pending = np.zeros(0, dtype=np.float32)
        self.messages = 0
        self.message_bytes = 0
        self.warned = False

    def feed(self, msg):
        self._note(len(msg))
        data = self.odd + msg
        if len(data) % 2:
            data, self.odd = data[:-1], data[-1:]
        else:
            self.odd = b""
        pcm = np.frombuffer(data, "<i2").astype(np.float32) / 32768
        out = self.rs.process(pcm)
        self.pending = np.concatenate([self.pending, out]) if len(self.pending) else out
        n = len(self.pending) // BLOCK
        blocks = [self.pending[i * BLOCK:(i + 1) * BLOCK] for i in range(n)]
        self.pending = self.pending[n * BLOCK:]
        return blocks

    def _note(self, size):
        """Very small messages work now, but they cost a WebSocket frame each: say so once."""
        if self.warned:
            return
        self.messages += 1
        self.message_bytes += size
        if self.messages == 200:
            avg_ms = self.message_bytes / self.messages / 2 / IN_RATE * 1000
            if avg_ms < SMALL_MESSAGE_MS:
                print(f"[stack] {self.label}: client sends {avg_ms:.1f} ms audio messages on average; "
                      f"~100 ms (4800 bytes) is recommended", flush=True)
            self.warned = True


def vad_block(vad, block):
    """Speech probability of a block: the highest of its 512-sample windows,
    each fed in order so the VAD's state follows the whole signal."""
    import torch
    best = 0.0
    with torch.inference_mode():
        for i in range(0, len(block) - VAD_WINDOW + 1, VAD_WINDOW):
            w = torch.tensor(block[i:i + VAD_WINDOW], dtype=torch.float32)
            best = max(best, vad(w, OUT_RATE).item())
    return best
