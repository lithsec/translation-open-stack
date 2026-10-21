#!/usr/bin/env python3
"""Pause statistics of a clip: how often the speaker pauses, for how long, and
how much speech runs between pauses, from Silero VAD speech probabilities.

    python3 pauses.py clip.wav --probs clip.npz [--out pauses.json]     # runs Silero (needs torch)
    python3 pauses.py --probs clip.npz [--out pauses.json]              # reuses saved probabilities

The probabilities are computed as omni-stt computes them: Silero VAD (the
pinned revision in services/omni-stt/server.py) over 512-sample windows (32 ms
at 16 kHz), streamed in order, on 96 ms blocks. They are saved to --probs as
`x` (the 16 kHz float audio) and `p` (one probability per window), the file
cutsim.py takes. Silero needs torch (`pip install torch`; the first run
downloads the model through torch.hub); the statistics alone need only numpy.

A gap is a run of windows under the threshold, counted between the first and
last speech window. For each threshold: the number of gaps at least k ms long
(and per minute), and the speech between two gaps of at least k ms (median,
p90, max), which is how long a piece gets when the cutter waits for such a gap.
"""
import argparse
import json
import sys
import wave

import numpy as np

RATE = 16000
WINDOW = 512                 # Silero's frame at 16 kHz
BLOCK = 3 * WINDOW           # omni-stt's 96 ms block
WINDOW_MS = WINDOW * 1000 // RATE
VAD_REPO = "snakers4/silero-vad"
VAD_REF = "5cd7945676eb32225748052e2e6a0580e4686a08"    # services/omni-stt/server.py VAD_REF
GAP_STEPS_MS = (80, 120, 160, 200, 300, 500)
RATE_STEPS_MS = (200, 300, 500)
PHRASE_STEPS_MS = (96, 160, 200, 300, 500)


def read_wav(path):
    with wave.open(path) as w:
        if w.getframerate() != RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit(f"{path}: need {RATE} Hz mono PCM16")
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    n = len(x) // BLOCK
    return x[:n * BLOCK]


def silero_probs(x):
    """One speech probability per 512-sample window, in stream order."""
    import torch
    torch.set_num_threads(1)
    vad, _ = torch.hub.load(f"{VAD_REPO}:{VAD_REF}", "silero_vad", trust_repo=True)
    probs = []
    with torch.inference_mode():
        for i in range(0, len(x) - WINDOW + 1, WINDOW):
            probs.append(vad(torch.tensor(x[i:i + WINDOW]), RATE).item())
    return np.array(probs, dtype=np.float32)


def gaps(p, thr):
    """(gap lengths in ms, first speech window, last speech window)."""
    sp = p >= thr
    if not sp.any():
        return np.zeros(0), 0, -1
    first = int(np.argmax(sp))
    last = len(p) - 1 - int(np.argmax(sp[::-1]))
    runs, i = [], first
    while i <= last:
        if not sp[i]:
            j = i
            while j <= last and not sp[j]:
                j += 1
            runs.append((j - i) * WINDOW_MS)
            i = j
        else:
            i += 1
    return np.array(runs), first, last


def phrases(p, thr, k_ms):
    """Speech between two gaps of at least k_ms, in seconds, one per phrase."""
    sp = p >= thr
    _, first, last = gaps(p, thr)
    i, start, out = first, first, []
    while i <= last:
        if not sp[i]:
            j = i
            while j <= last and not sp[j]:
                j += 1
            if (j - i) * WINDOW_MS >= k_ms:
                out.append((i - start) * WINDOW_MS / 1000)
                start = j
            i = j
        else:
            i += 1
    return np.array(out) if out else np.array([(last + 1 - first) * WINDOW_MS / 1000])


def stats(p, thresholds):
    out = []
    for thr in thresholds:
        runs, first, last = gaps(p, thr)
        if last < first:
            out.append({"threshold": thr, "span_s": 0, "gaps": 0})
            continue
        span_s = (last - first + 1) * WINDOW_MS / 1000
        row = {
            "threshold": thr,
            "span_s": round(span_s),
            "gaps": int(len(runs)),
            "gaps_at_least_ms": {str(k): int((runs >= k).sum()) for k in GAP_STEPS_MS},
            "gaps_per_min_at_least_ms": {str(k): round(float((runs >= k).sum() / span_s * 60), 1) for k in RATE_STEPS_MS},
            "speech_between_gaps_at_least_ms": {},
        }
        for k in PHRASE_STEPS_MS:
            ph = phrases(p, thr, k)
            row["speech_between_gaps_at_least_ms"][str(k)] = {
                "p50_s": round(float(np.median(ph)), 1),
                "p90_s": round(float(np.percentile(ph, 90)), 1),
                "max_s": round(float(ph.max()), 1),
            }
        out.append(row)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="pause statistics from Silero VAD")
    ap.add_argument("wav", nargs="?", help="16 kHz mono PCM16 WAV (omit to reuse --probs)")
    ap.add_argument("--probs", required=True, help="npz with x and p: written when a WAV is given, read otherwise")
    ap.add_argument("--thresholds", default="0.5,0.35,0.2", help="speech probability thresholds")
    ap.add_argument("--out", help="write the JSON here too")
    args = ap.parse_args(argv)
    thresholds = [float(t) for t in args.thresholds.split(",")]
    if args.wav:
        x = read_wav(args.wav)
        p = silero_probs(x)
        np.savez(args.probs, x=x, p=p)
        print(f"{args.probs}: {len(x) / RATE:.1f} s, {len(p)} windows", file=sys.stderr)
    else:
        p = np.load(args.probs)["p"]
    text = json.dumps(stats(p, thresholds), indent=1)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
