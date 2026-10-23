# Builds the grading jobs (every system side by side, one call per direction) and,
# after grade.py, the table.
#
#   python3 -I round.py jobs WORK      -> WORK/grade_jobs.json
#   python3 -I round.py table WORK     -> WORK/mt_scores.json (+ printed)
# Score: the share of the possible 3 points per sentence, x100; "crit" = sentences marked critical.
import json, os, sys

mode, WORK = sys.argv[1], sys.argv[2]
J = json.load(open(os.path.join(WORK, "mt_jobs.json")))
SYSTEMS = sorted(os.listdir(os.path.join(WORK, "mt")))

if mode == "jobs":
    out = []
    for k, j in J.items():
        systems = {}
        for s in SYSTEMS:
            p = os.path.join(WORK, "mt", s, f"{k}.json")
            if os.path.exists(p):
                systems[s] = json.load(open(p))["out"]
        out.append({"id": k, "src": j["src"], "tgt": j["tgt"], "source": j["source"], "reference": j["reference"], "systems": systems})
    json.dump(out, open(os.path.join(WORK, "grade_jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(out), "jobs")
else:
    G = json.load(open(os.path.join(WORK, "grades.json")))
    table = {}
    for k, g in G.items():
        n = len(J[k]["source"])
        for s, items in g["grades"].items():
            pts = sum(max(0, min(3, int(x.get("score", 0)))) for x in items[:n])
            table.setdefault(k, {})[s] = {"score": round(100 * pts / (3 * n), 1),
                                          "crit": sum(1 for x in items[:n] if x.get("critical"))}
    json.dump(table, open(os.path.join(WORK, "mt_scores.json"), "w"), indent=1)
    for k in J:
        if k in table:
            print(f"{k:12s} " + "  ".join(f"{s}: {v['score']} ({v['crit']})" for s, v in sorted(table[k].items())))
