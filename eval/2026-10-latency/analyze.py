# Turns the harness logs (run_route.ts) into per-sentence latencies, grades
# the translations, and writes results.json.
#
#   GEMINI_API_KEY=... python3 analyze.py <clipDir> <runsDir> [results.json]
#
# Timeline: every event's t is ms on the clip's speech timeline (chunk k of
# 100 ms is delivered at (k+1)*100 ms, as a microphone would). Each
# sentence's speech start/end come from the audio itself (20 ms frames at or
# above 20% of the sentence's 90th-percentile loudness), not from the padded
# clip marks.
#
# Which output belongs to which sentence:
#   pipeline routes (Azure / omni-stt finals -> translate -> voice): exact.
#     The probes log each final with its audio span; a span belongs to the
#     sentence it overlaps most. Captions carry the final's source text
#     ('input' event), so each caption + the audio after it (Azure / Haitian
#     voices speak after the caption) is that final's segment. Azure + Gemini
#     (sentence mode) answers each final with exactly one Gemini utterance,
#     in order, and its audio comes before its 'done'.
#   streaming routes (Gemini Live Translate, Azure + Gemini streaming): an LLM
#     (gemini-3.5-flash, temperature 0) labels each output transcript piece
#     with the source sentence it renders; labels are forced monotonic and no
#     earlier than 300 ms after that sentence's speech starts. Each voiced
#     audio chunk takes the label of the latest piece that arrived by 250 ms
#     after it.
#
# Played: one listener's player plays chunks in order, as they arrive or as
# soon as the previous chunk ends (whichever is later), as LT's playout does.
import json, os, re, statistics, sys, time, urllib.request, wave
import numpy as np

CLIPS, RUNS = sys.argv[1], sys.argv[2]
OUT = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
CACHE = os.path.join(RUNS, "cache")
os.makedirs(CACHE, exist_ok=True)
JUDGE = "gemini-3.5-flash"
LEAD_MS = 250
NAMES = {"en": "English", "es": "Spanish", "ja": "Japanese", "km": "Khmer", "ht": "Haitian Creole", "lo": "Lao"}
STREAMING = {"gemini-lt", "azure-gemini-stream"}
CAPTION_FIRST = {"azure-foundry", "ht-exception", "ht-voice-gemini", "ht-voice-coqui"}
LABELS = {
    "azure-foundry": ("Azure STT -> Foundry gpt-5.6-sol -> Azure voice", True),
    "azure-gemini": ("Azure STT -> Gemini Live (sentence at a time)", True),
    "azure-gemini-stream": ("Azure STT -> Gemini Live (streaming words)", True),
    "gemini-lt": ("Gemini Live Translate (speech to speech)", True),
    "ht-exception": ("omni-stt /listen (beside Azure) -> Foundry gpt-5.6-sol -> Azure voice", True),
    "ht-voice-gemini": ("Azure STT -> Foundry gpt-5.6-sol -> Gemini voice (Haitian Creole)", True),
    "ht-voice-coqui": ("Azure STT -> Foundry gpt-5.6-sol -> omni-stt /speak Coqui (Haitian Creole)", True),
}


def speech_bounds(lang):
    meta = json.load(open(os.path.join(CLIPS, f"{lang}.json")))
    with wave.open(os.path.join(CLIPS, f"{lang}.wav")) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)
    out = []
    for s in meta["sentences"]:
        a = int(s["start"] * 16000)
        seg = x[a:int(s["end"] * 16000)]
        f = 320
        n = len(seg) // f
        rms = np.sqrt((seg[: n * f].reshape(n, f) ** 2).mean(axis=1))
        loud = np.where(rms >= 0.2 * np.percentile(rms, 90))[0]
        out.append((round((s["start"] + loud[0] * 0.02) * 1000), round((s["start"] + (loud[-1] + 1) * 0.02) * 1000)))
    return out


