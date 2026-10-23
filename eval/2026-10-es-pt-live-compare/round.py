# One blind round: per direction, every system side by side (grade.py, the
# unseen round's grader), against the written text and, for English sources,
# against what was said. For Spanish and Portuguese sources "said" scores only
# the sentences whose recording matches its text (the unseen witness).
#
#   python3 -I round.py jobs  CLIPS UNSEEN_OUT OUT     -> OUT/jobs.json
#   GEMINI_API_KEY=... python3 -I grade.py OUT/jobs.json OUT/grades.json
#   python3 -I round.py table CLIPS UNSEEN_OUT OUT     -> results.json (here)
import json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-real-voices"))
from judge import cer  # noqa: E402

MODE, CLIPS, HO, OUT = sys.argv[1:5]
DIRS = ["en-es", "en-pt", "en-fr", "en-ja", "en-km", "en-lo", "en-ht", "es-en", "pt-en"]
SYSTEMS = ["hymt2-7b@or", "gemma-4-31b-it@or", "sol@low", "gemini-live-translate"]
J = lambda p: json.load(open(p))
W = {l: J(os.path.join(HO, "witness", f"{l}.json")) for l in ["en", "es", "pt"]}
SAID_EN = J(os.path.join(HO, "said_en.json"))
SENTENCES_PER_HOUR = 392   # ../2026-10-translation-cost
PRICE = {"hymt2-7b@or": (0.074, 0.295), "gemma-4-31b-it@or": (0.20, 0.40)}   # OpenRouter list $/M in, out (2026-10-22)
SOL = (4.40, 22.0)          # ../2026-10-translation-cost: billed list rate per M in / out (reasoning billed as out)


def flagged(l):
    return {r["i"] for r in W[l] if r.get("cut_off") or r.get("meaning_differs")}


def outputs(d):
    s, t = d.split("-")
    sys_ = {}
    for name in SYSTEMS[:3]:
        p = os.path.join(OUT, "mt", name, f"{d}.json")
        if os.path.exists(p):
            sys_[name] = J(p)["out"]
    p = os.path.join(OUT, "live", f"en-{t}.sent.json")
    if s == "en" and os.path.exists(p):
        sys_["gemini-live-translate"] = J(p)["live_out"]
    return sys_


en = J(os.path.join(CLIPS, "en.txt.json"))
said_en = [SAID_EN.get(str(i), x) for i, x in enumerate(en)]

