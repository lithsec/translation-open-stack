# Typed-translation grading jobs (every system side by side, one blind call per direction and set) and,
# after grade.py, the table. Sources and references are the FLEURS texts of the same ids: X->en against
# the English text, en->X against X's own; "L-en-asr" translates Whisper's output but is graded against
# the English text, with what was read (the FLEURS text of L) as its source.
#   python3 -I round_mt.py jobs WORK    -> WORK/mt_grade_jobs.json
#   python3 -I round_mt.py table WORK   -> WORK/mt_scores.json (+ printed)
import json, os, sys
from pathlib import Path

mode, WORK = sys.argv[1], Path(sys.argv[2])


def texts(lang, st):
    return json.load(open(WORK / f"clips_{st}_reg" / f"{lang}.txt.json"))


if mode == "jobs":
    systems = {f.stem: json.load(open(f)) for f in sorted((WORK / "mt").glob("*.json"))}
    jobs = []
    for job in sorted({j for d in systems.values() for j in d}):
        s, t = job.split("-")[:2]
        for st in ("a", "b"):
            src, ref = texts(s, st), texts(t, st)
            sy = {name: [r["out"] for r in d[job] if r["id"].startswith(st)] for name, d in systems.items() if job in d}
            jobs.append({"id": f"{job}:{st}", "src": s, "tgt": t, "source": src, "reference": ref, "systems": sy})
    json.dump(jobs, open(WORK / "mt_grade_jobs.json", "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs")
else:
    G = json.load(open(WORK / "mt_grades.json"))
    J = {j["id"]: j for j in json.load(open(WORK / "mt_grade_jobs.json"))}
    table = {}
    for k, g in G.items():
        n = len(J[k]["source"])
        for s, items in g["grades"].items():
            pts = sum(max(0, min(3, int(x.get("score", 0)))) for x in items[:n])
            table.setdefault(k, {})[s] = {"score": round(100 * pts / (3 * n), 1), "crit": sum(1 for x in items[:n] if x.get("critical"))}
    both = {}
    for k, v in table.items():
        job = k.split(":")[0]
        for s, c in v.items():
            b = both.setdefault(job, {}).setdefault(s, {"score": 0, "crit": 0, "n": 0})
            b["score"] += c["score"]; b["crit"] += c["crit"]; b["n"] += 1
    for job, v in both.items():
        for s, b in v.items():
            b["score"] = round(b["score"] / b["n"], 1)
    json.dump({"per_set": table, "both_sets": both}, open(WORK / "mt_scores.json", "w"), indent=1)
    for job in sorted(both):
        print(f"{job:12s} " + "  ".join(f"{s}: {v['score']} ({v['crit']})" for s, v in sorted(both[job].items())))