def gemini(prompt, schema_hint=""):
    key = os.environ["GEMINI_API_KEY"]
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": 32768}}
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{JUDGE}:generateContent",
                data=json.dumps(body).encode(), headers={"x-goog-api-key": key, "content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                j = json.load(r)
            txt = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
            return json.loads(txt)
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"judge failed: {err}")


def cached(name, fn):
    p = os.path.join(CACHE, name + ".json")
    if os.path.exists(p):
        return json.load(open(p))
    v = fn()
    json.dump(v, open(p, "w"), ensure_ascii=False, indent=1)
    return v


def assign_span(span, bounds):
    """The sentence a final's audio span overlaps most (or the nearest)."""
    s, e = span
    best, bi = -1e9, 0
    for i, (a, b) in enumerate(bounds):
        ov = min(e, b + 400) - max(s, a - 300)
        if ov > best:
            best, bi = ov, i
    return bi


def label_streaming(run_name, pieces, src_sent, tgt, bounds):
    listing = "\n".join(f"{k}\t{p['t'] / 1000:.1f}s\t{p['text']}" for k, p in enumerate(pieces))
    prompt = f"""A live interpreter rendered {len(src_sent)} source sentences into {NAMES[tgt]}. Its output arrived as numbered transcript pieces (id, time, text). Label every piece with the index (0-based) of the source sentence it renders. Pieces are in order; labels never go backwards. A piece that spans two sentences gets the sentence it mostly renders. A piece that renders nothing (filler, a repeat of earlier content, a comment) gets the sentence of its neighbours.

Source sentences:
{json.dumps(list(enumerate(src_sent)), ensure_ascii=False)}

Pieces:
{listing}

Return JSON: {{"s": [0, 0, 1, ...]}}: one sentence index per piece, in piece order, exactly {len(pieces)} integers."""
    res = cached(f"labels-{run_name}", lambda: gemini(prompt))
    arr = res["s"] if isinstance(res, dict) else res
    lab = {k: int(v) for k, v in enumerate(arr)}
    out, cur = [], 0
    for k, p in enumerate(pieces):
        s = max(cur, min(lab.get(k, cur), len(src_sent) - 1))
        # Not before that sentence has begun to be heard.
        while s > cur and p["t"] < bounds[s][0] + 300:
            s -= 1
        out.append(s)
        cur = s
    return out


def segments(run, bounds):
    """[(sentence, [events])] in order; events are text/done/audio with t."""
    ev = [e for e in run["events"] if e.get("t") is not None]
    route = run["route"]
    if route in STREAMING:
        return None
    finals = [e for e in ev if e["kind"] in ("azure-final", "omni-final")]
    span_of = lambda f: assign_span((f["startMs"], f["endMs"]), bounds)
    segs = []
    if route == "azure-gemini":
        azure = [f for f in finals if f["kind"] == "azure-final"]
        cur, k = [], 0
        for e in ev:
            if e["kind"] in ("audio", "text"):
                cur.append(e)
            elif e["kind"] == "done":
                cur.append(e)
                sent = span_of(azure[k]) if k < len(azure) else len(bounds) - 1
                segs.append((sent, cur))
                cur, k = [], k + 1
        return segs
    # Caption first: input(source) + text + done, then that segment's audio.
    last_input = None
    for e in ev:
        if e["kind"] == "input":
            last_input = e["text"]
        elif e["kind"] == "text":
            src = last_input
            f = next((f for f in reversed(finals) if f["text"].strip() == (src or "").strip() and f["t"] <= e["t"]), None)
            sent = span_of(f) if f else (segs[-1][0] if segs else 0)
            segs.append((sent, [e]))
        elif e["kind"] in ("audio", "done") and segs:
            segs[-1][1].append(e)
    return segs


