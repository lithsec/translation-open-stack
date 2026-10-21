#!/usr/bin/env python3
"""The voices' silence trim (server/engines/common.py: voiced_span,
trim_silence), on synthetic audio: dead air around a tone is cut to the kept
lead and tail, speech is never cut into, silence and a quiet hiss are left
alone, and to_pcm16's edge ramps still sit on the trimmed ends.

    python3 tests/test_voice_trim.py   (or python3 -m pytest tests/test_voice_trim.py)

Needs numpy and scipy, nothing else.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))
from engines.common import (RATE, TRIM_LEAD_MS, TRIM_TAIL_MS, peak_normalise,  # noqa: E402
                            to_pcm16, trim_silence, voiced_span)

SR = 22050      # Coqui's and MMS's native rate for the Haitian voices (16 kHz for MMS; either works)


def ms(n, rate=SR):
    return int(rate * n / 1000)


def tone(dur_ms, rate=SR, amp=0.5, hz=220.0):
    t = np.arange(ms(dur_ms, rate)) / rate
    return (amp * np.sin(2 * np.pi * hz * t)).astype("float32")


def silence(dur_ms, rate=SR):
    return np.zeros(ms(dur_ms, rate), dtype="float32")


def hiss(dur_ms, dbfs, rate=SR, seed=1):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(ms(dur_ms, rate)) * 10 ** (dbfs / 20)).astype("float32")


def clip(dur_ms, lead_ms, tail_ms, rate=SR, floor=None):
    """lead silence + tone + tail silence, on an optional noise floor."""
    x = np.concatenate([silence(lead_ms, rate), tone(dur_ms, rate), silence(tail_ms, rate)])
    if floor is not None:
        rng = np.random.default_rng(1)
        x = x + rng.standard_normal(len(x)) * 10 ** (floor / 20)
    return x.astype("float32")


def test_dead_air_is_cut_to_the_kept_lead_and_tail():
    x = clip(500, 400, 600)
    y = trim_silence(x, SR)
    # The whole tone, 60 ms before it and 80 ms after it, give or take a frame.
    want = ms(TRIM_LEAD_MS) + ms(500) + ms(TRIM_TAIL_MS)
    assert abs(len(y) - want) <= ms(10), (len(y), want)
    start, end = voiced_span(y, SR)
    assert abs(start - ms(TRIM_LEAD_MS)) <= ms(10)
    assert abs((len(y) - end) - ms(TRIM_TAIL_MS)) <= ms(10)
    # Nothing of the tone is gone: the voiced part is as long as before.
    s0, e0 = voiced_span(x, SR)
    assert abs((end - start) - (e0 - s0)) <= ms(10)


def test_no_leading_silence_is_left_alone_but_the_tail():
    x = clip(500, 0, 600)
    y = trim_silence(x, SR)
    assert np.array_equal(y[:ms(500)], x[:ms(500)])                 # the front is untouched
    assert abs(len(y) - (ms(500) + ms(TRIM_TAIL_MS))) <= ms(10)


def test_no_trailing_silence_is_left_alone_but_the_lead():
    x = clip(500, 400, 0)
    y = trim_silence(x, SR)
    assert np.array_equal(y[-ms(500):], x[-ms(500):])
    assert abs(len(y) - (ms(TRIM_LEAD_MS) + ms(500))) <= ms(10)


def test_all_silent_audio_is_unchanged():
    for x in (silence(800), hiss(800, -50), hiss(800, -60), np.zeros(0, dtype="float32")):
        y = trim_silence(x, SR)
        assert y is x or np.array_equal(y, x), len(x)
        assert voiced_span(x, SR) is None


def test_a_noise_floor_counts_as_silence():
    """A hiss at -50 dBFS under the dead air is trimmed like digital silence."""
    x = clip(500, 400, 600, floor=-50)
    y = trim_silence(x, SR)
    want = ms(TRIM_LEAD_MS) + ms(500) + ms(TRIM_TAIL_MS)
    assert abs(len(y) - want) <= ms(10), (len(y), want)
    # The same after the level is set (the engines normalise first): -50 dBFS
    # of hiss under a tone at -6 dBFS stays silence at -1 dBFS.
    y = trim_silence(peak_normalise(x), SR)
    assert abs(len(y) - want) <= ms(10), (len(y), want)


def test_a_short_lead_is_not_padded():
    x = clip(500, 30, 600)
    y = trim_silence(x, SR)
    assert np.array_equal(y[:ms(30)], x[:ms(30)])
    assert abs(len(y) - (ms(30) + ms(500) + ms(TRIM_TAIL_MS))) <= ms(10)
    x = clip(500, 50, 70)
    assert trim_silence(x, SR) is x                                  # nothing to cut


def test_speech_is_never_cut_into():
    """A soft onset and a soft release (-30 dB below the peak) are inside the
    kept lead and tail; a quiet word 35 dB down, well inside the clip, is kept."""
    soft = tone(40, amp=0.5 * 10 ** (-30 / 20))
    quiet_word = tone(200, amp=0.5 * 10 ** (-35 / 20))
    x = np.concatenate([silence(400), soft, tone(300), silence(100), quiet_word, silence(100),
                        tone(300), soft, silence(600)])
    y = trim_silence(x, SR)
    body = len(x) - ms(400) - ms(600)
    assert abs(len(y) - (ms(TRIM_LEAD_MS) + body + ms(TRIM_TAIL_MS))) <= ms(10)
    # The result is one slice of the input that holds the whole body, soft
    # ends and quiet word included: the trim only touches the dead air.
    a = voiced_span(x, SR)[0] - ms(TRIM_LEAD_MS)
    assert np.array_equal(y, x[a:a + len(y)])
    assert a <= ms(400) and a + len(y) >= ms(400) + body


def test_rate_independent():
    for rate in (16000, 22050, 24000, 44100):
        x = np.concatenate([silence(400, rate), tone(500, rate), silence(600, rate)])
        y = trim_silence(x, rate)
        want = ms(TRIM_LEAD_MS, rate) + ms(500, rate) + ms(TRIM_TAIL_MS, rate)
        assert abs(len(y) - want) <= ms(10, rate), (rate, len(y), want)


def test_ramps_sit_on_the_trimmed_ends():
    """The engines' order: peak_normalise, trim_silence, to_pcm16. The 24 kHz
    output starts and ends at zero (no click) and is the trimmed length."""
    x = clip(500, 400, 600)
    pcm = to_pcm16(trim_silence(peak_normalise(x), SR), SR)
    y = np.frombuffer(pcm, "<i2").astype("float32") / 32768
    want = (TRIM_LEAD_MS + 500 + TRIM_TAIL_MS) * RATE // 1000
    assert abs(len(y) - want) <= RATE // 100, (len(y), want)
    assert abs(y[0]) < 0.01 and abs(y[-1]) < 0.01
    assert 0.85 < np.abs(y).max() < 0.9
    # The ramps are the first and last 3 ms, inside the kept lead and tail.
    n = int(RATE * 0.003)
    assert np.abs(y[:n]).max() < 0.01 and np.abs(y[-n:]).max() < 0.01
    # With nothing to trim (tone from the first sample to the last) the ramps
    # are still there: the ends rise from zero over 3 ms.
    pcm = to_pcm16(trim_silence(peak_normalise(clip(500, 0, 0)), SR), SR)
    y = np.frombuffer(pcm, "<i2").astype("float32") / 32768
    assert abs(y[0]) < 0.01 and abs(y[-1]) < 0.01
    assert np.abs(y[:n // 3]).max() < 0.4 < np.abs(y[n:4 * n]).max()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
