"""Score sweep.py's out.json per language and setting:

    python3 score_sweep.py <clips> <out.json> [settings...]

CER of all the pieces joined against all the sentences joined (a cut costs
nothing unless words are lost or garbled), pieces, cuts more than 0.3 s inside
a sentence, and the wait after each sentence ends until the piece holding that
end was cut (p50 / p90, s: what a pause rule adds to latency)."""
import json, os, re, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "..", "2026-10-real-voices", "judge.py")).read()
ns = {"re": re, "unicodedata": unicodedata}
exec(src[src.index("def norm"):src.index("def delays")], ns)   # norm() and cer() only: no Vertex
cer = ns["cer"]


def pct(v, q):
    v = sorted(v)
    return round(v[min(len(v) - 1, int(q * (len(v) - 1) + 0.5))], 2) if v else None


def score(clips, ps, lang):
    S = json.load(open(os.path.join(clips, f"{lang}.json")))["sentences"]
    gold = json.load(open(os.path.join(clips, f"{lang}.txt.json")))
    waits = []
    for s in S:
        held = [p for p in ps if p["a"] <= s["end"] <= p["e"] + 0.3]
        if held:
            waits.append(held[0]["t"] - s["end"])
    return {"cer": round(cer(" ".join(gold), " ".join(p["text"] for p in ps)), 4), "pieces": len(ps),
            "inside": sum(1 for p in ps for s in S if s["start"] + 0.3 < p["e"] < s["end"] - 0.3),
            "wait_p50": pct(waits, .5), "wait_p90": pct(waits, .9)}


if __name__ == "__main__":
    CL, F = sys.argv[1], sys.argv[2]
    d = json.load(open(F))
    names = sys.argv[3:] or list(d["res"])
    out = {n: {l: score(CL, ps, l) for l, ps in d["res"][n].items()} for n in names}
    langs = list(next(iter(out.values())))
    print("setting".ljust(14) + "".join(l.rjust(24) for l in langs))
    for n, r in out.items():
        print(n.ljust(14) + "".join(f"{100 * r[l]['cer']:5.1f}% {r[l]['pieces']:3d}p {r[l]['wait_p50']:4.1f}/{r[l]['wait_p90']:4.1f}s".rjust(24) for l in langs))
    json.dump(out, open(F.replace(".json", ".scores.json"), "w"), indent=1)