def per_sentence(run, run_name, src_sent, bounds):
    ev = [e for e in run["events"] if e.get("t") is not None and e["kind"] in ("text", "done", "audio")]
    # Played time for every audio chunk: one sequential player.
    cursor = 0.0
    for e in ev:
        if e["kind"] == "audio":
            e["play"] = max(e["t"], cursor)
            e["play_end"] = e["play"] + e["samples"] / e["rate"] * 1000
            cursor = e["play_end"]
    n = len(bounds)
    by = {i: [] for i in range(n)}
    last_seg = {}
    if run["route"] in STREAMING:
        pieces = [e for e in ev if e["kind"] == "text" and e["text"].strip()]
        labels = label_streaming(run_name, pieces, src_sent, run["tgt"], bounds) if pieces else []
        for p, s in zip(pieces, labels):
            p["s"] = s
            by[s].append(p)
        # A voiced chunk renders the latest transcript piece that has arrived
        # by LEAD_MS after it (Gemini sends a piece's transcript with, or just
        # before, its audio). Nearest-in-time gave a sentence the previous
        # sentence's trailing audio.
        times = [p["t"] for p in pieces]
        j = -1
        for e in ev:
            if e["kind"] == "audio" and "on" in e and pieces:
                while j + 1 < len(times) and times[j + 1] <= e["t"] + LEAD_MS:
                    j += 1
                by[labels[max(j, 0)]].append(e)
    else:
        for s, seg in segments(run, bounds):
            by[s].extend(seg)
            last_seg[s] = seg
    rows = []
    for i in range(n):
        a, b = bounds[i]
        es = sorted(by[i], key=lambda e: e["t"])
        texts = [e for e in es if e["kind"] == "text" and e["text"].strip()]
        # Voiced chunks only (some routes stream silence between turns).
        auds = [e for e in es if e["kind"] == "audio" and "on" in e]
        if run["route"] in STREAMING:
            out_text = "".join(e["text"] for e in texts).strip()
        else:
            dones = [e for e in es if e["kind"] == "done"]
            out_text = " ".join(e["text"].strip() for e in dones if e["text"].strip()) or "".join(e["text"] for e in texts).strip()
        r = {"i": i, "speech_start_ms": a, "speech_end_ms": b, "text": out_text}
        if texts:
            r["stop_to_first_text_ms"] = round(texts[0]["t"] - b)
            r["stop_to_final_text_ms"] = round(texts[-1]["t"] - b)
        if auds:
            # Arrival: the first voiced sample, were the chunk played the
            # moment it arrives (the route's own responsiveness). Played:
            # after whatever is still playing ahead of it (adds the voice's
            # speaking rate and how long the pauses are).
            first = auds[0]["t"] + auds[0]["on"]
            r["stop_to_first_audio_ms"] = round(first - b)
            r["stop_to_first_audio_played_ms"] = round(min(e["play"] + e["on"] for e in auds) - b)
            r["start_to_first_audio_ms"] = round(first - a)
            # This sentence's own audio played through from its first sample
            # (nothing earlier queued): when the listener has heard all of it.
            cur, end = 0.0, 0.0
            for e in auds:
                st = max(e["t"], cur)
                cur = st + e["samples"] / e["rate"] * 1000
                end = st + e["off"]
            r["stop_to_audio_end_ms"] = round(end - b)
            r["stop_to_audio_end_played_ms"] = round(max(e["play"] + e["off"] for e in auds) - b)
            r["audio_ms"] = round(sum(e["samples"] / e["rate"] * 1000 for e in auds))
            tail = [e for e in last_seg.get(i, []) if e["kind"] == "audio" and "on" in e]
            if tail:
                # Pipelines: the segment holding the sentence's last words.
                r["stop_to_tail_audio_ms"] = round(tail[0]["t"] + tail[0]["on"] - b)
        rows.append(r)
    return rows


