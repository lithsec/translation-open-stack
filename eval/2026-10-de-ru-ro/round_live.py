# Live grading jobs (configurations side by side, one blind call per direction and set) and, after
# grade.py, the tables; then results.json for the whole round. A configuration's output is
# live_out of analyze_e2e.py's sentences.json (eval/2026-10-unseen, run with ORDER set to the six
# directions here), graded against the FLEURS texts as round_mt.py.
#   python3 -I round_live.py jobs WORK     -> WORK/live_grade_jobs.json, WORK/german_grade_jobs.json
#   python3 -I round_live.py table WORK    -> WORK/live_scores.json, ./results.json (+ printed)
import json, statistics, sys
from pathlib import Path

mode, WORK = sys.argv[1], Path(sys.argv[2])
D6 = ["en-de", "de-en", "en-ru", "ru-en", "en-ro", "ro-en"]


def text(st, lang):
    return json.load(open(WORK / f"clips_{st}_reg" / f"{lang}.txt.json"))


def out(e, d):
    return json.load(open(WORK / f"e2e_{e}" / "out" / "sentences.json"))[d]["live_out"]


def scores(G, J, by_set=False):
    both = {}
    for k, g in G.items():
        n, d = len(J[k]["source"]), (k if by_set else k.split(":")[0])
        for s, items in g["grades"].items():
            b = both.setdefault(d, {}).setdefault(s, [0, 0, 0])
            b[0] += sum(max(0, min(3, int(x.get("score", 0)))) for x in items[:n])
            b[1] += sum(1 for x in items[:n] if x.get("critical"))
            b[2] += 3 * n
    return {d: {s: {"score": round(100 * b[0] / b[2], 1), "crit": b[1]} for s, b in v.items()} for d, v in both.items()}


def latency(e, d):
    L = json.load(open(WORK / f"e2e_{e}" / "out" / "latency.json"))[d]
    return {"stop_to_first_audio_ms": L["stop_to_first_audio_ms"], "cer": L["cer"]}


if mode == "jobs":
    jobs = []
    for d in D6:
        s, t = d.split("-")
        for st in "ab":
            jobs.append({"id": f"{d}:{st}", "src": s, "tgt": t, "source": text(st, s), "reference": text(st, t),
                         "systems": {C: out(f"{C}_{st}_reg", d) for C in ("C1", "C2")}})
    json.dump(jobs, open(WORK / "live_grade_jobs.json", "w"), ensure_ascii=False, indent=1)
    # German turns: C1 against C3 on set a, both pause patterns (the irr clip reads set a's sentences)
    jobs = [{"id": f"de-en-turns:{pat}", "src": "de", "tgt": "en", "source": text("a", "de"), "reference": text("a", "en"),
             "systems": {C: out(f"{C}_a_{pat}", "de-en") for C in ("C1", "C3")}} for pat in ("reg", "irr")]
    json.dump(jobs, open(WORK / "german_grade_jobs.json", "w"), ensure_ascii=False, indent=1)
else:
    live = scores(json.load(open(WORK / "live_grades.json")), {j["id"]: j for j in json.load(open(WORK / "live_grade_jobs.json"))})
    german = scores(json.load(open(WORK / "german_grades.json")), {j["id"]: j for j in json.load(open(WORK / "german_grade_jobs.json"))}, by_set=True)
    json.dump(live, open(WORK / "live_scores.json", "w"), indent=1)
    lat = {C: {d: {st: latency(f"{C}_{st}_reg", d) for st in "ab"} for d in D6} for C in ("C1", "C2")}
    for C in ("C1", "C2"):
        for d in D6:
            lat[C][d]["p50_mean_ms"] = round(statistics.mean(lat[C][d][st]["stop_to_first_audio_ms"]["p50"] for st in "ab"))
    glat = {f"{C}_{pat}": latency(f"{C}_a_{pat}", "de-en") for C in ("C1", "C3") for pat in ("reg", "irr")}
    res = {
        "grader": "gemini-pro-latest, blind, all systems side by side, one call per direction and set",
        "recognition": json.load(open(WORK / "asr_scores.json")),
        "typed_mt": json.load(open(WORK / "mt_scores.json"))["both_sets"],
        "live": {"scores": live, "latency": lat},
        "german_turns": {"scores": german, "latency": glat},
    }
    json.dump(res, open(Path(__file__).parent / "results.json", "w"), ensure_ascii=False, indent=1)
    for d in D6:
        print(d, live[d], "| p50 stop->first", {C: lat[C][d]["p50_mean_ms"] for C in lat})
    for k, v in german.items():
        print(k, v, {g: glat[g]["stop_to_first_audio_ms"] for g in glat})
