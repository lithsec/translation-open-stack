"""Optional spectral noise reduction in front of the recogniser. Off by default.

    STT_DENOISE=1            turn it on (per connection, its own state)
    STT_DENOISE_NR_DB=12     the most any band is attenuated, in dB (afftdn's nr)
    STT_DENOISE_TRACK_S=1.5  the noise floor is the quietest a band has been in this long
    STT_DENOISE_OVERSUB=3.0  over-subtraction: how far above the floor a band must be to count as speech

Why: in the audio-degradation test (eval/2026-10-real-voices/README.md, "Cleanup
on the room mic") ffmpeg's afftdn (nr 12 dB, noise tracking) in front of
Omnilingual took a room mic (reverb + noise at 10 dB SNR) from +54 to +39
character-error points over clean, mostly by giving the segmenter its pauses
back (English: 25 of 30 sentences dropped, 9 with afftdn). The same filter made
Azure worse (+44 to +45), and RNNoise made Azure worse still (+54), so this is
a plain spectral method, not a learned one, and it is off unless asked for.
This module is an equivalent of afftdn written in numpy, so the service gains
no dependency; its effect through the service is not yet measured (the
measurement was ffmpeg's filter on files). It helps a distant or noisy
microphone; on clean close-mic audio it can only cost a little.

How: a short-time Fourier transform, 512 points at 16 kHz with a 256-sample hop
(50% overlap) under a Hann window, split as its square root at analysis and
again at synthesis so a gain change is tapered at the frame edges too. Per
bin, the power is smoothed over frames and its minimum over the last TRACK_S
seconds (minimum statistics: sub-window minima, as afftdn tracks the quietest
recent frames) is the noise floor; a fall in the noise is followed at once, a
rise after TRACK_S. The gain is Wiener's, from a decision-directed a priori
SNR (Ephraim and Malah) against OVERSUB times the floor, never below
-NR_DB: that floor leaves a little residual noise so speech is not hollowed
out and the gaps do not warble. Overlap-add puts the frames back together.

Streaming: process() takes the 16 kHz float32 blocks the service feeds the
VAD, any size, and keeps the frame, tracker and overlap state between calls, so
block by block gives the same samples as the whole signal at once. The output is
the input delayed by DELAY samples (the overlap, 256 = 16 ms: the first call
leads with that much silence); a block that is a multiple of the hop comes back
the same size as it went in, so the service's 1536-sample blocks keep their
shape and the VAD's windows line up as before. The VAD sees the denoised audio:
the pauses afftdn gave back to the segmenter are the measured gain, and it
would be lost if the VAD listened to the raw signal; the cost is that a soft
onset the reducer attenuates can be missed by the VAD too.

Before the floor has had TRACK_S to settle it is the initial NF_DB per bin
(afftdn's nf), so the first second or so of a connection is barely touched.
"""
import numpy as np

RATE = 16000
N_FFT = 512
HOP = 256
DELAY = N_FFT - HOP            # samples of latency added: 16 ms at 16 kHz
NR_DB = 12.0                   # the gain floor (afftdn's nr)
TRACK_S = 1.5                  # minimum-statistics window
OVERSUB = 3.0                  # over-subtraction factor on the tracked floor (a minimum sits below the mean)
NF_DB = -50.0                  # the floor before anything has been heard (afftdn's nf), dBFS of white noise
SUB_FRAMES = 8                 # frames per minimum-statistics sub-window (128 ms)
POWER_SMOOTH = 0.6             # one-pole smoothing of the per-bin power over frames, for the tracker
DD_SMOOTH = 0.9                # decision-directed weight on the previous frame's clean estimate
EPS = 1e-12


def enabled(env):
    return str(env.get("STT_DENOISE", "0")).strip().lower() in ("1", "true", "yes", "on")


def from_env(env):
    """A fresh Denoiser from the environment, or None when STT_DENOISE is off."""
    if not enabled(env):
        return None
    return Denoiser(nr_db=float(env.get("STT_DENOISE_NR_DB", NR_DB)),
                    track_s=float(env.get("STT_DENOISE_TRACK_S", TRACK_S)),
                    oversub=float(env.get("STT_DENOISE_OVERSUB", OVERSUB)))


def wrap(audio_in, env):
    """audio_in itself when STT_DENOISE is off; otherwise an input whose feed()
    gives the same blocks, denoised, with this connection's own state."""
    den = from_env(env)
    return audio_in if den is None else DenoisedInput(audio_in, den)


