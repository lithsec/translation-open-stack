# Per pause pattern: sentences against CT (b) Gemma-sol (and, on reg, sol deciding), from results.json and
# results_r2.json. Quality is the mean of the two rounds; latencies in seconds for that clip.
#   python3 -I patterns.py
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
R = [json.load(open(os.path.join(HERE, f))) for f in ("results.json", "results_r2.json")]
print("| Direction | Pauses | Arm | Quality | Critical | First audio | Last audio p50 / p90 | Wait p90 | Longest wait |")
print("|---|---|---|---|---|---|---|---|---|")
for d in ["en-ht", "en-km", "en-lo", "ht-en", "km-en", "lo-en"]:
    for pat in ("reg", "irr"):
        row = R[0]["rows"][f"{pat}:{d}"]
        for n in sorted(row, key=lambda n: (not n.startswith("S-"), "-gs-" not in n, n)):
            if not (n.startswith("S-") or "-gs-" in n or "-sol-" in n):
                continue
            r = row[n]
            q = sum(x["rows"][f"{pat}:{d}"][n]["said"]["q"] for x in R) / 2
            L = {k: v / 1000 for k, v in r["lat"].items()}
            arm = ("Sentences, sol" if n.startswith("S-") else "CT (a) Gemma-sol" if n.startswith("cta") else
                   "CT (b) Gemma-sol" if "-gs-" in n else "CT (b) sol decides")
            print(f"| {d.replace('-', '→')} | {pat} | {arm} | {q:.1f} | {r['said']['crit']} | {L['first_p50']:.1f} | "
                  f"{L['last_p50']:.1f} / {L['last_p90']:.1f} | {L['wait_p90']:.1f} | {L['longest_wait']:.1f} |")