def grade(run_name, src, tgt, src_sent, ref, outs):
    refline = f"Reference translations ({NAMES[tgt] if ref and ref[1] == tgt else 'English'}, authoritative for meaning):\n{json.dumps(ref[0], ensure_ascii=False)}\n" if ref else "(No reference: judge against the source.)\n"
    prompt = f"""You are an expert {NAMES[src]}->{NAMES[tgt]} interpretation evaluator. A live system interpreted each source sentence; grade its output per sentence.
3 = meaning fully correct and natural; 2 = meaning correct but awkward or unidiomatic; 1 = partly wrong, or something important omitted or added; 0 = wrong meaning, wrong language, garbled, or missing.
critical=true when a number, time, date, amount, name, negation, or who-did-what is wrong.
The speech recognition may have misheard; grade what reached the listener against what was actually said.

Source sentences ({NAMES[src]}):
{json.dumps(src_sent, ensure_ascii=False)}

{refline}
System output per sentence ({NAMES[tgt]}):
{json.dumps(outs, ensure_ascii=False)}

Return JSON: {{"scores": [{{"i": 0, "score": 3, "critical": false}}, ... {len(src_sent)} items]}}"""
    res = cached(f"grade-{run_name}", lambda: gemini(prompt))
    return res["scores"] if isinstance(res, dict) else res


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = int(np.floor(k)), int(np.ceil(k))
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo))


