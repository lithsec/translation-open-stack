# The results: per direction, pattern and variant, the four grading measures (grading.py),
# compression, and the backlog from the measured audio (tts_rates.py).
#
# Backlog: each chunk's audio starts at max(translation done + its measured time to first
# audio, end of the previous chunk's audio) and lasts its measured length: one voice, played
# in order, nothing skipped. Per read sentence, "last" = when its last chunk's audio starts,
# after the speaker finishes that sentence (as in ../2026-10-simultaneous-phrases), and
# "end" = when all audio has finished, after the speaker's last sentence ends.
#
#   python3 -I table_conv.py CLIPS WORK results.json   -> results.json, a console table
import json, os, statistics, sys, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CLIPS, WORK, OUT = sys.argv[1:4]
J = lambda p: json.load(open(p))
DIRS = ["en-es", "en-pt", "en-fr", "es-en", "fr-en"]
GROUPS = {"out of English": ["en-es", "en-pt", "en-fr"], "into English": ["es-en", "fr-en"]}
PATTERNS = ["conv"]
VARIANTS = {"V0": ("cur", 0), "V2": ("cur", 20), "V3": ("con", 15), "V4": ("con", 0)}
MODES = ["P8", "S"]
UL = {l: J(os.path.join(WORK, f"units_{l}.json"))["sentences"] for l in ("en", "es", "fr")}
GR = J(os.path.join(WORK, "grades.json"))


def bounds(clips, lang):
    """Speech start/end of each read sentence, ms (as ../2026-10-simultaneous-phrases/analyze.py)."""
    meta = J(os.path.join(clips, f"{lang}.json"))
    with wave.open(os.path.join(clips, f"{lang}.wav")) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)
    out = []
    for s in meta["sentences"]:
        a = int(s["start"] * 16000)
        seg = x[a:int(s["end"] * 16000)]
        n = len(seg) // 320
        rms = np.sqrt((seg[: n * 320].reshape(n, 320) ** 2).mean(axis=1))
        loud = np.where(rms >= 0.2 * np.percentile(rms, 90))[0]
        out.append((round((s["start"] + loud[0] * 0.02) * 1000), round((s["start"] + (loud[-1] + 1) * 0.02) * 1000)))
    return out


def pct(v, p):
    v = sorted(x for x in v if x is not None)
    return round(v[min(len(v) - 1, int(p * len(v)))]) if v else None


def text_measures(pattern, d, text):
    U = UL[d.split("-")[0]]
    jd = J(os.path.join(WORK, "judge", f"{d}_{text}.json"))["sentences"]
    ess = conv_ess = allu = conv = dist = 0
    for s in jd:
        for u, lab in zip(U[s["i"]]["units"], s["labels"]):
            allu += 1
            conv += lab == "conveyed"
            dist += lab == "distorted"
            if u["essential"]:
                ess += 1
                conv_ess += lab == "conveyed"
    qa = J(os.path.join(WORK, "qa", f"{d}_{text}.json"))["scores"]
    val = {"correct": 1.0, "partial": 0.5}
    qacc = sum(val.get(x["score"], 0.0) for x in qa) / max(1, len(qa))
    out = {"unit_recall_essential": round(100 * conv_ess / max(1, ess), 1), "unit_recall_all": round(100 * conv / max(1, allu), 1),
           "distortion": round(100 * dist / max(1, allu), 1), "distorted_units": dist, "units": allu,
           "qa": round(100 * qacc, 1), "qa_wrong": sum(1 for x in qa if x["score"] == "wrong"), "questions": len(qa)}
    for ref in ("SAID",):
        g = GR[f"{ref}:{pattern}:{d}"]["grades"][text]
        out[ref.lower()] = {"q": round(100 * sum(x.get("score", 0) for x in g) / (3 * len(g)), 1),
                            "crit": sum(1 for x in g if x.get("critical"))}
    return out


