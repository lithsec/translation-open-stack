# Scores stream.py's runs against the FLEURS text: WER and CER on each clip's whole text (every final joined, in
# order), under two normalisations: "plain" (NFKC, lower case, punctuation to spaces) and "spelled" (also digits
# spelled out with num2words, as ../2026-10-whisper-vs-azure/score.py, so "12" and "twelve" score alike). CER is on
# characters with spaces removed. Also, per run:
#   finals         how many finals the recogniser gave for the 20 sentences
#   forced         finals at the forced cut (duration >= 19.5 s of the 20 s)
#   mid-sentence   finals that end inside a read sentence (align.py cuts: by text, as MAI's offsets are off): a
#                  sentence split across two finals, the piece Talk translates on its own
#   joined         finals spanning two or more read sentences (align.py)
#   lag p50/p90    a final's arrival after the end of its audio (s)
#   python3 -I score.py <out root> <styles root> RESULTS.json
import json, os, re, statistics, sys, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import align  # noqa: E402
from num2words import num2words

OUT, STY, RES = sys.argv[1], sys.argv[2], sys.argv[3]
ORD = re.compile(r"(\d+)(st|nd|rd|th)\b", re.I)


def spell(s):
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    s = ORD.sub(lambda m: " " + num2words(int(m.group(1)), to="ordinal") + " ", s)
    return re.sub(r"\d+", lambda m: " " + num2words(int(m.group(0))) + " ", s)


def norm(s, spelled):
    s = unicodedata.normalize("NFKC", s)
    if spelled:
        s = spell(s)
    s = re.sub(r"[^\w\s']|_", " ", s.lower()).replace("'", "")
    return re.sub(r"\s+", " ", s).strip()


def ed(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def rates(ref, hyp, spelled):
    r, h = norm(ref, spelled), norm(hyp, spelled)
    return {"wer": round(100 * ed(r.split(), h.split()) / len(r.split()), 2),
            "cer": round(100 * ed(r.replace(" ", ""), h.replace(" ", "")) / len(r.replace(" ", "")), 2),
            "words": len(r.split()), "chars": len(r.replace(" ", ""))}


runs = {}
for rec in sorted(r for r in os.listdir(OUT) if r.split("-")[0] in ("azure", "mai") and os.path.isdir(os.path.join(OUT, r))):
    for f in sorted(os.listdir(os.path.join(OUT, rec))):
        x = json.load(open(os.path.join(OUT, rec, f)))
        name = x["clip"]
        meta = json.load(open(os.path.join(STY, f"clips_{name}", "en.json")))
        gold = json.load(open(os.path.join(STY, f"clips_{name}", "en.txt.json")))
        ref, hyp = " ".join(gold), " ".join(fi["text"] for fi in x["finals"])
        lags = [fi["arrivedMs"] / 1000 - (fi["offsetMs"] + fi["durationMs"]) / 1000 for fi in x["finals"]]
        forced = sum(fi["durationMs"] >= 19500 for fi in x["finals"])
        c = align.cuts(x["finals"], gold)
        mid, joined = sum(z["mid"] for z in c), sum(z["joined"] for z in c)
        runs[f"{rec} {name}"] = {"recogniser": rec, "set": name.split("_")[0], "style": name.split("_")[1],
                                "err": x["err"], "plain": rates(ref, hyp, False), "spelled": rates(ref, hyp, True),
                                "finals": len(x["finals"]), "forced": forced, "midSentence": mid, "joined": joined,
                                "lagP50": round(statistics.median(lags), 2) if lags else None,
                                "lagP90": round(sorted(lags)[int(0.9 * (len(lags) - 1))], 2) if lags else None,
                                "firstPartialS": round(x["firstPartialMs"] / 1000, 2) if x.get("firstPartialMs") else None,
                                "partials": x.get("partials")}

# Pooled over sets a and b (errors over the pooled reference length).
table = {}
for k, v in runs.items():
    t = table.setdefault(f"{v['recogniser']} {v['style']}", {"wE": 0, "w": 0, "cE": 0, "c": 0, "sE": 0, "sC": 0, "sw": 0, "sW": 0,
                                                          "finals": 0, "forced": 0, "midSentence": 0, "joined": 0, "lags": []})
    for n, key in (("plain", ""), ("spelled", "s")):
        r = v[n]
        if key:
            t["sW"] += r["wer"] * r["words"] / 100; t["sw"] += r["words"]; t["sE"] += r["cer"] * r["chars"] / 100; t["sC"] += r["chars"]
        else:
            t["wE"] += r["wer"] * r["words"] / 100; t["w"] += r["words"]; t["cE"] += r["cer"] * r["chars"] / 100; t["c"] += r["chars"]
    for m in ("finals", "forced", "midSentence", "joined"):
        t[m] += v[m]
    t["lags"].append(v["lagP50"])
pooled = {k: {"werPlain": round(100 * t["wE"] / t["w"], 2), "cerPlain": round(100 * t["cE"] / t["c"], 2),
              "werSpelled": round(100 * t["sW"] / t["sw"], 2), "cerSpelled": round(100 * t["sE"] / t["sC"], 2),
              "finals": t["finals"], "forced": t["forced"], "midSentence": t["midSentence"], "joined": t["joined"],
              "lagP50MeanOfSets": round(statistics.mean(t["lags"]), 2)} for k, t in sorted(table.items())}
json.dump({"pooled": pooled, "runs": runs}, open(RES, "w"), indent=1)
print(f"{'run':22} {'WER':>6} {'CER':>6} {'WERs':>6} {'CERs':>6} {'fin':>4} {'forc':>4} {'mid':>4} {'join':>4} {'lag':>5}")
for k, p in pooled.items():
    print(f"{k:22} {p['werPlain']:6} {p['cerPlain']:6} {p['werSpelled']:6} {p['cerSpelled']:6} {p['finals']:4} {p['forced']:4} {p['midSentence']:4} {p['joined']:4} {p['lagP50MeanOfSets']:5}")
