#!/usr/bin/env python3
"""Energy dips in a clip: short drops below the running loud level, which is
what a cutter without a VAD could cut at, and how close given times are to one.

    python3 dips.py clip.wav [--depths 12,15,18] [--min-ms 60] [--near run.jsonl | --near 12.3,45.6]

Level: RMS per 10 ms frame in dB; the running loud level follows it up fast
(0.1 per frame) and down slowly (0.002 per frame). A dip is a run of frames at
least --min-ms long that sit --depth dB or more under that level. For each
depth: how many dips, per minute, their median length; and with --near, the
share of the given times (seconds, or an event log's piece ends: the `end_ms`
of its `input` events) that fall within 150 ms of a dip's start, against the
same number of random times, so a cutter's choice of boundary can be checked
against the audio. Standard library and numpy.
"""
import argparse
import json
import random
import wave

import numpy as np

FRAME_MS = 10
NEAR_MS = 150


def levels(wav):
    with wave.open(wav) as w:
        rate = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)
    f = rate * FRAME_MS // 1000
    n = len(x) // f
    db = 20 * np.log10(np.sqrt((x[:n * f].reshape(n, f) ** 2).mean(axis=1)) / 32768 + 1e-9)
    lvl = np.zeros(n)
    L = -30.0
    for i in range(n):
        L += (0.1 if db[i] > L else 0.002) * (db[i] - L)
        lvl[i] = L
    return db, lvl


def find_dips(db, lvl, depth, min_ms):
    """(start_ms, length_ms) of each run of frames at least depth dB under the level."""
    q = db < lvl - depth
    out, i, n = [], 0, len(q)
    need = max(1, min_ms // FRAME_MS)
    while i < n:
        if q[i]:
            j = i
            while j < n and q[j]:
                j += 1
            if j - i >= need:
                out.append((i * FRAME_MS, (j - i) * FRAME_MS))
            i = j
        else:
            i += 1
    return out


def times_from(spec):
    """Seconds from a comma list, or piece ends (ms) from an event log."""
    if spec.endswith(".jsonl"):
        out = []
        for line in open(spec, encoding="utf-8"):
            if line.strip():
                e = json.loads(line)
                if e.get("kind") == "input" and e.get("end_ms") is not None:
                    out.append(float(e["end_ms"]))
        return out
    return [float(s) * 1000 for s in spec.split(",") if s.strip()]


def near_share(dips, times):
    if not dips or not times:
        return None
    starts = np.array([s for s, _ in dips], dtype=float)
    return round(sum(1 for t in times if np.min(np.abs(starts - t)) <= NEAR_MS) / len(times), 2)


def main(argv=None):
    ap = argparse.ArgumentParser(description="energy dips in a clip")
    ap.add_argument("wav")
    ap.add_argument("--depths", default="12,15,18,20,25", help="dB under the running level")
    ap.add_argument("--min-ms", type=int, default=60)
    ap.add_argument("--near", help="times to check against dip starts: seconds, or an event log (.jsonl)")
    ap.add_argument("--out", help="write the JSON here too")
    args = ap.parse_args(argv)
    db, lvl = levels(args.wav)
    minutes = len(db) * FRAME_MS / 60000
    times = times_from(args.near) if args.near else []
    random.seed(1)
    rnd = [random.uniform(0, len(db) * FRAME_MS) for _ in times]
    rows = []
    for depth in (float(d) for d in args.depths.split(",")):
        dips = find_dips(db, lvl, depth, args.min_ms)
        row = {"depth_db": depth, "dips": len(dips), "per_min": round(len(dips) / max(1e-9, minutes), 1),
               "len_p50_ms": int(np.median([ln for _, ln in dips])) if dips else 0}
        if times:
            row["times"] = len(times)
            row["near_dip_share"] = near_share(dips, times)
            row["random_near_dip_share"] = near_share(dips, rnd)
        rows.append(row)
    text = json.dumps(rows, indent=1)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
