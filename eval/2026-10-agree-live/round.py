# Grading jobs (one blind call per direction and clip, the configurations side by side, against the FLEURS text in
# the target language) and, after grade.py, the tables and results.json. A configuration's output is live_out of
# analyze.py's sentences.json.
#   python3 -I round.py jobs WORK     -> WORK/stream_jobs.json, WORK/german_jobs.json
#   python3 -I round.py table WORK    -> ./results.json (+ printed)
import json, os, statistics, sys

mode, WORK = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
D4 = ["en-es", "es-en", "en-fr", "fr-en"]
STREAM = {"U": "Utterance", "C": "Simultaneous, clause rule", "A": "Simultaneous, agree"}
GERMAN = {"G1": "Default turns (cut at 9 s)", "G3": "Long turns, cut at 15 s", "G4": "Long turns, cut at 10 s",
          "G5": "Long turns, cut at 12 s"}
J = lambda p: json.load(open(p, encoding="utf-8"))


def clips(run):
    return os.path.realpath(os.path.join(WORK, f"e2e_{run}", "clips"))


def text(run, lang):
    return J(os.path.join(clips(run), f"{lang}.txt.json"))


def sentences(run, d):
    return J(os.path.join(WORK, f"e2e_{run}", "out", "sentences.json"))[d]


def latency(run, d):
    return J(os.path.join(WORK, f"e2e_{run}", "out", "latency.json"))[d]


if mode == "jobs":
    jobs = []
    for p in ("reg", "irr"):
        for d in D4:
            s, t = d.split("-")
            jobs.append({"id": f"{d}:{p}", "src": s, "tgt": t, "source": text(f"st_U_{p}", s),
                         "reference": text(f"st_U_{p}", t),
                         "systems": {k: sentences(f"st_{k}_{p}", d)["live_out"] for k in STREAM}})
    json.dump(jobs, open(os.path.join(WORK, "stream_jobs.json"), "w"), ensure_ascii=False, indent=1)
    jobs = [{"id": f"de-en:{p}", "src": "de", "tgt": "en", "source": text(f"de_G1_{p}", "de"),
             "reference": text(f"de_G1_{p}", "en"),
             "systems": {k: sentences(f"de_{k}_{p}", "de-en")["live_out"] for k in GERMAN}} for p in ("reg", "irr")]
    json.dump(jobs, open(os.path.join(WORK, "german_jobs.json"), "w"), ensure_ascii=False, indent=1)
    sys.exit()


def scores(grades, jobs):
    out = {}
    for k, g in grades.items():
        n = len(jobs[k]["source"])
        for s, items in g["grades"].items():
            items = items[:n]
            out.setdefault(k, {})[s] = {"score": round(100 * sum(max(0, min(3, int(x.get("score", 0)))) for x in items) / (3 * n), 1),
                                        "crit": sum(1 for x in items if x.get("critical"))}
    return out


def lat(run, d):
    L = latency(run, d)
    keep = ("start_to_first_audio_ms", "stop_to_first_audio_ms", "stop_to_audio_end_ms")
    return {k: L.get(k) for k in keep} | {"cer": L.get("cer"), "missing_audio": L.get("missing_audio")}


res = {"grader": "gemini-pro-latest, blind, the configurations side by side, one call per direction and clip"}
for name, systems, runs, dirs in (("stream", STREAM, lambda k, p: f"st_{k}_{p}", D4),
                                  ("german", GERMAN, lambda k, p: f"de_{k}_{p}", ["de-en"])):
    jp, gp = os.path.join(WORK, f"{name}_jobs.json"), os.path.join(WORK, f"{name}_grades.json")
    if not os.path.exists(gp):
        continue
    jobs = {j["id"]: j for j in J(jp)}
    sc = scores(J(gp), jobs)
    res[name] = {"systems": systems, "scores": sc,
                 "latency": {f"{d}:{p}": {k: lat(runs(k, p), d) for k in systems} for p in ("reg", "irr") for d in dirs}}
    print(f"\n{name}")
    for key in sc:
        print(" ", key, " | ".join(f"{k} {sc[key][k]['score']} ({sc[key][k]['crit']}) "
                                    f"start->first {res[name]['latency'][key][k]['start_to_first_audio_ms']['p50']} "
                                    f"stop->first {res[name]['latency'][key][k]['stop_to_first_audio_ms']['p50']}/"
                                    f"{res[name]['latency'][key][k]['stop_to_first_audio_ms']['p90']}"
                                    for k in systems if k in sc[key]))
json.dump(res, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