res = {"grader": "gemini-pro-latest", "rows": {}}
for pattern in PATTERNS:
    for d in DIRS:
        bnd = bounds(CLIPS, d.split("-")[0])
        row = res["rows"].setdefault(f"{pattern}:{d}", {})
        for mode in MODES:
            base_chars = base_secs = None
            for var, (prompt, rate) in VARIANTS.items():
                text = f"{mode}-{prompt}"
                sim = J(os.path.join(WORK, "sim", text, f"conv_{d}.json"))
                tts = J(os.path.join(WORK, "tts", f"{var}-{mode}", f"conv_{d}.json"))["chunks"]
                seg = J(os.path.join(WORK, "seg", text, f"conv_{d}.json"))
                owner = seg["chunk_of_char"]
                stream = " ".join(c["out"].strip() for c in sim["chunks"] if c["out"].strip())
                sent_chunks = [sorted({owner[k] for k in range(a, b) if not stream[k].isspace()}) if a is not None else []
                               for a, b in seg["spans"]]
                free, start, end = 0.0, [], []
                for c, t in zip(sim["chunks"], tts):
                    s0 = max(c["done"] + t["ttfa_ms"], free)
                    free = s0 + 1000 * t["seconds"]
                    start.append(s0)
                    end.append(free)
                last = [max(start[k] for k in ks) - bnd[i][1] for i, ks in enumerate(sent_chunks) if ks]
                fin = [max(end[k] for k in ks) - bnd[i][1] for i, ks in enumerate(sent_chunks) if ks]
                chars = sum(len(x) for x in seg["out"]) / len(seg["out"])
                secs = sum(t["seconds"] for t in tts) / len(seg["out"])
                if var == "V0":
                    base_chars, base_secs = chars, secs
                r = {"mode": mode, "prompt": prompt, "rate": rate, **text_measures(pattern, d, text),
                     "chars_per_sentence": round(chars, 1), "audio_s_per_sentence": round(secs, 2),
                     "chars_vs_V0": round(chars / base_chars, 3), "audio_vs_V0": round(secs / base_secs, 3),
                     "last_audio_start_after_sentence_end_ms": {"p50": pct(last, .5), "p90": pct(last, .9)},
                     "sentence_heard_in_full_after_its_end_ms": {"p50": pct(fin, .5), "p90": pct(fin, .9)},
                     "all_audio_done_after_speaker_stops_ms": round(max(end) - bnd[-1][1]),
                     "ttfa_p50_ms": pct([t["ttfa_ms"] for t in tts if t["seconds"]], .5)}
                row[f"{var}-{mode}"] = r

# Averages per group of directions, per variant and mode.
avg = {}
keys = ["unit_recall_essential", "unit_recall_all", "distortion", "qa", "chars_vs_V0", "audio_vs_V0", "all_audio_done_after_speaker_stops_ms"]
for gname, gd in GROUPS.items():
    for mode in MODES:
        for var in VARIANTS:
            rs = [res["rows"][f"conv:{d}"][f"{var}-{mode}"] for d in gd]
            a = {k: round(statistics.mean(r[k] for r in rs), 3 if "vs" in k else 1) for k in keys}
            a["said_q"] = round(statistics.mean(r["said"]["q"] for r in rs), 1)
            a["crit_said"] = sum(r["said"]["crit"] for r in rs)
            a["distorted_units"] = sum(r["distorted_units"] for r in rs)
            a["last_p50_ms"] = round(statistics.mean(r["last_audio_start_after_sentence_end_ms"]["p50"] for r in rs))
            a["last_p90_ms"] = round(statistics.mean(r["last_audio_start_after_sentence_end_ms"]["p90"] for r in rs))
            avg[f"{gname}|{var}-{mode}"] = a
res["averages"] = avg
json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
for gname in GROUPS:
    for mode in MODES:
        print(f"\n{gname} {mode}")
        for var in VARIANTS:
            a = avg[f"{gname}|{var}-{mode}"]
            print(f"  {var} ess {a['unit_recall_essential']:5} dist {a['distortion']:4} ({a['distorted_units']}) qa {a['qa']:5} said {a['said_q']:5} crit {a['crit_said']:2} chars {a['chars_vs_V0']} audio {a['audio_vs_V0']} last {a['last_p50_ms']}/{a['last_p90_ms']} end {a['all_audio_done_after_speaker_stops_ms']}")
for d in DIRS:
    print(f"\n{d}")
    for k, r in res["rows"][f"conv:{d}"].items():
        L = r["last_audio_start_after_sentence_end_ms"]
        print(f"  {k:6} ess {r['unit_recall_essential']:5} dist {r['distortion']:4} qa {r['qa']:5} said {r['said']['q']:5}({r['said']['crit']}) chars {r['chars_vs_V0']} audio {r['audio_vs_V0']} last {L['p50']}/{L['p90']} end {r['all_audio_done_after_speaker_stops_ms']}")
