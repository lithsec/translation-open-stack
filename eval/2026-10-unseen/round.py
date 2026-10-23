# jobs: one blind round per (pause pattern, direction), every system that ran it side by side,
# graded against the written text, and for English sources also against what was said.
# table: quality (share of the possible 3 per sentence), critical errors, against both references.
# For other sources "said" = the sentences whose recording matches its text (witness), scored alone.
import json, os, sys
H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYS = ["A", "B", "C", "D"]
W = {l: json.load(open(os.path.join(H, "out", "witness", f"{l}.json"))) for l in ["en", "es", "fr", "ja", "km", "lo", "pt", "ht"]
     if os.path.exists(os.path.join(H, "out", "witness", f"{l}.json"))}
SAID_EN = json.load(open(os.path.join(H, "out", "said_en.json")))   # {"i": said text} for English recordings that differ


def flagged(l):
    return {r["i"] for r in W.get(l, []) if r.get("cut_off") or r.get("meaning_differs")}


def runs(var):
    out = {}
    for s in SYS:
        p = os.path.join(H, f"e2e_{s}_{var}", "out", "sentences.json")
        if os.path.exists(p):
            for d, v in json.load(open(p)).items():
                out.setdefault(d, {})[s] = v["live_out"]
    for s, f in (("D", f"qe_{var}.json"), ("E", f"e_{var}.json")):   # QE pick; Hy-MT2-30B on OpenRouter
        q = os.path.join(H, "out", f)
        if os.path.exists(q):
            for d, v in json.load(open(q)).items():
                out.setdefault(d, {})[s] = v["live_out"]
    return out


if sys.argv[1] == "jobs":
    jobs = []
    for var in ["reg", "irr"]:
        CL = os.path.join(H, f"clips_{var}")
        en = json.load(open(os.path.join(CL, "en.txt.json")))
        said = [SAID_EN.get(str(i), t) for i, t in enumerate(en)]
        for d, systems in sorted(runs(var).items()):
            s, t = d.split("-")
            if s == "en":
                jobs.append({"id": f"WRITTEN:{var}:{d}", "src": s, "tgt": t, "source": en, "reference": en, "systems": systems})
                jobs.append({"id": f"SAID:{var}:{d}", "src": s, "tgt": t, "source": said, "reference": said, "systems": systems})
            else:
                ref = json.load(open(os.path.join(H, "out", "meaning_ht.json"))) if s == "ht" else en
                jobs.append({"id": f"WRITTEN:{var}:{d}", "src": s, "tgt": t, "source": json.load(open(os.path.join(CL, f"{s}.txt.json"))),
                             "reference": ref, "systems": systems})
    json.dump(jobs, open(os.path.join(H, "out", "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs")
else:
    G = json.load(open(os.path.join(H, "out", "grades.json")))
    q = lambda g: {"q": round(100 * sum(x.get("score", 0) for x in g) / (3 * max(1, len(g))), 1),
                   "crit": sum(1 for x in g if x.get("critical")), "n": len(g)}
    res = {}
    for k, v in G.items():
        ref, var, d = k.split(":")
        s = d.split("-")[0]
        for sysn, g in v["grades"].items():
            r = res.setdefault(var, {}).setdefault(d, {}).setdefault(sysn, {})
            r["written"] = q(g) if ref == "WRITTEN" else r.get("written")
            if ref == "SAID":
                r["said"] = q(g)
            elif s != "en":
                bad = flagged(s)
                r["said"] = q([x for x in g if x["i"] not in bad])
    json.dump(res, open(os.path.join(H, "out", "quality.json"), "w"), indent=1)
    for var in res:
        for d in sorted(res[var]):
            print(var, d, {s: (x.get("written", {}) or {}).get("q") for s, x in sorted(res[var][d].items())},
                  "said", {s: (x.get("said", {}) or {}).get("q") for s, x in sorted(res[var][d].items())})
