# Characters wrong per recogniser on the 24-sentence set (../../2026-11-khmer-table-talk/code/analyze.py's method:
# NFC, spaces and punctuation removed, corpus edit distance / reference characters), and seconds per sentence.
#   python3 -I cer.py SET24.json RUN.json [RUN.json ...]
import json, statistics as st, sys, unicodedata
S = json.load(open(sys.argv[1])); ref = {s["km_file"]: s["km"] for s in S}
def norm(s): return "".join(c for c in unicodedata.normalize("NFC", s or "") if not (c.isspace() or unicodedata.category(c).startswith("P")))
def lev(a, b):
    p = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        c = [i]
        for j, y in enumerate(b, 1): c.append(min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (x != y)))
        p = c
    return p[-1]
def score(rows):
    rows = [r for r in rows if r["file"] in ref]
    e = sum(lev(norm(ref[r["file"]]), norm(r["hyp"])) for r in rows); n = sum(len(norm(ref[r["file"]])) for r in rows)
    out = {"n": len(rows), "cer": round(100 * e / n, 1), "empty": sum(1 for r in rows if not r["hyp"].strip())}
    if rows and "s" in rows[0]:
        out |= {"s_p50": round(st.median(r["s"] for r in rows), 2), "rtf": round(sum(r["s"] for r in rows) / sum(r["audio_s"] for r in rows), 2)}
    return out
if __name__ == "__main__":
    for f in sys.argv[2:]: print(f, score(json.load(open(f))))
