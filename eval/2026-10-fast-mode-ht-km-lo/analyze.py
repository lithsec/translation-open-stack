# Timeline and tables.
#
# Timing is per recogniser segment (one Azure final = one stretch of speech): its speech
# starts at the final's offset and ends at offset + duration, on the clip's clock. Each
# chunk's voice starts at max(translation done + measured time to first audio, the
# previous chunk's audio end + gap) (one voice, played in order; gap 120 ms between
# phrases, 300 ms after a segment's last chunk) and lasts its measured (trimmed) length.
#   first   first audio of the segment - its speech start
#   last    start of the segment's last chunk - its speech end
#   done    end of all audio - end of the last segment's speech (the monologue backlog)
# Read clips: the unseen regular- and irregular-pause clips; conv: the meeting excerpt.
#
#   python3 -I analyze.py WORK RECDIR CONV_RECDIR > table.md ; writes WORK/results.json
import json, os, statistics as st, sys

WORK, RECDIR, CONV_REC = sys.argv[1:4]
SYSTEMS = ["P8-sol", "P8-gemma31", "S-sol", "S-gemma31"]
PATTERNS = ["reg", "irr", "conv"]
TARGETS = ["ht", "km", "lo"]
GAP_P, GAP_S = 0.12, 0.30
J = lambda p: json.load(open(p))
# list price per million tokens (OpenRouter list for Gemma 4 31B on the allowed hosts; Foundry list for sol)
PRICE = {"gemma31": (0.20, 0.40), "sol": (4.40, 22.0)}


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f = int(k)
    return xs[f] + (xs[min(f + 1, len(xs) - 1)] - xs[f]) * (k - f)


def rec(pattern):
    return J(os.path.join(CONV_REC, "std_conv_en.json") if pattern == "conv" else os.path.join(RECDIR, f"std_{pattern}_en.json"))


def timeline(name, pattern, t):
    sim = J(os.path.join(WORK, "sim", name, f"{pattern}_en-{t}.json"))
    tts = J(os.path.join(WORK, "tts", name, f"{pattern}_en-{t}.json"))["rows"]
    fins = rec(pattern)["finals"]
    seg_t = [((f.get("offsetMs") or 0) / 1000, ((f.get("offsetMs") or 0) + (f.get("durationMs") or 0)) / 1000) for f in fins]
    ch = sim["chunks"]
    # A few calls took 8-70 s (a provider stall or a retried request): one such call delays every
    # later chunk of the stream. Those calls are replaced by the stream's median call time and
    # counted, so a single stall does not decide the comparison (OUTLIER_MS=0 keeps them).
    lim = float(os.environ.get("OUTLIER_MS", "8000"))
    med = st.median(c["wall_ms"] for c in ch)
    walls = [med if lim and c["wall_ms"] > lim else c["wall_ms"] for c in ch]
    outliers = sum(1 for c in ch if lim and c["wall_ms"] > lim)
    busy, done = 0.0, []
    for c, w in zip(ch, walls):
        s0 = max(c["t"], busy)
        busy = s0 + w
        done.append(busy)
    end, starts = 0.0, []
    for k, (c, a) in enumerate(zip(ch, tts)):
        gap = GAP_S if k and ch[k - 1]["final"] else GAP_P
        s = max(done[k] / 1000 + a["ttfa_ms"] / 1000, end + (gap if end else 0))
        starts.append(s)
        end = s + a["seconds"]
    first, last, free = [], [], []
    for g in sorted({c["segment"] for c in ch}):
        ks = [k for k, c in enumerate(ch) if c["segment"] == g]
        if g >= len(seg_t):
            continue
        a, b = seg_t[g]
        first.append(starts[ks[0]] - a)
        last.append(starts[ks[-1]] - b)
        free.append(done[ks[0]] / 1000 + tts[ks[0]]["ttfa_ms"] / 1000 - a)   # without waiting for earlier audio
    speech_end = max(b for _, b in seg_t)
    audio_s = sum(a["seconds"] for a in tts)
    pt = sum(c.get("prompt_tokens") or 0 for c in ch)
    ct = sum(c.get("completion_tokens") or 0 for c in ch)
    dur_h = speech_end / 3600
    pi, po = PRICE[sim["config"]["mt"]]
    cost_h = (pt * pi + ct * po) / 1e6 / dur_h if dur_h else None
    ttfa = [a["ttfa_ms"] for a in tts if a["seconds"]]
    return {"chunks": len(ch), "outlier_calls": outliers, "free_first_p50": pct(free, .5), "free_first_p90": pct(free, .9), "first_p50": pct(first, .5), "first_p90": pct(first, .9), "last_p50": pct(last, .5),
            "last_p90": pct(last, .9), "done": end - speech_end, "audio_s": audio_s, "speech_s": speech_end,
            "ttfa_p50_ms": pct(ttfa, .5), "translate_ms_p50": pct([c["wall_ms"] for c in ch], .5),
            "mt_cost_per_hour_list": cost_h, "voice": J(os.path.join(WORK, "tts", name, f"{pattern}_en-{t}.json"))["voice"]}


