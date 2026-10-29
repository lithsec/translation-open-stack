# Grading jobs (one blind call per direction and clip, the arms side by side, against the FLEURS text in the target
# language) and, after grade.py, the tables and results.json. An arm's output is live_out of analyze.py's
# sentences.json.
#   python3 -I round.py jobs WORK     -> WORK/jobs.json
#   python3 -I round.py table WORK    -> ./results.json (+ printed)
import json, os, statistics, sys

mode, WORK = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
CLIPS = ["a_reg", "a_irr", "b_reg"]
ARMS = {"en-de": {"U5": "Utterance", "A": "Agree", "T": "Complete thought"},
        "de-en": {"U1": "Utterance, default turns", "U5": "Utterance, long turns cut at 12 s", "T": "Complete thought"}}
J = lambda p: json.load(open(p, encoding="utf-8"))


def run_dir(arm, cl):
    return os.path.join(WORK, f"e2e_{arm}_{cl}")


def text(cl, lang):
    return J(os.path.join(WORK, "drr", f"clips_{cl}", f"{lang}.txt.json"))


if mode == "jobs":
    jobs = []
    for d, arms in ARMS.items():
        s, t = d.split("-")
        for cl in CLIPS:
            jobs.append({"id": f"{d}:{cl}", "src": s, "tgt": t, "source": text(cl, s), "reference": text(cl, t),
                         "systems": {a: J(os.path.join(run_dir(a, cl), "out", "sentences.json"))[d]["live_out"]
                                     for a in arms}})
    json.dump(jobs, open(os.path.join(WORK, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    sys.exit()

jobs = {j["id"]: j for j in J(os.path.join(WORK, "jobs.json"))}
grades = J(os.path.join(WORK, "grades.json"))
res = {"grader": "gemini-pro-latest, blind, the arms side by side, one call per direction and clip", "arms": ARMS,
       "clips": {}, "summary": {}}
for key, g in grades.items():
    d, cl = key.split(":")
    n = len(jobs[key]["source"])
    row = {}
    for a, items in g["grades"].items():
        items = items[:n]
        L = J(os.path.join(run_dir(a, cl), "out", "latency.json"))[d]
        row[a] = {"score": round(100 * sum(max(0, min(3, int(x.get("score", 0)))) for x in items) / (3 * n), 1),
                  "crit": sum(1 for x in items if x.get("critical")),
                  **{k: L.get(k) for k in ("start_to_first_audio_ms", "stop_to_first_audio_ms", "stop_to_audio_end_ms")}}
    res["clips"][key] = row
for d, arms in ARMS.items():
    keys = [f"{d}:{cl}" for cl in CLIPS if f"{d}:{cl}" in res["clips"]]
    for a in arms:
        rows = [res["clips"][k][a] for k in keys]
        med = lambda f, q: round(statistics.median(r[f][q] for r in rows) / 1000, 1)  # noqa: E731
        res["summary"].setdefault(d, {})[a] = {
            "score": round(statistics.mean(r["score"] for r in rows), 1),
            "crit": round(statistics.mean(r["crit"] for r in rows), 1),
            "start_to_first_audio_s": med("start_to_first_audio_ms", "p50"),
            "stop_to_first_audio_s": med("stop_to_first_audio_ms", "p50"),
            "stop_to_audio_end_s": [med("stop_to_audio_end_ms", "p50"), med("stop_to_audio_end_ms", "p90")]}
        print(d, a, res["summary"][d][a], "|", " ".join(f"{k.split(':')[1]} {res['clips'][k][a]['score']}" for k in keys))
json.dump(res, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
