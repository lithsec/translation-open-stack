# Full-stack round: one blind grading call per (clip set, direction, reference), every system that ran
# the direction side by side; then the table (quality, critical errors, recognition CER, latency, drops).
#   python3 full_round.py <full dir> jobs   -> out/jobs.json
#   python3 full_round.py <full dir> table  (after grade.py out/jobs.json out/grades.json) -> out/results.json
import json, os, sys
F, MODE = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "dev/translation-open-stack-full/eval/2026-10-real-voices"))
from judge import cer  # noqa: E402
SETS = {"a": os.path.join(os.path.dirname(F), "heldout"), "b": os.path.join(F, "setb")}
# system label per run dir and the directions it ran with that translator
RUNS = {"A": None, "B": "gemma", "L": "milmmt", "PA": "pre38", "PL": "pre38"}
GEMMA_IN_A = {"en-ht", "ht-en"}
OUT = os.path.join(F, "out"); os.makedirs(OUT, exist_ok=True)


def label(run, d):
    if run == "A":
        return "gemma" if d in GEMMA_IN_A else "hymt"
    return RUNS[run]


def witness(st, l):
    p = os.path.join(SETS[st], "out", "witness", f"{l}.json")
    return json.load(open(p)) if os.path.exists(p) else []


def flagged(st, l):
    return {r["i"] for r in witness(st, l) if r.get("cut_off") or r.get("meaning_differs")}


def collect():
    data = {}
    for st in SETS:
        for run in RUNS:
            e = os.path.join(F, f"e2e_{run}_{st}", "out")
            if not os.path.exists(os.path.join(e, "sentences.json")):
                continue
            sents, lat = json.load(open(os.path.join(e, "sentences.json"))), json.load(open(os.path.join(e, "latency.json")))
            for d, v in sents.items():
                data.setdefault(st, {}).setdefault(d, {})[label(run, d)] = {"live_out": v["live_out"], "heard": v["heard_per_sentence"], "lat": lat.get(d, {}), "run": run}
    return data


if MODE == "jobs":
    jobs = []
    for st, dd in collect().items():
        CL = os.path.join(SETS[st], "clips_reg")
        en = json.load(open(os.path.join(CL, "en.txt.json")))
        said_en = json.load(open(os.path.join(SETS[st], "out", "said_en.json")))
        said = [said_en.get(str(i), t) for i, t in enumerate(en)]
        for d, systems in sorted(dd.items()):
            s, t = d.split("-")
            sy = {k: v["live_out"] for k, v in systems.items()}
            if s == "en":
                jobs.append({"id": f"WRITTEN:{st}:{d}", "src": s, "tgt": t, "source": en, "reference": en, "systems": sy})
                jobs.append({"id": f"SAID:{st}:{d}", "src": s, "tgt": t, "source": said, "reference": said, "systems": sy})
            else:
                ref = json.load(open(os.path.join(SETS[st], "out", "meaning_ht.json"))) if s == "ht" else en
                jobs.append({"id": f"WRITTEN:{st}:{d}", "src": s, "tgt": t, "source": json.load(open(os.path.join(CL, f"{s}.txt.json"))),
                             "reference": ref, "systems": sy})
    json.dump(jobs, open(os.path.join(OUT, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs")
else:
    G = json.load(open(os.path.join(OUT, "grades.json")))
    data = collect()
    q = lambda g: {"q": round(100 * sum(x.get("score", 0) for x in g) / (3 * max(1, len(g))), 1),
                   "crit": sum(1 for x in g if x.get("critical")), "n": len(g)}
    res = {}
    for k, v in G.items():
        ref, st, d = k.split(":")
        s = d.split("-")[0]
        for sysn, g in v["grades"].items():
            r = res.setdefault(st, {}).setdefault(d, {}).setdefault(sysn, {})
            if ref == "WRITTEN":
                r["written"] = q(g)
                if s != "en":
                    bad = flagged(st, s)
                    r["said"] = q([x for x in g if x["i"] not in bad])
            else:
                r["said"] = q(g)
    for st, dd in data.items():
        CL = os.path.join(SETS[st], "clips_reg")
        for d, systems in dd.items():
            s = d.split("-")[0]
            txt = json.load(open(os.path.join(CL, f"{s}.txt.json")))
            if s == "en":
                said_en = json.load(open(os.path.join(SETS[st], "out", "said_en.json")))
                ref, keep = [said_en.get(str(i), t) for i, t in enumerate(txt)], range(len(txt))
            else:
                bad = flagged(st, s)
                ref, keep = txt, [i for i in range(len(txt)) if i not in bad]
            for sysn, v in systems.items():
                hyp = " ".join(v["heard"][i] or "" for i in keep)
                gold = " ".join(ref[i] for i in keep)
                r = res.setdefault(st, {}).setdefault(d, {}).setdefault(sysn, {})
                lat = v["lat"]
                r.update({"cer_said": round(cer(gold, hyp), 4), "cer_written": lat.get("cer"),
                          "missing_audio": lat.get("missing_audio"), "utterances": lat.get("utterances"),
                          "stop_to_first_audio_ms": lat.get("stop_to_first_audio_ms"),
                          "stop_to_tail_audio_ms": lat.get("stop_to_tail_audio_ms"),
                          "dropped_utterances": (lat.get("stage") or {}).get("dropped_utterances"),
                          "gpu": lat.get("gpu"), "run": v["run"]})
    json.dump(res, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    for st in sorted(res):
        for d in sorted(res[st]):
            print(st, d, {k: ((x.get("written") or {}).get("q"), (x.get("said") or {}).get("q"), (x.get("said") or {}).get("crit"),
                              x.get("cer_said"), (x.get("stop_to_tail_audio_ms") or {}).get("p50"), x.get("missing_audio"))
                          for k, x in sorted(res[st][d].items())})
