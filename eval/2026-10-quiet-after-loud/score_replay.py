# Score q_replay.py output: characters wrong against what was said, sentence starts lost (the
# sentence's first voiced audio not inside any piece sent to the recogniser), pieces, cuts.
#   UNSEEN=<dir with clips_reg/, clips_irr/, out/witness/ from ../2026-10-unseen> python3 score_replay.py replay.json
import json, os, sys, wave
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "2026-10-real-voices"))
from judge import cer  # noqa: E402
H = os.environ["UNSEEN"]
R = json.load(open(sys.argv[1]))["res"]
out = {}


def said(lang, var):
    txt = json.load(open(f"{H}/clips_{var}/{lang}.txt.json"))
    wp = f"{H}/out/witness/{lang}.json"
    if os.path.exists(wp):
        w = {r["i"]: r.get("said") for r in json.load(open(wp))}
        txt = [w.get(i) or t for i, t in enumerate(txt)]
    return txt


def onsets(lang, var):
    meta = json.load(open(f"{H}/clips_{var}/{lang}.json"))
    with wave.open(f"{H}/clips_{var}/{lang}.wav") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
    res = []
    for s in meta["sentences"]:
        a, e = int(s["start"] * 16000), int(s["end"] * 16000)
        seg = np.abs(x[a:e])
        fr = [seg[i:i + 320].max() for i in range(0, len(seg) - 320, 320)]
        thr = 0.15 * np.percentile(fr, 95)
        k = next(i for i, v in enumerate(fr) if v >= thr)
        res.append(s["start"] + k * 0.02)
    return res


for var_name, clips in R.items():
    for clip, pieces in clips.items():
        lang, cond = clip.split("_", 1)
        var = cond if cond in ("reg", "irr") else "reg"
        ref = said(lang, var)
        hyp = " ".join(p["text"] for p in pieces if p["text"])
        on = onsets(lang, var)
        lost = sum(1 for t in on if not any(p["a"] - 0.15 <= t <= p["e"] for p in pieces))
        empty = sum(1 for p in pieces if not p["text"].strip())
        out.setdefault(clip, {})[var_name] = {"cer": round(100 * cer(" ".join(ref), hyp), 1), "starts_lost": lost,
                                              "pieces": len(pieces), "forced": sum(1 for p in pieces if p["how"] != "end"),
                                              "empty": empty}
for clip in sorted(out):
    print(clip.ljust(12), "  ".join(f"{v}: {d['cer']:5.1f}% lost {d['starts_lost']} pcs {d['pieces']}" for v, d in out[clip].items()))
json.dump(out, open(sys.argv[1].replace(".json", ".scores.json"), "w"), indent=1)
