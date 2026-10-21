#!/usr/bin/env python3
"""services/omni-stt/denoise.py, the optional spectral noise reducer: what it
does to a voice-like tone in white noise, to a clean tone, to silence; that the
stream of blocks equals the whole signal; that a connection starts fresh; and
that with STT_DENOISE off nothing touches the audio.

    python3 tests/test_omni_stt_denoise.py      (numpy; scipy for the AudioIn test)
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))                  # audio_in
sys.path.insert(0, os.path.join(ROOT, "services", "omni-stt"))    # denoise, server (the service's)
import denoise as dn  # noqa: E402

R = dn.RATE
SETTLED = int(1.6 * R)       # the floor has had TRACK_S to settle by here


def db(x):
    return 10 * np.log10(max(float(x), 1e-30))


def snr_db(clean, y):
    """SNR of y against clean, over the same samples."""
    return db(np.mean(clean ** 2)) - db(np.mean((y - clean) ** 2))


def aligned(y):
    """The output without its DELAY lead, so y[i] is the input's sample i."""
    return y[dn.DELAY:]


def voice(seconds=4.0):
    """A tone that moves like a voice: a pitch that wobbles, a few harmonics,
    four 'syllables' a second. A steady tone would be absorbed into the floor
    after TRACK_S, as it would by any tracking noise reducer. -20 dBFS RMS;
    a whole number of hops long."""
    t = np.arange(int(seconds * R) // dn.HOP * dn.HOP) / R
    f0 = 180 + 25 * np.sin(2 * np.pi * 2.5 * t)
    ph = 2 * np.pi * np.cumsum(f0) / R
    x = sum(np.sin(h * ph) / h for h in (1, 2, 3, 4, 5))
    x *= 0.5 - 0.5 * np.cos(2 * np.pi * 4 * t)
    return (0.1 * x / np.sqrt(np.mean(x ** 2))).astype(np.float32)


def tone(seconds=1.2):
    t = np.arange(int(seconds * R)) / R
    return (0.1 * np.sqrt(2) * np.sin(2 * np.pi * 440 * t)).astype(np.float32)   # -20 dBFS RMS


def test_white_noise_at_5_db_gains_at_least_5_db():
    clean = voice()
    rng = np.random.default_rng(0)
    x = (clean + rng.standard_normal(len(clean)) * 0.1 * 10 ** (-5 / 20)).astype(np.float32)
    y = aligned(dn.denoise(x))
    n = len(y)
    before, after = snr_db(clean[SETTLED:n], x[SETTLED:n]), snr_db(clean[SETTLED:n], y[SETTLED:n])
    assert 4.5 < before < 5.5, before
    assert after - before >= 5.0, (before, after)       # measured ~7.1 dB (2026-10-21)


def test_a_clean_tone_is_left_alone():
    # A steady tone shorter than TRACK_S: nothing to subtract, nothing lost.
    c = tone()
    y = aligned(dn.denoise(c))
    n, s = len(y), int(0.3 * R)                         # past the stream's 16 ms fade-in
    change = db(np.mean(y[s:] ** 2)) - db(np.mean(c[s:n] ** 2))
    assert abs(change) < 0.1, change                    # measured 0.002 dB
    assert snr_db(c[s:n], y[s:]) > 40, snr_db(c[s:n], y[s:])
    # A clean voice-like tone, 4 s: its own dips set the floor, and it loses under 1 dB.
    c = voice()
    y = aligned(dn.denoise(c))
    n = len(y)
    change = db(np.mean(y[SETTLED:] ** 2)) - db(np.mean(c[SETTLED:n] ** 2))
    assert abs(change) < 1.0, change                    # measured -0.57 dB
    assert snr_db(c[SETTLED:n], y[SETTLED:]) > 15, snr_db(c[SETTLED:n], y[SETTLED:])


def test_silence_in_silence_out():
    z = np.zeros(31 * 1536, dtype=np.float32)            # ~3 s, in the service's blocks
    y = dn.denoise(z)
    assert len(y) == len(z) and not np.any(y)
    # Noise far below anything: it comes back no louder and without pumping.
    low = (np.random.default_rng(9).standard_normal(3 * R) * 10 ** (-70 / 20)).astype(np.float32)
    y = aligned(dn.denoise(low))
    assert np.mean(y ** 2) <= np.mean(low ** 2)
    frames = y[:len(y) // dn.HOP * dn.HOP].reshape(-1, dn.HOP)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    assert rms.max() / np.median(rms) < 2.0, rms.max() / np.median(rms)    # measured 1.3


def test_blocks_equal_the_whole_signal():
    clean = voice(3.0)
    x = (clean + np.random.default_rng(1).standard_normal(len(clean)) * 0.03).astype(np.float32)
    whole = dn.denoise(x)
    assert len(whole) == len(x)
    for size in (1536, 512, 256, 1000, 100, 7):          # the service's block, the VAD's window, odd sizes
        d = dn.Denoiser()
        out = np.concatenate([d.process(x[i:i + size]) for i in range(0, len(x), size)])
        if size % dn.HOP == 0:
            assert len(out) == len(x), (size, len(out))   # a multiple of the hop: a block out per block in
        else:
            assert len(x) - 2 * dn.HOP < len(out) <= len(x), (size, len(out))
        n = len(out)
        assert np.max(np.abs(out - whole[:n])) < 1e-6, size
    # Latency: the output is the input, DELAY samples later.
    d = dn.Denoiser()
    first = d.process(x[:1536])
    assert len(first) == 1536 and not np.any(first[:dn.DELAY]) and dn.DELAY == 256


def test_each_connection_starts_fresh():
    c = voice(2.0)
    noisy = (c + np.random.default_rng(2).standard_normal(len(c)) * 0.05).astype(np.float32)
    a, b = dn.Denoiser(), dn.Denoiser()
    a.process(noisy)                                     # a has heard noise; b has heard nothing
    ya, yb = a.process(c), b.process(c)
    assert np.array_equal(yb, dn.denoise(c))
    assert not np.array_equal(ya, yb)
    env = {"STT_DENOISE": "1"}
    assert dn.from_env(env) is not dn.from_env(env)      # one state per call: per connection
    assert dn.from_env({"STT_DENOISE": "1", "STT_DENOISE_NR_DB": "6"}).gain_floor == 10 ** (-6 / 20)
    assert dn.from_env({"STT_DENOISE": "1", "STT_DENOISE_TRACK_S": "3"}).subs == round(3 * R / dn.HOP / dn.SUB_FRAMES)


def test_off_is_a_no_op():
    from audio_in import AudioIn
    assert dn.from_env({}) is None and dn.from_env({"STT_DENOISE": "0"}) is None
    plain = AudioIn("t")
    assert dn.wrap(plain, {}) is plain and dn.wrap(plain, {"STT_DENOISE": "0"}) is plain
    assert isinstance(dn.wrap(AudioIn("t"), {"STT_DENOISE": "1"}), dn.DenoisedInput)
    # Through the service's audio_input: the flag off gives AudioIn's own blocks.
    import server as stt
    old = os.environ.pop("STT_DENOISE", None)
    try:
        data = (np.clip(voice(0.5), -1, 1) * 32767).astype("<i2").tobytes()
        off = stt.audio_input(16000, "t")
        assert isinstance(off, AudioIn)
        got = np.concatenate(off.feed(data))
        want = np.frombuffer(data, "<i2").astype(np.float32) / 32768
        assert np.array_equal(got, want[:len(got)]) and len(got) == len(want) // 1536 * 1536
        os.environ["STT_DENOISE"] = "1"
        on = stt.audio_input(16000, "t")
        assert isinstance(on, dn.DenoisedInput)
        blocks = on.feed(data)
        assert [len(b) for b in blocks] == [1536] * (len(want) // 1536)
        assert not np.array_equal(np.concatenate(blocks), got)
    finally:
        os.environ.pop("STT_DENOISE", None)
        if old is not None:
            os.environ["STT_DENOISE"] = old


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
