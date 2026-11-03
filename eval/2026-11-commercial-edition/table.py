# results.json for the round and the README tables: round.py's out/results.json (14 directions + Lao
# nonprofit) and round_drr.py's drr_results.json (de, ru, ro beside the saved C1), with the translator each
# commercial direction used, and the earlier nonprofit numbers of ../2026-10-full-stack for context.
#   python3 -I table.py results
import json, os, sys
R = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
fs = json.load(open(os.path.join(R, "out", "results.json")))
drr = json.load(open(os.path.join(R, "drr_results.json")))
FS = json.load(open(os.path.join(HERE, "..", "2026-10-full-stack", "results.json")))["results"]
# commercial routes (python3 server/stack_config.py check --edition commercial; languages.toml)
TR = {"en-es": "Gemma 4", "es-en": "Hy-MT2", "en-pt": "Gemma 4", "pt-en": "Hy-MT2", "en-fr": "Gemma 4", "fr-en": "Hy-MT2",
      "en-ja": "Gemma 4", "ja-en": "Gemma 4", "en-km": "Gemma 4", "km-en": "Hy-MT2", "en-lo": "MADLAD 7B", "lo-en": "Hy-MT2",
      "en-ht": "Gemma 4", "ht-en": "Gemma 4", "en-de": "Gemma 4", "de-en": "Hy-MT2", "en-ru": "Gemma 4", "ru-en": "Gemma 4",
      "en-ro": "MADLAD 7B", "ro-en": "MADLAD 7B"}
ORDER = ["en-es", "es-en", "en-pt", "pt-en", "en-fr", "fr-en", "en-ja", "ja-en", "en-km", "km-en", "en-lo", "lo-en",
         "en-ht", "ht-en", "en-de", "de-en", "en-ru", "ru-en", "en-ro", "ro-en"]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def pick(d, sysn):
    """per-set rows of one system in one direction"""
    if d in drr:
        rows = [drr[d][st][sysn] for st in "ab" if sysn in drr[d].get(st, {})]
        return [{"said": r["quality"], "written": r["quality"], "cer_said": r["cer"], **r} for r in rows]
    return [fs[st][d][sysn] for st in "ab" if d in fs.get(st, {}) and sysn in fs[st][d]]


def summary(d, sysn):
    rows = pick(d, sysn)
    if not rows:
        return None
    g = lambda k, f: [((r.get(k) or {}).get(f)) for r in rows]
    return {"sets": len(rows),
            "said": mean(g("said", "q")), "written": mean(g("written", "q")),
            "crit_said": sum(x or 0 for x in g("said", "crit")), "crit_written": sum(x or 0 for x in g("written", "crit")),
            "first_audio_p50": g("stop_to_first_audio_ms", "p50"), "first_audio_p90": g("stop_to_first_audio_ms", "p90"),
            "last_audio_p50": g("stop_to_tail_audio_ms", "p50"), "last_audio_p90": g("stop_to_tail_audio_ms", "p90"),
            "missing_audio": sum(r.get("missing_audio") or 0 for r in rows),
            "dropped_utterances": sum(r.get("dropped_utterances") or 0 for r in rows),
            "cer_said": mean([100 * r["cer_said"] for r in rows if r.get("cer_said") is not None]),
            "per_set": {st: {"said": (r.get("said") or {}).get("q"), "written": (r.get("written") or {}).get("q")} for st, r in zip("ab", rows)}}


out = {"note": "Commercial edition (EDITION=commercial), live at real time, one direction at a time, one RTX PRO 6000 Blackwell 96 GB. "
               "Quality = share of the possible 3 per sentence (gemini-pro-latest, blind; Lao: commercial and nonprofit in one call; "
               "de/ru/ro: commercial and the saved nonprofit C1 of eval/2026-10-de-ru-ro in one call, 0-3 against the FLEURS text; "
               "the other 12: commercial graded alone). Latency in ms from the speaker stopping, per set [a, b]. cer_said in %.",
       "translator": TR, "commercial": {}, "lao_nonprofit": {}, "de_ru_ro_C1": {}, "full_stack_2026_10": {}}
for d in ORDER:
    out["commercial"][d] = summary(d, "commercial")
    if d in ("en-lo", "lo-en"):
        out["lao_nonprofit"][d] = summary(d, "nonprofit")
    if d in drr:
        out["de_ru_ro_C1"][d] = summary(d, "C1")
out["raw"] = {"full": fs, "drr": drr}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)


def f(x):
    return "–" if x is None else (f"{x / 1000:.1f}" if isinstance(x, (int, float)) else str(x))


def lat(v):
    return " / ".join(f(x) for x in v)


print("| Direction | Translator | Quality, said (written) | Critical | First audio p50 | First audio p90 | Last audio p50 | Last audio p90 | Drops | Recognition |")
print("|---|---|---|---|---|---|---|---|---|---|")
for d in ORDER:
    s = out["commercial"][d]
    if not s:
        print(f"| {d.replace('-', '→')} | {TR[d]} | not run | | | | | | | |"); continue
    q = f"{s['said']} ({s['written']})" if d not in drr else f"{s['said']}"
    print(f"| {d.replace('-', '→')} | {TR[d]} | {q} | {s['crit_said']} | {lat(s['first_audio_p50'])} | {lat(s['first_audio_p90'])} | "
          f"{lat(s['last_audio_p50'])} | {lat(s['last_audio_p90'])} | {s['missing_audio']} / {s['dropped_utterances']} | {s['cer_said']}% |")
for name, key in (("Lao nonprofit", "lao_nonprofit"), ("de/ru/ro C1", "de_ru_ro_C1")):
    print("\n" + name)
    for d, s in out[key].items():
        if s:
            print(d, s["said"], s["written"], s["crit_said"], lat(s["first_audio_p50"]), lat(s["last_audio_p50"]), lat(s["last_audio_p90"]),
                  s["missing_audio"], s["dropped_utterances"], s["cer_said"], s["per_set"])
