# The README tables from results.json: means over both pause patterns and the two directions in
# each group; latencies are medians of the per-direction medians, in seconds.
#   python3 -I table.py
import json, os, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
rows = json.load(open(os.path.join(HERE, "results.json")))["rows"]
REC = {"mai": "MAI-Transcribe-2-Streaming", "nemo": "Nemotron 3.5 ASR streaming"}
NAME = {"S": "Sentence", "P8": "Phrase ≤8", "judge": "Judge", "decide": "Decide", "agree": "Agree"}
GROUPS = {"Out of English (en→es, en→fr)": ("en-es", "en-fr"), "Into English (es→en, fr→en)": ("es-en", "fr-en")}

systems = []
for k in rows:
    systems += [s for s in rows[k] if s not in systems]
systems.sort(key=lambda s: (list(REC).index(s.split("-")[1]), list(NAME).index(s.split("-")[0])))

for title, dirs in GROUPS.items():
    print(f"**{title}**\n")
    print("| Recogniser | Policy | Quality, said | Critical | Speech starts → first audio (s) | "
          "Speech ends → last audio (s) | Chunks wrong later | Gemma calls per sentence |")
    print("|---|---|---|---|---|---|---|---|")
    for s in systems:
        R = [rows[k][s] for k in rows if k.split(":")[1] in dirs and s in rows[k]]
        if not R:
            continue
        lat = lambda f: round(st.median(r["lat"][f] for r in R) / 1000, 1)
        c = [r["contradictions"] for r in R if r.get("contradictions")]
        wrong = f"{round(100 * sum(x['wrong'] for x in c) / sum(x['chunks'] for x in c))}%" if c else "–"
        p, rec = s.split("-")
        print(f"| {REC[rec]} | {NAME[p]} | {st.mean(r['said']['q'] for r in R):.1f} | "
              f"{st.mean(r['said']['crit'] for r in R):g} | {lat('sentence_start_to_first_audio_p50')} | "
              f"{lat('sentence_end_to_last_audio_p50')} | {wrong} | {st.mean(r['calls_per_sentence'] for r in R):.1f} |")
    print()
