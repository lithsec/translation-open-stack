#!/usr/bin/env python3
"""Leading and trailing silence in voice output, before and after the stack's
trim (server/engines/common.py: voiced_span, trim_silence), with the same
rule the voices use: a 10 ms frame is voiced when its RMS is within 40 dB of
the clip's peak and above -45 dBFS; the trim keeps 60 ms before the first
voiced frame and 80 ms after the last.

    python3 eval/2026-10-ht-voices/silence.py mp3/*.mp3 [more files...]

WAV is read directly (numpy, scipy); anything else is decoded with ffmpeg
when it is installed. One line per file and a summary per voice (the part of
the file name before "__"). The percentages are of each clip's duration, and
the summary's "of audio" is the silence over the voice's total audio.

Numbers from the stored samples are in README.md and in the /speak section
of services/omni-stt/README.md. Note that the stored Coqui samples had
already been through the engine's earlier trim (gen_open.py), and that an MP3
round trip can add or remove a few tens of milliseconds at the ends.
"""
import os
import shutil
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "server"))
from engines.common import (TRIM_BELOW_PEAK_DB, TRIM_FLOOR_DBFS, TRIM_FRAME_MS,  # noqa: E402
                            TRIM_LEAD_MS, TRIM_TAIL_MS, trim_silence, voiced_span)


def load(path):
    """(rate, float32 mono samples in [-1, 1])."""
    if path.lower().endswith(".wav"):
        from scipy.io import wavfile
        rate, x = wavfile.read(path)
        if x.ndim > 1:
            x = x.mean(axis=1)
        if x.dtype.kind == "i":
            x = x.astype("float32") / float(2 ** (8 * x.dtype.itemsize - 1))
        elif x.dtype.kind == "u":
            x = (x.astype("float32") - 128) / 128
        return int(rate), x.astype("float32")
    if not shutil.which("ffmpeg"):
        raise SystemExit(f"{path}: not a WAV file and ffmpeg is not installed")
    rate = 24000
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-f", "f32le", "-ac", "1",
                          "-ar", str(rate), "-"], check=True, capture_output=True).stdout
    return rate, np.frombuffer(out, dtype="<f4").astype("float32")


def measure(path):
    """One file's numbers: duration, lead and tail silence in ms, and what the trim leaves."""
    rate, x = load(path)
    dur_ms = 1000.0 * len(x) / rate
    span = voiced_span(x, rate)
    if span is None:
        return dict(file=path, dur_ms=dur_ms, lead_ms=None, tail_ms=None, after_ms=dur_ms)
    start, end = span
    after = trim_silence(x, rate)
    return dict(file=path, dur_ms=dur_ms, lead_ms=1000.0 * start / rate,
                tail_ms=1000.0 * (len(x) - end) / rate, after_ms=1000.0 * len(after) / rate)


def main(paths):
    if not paths:
        raise SystemExit(__doc__)
    print(f"rule: {TRIM_FRAME_MS} ms frames, voiced above peak-{TRIM_BELOW_PEAK_DB:g} dB and "
          f"{TRIM_FLOOR_DBFS:g} dBFS; keep {TRIM_LEAD_MS} ms lead, {TRIM_TAIL_MS} ms tail")
    print(f"{'file':30s} {'dur s':>6s} {'lead ms':>8s} {'tail ms':>8s} {'silence':>8s} {'after s':>8s} {'cut ms':>7s}")
    rows = []
    for p in paths:
        r = measure(p)
        rows.append(r)
        name = os.path.basename(p)
        if r["lead_ms"] is None:
            print(f"{name:30s} {r['dur_ms'] / 1000:6.2f} {'-':>8s} {'-':>8s} {'no voice':>8s} {r['after_ms'] / 1000:8.2f} {0:7d}")
            continue
        sil = r["lead_ms"] + r["tail_ms"]
        print(f"{name:30s} {r['dur_ms'] / 1000:6.2f} {r['lead_ms']:8.0f} {r['tail_ms']:8.0f} "
              f"{100 * sil / r['dur_ms']:7.1f}% {r['after_ms'] / 1000:8.2f} {r['dur_ms'] - r['after_ms']:7.0f}")
    voices = {}
    for r in rows:
        v = os.path.basename(r["file"]).split("__")[0].rsplit(".", 1)[0]
        voices.setdefault(v, []).append(r)
    print()
    print(f"{'voice':16s} {'files':>5s} {'lead ms (min-med-max)':>22s} {'tail ms (min-med-max)':>22s} {'of audio':>8s} {'after':>8s} {'saved':>8s}")
    for v, rs in voices.items():
        rs = [r for r in rs if r["lead_ms"] is not None]
        if not rs:
            continue
        lead = sorted(r["lead_ms"] for r in rs)
        tail = sorted(r["tail_ms"] for r in rs)
        total = sum(r["dur_ms"] for r in rs)
        after = sum(r["after_ms"] for r in rs)
        sil = sum(r["lead_ms"] + r["tail_ms"] for r in rs)
        med = lambda a: a[len(a) // 2]      # noqa: E731
        print(f"{v:16s} {len(rs):5d} {lead[0]:7.0f}-{med(lead):4.0f}-{lead[-1]:4.0f}      "
              f"{tail[0]:7.0f}-{med(tail):4.0f}-{tail[-1]:4.0f}      {100 * sil / total:7.1f}% "
              f"{100 * (sil - (total - after)) / after:7.1f}% {100 * (total - after) / total:7.1f}%")
    print("\nof audio: lead+tail silence over the voice's total audio; after: the same over the"
          " trimmed audio; saved: what the trim removes.")


if __name__ == "__main__":
    main(sys.argv[1:])