def main():
    refs = json.load(open(os.path.join(CLIPS, "refs.json")))
    runs = sorted(f for f in os.listdir(RUNS) if re.match(r"r\d+-.*\.json$", f))
    groups = {}
    bounds_cache = {}
    for f in runs:
        run = json.load(open(os.path.join(RUNS, f)))
        name = f[:-5]
        src, tgt = run["src"], run["tgt"]
        if src not in bounds_cache:
            bounds_cache[src] = speech_bounds(src)
        bounds = bounds_cache[src]
        src_sent = json.load(open(os.path.join(CLIPS, f"{src}.txt.json")))
        rows = per_sentence(run, name, src_sent, bounds)
        if src == "ht":
            ref = (refs["ht_meaning_en"], "en")
        elif tgt in refs and tgt != "ht":
            ref = (refs[tgt], tgt)
        else:
            ref = None
        scores = grade(name, src, tgt, src_sent, ref, [r["text"] for r in rows])
        sc = {int(s["i"]): s for s in scores}
        for r in rows:
            s = sc.get(r["i"], {})
            r["score"] = int(s.get("score", 0)) if r["text"] else 0
            r["critical"] = bool(s.get("critical", False))
        json.dump({"run": name, "route": run["route"], "model": run.get("model"), "meta": run.get("meta"), "rows": rows},
                  open(os.path.join(RUNS, "cache", f"rows-{name}.json"), "w"), ensure_ascii=False, indent=1)
        key = (run["route"], src, tgt)
        g = groups.setdefault(key, {"runs": [], "rows": [], "meta": run.get("meta"), "dates": []})
        g["runs"].append(name)
        g["rows"].extend(rows)
        g["dates"].append(run["date"])
    routes = []
    for (route, src, tgt), g in sorted(groups.items()):
        rows = g["rows"]
        m = lambda k: {"p50": pct([r[k] for r in rows if k in r], 0.5), "p90": pct([r[k] for r in rows if k in r], 0.9)}
        firsts = [r for r in rows if "stop_to_first_audio_ms" in r]
        mid = sum(1 for r in firsts if r["stop_to_first_audio_ms"] < 0)
        scores = [r["score"] for r in rows]
        label, named = LABELS[route]
        routes.append({
            "route": route, "label": label, "vendor_named": named, "lang_pair": f"{src}-{tgt}",
            "runs": len(g["runs"]), "n": len(rows), "n_with_audio": len(firsts),
            "stop_to_first_audio_ms": m("stop_to_first_audio_ms"),
            "stop_to_first_audio_played_ms": m("stop_to_first_audio_played_ms"),
            "stop_to_tail_audio_ms": m("stop_to_tail_audio_ms") if route not in STREAMING else None,
            "stop_to_first_text_ms": m("stop_to_first_text_ms"),
            "stop_to_final_text_ms": m("stop_to_final_text_ms"),
            "start_to_first_audio_ms": m("start_to_first_audio_ms"),
            "stop_to_audio_end_ms": m("stop_to_audio_end_ms"),
            "stop_to_audio_end_played_ms": m("stop_to_audio_end_played_ms"),
            "speaks_mid_sentence": mid / max(1, len(firsts)) >= 0.25,
            "mid_sentence_share": round(mid / max(1, len(firsts)), 2),
            "quality": {
                "judge": JUDGE, "scale": "0-3 per sentence",
                "mean": round(statistics.mean(scores), 2) if scores else None,
                "pct_of_max": round(100 * statistics.mean(scores) / 3) if scores else None,
                "critical": sum(1 for r in rows if r["critical"]),
                "missing": sum(1 for r in rows if not r["text"]),
            },
            "models": g["meta"],
        })
    doc = json.load(open(OUT)) if os.path.exists(OUT) else {}
    doc.update({
        "date": min(d for g in groups.values() for d in g["dates"])[:10],
        "location": os.environ.get("EVAL_LOCATION", "unspecified"),
        "metric_notes": {
            "timeline": "ms on the source clip's speech timeline; 100 ms chunks of 16 kHz PCM sent in real time, each when it ends (as a mic delivers it)",
            "speech_end": "end of the sentence's speech found from the audio (last 20 ms frame >= 20% of the sentence's p90 loudness)",
            "stop_to_first_audio_ms": "speech end -> first VOICED sample of that sentence's translation, played on arrival (negative = it began speaking before the speaker finished)",
            "stop_to_first_audio_played_ms": "the same through one sequential player, i.e. also waiting for earlier translation still playing",
            "stop_to_tail_audio_ms": "pipelines only: speech end -> first voiced audio of the segment holding the sentence's last words (Azure ends segments on 150 ms pauses, so some sentences arrive in pieces)",
            "stop_to_first_text_ms": "speech end -> first caption text for that sentence",
            "stop_to_final_text_ms": "speech end -> last caption text for that sentence",
            "start_to_first_audio_ms": "speech start -> first voiced translated audio of that sentence",
            "stop_to_audio_end_ms": "speech end -> end of that sentence's translated speech, its own audio played through from its first sample (nothing earlier queued)",
            "speaks_mid_sentence": "true when >= 25% of sentences' first translated audio arrives before the speaker finished the sentence (mid_sentence_share gives the share)",
            "pooling": "p50/p90 over all sentences of all runs of the route x pair; sentences with no audio are left out of the audio percentiles (n_with_audio) and score 0 in quality",
            "quality": f"{JUDGE} (temperature 0) grades each sentence 0-3 against source + reference; Gemini grading Gemini outputs may favour them; ht-en references are model-made (Gemini 2.5 Pro), en-ht has none",
        },
        "routes": routes,
    })
    json.dump(doc, open(OUT, "w"), ensure_ascii=False, indent=1)
    for r in routes:
        print(f"{r['route']:20} {r['lang_pair']}  n={r['n']:3}  stop->audio {r['stop_to_first_audio_ms']['p50']}/{r['stop_to_first_audio_ms']['p90']}  "
              f"played {r['stop_to_first_audio_played_ms']['p50']}  tail {(r['stop_to_tail_audio_ms'] or {}).get('p50')}  text {r['stop_to_first_text_ms']['p50']}/{r['stop_to_first_text_ms']['p90']}  start->audio {r['start_to_first_audio_ms']['p50']}  "
              f"mid {r['mid_sentence_share']}  q {r['quality']['pct_of_max']}% crit {r['quality']['critical']} miss {r['quality']['missing']}")


if __name__ == "__main__":
    main()
