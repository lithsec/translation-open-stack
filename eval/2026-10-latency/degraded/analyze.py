# The degraded-audio round's analysis: ../analyze.py's timing, sentence
# matching and judge, unchanged (through ../languages/analyze.py's labels),
# run once per condition. Speech start/end always come from the CLEAN clip
# (the degraded copies have the same timeline; noise would fool the detector).
#
#   GEMINI_API_KEY=... python3 analyze.py <degraded clips dir> <runs dir> [results.json]
#
# Per route x direction x condition, on top of the usual measures:
#   missing      sentences with no translation at all (quality.missing)
#   partial      sentences whose output leaves out a meaningful part of the
#                source (judge, as ../content_check.py)
#   duplicates   sentences whose output says content twice (judge, as
#                ../content_check.py), and, for the omni-stt routes, sentences
#                delivered from both Azure and omni-stt ("both_sources": the
#                LT bug where Azure's segments leak through an Omnilingual room)
#   redials      LT's reconnecting wrapper redialled the session (no output
#                after 20 s of speech); pipeline spans are rebased (rebase_spans)
#   stall        Gemini LT: run_all.py's stall check, and whether it was rerun
import json, os, re, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLIPS, RUNS = (os.path.abspath(a) for a in sys.argv[1:3])
OUT = sys.argv[3] if len(sys.argv) > 3 else os.path.join(HERE, "results.json")
sys.argv = [sys.argv[0], os.path.join(CLIPS, "clean"), RUNS, os.devnull]
sys.path.insert(0, os.path.dirname(HERE))
import analyze as A  # noqa: E402  ../analyze.py
sys.path.insert(0, HERE)
from run_all import stall  # noqa: E402

# The new routes' labels, as ../languages/analyze.py adds them.
A.LABELS.update({
    "azure": ("Azure Speech translation -> Azure voice (Azure alone)", True),
    "omni-foundry": ("omni-stt /listen (Omnilingual, speaker language fixed) -> Foundry gpt-5.6-sol -> Azure voice", True),
})
A.CAPTION_FIRST |= {"azure", "omni-foundry"}

CONDS = ["clean", "room-mic", "noise-10dB", "bt-narrowband", "hall-reverb"]
ROUTE_ORDER = ["azure", "azure-foundry", "omni-foundry", "ht-exception", "gemini-lt"]


def seg_sources(run, bounds):
    """Pipelines: [(sentence, 'azure-final' | 'omni-final' | None)] per delivered
    segment, matched as ../analyze.py segments() does."""
    ev = [e for e in run["events"] if e.get("t") is not None]
    finals = [e for e in ev if e["kind"] in ("azure-final", "omni-final")]
    out, last_input, fresh = [], None, False
    for e in ev:
        if e["kind"] == "input":
            last_input, fresh = e["text"], True
        elif e["kind"] == "text" and fresh:
            fresh = False
            f = next((f for f in reversed(finals) if f["text"].strip() == (last_input or "").strip() and f["t"] <= e["t"]), None)
            out.append((A.assign_span((f["startMs"], f["endMs"]), bounds) if f else (out[-1][0] if out else 0), f["kind"] if f else None))
    return out


def rebase_spans(run):
    """LT's reconnecting wrapper redials when no output follows 20 s of speech
    (here: English room-mic). The new Azure / omni-stt session's audio offsets
    restart at 0, at the first chunk it gets: the wrapper buffers audio while
    connecting (at most 5 s, MAX_PENDING_CHUNKS) and flushes it when live. Put
    each final's span back on the clip timeline. Returns the redial count."""
    base, retry, n = 0.0, None, 0
    for e in run["events"]:
        if e.get("t") is None:
            continue
        if e["kind"] == "recovery" and e["action"] == "retrying":
            retry, n = e["t"], n + 1
        elif e["kind"] == "state" and e["state"] == "live" and retry is not None:
            base, retry = max(retry, e["t"] - 5000), None
        elif e["kind"] in ("azure-final", "omni-final") and base:
            e["startMs"] += base
            e["endMs"] += base
    return n