if MODE == "jobs":
    jobs = []
    for d in DIRS:
        s, t = d.split("-")
        if s == "en":
            jobs.append({"id": f"WRITTEN:{d}", "src": s, "tgt": t, "source": en, "reference": en, "systems": outputs(d)})
            jobs.append({"id": f"SAID:{d}", "src": s, "tgt": t, "source": said_en, "reference": said_en, "systems": outputs(d)})
        else:
            jobs.append({"id": f"WRITTEN:{d}", "src": s, "tgt": t, "source": J(os.path.join(CLIPS, f"{s}.txt.json")),
                         "reference": en, "systems": outputs(d)})
    json.dump(jobs, open(os.path.join(OUT, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs")
    sys.exit()

G = J(os.path.join(OUT, "grades.json"))
q = lambda g: {"q": round(100 * sum(x.get("score", 0) for x in g) / (3 * max(1, len(g))), 1),
               "crit": sum(1 for x in g if x.get("critical")), "n": len(g)}
res = {"grader": "gemini-pro-latest", "directions": {}, "recognition": {}, "latency": {}, "cost_per_hour": {}}
for k, v in G.items():
    ref, d = k.split(":")
    s = d.split("-")[0]
    for name, g in v["grades"].items():
        r = res["directions"].setdefault(d, {}).setdefault(name, {})
        if ref == "WRITTEN":
            r["written"] = q(g)
            if s != "en":
                r["said"] = q([x for x in g if x["i"] not in flagged(s)])
        else:
            r["said"] = q(g)

# Azure recognition, characters wrong against what was said
for l in ["en", "es", "pt"]:
    heard = J(os.path.join(OUT, "stt", f"{l}.sent.json"))
    said = said_en if l == "en" else [r["said"] for r in W[l]]
    res["recognition"][l] = {"azure_cer_vs_said": cer(" ".join(said), " ".join(heard)),
                             "azure_cer_vs_written": cer(" ".join(J(os.path.join(CLIPS, f"{l}.txt.json"))), " ".join(heard))}


def pct(v, p):
    v = sorted(x for x in v if x is not None)
    return round(v[min(len(v) - 1, int(p * len(v)))]) if v else None


# Latency, ms after the sentence's speech ends. Azure routes: the sentence's last
# Azure final arrives + one translation call (wall time); no voice included.
# Gemini Live: arrival of the first / last text of its translation of that sentence.
meta = J(os.path.join(CLIPS, "en.json"))["sentences"]
for l in ["en", "es", "pt"]:
    m = J(os.path.join(CLIPS, f"{l}.json"))["sentences"]
    fin = J(os.path.join(OUT, "stt", f"{l}.json"))["finals"]
    arr = []
    for i, sm in enumerate(m):
        hi = m[i + 1]["start"] if i + 1 < len(m) else 1e9
        fs = [f for f in fin if sm["start"] - 0.3 <= (f["offsetMs"] + f["durationMs"] / 2) / 1000 < hi]
        arr.append(max(f["arrivedMs"] for f in fs) - sm["end"] * 1000 if fs else None)
    res["latency"][f"azure_final_{l}"] = {"p50": pct(arr, .5), "p90": pct(arr, .9)}
    for d in DIRS:
        if d.split("-")[0] != l:
            continue
        for name in SYSTEMS[:3]:
            p = os.path.join(OUT, "mt", name, f"{d}.json")
            if os.path.exists(p):
                w = J(p)["wall_s"]
                tot = [a + 1000 * b for a, b in zip(arr, w) if a is not None and b is not None]
                res["latency"].setdefault(d, {})[name] = {"p50": pct(tot, .5), "p90": pct(tot, .9), "mt_wall_p50_s": pct([1000 * x for x in w if x], .5) / 1000}
for d in DIRS:
    if d.startswith("en-"):
        p = os.path.join(OUT, "live", f"en-{d[3:]}.sent.json")
        x = J(p)
        res["latency"].setdefault(d, {})["gemini-live-translate"] = {
            "first_p50": pct(x["first_ms"], .5), "first_p90": pct(x["first_ms"], .9),
            "last_p50": pct(x["last_ms"], .5), "last_p90": pct(x["last_ms"], .9),
            "sentences_without_output": sum(1 for o in x["live_out"] if not o.strip())}

# Translation cost per hour of speech (one listener language): mean tokens per sentence x 392 x list price
for d in DIRS:
    for name in SYSTEMS[:3]:
        p = os.path.join(OUT, "mt", name, f"{d}.json")
        if not os.path.exists(p):
            continue
        r = J(p)
        pi = statistics.mean(x for x in r["prompt_tokens"] if x)
        co = statistics.mean(x for x in r["completion_tokens"] if x)
        a, b = PRICE.get(name, SOL)
        res["cost_per_hour"].setdefault(d, {})[name] = round(SENTENCES_PER_HOUR * (pi * a + co * b) / 1e6, 4)
    prov = {}
    for name in SYSTEMS[:2]:
        p = os.path.join(OUT, "mt", name, f"{d}.json")
        if os.path.exists(p):
            prov[name] = sorted({x for x in J(p)["provider"] if x})
    res.setdefault("providers", {})[d] = prov

json.dump(res, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
for d in DIRS:
    print(d, {n: (v.get("written", {}).get("q"), v.get("said", {}).get("q"), v.get("written", {}).get("crit"))
              for n, v in res["directions"].get(d, {}).items()})
print(json.dumps(res["recognition"]), json.dumps(res["latency"], indent=0)[:3000])
print(json.dumps(res["cost_per_hour"]))
