#!/usr/bin/env python3
"""Offline checks on the GPU, by the service's own code (services/omni-stt/server.py):

  lid  VoxLingua107 ECAPA with the constrained argmax (server.constrained_choice,
       the stack's Pipeline.identify_conf) on every clip of CLIPS, whole and cut to
       its first 3 / 2 / 1.5 / 1 s, among realistic candidate sets. The same model
       and rule run on omni-stt and on the 7B service, so this is the 7B-only
       layout's switch detection too.
  cer  Haitian Creole CER of the 300M card (omni-stt's) and the 7B card on the
       same clips, each decoded with the ht code, batched as the service does
       (server.decode_batch), then its repetition guard. CER as eval/tools/judge.py.

    python3 offline.py lid CLIPS OUT.json
    python3 offline.py cer CLIPS OUT.json [card ...]

OUT.json keeps per-clip scores (and, for cer, the texts) on the pod only; the
README carries the summaries.
"""
import json, os, sys, time

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "services", "omni-stt"))
sys.path.insert(0, os.path.join(ROOT, "eval", "tools"))
import server as stt  # noqa: E402
from judge import cer  # noqa: E402

SETS = [["ht", "en"], ["ht", "fr"], ["ht", "es"], ["ht", "en", "fr"], ["ht", "en", "fr", "es"]]
CUTS = [None, 3.0, 2.0, 1.5, 1.0]
SR = 16000


def clips(path):
    rows = json.load(open(os.path.join(path, "manifest.json"), encoding="utf-8"))["rows"]
    for lang, rs in rows.items():
        for r in rs:
            w, sr = sf.read(r["clip"], dtype="float32")
            assert sr == SR
            yield lang, r, w


def lid(path, out):
    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model, index = stt.load_lid(dev)
    res = []
    t0 = time.time()
    for lang, r, w in clips(path):
        for cut in CUTS:
            x = w if cut is None else w[: int(cut * SR)]
            if cut is not None and len(w) < cut * SR * 0.9:
                continue   # a clip shorter than the cut is the whole-clip row already
            with torch.inference_mode():
                probs = model.classify_batch(torch.tensor(x).unsqueeze(0))[0].squeeze()
            row = {"lang": lang, "i": r["i"], "cut": cut or round(len(w) / SR, 2), "whole": cut is None, "sets": {}}
            for s in SETS:
                if lang not in s:
                    continue
                best, conf = stt.constrained_choice(probs, [(c, index[c]) for c in s])
                scores = {c: float(probs[index[c]]) for c in s}
                row["sets"][",".join(s)] = {"pick": best, "conf": round(conf, 4),
                                            "scores": {c: round(v, 3) for c, v in scores.items()}}
            res.append(row)
    print(f"lid: {len(res)} rows in {time.time() - t0:.0f}s", flush=True)
    json.dump(res, open(out, "w"), indent=0)
    summary(res)


def summary(res):
    for s in SETS:
        key = ",".join(s)
        for cut in ["whole"] + CUTS[1:]:
            rows = [r for r in res if key in r["sets"] and (r["whole"] if cut == "whole" else (not r["whole"] and r["cut"] == cut))]
            ht = [r for r in rows if r["lang"] == "ht"]
            other = [r for r in rows if r["lang"] != "ht"]
            miss = sum(r["sets"][key]["pick"] != "ht" for r in ht)
            false = sum(r["sets"][key]["pick"] == "ht" for r in other)
            wrong_other = sum(r["sets"][key]["pick"] not in ("ht", r["lang"]) for r in other)
            print(f"{key:12s} {str(cut):6s} ht {len(ht) - miss}/{len(ht)} (missed {miss})  "
                  f"others->ht {false}/{len(other)}  others->other {wrong_other}", flush=True)


def cer_run(path, out, cards):
    import torch
    dev = "cuda"
    ht = [(r, w) for lang, r, w in clips(path) if lang == "ht"]
    res = {}
    for card in cards:
        t0 = time.time()
        eng = stt.load_omni(dev, card)
        texts = []
        for k in range(0, len(ht), 8):
            batch = [(w, "ht") for _, w in ht[k:k + 8]]
            for (r, w), t in zip(ht[k:k + 8], stt.decode_batch(eng, batch)):
                kept, _ = stt.repetition_guard(t, len(w) / SR)
                texts.append(kept)
        refs = [r["ref"] for r, _ in ht]
        # Pooled over characters, as judge.cer per clip weighted by reference length.
        from judge import norm_text, edit_distance
        num = sum(edit_distance("".join(norm_text(a).split()), "".join(norm_text(b).split())) for a, b in zip(refs, texts))
        den = sum(len("".join(norm_text(a).split())) for a in refs)
        res[card] = {"pooled_cer": round(num / den, 4), "mean_clip_cer": round(float(np.mean([cer(a, b) for a, b in zip(refs, texts)])), 4),
                     "n": len(refs), "seconds": round(time.time() - t0, 1),
                     "clips": [{"i": r["i"], "ref": r["ref"], "hyp": t, "cer": cer(r["ref"], t)} for (r, _), t in zip(ht, texts)]}
        print(f"{card}: pooled CER {res[card]['pooled_cer']:.3f}  mean {res[card]['mean_clip_cer']:.3f}  n={len(refs)}", flush=True)
        del eng
        torch.cuda.empty_cache()
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    what, path, out = sys.argv[1:4]
    if what == "lid":
        lid(path, out)
    elif what == "cer":
        cer_run(path, out, sys.argv[4:] or ["omniASR_LLM_300M", "omniASR_LLM_7B_bf16"])
    elif what == "summary":
        summary(json.load(open(path)))
