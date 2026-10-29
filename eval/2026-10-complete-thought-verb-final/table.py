# ../2026-10-complete-thought-ht-km-lo/table.py for this run's ten directions and arms. '(prod)' marks production's
# sentence translator; 'Thoughts by fallback' here is the share of a CT arm's thoughts that came from the 2 s or 30-word
# fallback. That file:
# ../2026-10-complete-thought-endpointing/table.py for the ht/km/lo directions and arms. That file:
# The README's tables from results.json (round 1) and results_r2.json (round 2, when present): per
# direction and arm, quality is the mean of the two pause patterns and of the rounds; latencies are medians of
# the per-clip figures (longest wait: the larger of the two clips), in seconds.
#   python3 -I table.py
import json, os, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
R1 = json.load(open(os.path.join(HERE, "results.json")))
p2 = os.path.join(HERE, "results_r2.json")
R2 = json.load(open(p2)) if os.path.exists(p2) else None
DIRS = ["en-ja", "en-ko", "en-fa", "en-ur", "en-bn", "en-ta", "ja-en", "ko-en", "fa-en", "hi-en"]
SOL_PROD = {"en-ja", "en-fa", "ja-en", "ko-en", "hi-en"}
NAME = {}
for r in ("az", "mai"):
    NAME[f"S-sol-{r}"] = "Sentences, sol"
    NAME[f"S-{r}"] = "Sentences, Gemma"
    NAME[f"ctb-{r}"] = "CT (b), Gemma"
    NAME[f"ctb-gs-{r}"] = "CT (b), Gemma decides, sol translates"
    NAME[f"agree-{r}"] = "Agree, Gemma"
    NAME[f"room-{r}"] = "Room CT (b): one decider, production translator"
    NAME[f"room-g-{r}"] = "Room CT (b): one decider, Gemma translates"
ARROW = lambda d: d.replace("-", "→")


def rows(res, d, s):
    return [res["rows"][k][s] for k in res["rows"] if k.split(":")[1] == d and s in res["rows"][k]]


def q(res, d, s):
    R = [r["said"]["q"] for r in rows(res, d, s) if r.get("said")] if res else []
    return st.mean(R) if R else None


def line(d, s):
    R = rows(R1, d, s)
    lat = lambda f, agg=st.median: round(agg(r["lat"][f] for r in R) / 1000, 1)
    # A whole-sentence arm's chunk is a recogniser final, and on the irr clips one final often covers two or
    # three read sentences, so the check sees the same chunk under each of them and calls it "repeated". For
    # those arms only the reg clip counts (marked *).
    sent_arm = s.startswith("S-")
    c = [res_r["contradictions"] for k, res_r in ((k, R1["rows"][k][s]) for k in R1["rows"] if k.split(":")[1] == d and s in R1["rows"][k])
         if res_r.get("contradictions") and (not sent_arm or k.startswith("reg:"))]
    n = sum(x["chunks"] for x in c)
    wrong = f"{round(100 * sum(x['wrong'] for x in c) / n)}%{'*' if sent_arm else ''}" if n else "–"
    sp = [r["split"] for r in R if r.get("split")]
    ns = sum(x["sentences"] for x in sp)
    split = f"{round(100 * sum(x['sentences_split'] for x in sp) / ns)}%" if ns else "–"
    wt = [r["whole_thought_q"] for r in R if r.get("whole_thought_q") is not None]
    crit = st.mean(r["said"]["crit"] for r in R if r.get("said"))
    q1, q2 = q(R1, d, s), q(R2, d, s)
    qm = st.mean([x for x in (q1, q2) if x is not None])
    calls = {}
    for r in R:
        for k, v in r["calls_by_model_per_sentence"].items():
            calls[k] = calls.get(k, 0) + v / len(R)
    cs = " + ".join(f"{v:.1f}{' sol' if k == 'sol' else ''}" for k, v in sorted(calls.items(), key=lambda kv: kv[0] == "sol"))
    fb = sum(r["fallbacks"]["flush"] + r["fallbacks"]["force"] for r in R) / max(1, sum(r.get("thoughts", 0) for r in R))
    prod = " (prod)" if s.startswith("S-") and (s.startswith("S-sol") == (d in SOL_PROD)) else ""
    return (f"| {ARROW(d)} | {NAME[s]}{prod} | {q1:.1f} | {'–' if q2 is None else f'{q2:.1f}'} | **{qm:.1f}** | {crit:.1f} | "
            f"{lat('first_p50')} | {lat('last_p50')} | {lat('last_p90')} | {lat('longest_wait', max)} | {wrong} | {split} | "
            f"{st.mean(wt) if wt else float('nan'):.1f} | {cs} | {'–' if s.startswith('S-') else f'{100 * fb:.0f}%'} |"), qm


print("| Direction | Arm | Quality, said (round 1) | Round 2 | Mean | Critical | Speech starts → first audio (s) | "
      "Speech ends → last audio, p50 (s) | p90 (s) | Longest wait (s) | Chunks wrong later | Sentences split mid-clause | "
      "Quality of unsplit sentences | Calls per sentence | Thoughts by fallback |")
print("|---" * 15 + "|")
for d in DIRS:
    for s in NAME:
        if rows(R1, d, s):
            print(line(d, s)[0])
