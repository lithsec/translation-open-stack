# results.json: score.py's recognition figures (pooled over sets a and b) and the blind translation grades
# (../2026-11-talk-soniox/grade.py on mt_styles.py's jobs: share of the possible 3 per sentence, en→es and en→fr
# pooled, n = 80 per arm and style; critical errors of 80), and the markdown tables for the README.
#   python3 -I table.py <scores.json> <grades.json> results.json
import json, sys

S, G, OUT = (json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), sys.argv[3])
STYLES = ["paused", "irregular", "nonstop"]
ARMS = ["azure", "mai", "azure-default", "mai-default"]
q = {}
for k, v in G.items():
    _, clip, d = k.split(":")
    style = clip.split("_")[1]
    for arm, gr in v["grades"].items():
        a = q.setdefault((arm.removesuffix("-hear"), style), {"pts": 0, "max": 0, "critical": 0, "n": 0,
                                                              **{f"pts_{x}": 0 for x in ("es", "fr")}, **{f"max_{x}": 0 for x in ("es", "fr")}})
        t = d.split("-")[1]
        for x in gr:
            a["pts"] += x["score"]; a["max"] += 3; a["critical"] += bool(x["critical"]); a["n"] += 1
            a[f"pts_{t}"] += x["score"]; a[f"max_{t}"] += 3
res = {"recognition": S["pooled"], "translation": {}}
for (arm, style), a in sorted(q.items()):
    res["translation"][f"{arm} {style}"] = {"quality": round(100 * a["pts"] / a["max"], 1), "es": round(100 * a["pts_es"] / a["max_es"], 1),
                                           "fr": round(100 * a["pts_fr"] / a["max_fr"], 1), "critical": a["critical"], "n": a["n"]}
json.dump(res, open(OUT, "w"), indent=1)
print("| Recogniser (segmentation) | Style | WER plain | CER plain | WER spelled | CER spelled | Finals | Forced | Mid-sentence | Joined | Final lag p50 (s) | Quality en→es / fr (pooled) | Critical |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
lab = {"azure": "Azure standard (Talk: 300 ms)", "mai": "MAI (Talk: 300 ms)", "azure-default": "Azure standard (SDK default)",
       "mai-default": "MAI (SDK default)"}
for arm in ARMS:
    for st in STYLES:
        r = S["pooled"].get(f"{arm} {st}")
        if not r:
            continue
        t = res["translation"].get(f"{arm} {st}")
        tq = f"{t['es']} / {t['fr']} (**{t['quality']}**)" if t else "-"
        print(f"| {lab[arm]} | {st} | {r['werPlain']} | {r['cerPlain']} | {r['werSpelled']} | {r['cerSpelled']} | {r['finals']} | {r['forced']} | "
              f"{r['midSentence']} | {r['joined']} | {r['lagP50MeanOfSets']} | {tq} | {t['critical'] if t else '-'} |")