def unit_stats(pattern, t, name):
    p = os.path.join(WORK, "judge", f"{pattern}_en-{t}_{name}.json")
    if not os.path.exists(p):
        return None
    U = J(os.environ["UNITS_CONV" if pattern == "conv" else "UNITS_READ"])["sentences"]
    lab = J(p)["sentences"]
    ess = [l for s in lab for u, l in zip(U[s["i"]]["units"], s["labels"]) if u.get("essential", True)]
    allu = [l for s in lab for l in s["labels"]]
    return {"recall": 100 * ess.count("conveyed") / max(1, len(ess)), "distortion": 100 * allu.count("distorted") / max(1, len(allu))}


def qa_stats(pattern, t, name):
    p = os.path.join(WORK, "qa", f"{pattern}_en-{t}_{name}.json")
    if not os.path.exists(p):
        return None
    sc = [s["score"] for s in J(p)["scores"]]
    return 100 * (sc.count("correct") + 0.5 * sc.count("partial")) / max(1, len(sc))


def grades(job_id, name):
    p = os.path.join(WORK, "grades.json")
    if not os.path.exists(p):
        return None
    G = J(p).get(job_id)
    if not G:
        return None
    g = G["grades"][name]
    return {"score": 100 * sum(x["score"] for x in g) / (3 * len(g)), "critical": sum(1 for x in g if x.get("critical"))}


def contra(pattern, t, name):
    p = os.path.join(WORK, "contra.json")
    if not os.path.exists(p) or name not in ("P8-sol", "P8-gemma31"):
        return None
    R = J(p).get(f"{pattern}:en-{t}")
    if not R or name not in R:
        return None
    ch = sum(x.get("chunks", 0) for x in R[name])
    return 100 * sum(x.get("wrong", 0) for x in R[name]) / max(1, ch)


if __name__ == "__main__":
    res = {}
    for t in TARGETS:
        for pattern in PATTERNS:
            for n in SYSTEMS:
                r = timeline(n, pattern, t)
                r["said"] = grades(f"SAID:{pattern}:en-{t}", n)
                r["written"] = grades(f"WRITTEN:{pattern}:en-{t}", n) if pattern != "conv" else None
                r["units"] = unit_stats(pattern, t, n)
                r["qa"] = qa_stats(pattern, t, n)
                r["contradiction_pct"] = contra(pattern, t, n)
                res[f"{t}:{pattern}:{n}"] = r
    json.dump(res, open(os.path.join(WORK, "results.json"), "w"), indent=1)
    f = lambda x, d=1: "–" if x is None else f"{x:.{d}f}"
    for t in TARGETS:
        print(f"\n### English → {t}\n")
        print("| Clip | System | Said 0–100 (crit) | Unit recall | Distortion | Listener Q | Wrong phrases | First words (no queue) p50 | First audio p50/p90 | Last p50/p90 | All done | Voice / speech |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for pattern in PATTERNS:
            for n in SYSTEMS:
                r = res[f"{t}:{pattern}:{n}"]
                s = r["said"] or {}
                u = r["units"] or {}
                print(f"| {pattern} | {n} | {f(s.get('score'))} ({s.get('critical', '–')}) | {f(u.get('recall'))} | {f(u.get('distortion'))} | {f(r['qa'])} | "
                      f"{f(r['contradiction_pct'])} | {f(r['free_first_p50'])} s | {f(r['first_p50'])} / {f(r['first_p90'])} s | {f(r['last_p50'])} / {f(r['last_p90'])} s | {f(r['done'])} s | "
                      f"{f(r['audio_s'], 0)} / {f(r['speech_s'], 0)} s |")
