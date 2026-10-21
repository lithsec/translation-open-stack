"""A speaker who never pauses: the real-voice clips' sentences joined with
100-250 ms gaps, so omni-stt's ENDPOINT_MS (700 ms live) never ends a turn and
every cut is MAX_UTTERANCE_S's forced cut.

    python3 make_continuous.py --audio ../2026-10-real-voices/audio --out audio ht en km lo

Per language: <out>/<lang>.wav (16 kHz mono PCM16) and <out>/<lang>.json, the
sentence marks in the new clip ({"sentences": [{"i", "start", "end"}]}, seconds).
Each sentence is cut from the source clip by its mark and levelled to RMS 2000
(int16; peak capped at -1 dBFS), as endpoint_sweep.py --level does (the FLEURS
recordings' gains differ by 30 dB), and a faint noise floor (RMS 8, about
-72 dBFS) runs under the whole clip so the gaps are not digital silence.
Seeded: the same gaps every run.
"""
import argparse
import json
import os

import numpy as np
import soundfile as sf

RATE = 16000


def build(src_wav, src_marks, rng, gap_ms=(100, 250), target_rms=2000.0, lead_s=0.5):
    x, sr = sf.read(src_wav, dtype="int16")
    assert sr == RATE and x.ndim == 1
    marks = json.load(open(src_marks))["sentences"]
    parts = [np.zeros(int(lead_s * RATE), dtype=np.float32)]
    out_marks, t = [], len(parts[0])
    for k, m in enumerate(marks):
        seg = x[int(m["start"] * RATE):int(m["end"] * RATE)].astype(np.float32)
        rms = float(np.sqrt(np.mean(seg ** 2))) or 1.0
        seg = seg * min(target_rms / rms, 29204.0 / (float(np.abs(seg).max()) or 1.0))
        out_marks.append({"i": m["i"], "start": round(t / RATE, 3), "end": round((t + len(seg)) / RATE, 3)})
        parts.append(seg)
        t += len(seg)
        if k < len(marks) - 1:
            gap = np.zeros(int(rng.uniform(*gap_ms) * RATE / 1000), dtype=np.float32)
            parts.append(gap)
            t += len(gap)
    parts.append(np.zeros(int(lead_s * RATE), dtype=np.float32))
    y = np.concatenate(parts)
    y += rng.standard_normal(len(y)).astype(np.float32) * 8.0
    return np.clip(y, -32768, 32767).astype(np.int16), out_marks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="the real-voice clips: <lang>.wav and <lang>.json marks")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20261020)
    ap.add_argument("langs", nargs="+")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for lang in a.langs:
        rng = np.random.default_rng([a.seed, sum(map(ord, lang))])
        y, marks = build(os.path.join(a.audio, f"{lang}.wav"), os.path.join(a.audio, f"{lang}.json"), rng)
        sf.write(os.path.join(a.out, f"{lang}.wav"), y, RATE, subtype="PCM_16")
        json.dump({"lang": lang, "rate": RATE, "seconds": round(len(y) / RATE, 2), "sentences": marks},
                  open(os.path.join(a.out, f"{lang}.json"), "w"), indent=1)
        gaps = [b["start"] - e["end"] for e, b in zip(marks, marks[1:])]
        print(f"{lang}: {len(y) / RATE:.1f} s, {len(marks)} sentences, gaps {min(gaps) * 1000:.0f}-{max(gaps) * 1000:.0f} ms")


if __name__ == "__main__":
    main()
