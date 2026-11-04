# Score Chirp 3 on October's Lao clips exactly as hearing.py scored Omnilingual: CER over the joined finals (NFKC,
# lowercase, letters and digits only) against the joined FLEURS text; plus how long after a speaker's sentence ends
# each final arrives (by the clip's own sentence marks), and after Chirp's own end-of-speech (result_end_offset).
import json, sys, unicodedata

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
    return round(v[min(len(v) - 1, int(q * len(v)))], 2) if v else None


for pat in ("reg", "irr"):
    D = f"/tmp/rs/chirp/data/oct_lo/{pat}"
    ref = norm("".join(json.load(open(f"{D}/lo.txt.json"))))
    lay = json.load(open(f"{D}/lo.json"))
    ends = [s["end"] for s in lay["sentences"]]
    ev = json.load(open(f"/tmp/rs/chirp/runs/oct_lo_{pat}.json"))
    fin = [e for e in ev if e["type"] == "final"]
    inter = [e for e in ev if e["type"] == "interim"]
    cer = round(100 * lev(norm("".join(e["text"] for e in fin)), ref) / len(ref), 1)
    # After the speaker's sentence: the last sentence end at or before the final's own end offset.
    after_sentence = []
    for e in fin:
        eo = e["end_offset"]
        prev = [x for x in ends if eo is not None and x <= eo + 0.3]
        if prev: after_sentence.append(e["t"] - prev[-1])
    after_own_end = [e["t"] - e["end_offset"] for e in fin if e["end_offset"] is not None]
    piece = []
    last = 0.0
    for e in fin:
        if e["end_offset"] is not None:
            piece.append(e["end_offset"] - last); last = e["end_offset"]
    print(f"{pat}: finals {len(fin)} (interims {len(inter)}), piece p50 {pc(piece, .5)} s, CER {cer}% | "
          f"final after Chirp's own end p50/p90 {pc(after_own_end, .5)}/{pc(after_own_end, .9)} s | "
          f"after the speaker's sentence end p50/p90 {pc(after_sentence, .5)}/{pc(after_sentence, .9)} s")
