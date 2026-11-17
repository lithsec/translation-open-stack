# The third round, "Which hearing": the same translator and prompt per direction (the baseline's, mt.py) behind three
# recognisers, graded blind side by side in one fresh call per direction and set (grade.py, gemini-flash-latest,
# the same rubric and FLEURS references):
#   soniox-hear  Soniox's own transcript (soniox_hear.py, from the soniox_s2s.py streams)
#   mai-hear     MAI-Transcribe-2-Streaming (stt_azure.py RECOGNISER=mai), where MAI gave a transcript
#   azure-hear   Azure standard speech-to-text (stt_azure.py): the baseline of the first two rounds
#
#   python3 -I round_hearing.py restore CLIPS_ROOT OUT   -> the earlier arms' outputs back into OUT from results/
#   python3 -I round_hearing.py jobs    CLIPS_ROOT OUT   -> OUT/hearing/jobs.json
#   GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py OUT/hearing/jobs.json OUT/hearing/grades.json
#   python3 -I round_hearing.py jobs2   CLIPS_ROOT OUT <dir ...>   -> OUT/hearing/jobs_r2.json (top two within ~3)
#   GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py OUT/hearing/jobs_r2.json OUT/hearing/grades_r2.json
#   python3 -I round_hearing.py table   CLIPS_ROOT OUT   -> results.json "hearing", hearing-rows.json
import json, os, statistics, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
MODE, CLIPS, OUT = sys.argv[1:4]
EXTRA = sys.argv[4:]
sys.argv = sys.argv[:1] + [OUT]   # mt.py reads OUT from argv at import
sys.path.insert(0, HERE)
from mt import BASELINE  # noqa: E402

SETS = ["a", "b"]
DIRS = list(BASELINE)
LANGS = ["en"] + [d.split("-")[0] for d in DIRS if not d.startswith("en-")]
ROUND = "talk-hearing-2026-11"
GRADER = os.environ.get("GRADER", "gemini-flash-latest")
RES = os.path.join(HERE, "results")
H = os.path.join(OUT, "hearing")
J = lambda p: json.load(open(p))
clip = lambda st, l, ext: J(os.path.join(CLIPS, f"clips_{st}", f"{l}.{ext}"))


def dump(p, x):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(x, open(p, "w"), ensure_ascii=False, indent=1)


if MODE == "restore":
    for k, v in J(os.path.join(RES, "mt.json")).items():
        st, d = k.split(":")
        dump(os.path.join(OUT, "mt", st, f"{d}.json"), v)
    for k, v in J(os.path.join(RES, "soniox_hear.json")).items():
        st, d = k.split(":")
        dump(os.path.join(OUT, "soniox_hear", st, f"{d}.sent.json"), v["transcript"])
        dump(os.path.join(OUT, "mt_soniox_hear", st, f"{d}.json"), {x: v[x] for x in v if x != "transcript"})
    print("restored")
    sys.exit()


def mai_ok(st, src):
    """MAI gave both sets' transcripts for this source (so every direction from it has mai-hear in both sets)."""
    return all(os.path.exists(os.path.join(OUT, "mt_mai", s, f"{d}.json")) for s in SETS for d in DIRS if d.startswith(src + "-"))


def systems(st, d):
    out = {"soniox-hear": J(os.path.join(OUT, "mt_soniox_hear", st, f"{d}.json"))["out"],
           "azure-hear": J(os.path.join(OUT, "mt", st, f"{d}.json"))["out"]}
    p = os.path.join(OUT, "mt_mai", st, f"{d}.json")
    if mai_ok(st, d.split("-")[0]):
        out["mai-hear"] = J(p)["out"]
    return out


os.makedirs(H, exist_ok=True)
if MODE == "jobs":
    jobs = []
    for st in SETS:
        for d in DIRS:
            s, t = d.split("-")
            jobs.append({"id": f"hearing:{st}:{d}", "src": s, "tgt": t, "source": clip(st, s, "txt.json"),
                         "reference": clip(st, "en", "txt.json"), "systems": systems(st, d)})
    dump(os.path.join(H, "jobs.json"), jobs)
    print(len(jobs), "jobs,", sum(1 for j in jobs if "mai-hear" in j["systems"]), "with MAI")
    sys.exit()
if MODE == "jobs2":
    jobs = [dict(j, id="r2:" + j["id"]) for j in J(os.path.join(H, "jobs.json")) if j["id"].split(":")[2] in set(EXTRA)]
    dump(os.path.join(H, "jobs_r2.json"), jobs)
    print(len(jobs), "jobs")
    sys.exit()


def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c for c in s if c.isalnum())


def cer(ref, hyp):   # ../2026-10-real-voices/judge.py cer
    a, b = norm(ref), norm(hyp)
    if not a:
        return None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return round(prev[-1] / len(a), 4)


G = J(os.path.join(H, "grades.json"))
R2P = os.path.join(H, "grades_r2.json")
R2 = J(R2P) if os.path.exists(R2P) else {}
q = lambda g: round(100 * sum(x.get("score", 0) for x in g) / (3 * max(1, len(g))), 1)
res = J(os.path.join(HERE, "results.json"))
out = {"round": ROUND, "grader": GRADER, "n_per_set": 20, "directions": {}, "recognition_cer": {}}

