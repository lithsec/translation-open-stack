# ../../round.py for the Lao-on-Gemma re-run: one blind grading call per (clip set, direction, reference) with
# three systems side by side: this re-run (commercial, Gemma 4 both ways: e2e_G_{a,b} here) and the saved
# runs of the November round (commercial MADLAD 7B / Hy-MT2: ../e2e_C_*; nonprofit MiLMMT-46: ../e2e_N_*).
# Same clips (checked: check_texts), same references (../seta, ../setb), same grader (../../../2026-10-unseen/grade.py).
#   python3 -I round_lao.py jobs     -> out/jobs.json
#   GEMINI_API_KEY=... python3 -I ../../../2026-10-unseen/grade.py out/jobs.json out/grades.json
#   python3 -I round_lao.py table    -> out/results.json, the README table
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); R = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "2026-10-real-voices"))
from judge import cer  # noqa: E402
MODE = sys.argv[1]
SETS = {"a": os.path.join(R, "seta"), "b": os.path.join(R, "setb")}
RUNS = {"gemma": (HERE, "G"), "madlad_hymt": (R, "C"), "milmmt": (R, "N")}
NAME = {"gemma": "commercial, Gemma 4 (this re-run)", "madlad_hymt": "commercial, MADLAD 7B / Hy-MT2 (Nov round)",
        "milmmt": "nonprofit, MiLMMT-46 12B (Nov round)"}
DIRS = ["en-lo", "lo-en"]
OUT = os.path.join(HERE, "out"); os.makedirs(OUT, exist_ok=True)


def flagged(st, l):
    p = os.path.join(SETS[st], "out", "witness", f"{l}.json")
    return {r["i"] for r in (json.load(open(p)) if os.path.exists(p) else []) if r.get("cut_off") or r.get("meaning_differs")}


def collect():
    data = {}
    for st in SETS:
        for sysn, (base, tag) in RUNS.items():
            e = os.path.join(base, f"e2e_{tag}_{st}", "out")
            sents, lat = json.load(open(os.path.join(e, "sentences.json"))), json.load(open(os.path.join(e, "latency.json")))
            for d in DIRS:
                v = sents[d]
                data.setdefault(st, {}).setdefault(d, {})[sysn] = {"live_out": v["live_out"], "heard": v["heard_per_sentence"],
                                                                  "source": v["source"], "lat": lat.get(d, {})}
    return data


if MODE == "jobs":
    data = collect()
    jobs = []
    for st, dd in data.items():
        CL = os.path.join(SETS[st], "clips_reg")
        en = json.load(open(os.path.join(CL, "en.txt.json")))
        said_en = json.load(open(os.path.join(SETS[st], "out", "said_en.json")))
        said = [said_en.get(str(i), t) for i, t in enumerate(en)]
        for d, systems in sorted(dd.items()):
            s, t = d.split("-")
            src = json.load(open(os.path.join(CL, f"{s}.txt.json")))
            for k, v in systems.items():   # same clips: every run's sentence texts are the saved set's
                assert v["source"] == src, (st, d, k)
            sy = {k: v["live_out"] for k, v in systems.items()}
            if s == "en":
                jobs.append({"id": f"WRITTEN:{st}:{d}", "src": s, "tgt": t, "source": en, "reference": en, "systems": sy})
                jobs.append({"id": f"SAID:{st}:{d}", "src": s, "tgt": t, "source": said, "reference": said, "systems": sy})
            else:
                jobs.append({"id": f"WRITTEN:{st}:{d}", "src": s, "tgt": t, "source": src, "reference": en, "systems": sy})
    json.dump(jobs, open(os.path.join(OUT, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs")
    sys.exit()

G = json.load(open(os.path.join(OUT, "grades.json")))   # partial grades: the missing ones show as None
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
            r = res.setdefault(st, {}).setdefault(d, {}).setdefault(sysn, {})
            lat = v["lat"]
            r.update({"cer_said": round(cer(" ".join(ref[i] for i in keep), hyp), 4), "cer_written": lat.get("cer"),
                      "missing_audio": lat.get("missing_audio"), "utterances": lat.get("utterances"),
                      "stop_to_first_audio_ms": lat.get("stop_to_first_audio_ms"),
                      "stop_to_tail_audio_ms": lat.get("stop_to_tail_audio_ms"),
                      "dropped_utterances": (lat.get("stage") or {}).get("dropped_utterances")})
        g, o = systems["gemma"]["live_out"], {k: v["live_out"] for k, v in systems.items() if k != "gemma"}
        for k, x in o.items():
            res[st][d].setdefault("gemma", {}).setdefault("differs_from", {})[k] = sum(1 for a, b in zip(g, x) if a != b)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


summary = {}
for d in DIRS:
    for sysn in RUNS:
        rows = [res[st][d][sysn] for st in "ab"]
        gg = lambda k, f: [(r.get(k) or {}).get(f) for r in rows]
        summary.setdefault(d, {})[sysn] = {
            "system": NAME[sysn], "said": mean(gg("said", "q")), "written": mean(gg("written", "q")),
            "said_per_set": gg("said", "q"), "written_per_set": gg("written", "q"),
            "crit_said": sum(x or 0 for x in gg("said", "crit")), "crit_written": sum(x or 0 for x in gg("written", "crit")),
            "first_audio_p50": gg("stop_to_first_audio_ms", "p50"), "first_audio_p90": gg("stop_to_first_audio_ms", "p90"),
            "last_audio_p50": gg("stop_to_tail_audio_ms", "p50"), "last_audio_p90": gg("stop_to_tail_audio_ms", "p90"),
            "missing_audio": [r.get("missing_audio") for r in rows], "dropped_utterances": [r.get("dropped_utterances") for r in rows],
            "cer_said": mean([100 * r["cer_said"] for r in rows]), "differs_from": [r.get("differs_from") for r in rows]}
json.dump({"note": "Lao re-run on Gemma 4 (commercial), graded side by side with the November round's saved Lao outputs: "
                   "one blind call per (set, direction, reference), gemini-pro-latest. Latency ms per set [a, b]; cer_said in %.",
           "summary": summary, "per_set": res}, open(os.path.join(OUT, "results.json"), "w"), ensure_ascii=False, indent=1)
f = lambda v: " / ".join("–" if x is None else f"{x / 1000:.1f}" for x in v)
print("Grades:", len(G), "of 6 calls" + ("" if len(G) == 6 else " (None = not graded yet; set means are over the graded sets only)"))
print("| Direction | System | Quality, said (written) | Per set, said (written) | Critical, said | First audio p50 | First audio p90 | Last audio p50 | Last audio p90 | Drops | Recognition |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
for d in DIRS:
    for sysn in RUNS:
        s = summary[d][sysn]
        ps = ", ".join(f"{a} ({b})" for a, b in zip(s["said_per_set"], s["written_per_set"]))
        print_pending = None in s["said_per_set"] + s["written_per_set"]
        print(f"| {d.replace('-', '→')} | {s['system']} | {s['said']} ({s['written']}) | {ps} | {s['crit_said']} | {f(s['first_audio_p50'])} | "
              f"{f(s['first_audio_p90'])} | {f(s['last_audio_p50'])} | {f(s['last_audio_p90'])} | "
              f"{sum(s['missing_audio'])} / {sum(s['dropped_utterances'])} | {s['cer_said']}% |")
