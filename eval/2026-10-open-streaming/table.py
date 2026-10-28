# The README tables: this run's systems and the cloud rows of
# ../2026-10-simultaneous-phrases/results.json on the same four directions, as that
# README aggregates them (means over both pause patterns and the directions in each
# group; latencies are medians of the per-direction medians, in seconds; chunks wrong
# later pooled), plus recognition and GPU cost per recogniser.
#   python3 -I table.py
import json, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "results.json")))
C = json.load(open(os.path.join(HERE, "..", "2026-10-simultaneous-phrases", "results.json")))
GROUPS = {"Out of English (es, fr)": ["en-es", "en-fr"], "Into English (es, fr)": ["es-en", "fr-en"]}
PATTERNS = ["reg", "irr"]
REC = {"simul": "SimulStreaming, Whisper large-v3", "ctc": "Omnilingual CTC 3B track", "nemo": "Nemotron 3.5 ASR streaming",
       "mai": "MAI-Transcribe-2-Streaming (cloud)", "std": "Azure standard real-time (cloud)"}
OURS = [("P8-" + r, "Phrase ≤8", r) for r in ["simul", "ctc", "nemo"]] + [("S-" + r, "Sentence", r) for r in ["simul", "ctc", "nemo"]]
CLOUD = [("P8-gemma31", "Phrase ≤8", "mai"), ("P8-gemma31-std", "Phrase ≤8", "std"),
         ("S-gemma31", "Sentence", "mai"), ("S-gemma31-std", "Sentence", "std")]


def agg(res, name, dirs):
    rows = [res["rows"].get(f"{p}:{d}", {}).get(name) for p in PATTERNS for d in dirs]
    rows = [r for r in rows if r]
    if not rows:
        return None
    m = lambda xs: round(statistics.mean(xs), 1) if xs else None
    med = lambda xs: round(statistics.median(xs) / 1000, 1) if xs else None
    q = [r["said"]["q"] for r in rows if "said" in r]
    cr = [r["written"]["crit"] for r in rows if "written" in r]
    st = [r["lat"]["sentence_start_to_first_audio_p50"] for r in rows if r.get("lat", {}).get("sentence_start_to_first_audio_p50") is not None]
    en = [r["lat"]["sentence_end_to_last_audio_p50"] for r in rows if r.get("lat", {}).get("sentence_end_to_last_audio_p50") is not None]
    w = sum(r.get("contradictions", {}).get("wrong", 0) for r in rows)
    n = sum(r.get("contradictions", {}).get("chunks", 0) for r in rows)
    return {"q": m(q), "crit": m(cr), "start": med(st), "end": med(en),
            "wrong": f"{round(100 * w / n)}%" if n else "–", "mt_p50": med([r["mt_wall_p50_ms"] for r in rows if r.get("mt_wall_p50_ms")]),
            "n": len(rows)}


out = []
for g, dirs in GROUPS.items():
    out.append(f"\n**{g}**\n")
    out.append("| Recogniser | Mode | Quality, said | Critical | Speech starts → first audio (s) | Speech ends → last audio (s) | Chunks wrong later | Translation call p50 (s) |")
    out.append("|---|---|---|---|---|---|---|---|")
    for res, systems, tag in ((R, OURS, ""), (C, CLOUD, " ¹")):
        for name, mode, rec in systems:
            a = agg(res, name, dirs)
            if not a:
                continue
            f = lambda v: "–" if v is None else v
            out.append(f"| {REC[rec]}{tag} | {mode} | {f(a['q'])} | {f(a['crit'])} | {f(a['start'])} | {f(a['end'])} | {a['wrong'] if mode.startswith('Phrase') else '–'} | {f(a['mt_p50'])} |")
print("\n".join(out))

print("\n**Recognition (finals, whole clip; CER / WER %, against the written text; English also against what was said)**\n")
print("| Recogniser | en reg | en irr | en said reg / irr | es reg | es irr | fr reg | fr irr |")
print("|---|---|---|---|---|---|---|---|")
rec_rows = R.get("recognition", []) + [dict(x, cloud=True) for x in C.get("recognition", [])]
names = {"mai-stream": "mai", "std-stream": "std"}
for rec in ["simul", "ctc", "nemo", "mai", "std"]:
    get = lambda l, p, k="text": next((x[k] for x in rec_rows if names.get(x["system"], x["system"]) == rec and x["lang"] == l and x["pattern"] == p), None)
    fmt = lambda v: f"{v['cer']} / {v.get('wer', '–')}" if v else "–"
    said = f"{fmt(get('en', 'reg', 'said'))}; {fmt(get('en', 'irr', 'said'))}"
    print(f"| {REC[rec]} | {fmt(get('en', 'reg'))} | {fmt(get('en', 'irr'))} | {said} | {fmt(get('es', 'reg'))} | {fmt(get('es', 'irr'))} | {fmt(get('fr', 'reg'))} | {fmt(get('fr', 'irr'))} |")
