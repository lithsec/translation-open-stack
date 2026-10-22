# pieces <e2e dir> <out.json> [dirs...]: each live utterance's English (heard) and Hy-MT2 output.
# assemble <e2e dir> <qe.json> <out.json>: per sentence, the QE pick (lower MetricX of Hy-MT2 / MADLAD
# per utterance), joined across the utterances assigned to it exactly as analyze_e2e.py does.
import difflib, json, os, re, sys, wave
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "analyze_e2e.py")).read()
ns = {"np": np, "json": json, "os": os, "re": re, "wave": wave, "difflib": difflib}
mode, E = sys.argv[1], sys.argv[2]
ns["CL"] = os.path.join(E, "clips")
exec(src[src.index("def speech_bounds"):src.index("def pct")], ns)
RUNS = os.path.join(E, "out", "runs")
if mode == "pieces":
    out = []
    for d in sys.argv[4:]:
        run = json.load(open(os.path.join(RUNS, f"{d}.json")))
        for k, u in enumerate(ns["utterances"](run["events"])):
            out.append({"key": f"{os.path.basename(E)}:{d}:{k}", "src": u["heard"], "tgt": d.split("-")[1],
                        "hy": "".join(x["text"] for x in u["texts"]).strip()})
    json.dump(out, open(sys.argv[3], "w"), ensure_ascii=False, indent=0)
    print(len(out), "pieces")
else:
    Q = {p["key"]: p for p in json.load(open(sys.argv[3]))}
    res = {}
    for d in sorted({k.split(":")[1] for k in Q if k.startswith(os.path.basename(E) + ":")}):
        run = json.load(open(os.path.join(RUNS, f"{d}.json")))
        s = d.split("-")[0]
        gold = json.load(open(os.path.join(ns["CL"], f"{s}.txt.json")))
        us = ns["utterances"](run["events"])
        hit = ns["assign"](us, gold, ns["speech_bounds"](s))
        picks = []
        for k, u in enumerate(us):
            q = Q[f"{os.path.basename(E)}:{d}:{k}"]
            use = "madlad" if q.get("qe_madlad", 99) < q.get("qe_hy", 99) and q["madlad"].strip() else "hy"
            picks.append((use, q[use]))
        rows = [" ".join(picks[j][1] for j, h in enumerate(hit) if i in h).strip() for i in range(len(gold))]
        res[d] = {"live_out": rows, "madlad_share": round(sum(1 for p in picks if p[0] == "madlad") / max(1, len(picks)), 2)}
        print(d, res[d]["madlad_share"])
    json.dump(res, open(sys.argv[4], "w"), ensure_ascii=False, indent=1)
