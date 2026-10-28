#!/usr/bin/env python3
"""Clips for the 7B-only measurements, written to OUT (default /workspace/clips;
nothing here is committed):

  ht  CMU Haitian Creole speech (speech.cs.cmu.edu/haitian, read sentences,
      150 native speakers), N utterances spread over speakers, none of the 30
      sentences eval/2026-10-real-voices used (so unseen by every earlier
      omni-stt check); each with its text, for CER.
  en, fr, es  FLEURS test (google/fleurs, CC BY 4.0: en_us, fr_fr, es_419), N
      each, none of the sentence ids eval/2026-10-real-voices used.

    python3 prep_clips.py [OUT] [N]

Writes OUT/<lang>/<k>.wav (16 kHz mono, end silence trimmed) and
OUT/manifest.json {"rows": {lang: [{"i", "clip", "ref", "speaker", "seconds"}]}}.
"""
import io, json, os, random, sys, tarfile, urllib.request

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
RV = os.path.join(HERE, "..", "2026-10-real-voices", "sentences")
OUT = sys.argv[1] if len(sys.argv) > 1 else "/workspace/clips"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 60
RATE = 16000
FLEURS = {"en": "en_us", "fr": "fr_fr", "es": "es_419"}
HF = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
CMU = "http://speech.cs.cmu.edu/haitian/speech/data/cmu_haitian_speech"


def get(url):
    with urllib.request.urlopen(url, timeout=300) as r:
        return r.read()


def to16k(raw):
    w, sr = sf.read(io.BytesIO(raw), dtype="float32")
    if w.ndim > 1:
        w = w.mean(1)
    if sr != RATE:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(sr, RATE)
        w = resample_poly(w, RATE // g, sr // g).astype(np.float32)
    # Trim the silence the recordings carry at each end (relative to their own
    # loudness, 160 ms kept), as eval/2026-10-real-voices/fetch_audio.py does.
    f = RATE // 50
    n = len(w) // f
    if n >= 5:
        rms = np.sqrt((w[: n * f].reshape(n, f) ** 2).mean(1))
        loud = np.where(rms > max(np.percentile(rms, 90) * 0.1, 30 / 32768))[0]
        if len(loud):
            lo, hi = max(0, loud[0] - 8), min(n, loud[-1] + 9)
            if hi - lo >= 0.4 * n:
                w = w[lo * f: hi * f]
    return w


def save(lang, k, w):
    d = os.path.join(OUT, lang)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{k:03d}.wav")
    sf.write(p, w, RATE, subtype="PCM_16")
    return p


def haitian(n):
    seen = set(json.load(open(os.path.join(RV, "ht.json"), encoding="utf-8")))
    utts = []
    for ln in get(f"{CMU}/etc/txt.done.data").decode("utf-8").splitlines():
        p = ln.strip().split('"')
        if len(p) >= 3:
            utt, text = p[0].strip("( ").strip(), p[1].strip()
            # 2-25 words: short utterances too (the short-utterance rows cut them further).
            if 2 <= len(text.split()) <= 25 and text not in seen:
                utts.append((utt, text))
    rnd = random.Random(2610)
    by = {}
    for u in utts:
        by.setdefault(u[0].split("_")[0], []).append(u)
    spks = sorted(by)
    rnd.shuffle(spks)
    chosen = []
    while len(chosen) < n and any(by.values()):
        for s in spks:
            if by[s] and len(chosen) < n:
                chosen.append(by[s].pop(rnd.randrange(len(by[s]))))
    rows = []
    for k, (u, text) in enumerate(chosen):
        w = to16k(get(f"{CMU}/wav/{u}.wav"))
        rows.append({"i": k, "clip": save("ht", k, w), "ref": text, "speaker": u.split("_")[0],
                     "seconds": round(len(w) / RATE, 2)})
    print(f"ht: {len(rows)} clips, {len({r['speaker'] for r in rows})} speakers", flush=True)
    return rows


def fleurs(lang, cfg, n, used):
    rows_by_id = {}
    for line in get(f"{HF}/{cfg}/test.tsv").decode("utf-8").splitlines():
        f = line.split("\t")
        if len(f) >= 7 and f[5].isdigit() and int(f[5]) / 16000 <= 25 and f[0] not in used:
            rows_by_id.setdefault(f[0], []).append((f[1], f[2]))
    rnd = random.Random(2610 + len(lang))
    ids = rnd.sample(sorted(rows_by_id), min(n, len(rows_by_id)))
    want = {rows_by_id[i][0][0]: (i, rows_by_id[i][0][1]) for i in ids}
    got = {}
    with urllib.request.urlopen(f"{HF}/{cfg}/audio/test.tar.gz", timeout=900) as resp:
        with tarfile.open(fileobj=resp, mode="r|gz") as tar:
            for m in tar:
                b = os.path.basename(m.name)
                if b in want and m.isfile():
                    got[b] = to16k(tar.extractfile(m).read())
                    if len(got) == len(want):
                        break
    rows = []
    for k, (b, (i, text)) in enumerate(sorted(want.items(), key=lambda x: int(x[1][0]))):
        if b in got:
            rows.append({"i": k, "clip": save(lang, k, got[b]), "ref": text, "speaker": f"fleurs-{i}",
                         "seconds": round(len(got[b]) / RATE, 2)})
    print(f"{lang}: {len(rows)} clips", flush=True)
    return rows


if __name__ == "__main__":
    used = set(json.load(open(os.path.join(RV, "fleurs_ids.json"))))
    rows = {"ht": haitian(N)}
    for lang, cfg in FLEURS.items():
        rows[lang] = fleurs(lang, cfg, N, used)
    os.makedirs(OUT, exist_ok=True)
    json.dump({"rows": rows}, open(os.path.join(OUT, "manifest.json"), "w"), ensure_ascii=False, indent=1)
