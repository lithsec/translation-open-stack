# What the omni-stt recordings (stream_omni.py output) hold, per clip: pieces, piece length, how long after a piece
# ends its final arrives, the streaming track's commit lag, the prototype partials per piece, and CER (NFKC,
# lowercase, letters and digits only, Levenshtein over the joined text) of the finals and of the committed text.
#   python3 -I hearing.py OMNI_OUT CLIPS_ROOT > raw/hearing.json
import glob, json, os, sys, unicodedata

OUT, ROOT = sys.argv[1], sys.argv[2]
norm = lambda s: "".join(c for c in unicodedata.normalize("NFKC", s).lower() if c.isalnum())


def lev(a, b):
    p = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        r = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            r[j] = min(p[j - 1] + (x != y), p[j] + 1, r[j - 1] + 1)
        p = r
    return p[-1]


def pc(v, q):
    v = sorted(v)
    return round(v[min(len(v) - 1, int(q * len(v)))] / 1000, 2) if v else None


res = {}
for f in sorted(glob.glob(os.path.join(OUT, "*.json"))):
    tag, pat, lang = os.path.basename(f)[:-5].split("_")
    ms = json.load(open(f))["messages"]
    ref = norm("".join(json.load(open(os.path.join(ROOT, f"clips_{pat}", f"{lang}.txt.json")))))
    fin = [m for m in ms if m["sock"] == 0 and m["type"] == "inputTranscript"]
    com = [m for m in ms if m["type"] == "committed"]
    par = [m for m in ms if m["sock"] == 0 and m["type"] == "partial"]
    r = {"pieces": len(fin), "piece_s_p50": pc([m["end_ms"] - m["start_ms"] for m in fin], .5),
         "final_after_piece_end_s": [pc([m["t"] - m["end_ms"] for m in fin], .5), pc([m["t"] - m["end_ms"] for m in fin], .9)],
         "final_cer": round(100 * lev(norm("".join(m["text"] for m in fin)), ref) / len(ref), 1)}
    if com:
        r["commit_lag_s"] = [pc([m["t"] - m["end_ms"] for m in com], .5), pc([m["t"] - m["end_ms"] for m in com], .9)]
        r["committed_cer"] = round(100 * lev(norm("".join(m["text"] for m in com)), ref) / len(ref), 1)
    if par:
        r["partials_per_piece"] = round(len(par) / len(fin), 1)
    res[f"{tag}_{pat}_{lang}"] = r
json.dump(res, sys.stdout, indent=1)
