#!/usr/bin/env python3
"""Accuracy of the service's models on read sentences, clip by clip (no
streaming, no endpointing): the language ID among several candidate sets, and
Omnilingual's CER with the right language and with the one LID picked.

    python3 services/omni-stt/bench.py --eval eval/2026-10-real-voices \\
        --audio ht,en,fr --sets ht,en ht,fr ht,en,fr --pipeline ht,en --out bench.json

<eval>/audio/<lang>.wav + <lang>.json (sentence start/end) and
<eval>/sentences/<lang>.json (the read text), as eval/2026-10-real-voices has.
CER normalises as that eval's judge.py does: NFKC, lowercase, letters and digits only.
"""
import argparse
import json
import os
import sys
import time
import unicodedata
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server  # noqa: E402


def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c for c in s if c.isalnum())


def cer(ref, hyp):
    a, b = norm(ref), norm(hyp)
    if not a:
        return None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / len(a)


def pooled_cer(rows, key):
    """Edit distance over all characters, so long sentences weigh more."""
    edits = sum(r[key] * len(norm(r["ref"])) for r in rows if r.get(key) is not None)
    chars = sum(len(norm(r["ref"])) for r in rows if r.get(key) is not None)
    return edits / chars if chars else None


def clips(eval_dir, lang):
    import numpy as np
    marks = json.load(open(os.path.join(eval_dir, "audio", f"{lang}.json")))
    texts = json.load(open(os.path.join(eval_dir, "sentences", f"{lang}.json")))
    with wave.open(os.path.join(eval_dir, "audio", f"{lang}.wav")) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1, "16 kHz mono expected"
        pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
    for s in marks["sentences"]:
        yield s["i"], texts[s["i"]], pcm[int(s["start"] * 16000):int(s["end"] * 16000)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", required=True)
    ap.add_argument("--audio", default="ht,en")
    ap.add_argument("--sets", nargs="+", default=["ht,en"])
    ap.add_argument("--pipeline", default="ht,en", help="the set whose LID choice decides the transcript")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="bench.json")
    a = ap.parse_args()
    import torch
    m = server.Models()
    sets = [s.split(",") for s in a.sets]
    pipe_set = a.pipeline.split(",")
    rows = []
    for lang in a.audio.split(","):
        for n, (i, ref, pcm) in enumerate(clips(a.eval, lang)):
            if a.limit and n >= a.limit:
                break
            with torch.inference_mode():
                probs = m.lid.classify_batch(torch.tensor(pcm).unsqueeze(0))[0].squeeze()
            lid = {",".join(s): server.constrained_choice(probs, [(c, m.lid_index[c]) for c in s]) for s in sets}
            t0 = time.time()
            hyp = m.transcribe(pcm, lang)
            dt = time.time() - t0
            row = {"lang": lang, "i": i, "seconds": round(len(pcm) / 16000, 2), "ref": ref, "hyp": hyp,
                   "cer": cer(ref, hyp), "asr_s": round(dt, 2),
                   "lid": {k: [c, round(p, 3)] for k, (c, p) in lid.items()}}
            picked = lid.get(",".join(pipe_set), (lang, 1.0))[0]
            if picked != lang:
                # What the service would have sent: decoded as the wrong language.
                row["hyp_pipeline"] = m.transcribe(pcm, picked)
                row["cer_pipeline"] = cer(ref, row["hyp_pipeline"])
            else:
                row["cer_pipeline"] = row["cer"]
            rows.append(row)
            print(f"{lang} {i:2d} {row['seconds']:5.1f}s cer {row['cer']:.3f} rtf {dt / row['seconds']:.2f} "
                  + " ".join(f"[{k}]={c}:{p:.2f}" for k, (c, p) in row["lid"].items()), flush=True)
    summary = {}
    for lang in a.audio.split(","):
        rs = [r for r in rows if r["lang"] == lang]
        audio_s = sum(r["seconds"] for r in rs)
        summary[lang] = {
            "clips": len(rs), "audio_s": round(audio_s, 1),
            "cer_oracle_lang": round(pooled_cer(rs, "cer"), 4),
            "cer_pipeline": round(pooled_cer(rs, "cer_pipeline"), 4),
            "rtf": round(sum(r["asr_s"] for r in rs) / audio_s, 3),
            "lid_correct": {k: sum(r["lid"][k][0] == lang for r in rs) for k in map(",".join, sets) if lang in k.split(",")},
        }
    confusion = {}
    for k in map(",".join, sets):
        confusion[k] = {}
        for r in rows:
            if r["lang"] in k.split(","):
                cell = confusion[k].setdefault(r["lang"], {})
                cell[r["lid"][k][0]] = cell.get(r["lid"][k][0], 0) + 1
    out = {"device": m.device, "card": m.card, "summary": summary, "confusion": confusion, "rows": rows}
    json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"summary": summary, "confusion": confusion}, indent=1))


if __name__ == "__main__":
    main()
