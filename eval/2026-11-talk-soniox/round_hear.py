# The second round, "Soniox hearing + our translator": per direction and set, three systems side by side in one
# fresh grading call (grade.py, same grader, rubric and FLEURS references as round.py):
#   soniox-hear  Soniox's own transcript (soniox_hear.py) translated by the baseline's translator (mt.py HEAR=soniox)
#   baseline     Azure's transcript, the same translator (mt.py)
#   soniox-s2s   Soniox's own translation (soniox_s2s.py)
#
#   python3 -I round_hear.py jobs  CLIPS_ROOT OUT            -> OUT/hear/jobs.json
#   GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py OUT/hear/jobs.json OUT/hear/grades.json
#   python3 -I round_hear.py jobs2 CLIPS_ROOT OUT <dir ...>   -> OUT/hear/jobs_r2.json (second read where
#                                                                soniox-hear and baseline are within ~3 points)
#   GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py OUT/hear/jobs_r2.json OUT/hear/grades_r2.json
#   python3 -I round_hear.py table CLIPS_ROOT OUT            -> results.json "soniox_hear", soniox-hear-rows.json
import json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODE, CLIPS, OUT = sys.argv[1:4]
EXTRA = sys.argv[4:]
sys.argv = sys.argv[:1] + [OUT]   # mt.py reads OUT from argv at import
sys.path.insert(0, HERE)
from mt import BASELINE  # noqa: E402

SETS = ["a", "b"]
DIRS = list(BASELINE)
ROUND = "talk-soniox-hear-2026-11"
GRADER = os.environ.get("GRADER", "gemini-flash-latest")
H = os.path.join(OUT, "hear")
J = lambda p: json.load(open(p))
clip = lambda st, l, ext: J(os.path.join(CLIPS, f"clips_{st}", f"{l}.{ext}"))
NAMES = ["soniox-hear", "baseline", "soniox-s2s"]


def systems(st, d):
    return {"soniox-hear": J(os.path.join(OUT, "mt_soniox_hear", st, f"{d}.json"))["out"],
            "baseline": J(os.path.join(OUT, "mt", st, f"{d}.json"))["out"],
            "soniox-s2s": J(os.path.join(OUT, "soniox", st, f"{d}.json"))["sent"]}


os.makedirs(H, exist_ok=True)
if MODE == "jobs":
    jobs = []
    for st in SETS:
        for d in DIRS:
            s, t = d.split("-")
            jobs.append({"id": f"hear:{st}:{d}", "src": s, "tgt": t, "source": clip(st, s, "txt.json"),
                         "reference": clip(st, "en", "txt.json"), "systems": systems(st, d)})
    json.dump(jobs, open(os.path.join(H, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs")
    sys.exit()
if MODE == "jobs2":
    keep = set(EXTRA)
    jobs = [dict(j, id="r2:" + j["id"]) for j in J(os.path.join(H, "jobs.json")) if j["id"].split(":")[2] in keep]
    json.dump(jobs, open(os.path.join(H, "jobs_r2.json"), "w"), ensure_ascii=False)
    print(len(jobs), "jobs")
    sys.exit()

G = J(os.path.join(H, "grades.json"))
R2P = os.path.join(H, "grades_r2.json")
R2 = J(R2P) if os.path.exists(R2P) else {}
q = lambda g: round(100 * sum(x.get("score", 0) for x in g) / (3 * max(1, len(g))), 1)
out = {"round": ROUND, "grader": GRADER, "n_per_set": 20, "systems": NAMES, "directions": {}}
for d in DIRS:
    route, hear, tr = BASELINE[d]
    row = {"baseline_route": route, "translator": tr}
    for name in NAMES:
        per = {st: {"q": q(G[f"hear:{st}:{d}"]["grades"][name]),
                    "crit": sum(1 for x in G[f"hear:{st}:{d}"]["grades"][name] if x.get("critical")),
                    "n": len(G[f"hear:{st}:{d}"]["grades"][name])} for st in SETS}
        r = {"q": round(statistics.mean(per[st]["q"] for st in SETS), 1), "crit": sum(per[st]["crit"] for st in SETS),
             "n": sum(per[st]["n"] for st in SETS), "sets": per}
        if f"r2:hear:a:{d}" in R2:
            per2 = {st: {"q": q(R2[f"r2:hear:{st}:{d}"]["grades"][name]),
                         "crit": sum(1 for x in R2[f"r2:hear:{st}:{d}"]["grades"][name] if x.get("critical"))} for st in SETS}
            q1, q2 = (statistics.mean(p[st]["q"] for st in SETS) for p in (per, per2))
            r.update({"read1_q": round(q1, 1), "read2_q": round(q2, 1), "read2": per2, "q": round((q1 + q2) / 2, 1)})
        row[name] = r
    row["hear_minus_baseline"] = round(row["soniox-hear"]["q"] - row["baseline"]["q"], 1)
    row["hear_qualifies"] = row["soniox-hear"]["q"] >= 70 and row["soniox-hear"]["q"] >= row["baseline"]["q"] - 3
    out["directions"][d] = row

res = J(os.path.join(HERE, "results.json"))
res["soniox_hear"] = out
json.dump(res, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
rows = [{"src": d.split("-")[0], "tgt": d.split("-")[1], "round": ROUND, "sonioxHear": r["soniox-hear"]["q"],
         "baseline": {"route": r["baseline_route"], "quality": r["baseline"]["q"]}, "sonioxS2s": r["soniox-s2s"]["q"]}
        for d, r in out["directions"].items()]
rounds = {ROUND: {"kind": "real", "grader": GRADER, "source": "translation-open-stack eval/2026-11-talk-soniox"}}
open(os.path.join(HERE, "soniox-hear-rows.json"), "w").write(
    '{"rounds": ' + json.dumps(rounds) + ',\n "rows": [\n' + ",\n".join("  " + json.dumps(r) for r in rows) + "\n]}\n")
for d, r in out["directions"].items():
    print(f"{d} hear {r['soniox-hear']['q']:5.1f} c{r['soniox-hear']['crit']:2d} | base {r['baseline']['q']:5.1f} c{r['baseline']['crit']:2d} | s2s {r['soniox-s2s']['q']:5.1f} c{r['soniox-s2s']['crit']:2d} | {r['hear_minus_baseline']:+5.1f} {r['hear_qualifies']}"
          + (f"  r1 {r['soniox-hear']['read1_q']}/{r['baseline']['read1_q']} r2 {r['soniox-hear']['read2_q']}/{r['baseline']['read2_q']}" if "read1_q" in r["baseline"] else ""))
