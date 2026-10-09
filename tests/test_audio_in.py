"""python3 tests/test_audio_in.py  (numpy + scipy; no torch, no models)

Client audio is processed the same whatever size of message it arrives in
(issue #13): ~5 ms messages used to be resampled one by one, with a filter edge
at both ends of each, and the stack heard noise."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
from audio_in import AudioIn, StreamResampler, BLOCK, IN_RATE, OUT_RATE  # noqa: E402
from scipy.signal import resample_poly  # noqa: E402


def signal(seconds=2.0, seed=1):
    """Speech-like: a few tones with a moving envelope, plus a little noise."""
    t = np.arange(int(seconds * IN_RATE)) / IN_RATE
    rng = np.random.default_rng(seed)
    x = sum(np.sin(2 * np.pi * f * t + p) for f, p in [(180, 0.3), (720, 1.1), (2400, 2.0)])
    x *= 0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)
    return (0.2 * x + 0.01 * rng.standard_normal(len(t))).astype(np.float32)


def pcm16(x):
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


def through(data, size):
    a = AudioIn()
    out = []
    for i in range(0, len(data), size):
        out += a.feed(data[i:i + size])
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


def test_matches_resample_poly_on_the_whole_signal():
    x = signal()
    rs = StreamResampler()
    y = np.concatenate([rs.process(x[i:i + 120]) for i in range(0, len(x), 120)])  # 5 ms pieces
    ref = resample_poly(x.astype(np.float64), 2, 3)
    n = len(y) - 40          # the end is still in the filter (no flush mid-stream)
    err = np.max(np.abs(y[:n] - ref[:n]))
    assert err < 1e-4, err


def test_message_size_no_longer_matters():
    data = pcm16(signal())
    big = through(data, 4800)       # 100 ms messages
    for size in (256, 250, 4801, 2):  # ~5 ms, odd sizes, two bytes at a time
        small = through(data, size)
        n = min(len(big), len(small))
        assert n >= len(big) - BLOCK, (size, len(big), len(small))
        assert np.max(np.abs(big[:n] - small[:n])) < 1e-6, size


def test_blocks_are_whole_and_the_remainder_waits():
    a = AudioIn()
    assert a.feed(b"\x00\x00" * 100) == []          # 100 samples at 24 kHz: not a block yet
    blocks = a.feed(b"\x00\x00" * 4800)             # 200 ms
    assert blocks and all(len(b) == BLOCK for b in blocks)


def test_an_odd_byte_is_carried_to_the_next_message():
    data = pcm16(signal(0.5))
    whole = through(data, len(data))
    halves = AudioIn()
    out = halves.feed(data[:1001]) + halves.feed(data[1001:])
    got = np.concatenate(out)
    assert np.max(np.abs(got - whole[:len(got)])) < 1e-6


def test_small_messages_are_reported_once(capsys=None):
    import io, contextlib
    a = AudioIn("t")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for _ in range(400):
            a.feed(b"\x00\x00" * 120)  # 5 ms
    assert buf.getvalue().count("ms audio messages") == 1
    b = AudioIn("t")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for _ in range(400):
            b.feed(b"\x00\x00" * 2400)  # 100 ms
    assert "ms audio messages" not in buf.getvalue()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
