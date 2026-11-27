# Tables for the README: translation quality per set and translator, hearing (characters wrong, time to the last
# final), Azure's language ID between English and Khmer, and the voice check. Writes results.json.
#   python3 -I analyze.py DATA VOICEDIR OUT.json
import json, re, statistics as st, sys, unicodedata
D, V, OUT = sys.argv[1:4]
S = json.load(open(f"{D}/set.json")); MT = json.load(open(f"{D}/mt.json")); G = json.load(open(f"{D}/grades.json"))
ARMS = ["sol", "flash", "gemma", "azure"]
def norm(s): return "".join(c for c in unicodedata.normalize("NFC", s or "") if not (c.isspace() or unicodedata.category(c).startswith("P")))
def lev(a, b):
    p = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        c = [i]
        for j, y in enumerate(b, 1): c.append(min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (x != y)))
        p = c
    return p[-1]
def cer(pairs): return round(100 * sum(lev(norm(r), norm(h)) for r, h in pairs) / max(1, sum(len(norm(r)) for r, _ in pairs)), 1)
pct = lambda xs, q: sorted(xs)[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))] if xs else None
res = {"quality": {}, "latency_translate_ms": {}, "hearing": {}, "lid": {}, "voice": []}
for st_ in sorted({j["set"] for j in G}):
    for a in ARMS:
        sc, cr, rounds = [], 0, {1: [], 2: []}
        for j in (x for x in G if x["set"] == st_):
            for r, g in j["grades"].items():
                v = g.get(a, {}); s = v.get("score", 0); sc.append(s); rounds[int(r)].append(s); cr += 1 if v.get("critical") else 0
        res["quality"][f"{st_}:{a}"] = {"q": round(100 * sum(sc) / (3 * len(sc)), 1), "r1": round(100 * sum(rounds[1]) / (3 * len(rounds[1])), 1),
                                        "r2": round(100 * sum(rounds[2]) / (3 * len(rounds[2])), 1), "critical_per_round": cr / 2, "n": len(sc) // 2}
for k, v in MT.items():
    ms = [x["ms"] for x in v if x and not x.get("error") and x["out"]]
    res["latency_translate_ms"][k] = {"p50": pct(ms, .5), "p90": pct(ms, .9)}
km_ref = {s["km_file"]: s["km"] for s in S}
tr = json.load(open(f"{D}/tr_km.json"))
res["hearing"]["transcribe (chirp3 eval, stored)"] = {"cer": cer([(km_ref[r["file"]], r["hyp"]) for r in tr]),
    "final_after_speech_end_p50_s": pct([r["final_after_end_s"] for r in tr], .5), "note": "relative to the FLEURS file's end (files carry trailing silence)"}
for name in ("az_km_pin", "az_km_lid"):
    rows = json.load(open(f"{D}/{name}.json"))
    lag = [f["t"] - f["end"] for r in rows for f in r["finals"]]
    res["hearing"][name] = {"cer": cer([(km_ref[r["file"]], r["hyp"]) for r in rows]), "n": len(rows),
        "final_after_its_audio_p50_s": round(pct(lag, .5), 2), "p90_s": round(pct(lag, .9), 2),
        "final_after_speech_end_p50_s": pct([r["final_after_end_s"] for r in rows if r["final_after_end_s"] is not None], .5),
        "errors": sum(1 for r in rows if r["error"])}
for name, want in (("az_km_lid", "km-KH"), ("az_en_lid", "en-US")):
    rows = json.load(open(f"{D}/{name}.json"))
    segs = [f for r in rows for f in r["finals"]]
    chars = lambda fs: sum(len(norm(f["text"])) for f in fs)
    res["lid"][name] = {"segments": len(segs), "segments_right": sum(1 for f in segs if f["lang"] == want),
        "chars_right_pct": round(100 * chars([f for f in segs if f["lang"] == want]) / max(1, chars(segs)), 1),
        "sentences_all_right": sum(1 for r in rows if r["finals"] and all(f["lang"] == want for f in r["finals"])), "sentences": len(rows)}
en_rows = json.load(open(f"{D}/az_en_lid.json")); en_ref = {s["en_file"]: s["en"] for s in S}
res["hearing"]["az_en_lid (English clips)"] = {"cer": cer([(en_ref[r["file"]].lower(), r["hyp"].lower()) for r in en_rows])}
vj = json.load(open(f"{V}/voice.json")); heard = {}
for line in open(f"{V}/heard.tsv", encoding="utf-8"):
    f, j = line.rstrip("\n").split("\t", 1); heard[f] = json.loads(j).get("DisplayText", "")
for r in vj:
    text = MT["en-km:ref:sol"][r["i"] - 1]["out"]
    res["voice"].append({k: r[k] for k in ("i", "voice", "seconds", "voiced_s", "chars_per_voiced_s", "file")} | {"azure_km_stt_cer": cer([(text, heard.get(r["file"], ""))])})
for vn in ("en-US-AvaMultilingualNeural", "km-KH-SreymomNeural"):
    rs = [r for r in res["voice"] if r["voice"] == vn]
    texts = [MT["en-km:ref:sol"][r["i"] - 1]["out"] for r in rs]
    res.setdefault("voice_summary", {})[vn] = {"seconds": round(sum(r["seconds"] for r in rs), 1), "azure_km_stt_cer": cer([(t, heard.get(r["file"], "")) for t, r in zip(texts, rs)])}
json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
for k, v in res["quality"].items(): print(k, v)
print(json.dumps({k: res[k] for k in ("hearing", "lid", "voice_summary")}, indent=1))
print({k: v for k, v in res["latency_translate_ms"].items() if k.startswith(("en-km:ref", "km-en:ref"))})