def content(name, src, tgt, src_sent, outs):
    prompt = f"""A live interpreter rendered each {A.NAMES[src]} source sentence into {A.NAMES[tgt]}. For each sentence, compare the output with the source and say:
dup = true when the output says some content twice (a phrase or clause repeated, not a word that legitimately recurs);
missing = true when a meaningful part of the source (a clause, a name, a number, a qualifier) is absent from the output.
Ignore style. An empty output is missing.

Source:
{json.dumps(src_sent, ensure_ascii=False)}

Output:
{json.dumps(outs, ensure_ascii=False)}

Return JSON: {{"s": [{{"i": 0, "dup": false, "missing": false}}, ... {len(src_sent)} items]}}"""
    res = A.cached(f"content-{name}", lambda: A.gemini(prompt))
    return {int(x["i"]): x for x in (res["s"] if isinstance(res, dict) else res)}


def main():
    refs = json.load(open(os.path.join(CLIPS, "refs.json")))
    bounds_cache, routes = {}, []
    for cond in CONDS:
        d = os.path.join(RUNS, cond)
        if not os.path.isdir(d):
            continue
        A.RUNS, A.CACHE = d, os.path.join(d, "cache")
        os.makedirs(A.CACHE, exist_ok=True)
        for f in sorted(x for x in os.listdir(d) if re.match(r"r\d+-.*\.json$", x)):
            run = json.load(open(os.path.join(d, f)))
            name, route, src, tgt = f[:-5], run["route"], run["src"], run["tgt"]
            redials = rebase_spans(run)
            if src not in bounds_cache:
                bounds_cache[src] = A.speech_bounds(src)
            bounds = bounds_cache[src]
            src_sent = json.load(open(os.path.join(CLIPS, "clean", f"{src}.txt.json")))
            rows = A.per_sentence(run, name, src_sent, bounds)
            segs = A.segments(run, bounds)
            if segs is not None:
                for r in rows:
                    r["segments"] = sum(1 for s, _ in segs if s == r["i"])
            ref = refs.get(f"{src}-{tgt}")
            sc = {int(s["i"]): s for s in A.grade(name, src, tgt, src_sent, (ref, tgt) if ref else None, [r["text"] for r in rows])}
            cc = content(name, src, tgt, src_sent, [r["text"] for r in rows])
            for r in rows:
                s = sc.get(r["i"], {})
                r["score"] = int(s.get("score", 0)) if r["text"] else 0
                r["critical"] = bool(s.get("critical", False))
                r["dup"] = bool(cc.get(r["i"], {}).get("dup")) and bool(r["text"])
                r["partial"] = bool(cc.get(r["i"], {}).get("missing")) and bool(r["text"])
            json.dump({"run": name, "condition": cond, "route": route, "rows": rows},
                      open(os.path.join(A.CACHE, f"rows-{name}.json"), "w"), ensure_ascii=False, indent=1)
            m = lambda k: {"p50": A.pct([r[k] for r in rows if k in r], 0.5), "p90": A.pct([r[k] for r in rows if k in r], 0.9)}
            firsts = [r for r in rows if "stop_to_first_audio_ms" in r]
            mid = sum(1 for r in firsts if r["stop_to_first_audio_ms"] < 0)
            scores = [r["score"] for r in rows]
            seg = [r["segments"] for r in rows if "segments" in r]
            fd = [e for e in run["events"] if e["kind"] == "foundry"]
            src_info = {}
            if route in ("omni-foundry", "ht-exception"):
                ss = seg_sources(run, bounds)
                by = {}
                for s, k in ss:
                    by.setdefault(s, set()).add(k)
                src_info = {"segments_by_source": {k or "unmatched": sum(1 for _, x in ss if x == k) for k in {x for _, x in ss}},
                            "both_sources": sum(1 for v in by.values() if {"azure-final", "omni-final"} <= v),
                            "first_sentence_both": {"azure-final", "omni-final"} <= by.get(0, set())}
            st = None
            if route == "gemini-lt":
                prev = os.path.join(d, f"stalled-{name}.json")
                st = {"stall_check": stall(os.path.join(d, f)) or None,
                      "rerun_after": stall(prev) if os.path.exists(prev) else None}
            routes.append({
                "condition": cond, "route": route, "label": A.LABELS[route][0], "vendor_named": True, "lang_pair": f"{src}-{tgt}",
                "runs": 1, "n": len(rows), "n_with_audio": len(firsts),
                "stop_to_first_audio_ms": m("stop_to_first_audio_ms"),
                "stop_to_first_audio_played_ms": m("stop_to_first_audio_played_ms"),
                "stop_to_tail_audio_ms": m("stop_to_tail_audio_ms") if route not in A.STREAMING else None,
                "stop_to_first_text_ms": m("stop_to_first_text_ms"),
                "stop_to_final_text_ms": m("stop_to_final_text_ms"),
                "start_to_first_audio_ms": m("start_to_first_audio_ms"),
                "stop_to_audio_end_ms": m("stop_to_audio_end_ms"),
                "stop_to_audio_end_played_ms": m("stop_to_audio_end_played_ms"),
                "speaks_mid_sentence": mid / max(1, len(firsts)) >= 0.25,
                "mid_sentence_share": round(mid / max(1, len(firsts)), 2),
                **({"split_share": round(sum(1 for x in seg if x > 1) / len(seg), 2)} if seg else {}),
                "quality": {
                    "judge": A.JUDGE, "scale": "0-3 per sentence",
                    "mean": round(statistics.mean(scores), 2) if scores else None,
                    "pct_of_max": round(100 * statistics.mean(scores) / 3) if scores else None,
                    "critical": sum(1 for r in rows if r["critical"]),
                    "missing": sum(1 for r in rows if not r["text"]),
                    "partial": sum(1 for r in rows if r["partial"]),
                    "duplicates": sum(1 for r in rows if r["dup"]),
                },
                **({"sources": src_info} if src_info else {}),
                **({"stall": st} if st else {}),
                "redials": redials,
                "models": run.get("meta"),
                **({"foundry_requests": {"requests": len(fd), "429": sum(e["status"] == 429 for e in fd),
                                         "errors": sum(e["status"] not in (200, 429) for e in fd)}} if fd else {}),
                **({"omni_warm_ms": run["warmMs"]} if run.get("warmMs") else {}),
                "date": run["date"],
            })
    # Deltas against clean, same route and direction.
    clean = {(r["route"], r["lang_pair"]): r for r in routes if r["condition"] == "clean"}
    tail = lambda r: (r["stop_to_tail_audio_ms"] or r["stop_to_audio_end_ms"])["p50"]
    for r in routes:
        c = clean.get((r["route"], r["lang_pair"]))
        if c and r is not c:
            r["delta_vs_clean"] = {
                "quality_pct": r["quality"]["pct_of_max"] - c["quality"]["pct_of_max"],
                "missing": r["quality"]["missing"] - c["quality"]["missing"],
                "duplicates": r["quality"]["duplicates"] - c["quality"]["duplicates"],
                "last_words_p50_ms": (tail(r) - tail(c)) if tail(r) is not None and tail(c) is not None else None,
            }
    base = json.load(open(os.path.join(os.path.dirname(HERE), "results.json")))
    notes = dict(base["metric_notes"])
    notes["split_share"] = "pipelines only: share of sentences that reached the listener as more than one segment"
    notes["pooling"] = "one run of each condition x route x pair, 15 sentences; sentences with no audio are left out of the audio percentiles (n_with_audio) and score 0 in quality"
    notes["quality"] = notes["quality"].replace("en-ht has none", "every direction has a reference: FLoRes text of the target language (ht-en: the model-made English meanings)")
    notes["condition"] = "audio condition of the source clip, see README (clean, room-mic, noise-10dB, bt-narrowband, hall-reverb); speech bounds always from the clean clip"
    notes["quality.partial"] = "judge (gemini-3.5-flash): output present but a meaningful part of the source (clause, name, number, qualifier) absent"
    notes["quality.duplicates"] = "judge (gemini-3.5-flash): output says some content twice"
    notes["sources"] = "omni-stt routes: delivered segments by the final they came from (Azure's vs omni-stt's), and sentences delivered from both"
    notes["last_words"] = "stop_to_tail_audio_ms for pipelines; for gemini-lt (streaming) the README table uses stop_to_audio_end_ms instead (no segment boundary)"
    doc = {"date": min(r["date"] for r in routes)[:10], "location": os.environ.get("EVAL_LOCATION", "unspecified"),
           "metric_notes": notes, "routes": routes}
    json.dump(doc, open(OUT, "w"), ensure_ascii=False, indent=1)
    for r in sorted(routes, key=lambda r: (r["lang_pair"], ROUTE_ORDER.index(r["route"]), CONDS.index(r["condition"]))):
        q = r["quality"]
        print(f"{r['lang_pair']:6} {r['route']:14} {r['condition']:13} q {q['pct_of_max']:3}% miss {q['missing']:2} part {q['partial']:2} dup {q['duplicates']} "
              f"last {tail(r)} first {r['stop_to_first_audio_ms']['p50']} start {r['start_to_first_audio_ms']['p50']} {r.get('sources', '')} {r.get('stall', '')}")


if __name__ == "__main__":
    main()
