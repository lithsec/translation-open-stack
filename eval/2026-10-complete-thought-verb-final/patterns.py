# Per pause pattern (reg: 1.0-1.95 s between sentences; irr: 0.3-1.2 s), every arm, from results.json and
# results_r2.json (quality: the mean of the rounds that graded that direction). Latencies in seconds for that clip.
#   python3 -I patterns.py
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
DIRS = ["en-ja", "en-ko", "en-fa", "en-ur", "en-bn", "en-ta", "ja-en", "ko-en", "fa-en", "hi-en"]
NAME = {}
for r in ("az", "mai"):
    NAME[f"S-sol-{r}"] = "Sentences, sol"
    NAME[f"S-{r}"] = "Sentences, Gemma"
    NAME[f"ctb-{r}"] = "CT (b), Gemma"
    NAME[f"ctb-gs-{r}"] = "CT (b), Gemma-sol"
    NAME[f"agree-{r}"] = "Agree, Gemma"
    NAME[f"room-{r}"] = "Room CT (b), production translator"
    NAME[f"room-g-{r}"] = "Room CT (b), Gemma"
R = [json.load(open(os.path.join(HERE, f))) for f in ("results.json", "results_r2.json") if os.path.exists(os.path.join(HERE, f))]
print("| Direction | Pauses | Arm | Quality | Critical | First audio | Last audio p50 / p90 | Wait p90 | Longest wait |")
print("|---|---|---|---|---|---|---|---|---|")
for d in DIRS:
    for pat in ("reg", "irr"):
        row = R[0]["rows"].get(f"{pat}:{d}", {})
        for n in NAME:
            if n not in row or not row[n].get("said"):
                continue
            r = row[n]
            qs = [x["rows"][f"{pat}:{d}"][n]["said"]["q"] for x in R if x["rows"].get(f"{pat}:{d}", {}).get(n, {}).get("said")]
            L = {k: v / 1000 for k, v in r["lat"].items()}
            print(f"| {d.replace('-', '→')} | {pat} | {NAME[n]} | {sum(qs) / len(qs):.1f} | {r['said']['crit']} | {L['first_p50']:.1f} | "
                  f"{L['last_p50']:.1f} / {L['last_p90']:.1f} | {L['wait_p90']:.1f} | {L['longest_wait']:.1f} |")
