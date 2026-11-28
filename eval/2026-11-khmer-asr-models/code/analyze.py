# Tables for the README: per recogniser, characters wrong (cer.py), seconds per sentence, and sol's English graded
# (score 0-100 = mean of 0-3 grades / 3, both rounds, each round alone, critical errors per round). Writes results.json.
#   python3 -I analyze.py DATA OUT.json     (DATA: set.json, the run files, tr_km.json and az_km_pin.json of
#   ../../2026-11-khmer-table-talk, mt.json, grades.json)
import json, os, sys
sys.argv, (D, OUT) = sys.argv[:1] + [os.path.join(sys.argv[1], "set.json")], sys.argv[1:3]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cer import score  # noqa: E402
G = json.load(open(f"{D}/grades.json"))
RUNS = {"tha": "tha.json", "tha-greedy": "tha_greedy.json", "psar": "psar.json", "qwen": "qwen.json", "gemini": "gemini.json",
        "transcribe": "tr_km.json", "azure": "az_km_pin.json"}
res = {}
for arm in ["perfect", *RUNS]:
    sc, cr, rounds = [], 0, {"1": [], "2": []}
    for j in G:
        for r, g in j["grades"].items():
            v = g.get(arm, {}); s = v.get("score", 0); sc.append(s); rounds[str(r)].append(s); cr += 1 if v.get("critical") else 0
    row = {"sol": round(100 * sum(sc) / (3 * len(sc)), 1), "r1": round(100 * sum(rounds["1"]) / (3 * len(rounds["1"])), 1),
           "r2": round(100 * sum(rounds["2"]) / (3 * len(rounds["2"])), 1), "critical_per_round": cr / 2}
    if arm in RUNS and os.path.exists(f"{D}/{RUNS[arm]}"): row |= score(json.load(open(f"{D}/{RUNS[arm]}")))
    res[arm] = row
json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
for k, v in res.items(): print(k, v)