class DenoisedInput:
    """AudioIn's feed(bytes) -> blocks, each through the Denoiser."""

    def __init__(self, inner, denoiser):
        self.inner = inner
        self.denoiser = denoiser

    def feed(self, msg):
        return [self.denoiser.process(b) for b in self.inner.feed(msg)]

    def __getattr__(self, name):
        return getattr(self.inner, name)


class Denoiser:
    def __init__(self, nr_db=NR_DB, track_s=TRACK_S, oversub=OVERSUB, rate=RATE):
        if rate != RATE:
            raise ValueError(f"denoise: {rate} Hz; the service's blocks are {RATE} Hz")
        n = np.arange(N_FFT)
        self.win = np.sqrt(0.5 - 0.5 * np.cos(2 * np.pi * n / N_FFT))      # root of a periodic Hann
        self.gain_floor = 10 ** (-abs(nr_db) / 20)
        self.oversub = max(0.0, oversub)
        self.subs = max(1, int(round(track_s * RATE / HOP / SUB_FRAMES)))  # sub-windows in the track window
        bins = N_FFT // 2 + 1
        init = 10 ** (NF_DB / 10) * N_FFT / 2                               # white noise at NF_DB, per bin
        self.mins = np.full((self.subs, bins), np.inf)                       # past sub-windows' minima
        self.mins[0] = init
        self.sub_min = np.full(bins, np.inf)                                 # the current sub-window's
        self.sub_count = 0
        self.smooth = None                                                   # smoothed power, per bin
        self.prev_clean = np.zeros(bins)                                     # last frame's |G X|^2
        self.inbuf = np.zeros(0, dtype=np.float64)                           # samples not yet framed
        self.out = np.zeros(N_FFT, dtype=np.float64)                         # overlap-add accumulator
        self.started = False

    def process(self, block):
        """One block of 16 kHz float samples -> the denoised samples now final
        (the same count for a block that is a multiple of HOP, once the stream
        has started; the output trails the input by DELAY samples)."""
        x = np.asarray(block, dtype=np.float64)
        pieces = []
        if not self.started:
            self.started = True
            pieces.append(np.zeros(DELAY))
        self.inbuf = np.concatenate([self.inbuf, x]) if len(self.inbuf) else x
        n_frames = (len(self.inbuf) - N_FFT) // HOP + 1 if len(self.inbuf) >= N_FFT else 0
        for k in range(n_frames):
            frame = self.inbuf[k * HOP:k * HOP + N_FFT]
            self.out[:N_FFT] += self._frame(frame)
            pieces.append(self.out[:HOP].copy())
            self.out = np.concatenate([self.out[HOP:], np.zeros(HOP)])
        if n_frames:
            self.inbuf = self.inbuf[n_frames * HOP:]
        if not pieces:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(pieces).astype(np.float32)

    def _frame(self, frame):
        spec = np.fft.rfft(frame * self.win)
        power = np.abs(spec) ** 2
        # The tracked floor: the quietest the smoothed power has been in the window.
        if self.smooth is None:
            self.smooth = power.copy()
        else:
            self.smooth = POWER_SMOOTH * self.smooth + (1 - POWER_SMOOTH) * power
        np.minimum(self.sub_min, self.smooth, out=self.sub_min)
        floor = np.minimum(self.sub_min, self.mins.min(axis=0))
        self.sub_count += 1
        if self.sub_count == SUB_FRAMES:
            self.mins = np.roll(self.mins, 1, axis=0)
            self.mins[0] = self.sub_min
            self.sub_min = np.full_like(self.sub_min, np.inf)
            self.sub_count = 0
        noise = self.oversub * floor + EPS
        post = power / noise                                      # a posteriori SNR
        prio = DD_SMOOTH * self.prev_clean / noise + (1 - DD_SMOOTH) * np.maximum(post - 1, 0)
        gain = np.maximum(prio / (1 + prio), self.gain_floor)
        self.prev_clean = (gain ** 2) * power
        return np.fft.irfft(spec * gain, N_FFT) * self.win


def denoise(signal, **kw):
    """The whole signal at once (a fresh Denoiser): what the stream of blocks
    adds up to. The result trails the input by DELAY samples."""
    return Denoiser(**kw).process(np.asarray(signal, dtype=np.float32))
