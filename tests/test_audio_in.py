"""python3 tests/test_audio_in.py  (numpy + scipy; no torch, no models)

Client audio is processed the same whatever size of message it arrives in
(issue #13): ~5 ms messages used to be resampled one by one, with a filter edge
at both ends of each, and the stack heard noise."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
from audio_in import AudioIn, StreamResampler, QuietBoost, BLOCK, IN_RATE, OUT_RATE  # noqa: E402
import audio_in  # noqa: E402
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


def blocks_of(x):
    return [x[i:i + BLOCK] for i in range(0, len(x) - BLOCK + 1, BLOCK)]


def peak_after(boost, x):
    return max(float(np.max(np.abs(boost(b)))) for b in blocks_of(x))


def test_quiet_talker_is_brought_up_for_the_vad():
    # A sentence peaking at -45 dBFS (the October FLEURS clips that Silero
    # scored under 0.5 throughout) reaches the VAD near -20 dBFS.
    quiet = (0.006 / 0.2 * signal(3.0)[::3][:3 * OUT_RATE] / 1.6).astype(np.float32)
    b = QuietBoost()
    assert peak_after(b, quiet) > 0.05


def test_normal_speech_is_untouched():
    loud = signal(3.0)[::3][:3 * OUT_RATE]
    b = QuietBoost()
    for blk in blocks_of(loud):
        assert np.array_equal(b(blk), blk)


def test_gain_is_bounded_and_silence_stays_silent():
    b = QuietBoost()
    hiss = (1e-4 * np.random.default_rng(3).standard_normal(5 * OUT_RATE)).astype(np.float32)
    assert peak_after(b, hiss) < 0.002              # under the floor: no gain at all
    floor = (0.002 * np.random.default_rng(4).standard_normal(5 * OUT_RATE)).astype(np.float32)
    g = [QuietBoost().gain(blk) for blk in blocks_of(floor)]
    assert max(g) <= audio_in.QUIET_MAX_GAIN
    zeros = np.zeros(BLOCK, dtype=np.float32)
    assert np.array_equal(QuietBoost()(zeros), zeros)


def test_a_loud_word_lowers_the_gain_at_once():
    b = QuietBoost()
    quiet = np.full(BLOCK, 0.004, dtype=np.float32)
    for _ in range(20):
        b(quiet)
    assert b.gain(np.full(BLOCK, 0.5, dtype=np.float32)) == 1.0     # no clipping the next loud word
    # ...and after the speaker has gone quiet again for a few half-lives, a quiet voice is brought up again.
    for _ in range(int(7 * audio_in.QUIET_HALF_LIFE_S * OUT_RATE / BLOCK)):
        g = b.gain(quiet)
    assert g > 8


def test_a_quiet_talker_right_after_a_loud_one_is_heard_from_the_first_word():
    """eval/2026-10-quiet-after-loud: a reader at -60 dBFS 1 s after one at -18
    lost the first words of every such sentence: the slow half-life still held
    the loud level when the quiet voice began."""
    b = QuietBoost()
    loud = np.full(BLOCK, 0.12, dtype=np.float32)        # about -18 dBFS
    gap = np.full(BLOCK, 1e-4, dtype=np.float32)          # a 1 s pause, room hiss
    quiet = np.full(BLOCK, 0.001, dtype=np.float32)       # -60 dBFS
    for _ in range(int(3 * OUT_RATE / BLOCK)):
        b(loud)
    for _ in range(int(1.0 * OUT_RATE / BLOCK)):
        b(gap)
    assert b.gain(quiet) >= 8                             # its first block is already brought up


def test_word_gaps_inside_loud_speech_keep_the_slow_half_life():
    b = QuietBoost()
    loud = np.full(BLOCK, 0.12, dtype=np.float32)
    gap = np.full(BLOCK, 1e-4, dtype=np.float32)
    for _ in range(int(3 * OUT_RATE / BLOCK)):
        b(loud)
    for _ in range(2):                                    # a ~0.2 s gap between words
        b(gap)
    assert b.gain(np.full(BLOCK, 0.05, dtype=np.float32)) < 2   # the next, softer word is not pumped


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
