# Hearing scores per language and arm: CER over the joined finals (October's hearing.py method), the final's delay
# after its own end of speech, after the speaker's sentence end, and the piece length.
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


pc = lambda v, q: round(sorted(v)[min(len(v) - 1, int(q * len(v)))], 2) if v else None


def pieces(lang, arm):
    ev = json.load(open(f"/tmp/rs/chirp/runs/asia_{lang}_{arm}.json"))
    if arm == "chirp":
        out, last = [], 0.0
        for e in ev:
            if e["type"] == "final" and e.get("text", "").strip():
                out.append({"text": e["text"].strip(), "start": last, "end": e["end_offset"], "arrive": e["t"]}); last = e["end_offset"]
        return out
    return [{"text": e["text"].strip(), "start": e["start"], "end": e["end"], "arrive": e["t"]} for e in ev]


if __name__ == "__main__":
    for lang in sys.argv[1:]:
        c = json.load(open(f"/tmp/rs/chirp/data/asia/{lang}/clip.json"))
        ref = norm("".join(c["text"]))
        ends = [s["end"] for s in c["sentences"]]
        for arm in ("chirp", "mai" if lang in ("ja", "vi", "zh") else "azure"):
            try:
                P = pieces(lang, arm)
            except FileNotFoundError:
                continue
            cer = round(100 * lev(norm("".join(p["text"] for p in P)), ref) / len(ref), 1)
            own = [p["arrive"] - p["end"] for p in P]
            after = []
            for p in P:
                prev = [x for x in ends if x <= p["end"] + 0.3]
                if prev and p["end"] - prev[-1] < 1.0: after.append(p["arrive"] - prev[-1])
            print(f"{lang} {arm:6} pieces {len(P):3} piece p50 {pc([p['end'] - p['start'] for p in P], .5)} s | CER {cer:5.1f}% | "
                  f"final after own end p50/p90 {pc(own, .5)}/{pc(own, .9)} s | after sentence end p50/p90 {pc(after, .5)}/{pc(after, .9)} s")