# Recognition, characters wrong against the FLEURS text of the whole clip (mean of sets a and b). MAI from its finals
# here; Soniox and Azure from the first round (results.json recognition_cer), except where a clip was re-run on
# rebuilt audio (OUT/stt/<set>/<lang>.json, OUT/soniox/<set>/<lang>-*.json: uk set a), which is computed here.
for l in LANGS:
    r = {}
    for st in SETS:
        gold = " ".join(clip(st, l, "txt.json"))
        p = os.path.join(OUT, "stt", st, f"{l}.json")
        r.setdefault("azure", {})[st] = cer(gold, " ".join(f["text"] for f in J(p)["finals"])) if os.path.exists(p) \
            else res["recognition_cer"][l]["azure"][st]
        so = [os.path.join(OUT, "soniox", st, f"{d}.json") for d in DIRS if d.startswith(l + "-")]
        r.setdefault("soniox", {})[st] = round(statistics.mean(cer(gold, J(x)["heard"]) for x in so), 4) \
            if all(os.path.exists(x) for x in so) else res["recognition_cer"][l]["soniox"][st]
        p = os.path.join(OUT, "stt_mai", st, f"{l}.json")
        r.setdefault("mai", {})[st] = cer(gold, " ".join(f["text"] for f in J(p)["finals"])) \
            if os.path.exists(p) and not J(p)["err"] and J(p)["finals"] else None
    for k in r:
        r[k]["mean"] = round(statistics.mean(r[k][st] for st in SETS), 4) if None not in r[k].values() else None
    out["recognition_cer"][l] = r

for d in DIRS:
    route, hear, tr = BASELINE[d]
    row = {"baseline_route": route, "translator": tr}
    names = list(G[f"hearing:a:{d}"]["grades"])
    for name in ["soniox-hear", "mai-hear", "azure-hear"]:
        if name not in names:
            row[name] = None
            continue
        gs = {st: G[f"hearing:{st}:{d}"]["grades"][name] for st in SETS}
        per = {st: {"q": q(gs[st]), "crit": sum(1 for x in gs[st] if x.get("critical")), "n": len(gs[st])} for st in SETS}
        r = {"q": round(statistics.mean(per[st]["q"] for st in SETS), 1), "crit": sum(per[st]["crit"] for st in SETS),
             "n": sum(per[st]["n"] for st in SETS), "sets": per}
        if f"r2:hearing:a:{d}" in R2:
            g2 = {st: R2[f"r2:hearing:{st}:{d}"]["grades"][name] for st in SETS}
            per2 = {st: {"q": q(g2[st]), "crit": sum(1 for x in g2[st] if x.get("critical"))} for st in SETS}
            q1, q2 = (statistics.mean(p[st]["q"] for st in SETS) for p in (per, per2))
            r.update({"read1_q": round(q1, 1), "read2_q": round(q2, 1), "read2": per2, "q": round((q1 + q2) / 2, 1)})
        row[name] = r
    scored = {n: row[n]["q"] for n in ["soniox-hear", "mai-hear", "azure-hear"] if row[n]}
    top = max(scored.values())
    row["winner"] = sorted(n for n, v in scored.items() if v == top)
    best_other = max(v for n, v in scored.items() if n != "soniox-hear")
    row["soniox_minus_best_other"] = round(scored["soniox-hear"] - best_other, 1)
    row["soniox_qualifies"] = scored["soniox-hear"] >= 70 and scored["soniox-hear"] >= best_other - 3
    out["directions"][d] = row

res["hearing"] = out
json.dump(res, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
rows = [{"src": d.split("-")[0], "tgt": d.split("-")[1], "round": ROUND, "sonioxHear": r["soniox-hear"]["q"],
         "maiHear": r["mai-hear"]["q"] if r["mai-hear"] else None, "azureHear": r["azure-hear"]["q"],
         "baselineRoute": r["baseline_route"]} for d, r in out["directions"].items()]
rounds = {ROUND: {"kind": "real", "grader": GRADER, "source": "translation-open-stack eval/2026-11-talk-soniox"}}
open(os.path.join(HERE, "hearing-rows.json"), "w").write(
    '{"rounds": ' + json.dumps(rounds) + ',\n "rows": [\n' + ",\n".join("  " + json.dumps(r) for r in rows) + "\n]}\n")
f = lambda r: "  -  " if not r else f"{r['q']:5.1f} c{r['crit']:2d}" + (f" [{r['read1_q']},{r['read2_q']}]" if "read1_q" in r else "")
for d, r in out["directions"].items():
    print(f"{d} soniox {f(r['soniox-hear'])} | mai {f(r['mai-hear'])} | azure {f(r['azure-hear'])} | win {','.join(r['winner'])} | {r['soniox_minus_best_other']:+5.1f} {r['soniox_qualifies']}")
print(json.dumps({l: {k: v["mean"] for k, v in r.items()} for l, r in out["recognition_cer"].items()}))
