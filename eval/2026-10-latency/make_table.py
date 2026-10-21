# Prints the README's table from results.json.
import json, os, sys
doc = json.load(open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")))
ORDER = ["en-es", "es-en", "en-ja", "km-en", "ht-en", "en-ht"]
s = lambda v: "–" if v is None else f"{v / 1000:.1f}"
pp = lambda m: "–" if not m or m.get("p50") is None else f"{s(m['p50'])} / {s(m['p90'])}"
print("| Pair | Route | Stop → first audio p50 / p90 (s) | Stop → audio of last words p50 / p90 | Stop → first caption p50 | Start → first audio p50 | Stop → end of its audio p50 | Voiced before speaker finished | Quality (missing) |")
print("|---|---|---|---|---|---|---|---|---|")
for pair in ORDER:
    for r in sorted((r for r in doc["routes"] if r["lang_pair"] == pair), key=lambda r: (r["stop_to_tail_audio_ms"] or r["stop_to_first_audio_ms"])["p50"] if r["route"] not in ("gemini-lt", "azure-gemini-stream") else -99999):
        q = r["quality"]
        print(f"| {pair} | `{r['route']}` | {pp(r['stop_to_first_audio_ms'])} | {pp(r['stop_to_tail_audio_ms'])} | {s(r['stop_to_first_text_ms']['p50'])} | "
              f"{s(r['start_to_first_audio_ms']['p50'])} | {s(r['stop_to_audio_end_ms']['p50'])} | {round(100 * r['mid_sentence_share'])}% | {q['pct_of_max']}% ({q['missing']}/{r['n']}) |")
