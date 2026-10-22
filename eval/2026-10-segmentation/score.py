"""Score a replay (replay.py's out.json) against the read sentences:

    python3 score.py <clips> <out.json> [-v]

<clips>/<lang>.json holds the sentence times ("sentences": [{"start","end"}]),
<lang>.txt.json the sentences' text. Columns: CER of all the pieces joined
against all the sentences joined (so a cut costs nothing unless it loses or
garbles words), the number of pieces, cuts that fall more than 0.3 s inside a
sentence, and pieces the recogniser returned empty. -v lists the pieces."""
import json, os, re, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "..", "2026-10-real-voices", "judge.py")).read()
ns = {"re": re, "unicodedata": unicodedata}
exec(src[src.index("def norm"):src.index("def delays")], ns)   # norm() and cer() only: no Vertex
cer = ns["cer"]

CL, F = sys.argv[1], sys.argv[2]
d = json.load(open(F))
out = {}
for lang, ps in d["res"].items():
    S = json.load(open(os.path.join(CL, f"{lang}.json")))["sentences"]
    gold = json.load(open(os.path.join(CL, f"{lang}.txt.json")))
    c = cer(" ".join(gold), " ".join(p["text"] for p in ps))
    inside = sum(1 for p in ps for s in S if s["start"] + 0.3 < p["e"] < s["end"] - 0.3)
    empty = sum(1 for p in ps if not p["text"])
    out[lang] = {"cer": c, "pieces": len(ps), "inside": inside, "empty": empty}
    print(f"{lang}: CER {c:.3f}  pieces {len(ps)} (sentences {len(S)})  cuts inside a sentence {inside}  empty {empty}")
    if "-v" in sys.argv:
        for p in ps:
            print(f"   {p['a']:7.2f}-{p['e']:7.2f} {p['how']:8s} {p['text'][:110]}")
print("mean CER", round(sum(v["cer"] for v in out.values()) / len(out), 4))
