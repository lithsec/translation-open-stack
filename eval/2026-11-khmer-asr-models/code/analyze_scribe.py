# Tables for the README's OpenRouter and ElevenLabs sections: characters wrong (cer.py's normalisation) on the 24
# sentences, seconds per call, sol's English graded in one shared set of rounds (runs/grades_scribe.json: perfect,
# Transcribe, Azure, Tha-ASR beam, Gemini 3.5 Transcribe, Scribe v2, Scribe v3, gpt-transcribe), paired bootstrap
# differences, and the realtime runs on the first 5 sentences. Writes results/results_scribe.json.
#   python3 -I analyze_scribe.py RUNS OUT.json
import json, os, random, statistics, sys, unicodedata
R, OUT = sys.argv[1:3]
S = json.load(open(f"{R}/set.json")); ref = {s["km_file"]: s["km"] for s in S}; five = [s["km_file"] for s in S[:5]]
def norm(s): return "".join(c for c in unicodedata.normalize("NFC", s or "") if not (c.isspace() or unicodedata.category(c).startswith("P")))
def lev(a, b):
    p = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        c = [i]
        for j, cb in enumerate(b, 1): c.append(min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (ca != cb)))
        p = c
    return p[-1]
def load(f): return {os.path.basename(r["file"]): r for r in json.load(open(f"{R}/{f}"))}
def cer(rows, files): return round(100 * sum(lev(norm(ref[f]), norm(rows[f]["hyp"])) for f in files) / sum(len(norm(ref[f])) for f in files), 1)
out = {"batch": {}, "realtime_first5": {}, "sol": {}, "paired": {}}
for name, f in {"openrouter/scribe-v2": "openrouter/scribe-v2.json", "elevenlabs/scribe-v2": "elevenlabs/scribe-v2_batch.json",
                "elevenlabs/scribe-v3": "elevenlabs/scribe-v3_batch.json", "openrouter/gpt-transcribe (auto)": "openrouter/gpt-transcribe_auto.json",
                "openrouter/gpt-4o-transcribe (auto)": "openrouter/gpt-4o-transcribe_auto.json", "openrouter/whisper-large-v3 (km)": "openrouter/whisper-large-v3_km.json",
                "openrouter/whisper-large-v3 (auto)": "openrouter/whisper-large-v3_auto.json", "openrouter/whisper-large-v3-turbo (km)": "openrouter/whisper-large-v3-turbo_km.json"}.items():
    rows = load(f); files = [x for x in ref if x in rows]
    out["batch"][name] = {"n": len(files), "cer": cer(rows, files), "s_p50": statistics.median(rows[x]["s"] for x in files),
                          "empty": sum(1 for x in files if not rows[x]["hyp"].strip()),
                          "not_khmer_script": sum(1 for x in files if rows[x]["hyp"].strip() and sum('ក' <= c <= '៿' for c in rows[x]["hyp"]) < len(norm(rows[x]["hyp"])) / 2)}
for name, f in {"scribe_v2_realtime vad": "elevenlabs/scribe-v2-realtime_vad.json", "scribe_v2_realtime manual": "elevenlabs/scribe-v2-realtime_manual.json",
                "scribe_v3_live vad": "elevenlabs/scribe-v3-live_vad.json", "scribe_v3_live manual": "elevenlabs/scribe-v3-live_manual.json",
                "scribe_v2 batch (same 5)": "elevenlabs/scribe-v2_batch.json", "scribe_v3 batch (same 5)": "elevenlabs/scribe-v3_batch.json"}.items():
    rows = load(f); row = {"cer": cer(rows, five)}
    if "first_partial_s" in rows[five[0]]:
        row |= {"first_partial_s_p50": statistics.median(rows[x]["first_partial_s"] for x in five), "final_after_end_s_p50": statistics.median(rows[x]["final_after_end_s"] for x in five)}
    out["realtime_first5"][name] = row
G = json.load(open(f"{R}/grades_scribe.json"))
arms = ["perfect", "transcribe", "azure", "tha", "gemini", "scribe", "scribe-v3", "gpt-transcribe"]
def per(a): return [sum(j["grades"][r].get(a, {}).get("score", 0) for r in j["grades"]) / len(j["grades"]) for j in G]
for a in arms:
    rd = {r: [j["grades"][r].get(a, {}).get("score", 0) for j in G] for r in ("1", "2")}
    out["sol"][a] = {"sol": round(100 * sum(per(a)) / (3 * len(G)), 1), "r1": round(100 * sum(rd["1"]) / (3 * len(G)), 1), "r2": round(100 * sum(rd["2"]) / (3 * len(G)), 1),
                     "critical_per_round": sum(1 for j in G for r in j["grades"] if j["grades"][r].get(a, {}).get("critical")) / 2}
for a, b in [("scribe", "transcribe"), ("scribe-v3", "transcribe"), ("tha", "transcribe")]:
    d = [p - q for p, q in zip(per(a), per(b))]; rng = random.Random(1)
    bs = sorted(100 * sum(d[rng.randrange(len(d))] for _ in d) / (3 * len(d)) for _ in range(10000))
    out["paired"][f"{a} - {b}"] = {"diff": round(100 * sum(d) / (3 * len(d)), 1), "ci95": [round(bs[250], 1), round(bs[9750], 1)]}
json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, indent=1))
