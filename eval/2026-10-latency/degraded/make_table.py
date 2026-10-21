# Prints the README's tables from results.json (this folder's).
#   python3 make_table.py [results.json]
import json, os, statistics, sys

doc = json.load(open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")))
PAIRS = ["en-es", "es-en", "en-ja", "km-en", "ht-en"]
ROUTES = ["azure", "azure-foundry", "omni-foundry", "ht-exception", "gemini-lt"]
CONDS = ["clean", "room-mic", "noise-10dB", "bt-narrowband", "hall-reverb"]
R = {(r["lang_pair"], r["route"], r["condition"]): r for r in doc["routes"]}
conds = [c for c in CONDS if any(k[2] == c for k in R)]


def last(r):
    m = r["stop_to_tail_audio_ms"] or r["stop_to_audio_end_ms"]
    return m["p50"]


s = lambda v: "–" if v is None else f"{v / 1000:.1f}"
print("Per direction: quality % / missing / last words p50 (s)\n")
print("| Pair | Route | " + " | ".join(conds) + " |")
print("|---|---|" + "---|" * len(conds))
for p in PAIRS:
    for rt in ROUTES:
        cells = [R.get((p, rt, c)) for c in conds]
        if not any(cells):
            continue
        txt = ["–" if r is None else f"{r['quality']['pct_of_max']} / {r['quality']['missing']} / {s(last(r))}" for r in cells]
        print(f"| {p} | `{rt}` | " + " | ".join(txt) + " |")

print("\nAveraged over en-es, es-en, en-ja, km-en (the four directions all four routes serve): quality % (Δ vs clean), missing of 60, duplicates, last words p50 (s)\n")
print("| Route | " + " | ".join(conds) + " |")
print("|---|" + "---|" * len(conds))
for rt in ["azure", "azure-foundry", "omni-foundry", "gemini-lt"]:
    out, base = [], None
    for c in conds:
        rs = [R.get((p, rt, c)) for p in PAIRS[:4]]
        if not all(rs):
            out.append("–")
            continue
        q = statistics.mean(r["quality"]["pct_of_max"] for r in rs)
        base = q if c == "clean" else base
        d = "" if c == "clean" or base is None else f" ({q - base:+.0f})"
        miss = sum(r["quality"]["missing"] for r in rs)
        dup = sum(r["quality"]["duplicates"] for r in rs)
        lw = statistics.median(last(r) for r in rs if last(r) is not None)
        out.append(f"{q:.0f}{d} / {miss} / {dup} / {s(lw)}")
    print(f"| `{rt}` | " + " | ".join(out) + " |")

print("\nOther measures per run: start→first audio p50, stop→last words p90, duplicates (judge), both-sources sentences (omni routes), stall\n")
print("| Pair | Route | Condition | Start→first audio p50 | Last words p90 | Partial | Dup | Both sources | Stall |")
print("|---|---|---|---|---|---|---|---|---|")
for p in PAIRS:
    for rt in ROUTES:
        for c in conds:
            r = R.get((p, rt, c))
            if not r:
                continue
            m = r["stop_to_tail_audio_ms"] or r["stop_to_audio_end_ms"]
            src = r.get("sources", {})
            st = r.get("stall") or {}
            stl = "; ".join(x for x in [st.get("rerun_after") and f"rerun ({st['rerun_after']})", st.get("stall_check")] if x) or ""
            print(f"| {p} | `{rt}` | {c} | {s(r['start_to_first_audio_ms']['p50'])} | {s(m['p90'])} | {r['quality']['partial']} | {r['quality']['duplicates']} | "
                  f"{src.get('both_sources', '') if src else ''}{' (incl. 1st)' if src.get('first_sentence_both') else ''} | {stl} |")
