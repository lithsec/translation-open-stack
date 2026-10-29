# ../2026-10-open-streaming/analyze_open.py for the commit policies of simulate_policy.py: the same
# placement, latency, grading jobs and table, with these systems, and the number of translator calls
# per sentence. Every policy but S counts as phrase output for "chunks wrong later".
#
#   python3 -I analyze_policy.py jobs  CLIPS_ROOT UNSEEN_OUT WORK   -> WORK/jobs.json, WORK/contra_jobs.json
#   GEMINI_API_KEY=... python3 -I ../2026-10-simultaneous-phrases/seg_all.py CLIPS_ROOT WORK   (before jobs)
#   GEMINI_API_KEY=... python3 -I ../2026-10-es-pt-live-compare/grade.py WORK/jobs.json WORK/grades.json
#   GEMINI_API_KEY=... python3 -I ../2026-10-simultaneous-phrases/contradictions.py WORK/contra_jobs.json WORK/contra.json
#   python3 -I analyze_policy.py table CLIPS_ROOT UNSEEN_OUT WORK   -> results.json (here, merged by system)
import json, os, statistics, sys
import numpy as np, wave

MODE, ROOT, UO, WORK = sys.argv[1:5]
HERE = os.path.dirname(os.path.abspath(__file__))
DIRS = ["en-es", "en-fr", "es-en", "fr-en"]
PATTERNS = ["reg", "irr"]
RECS = [r for r in os.environ.get("RECS", "mai,nemo").split(",") if r]
POLICIES = os.environ.get("POLICIES", "S,P8,judge,decide,agree").split(",")
SYSTEMS = [f"{m}-{r}" for r in RECS for m in POLICIES]
PHRASE = [s for s in SYSTEMS if not s.startswith("S-")]
LIVE = "gemini-live-translate"
J = lambda p: json.load(open(p))
PRICE = {"gemma31-gapi": (0.0, 0.0)}   # tokens are reported instead (tokens_per_hour)


def bounds(clips, lang):
    """Speech start/end of each read sentence, ms (energy, as segment.py speech_ends)."""
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
    return meta, out


def pct(v, p):
    v = sorted(x for x in v if x is not None)
    return round(v[min(len(v) - 1, int(p * len(v)))]) if v else None


def place(sim, rec, meta, lang):
    """Each chunk's source span on the audio."""
    finals = rec["finals"]
    by_seg = {}
    for c in sim["chunks"]:
        by_seg.setdefault(c["segment"], []).append(c)
    for k, cs in by_seg.items():
        f = finals[k] if k < len(finals) else None
        total = sum(len(c["src"]) for c in cs) or 1
        pos = 0
        for c in cs:
            if f:
                a = f["offsetMs"] + f["durationMs"] * pos / total
                b = f["offsetMs"] + f["durationMs"] * (pos + len(c["src"])) / total
            else:
                a = b = c["t"]
            pos += len(c["src"])
            c["src_start"], c["src_end"] = a, b


def timeline(sim, tts, tgt):
    """Audio start of each chunk: done + time to first audio; queued: also after the previous chunk's audio."""
    ttfa, cps = tts[tgt]["ttfa_p50"], tts[tgt]["cps"]
    free = 0.0
    for c in sim["chunks"]:
        c["audio"] = c["done"] + ttfa
        c["audio_q"] = max(c["audio"], free)
        free = c["audio_q"] + 1000 * len(c["out"]) / max(cps, 1)


def load(system, pattern, d):
    p = os.path.join(WORK, "sim", system, f"{pattern}_{d}.json")
    return J(p) if os.path.exists(p) else None


def prepared(pattern, d):
    """{system: (sim, sentence texts)} with chunks placed and timed."""
    s, t = d.split("-")
    clips = os.path.join(ROOT, f"clips_{pattern}")
    meta, bnd = bounds(clips, s)
    tts = J(os.path.join(WORK, "tts.json"))
    res = {}
    for name in SYSTEMS:
        sim = load(name, pattern, d)
        if not sim:
            continue
        rec = J(os.path.join(WORK, "rec", f"{sim['config']['rec']}_{pattern}_{s}.json"))
        place(sim, rec, meta, s)
        timeline(sim, tts, t)
        segp = os.path.join(WORK, "seg", name, f"{pattern}_{d}.json")
        if not os.path.exists(segp):
            # No Gemini cut (seg_all.py) yet: each chunk goes to the read sentence its
            # source span overlaps most on the audio (placement as above). Latency only;
            # grading needs the verbatim cut.
            sent = [[] for _ in bnd]
            for k, c in enumerate(sim["chunks"]):
                if not c["out"].strip():
                    continue
                ov = [min(b, c["src_end"]) - max(a, c["src_start"]) for a, b in bnd]
                i = max(range(len(bnd)), key=lambda j: (ov[j], -abs(bnd[j][0] - c["src_start"])))
                sent[i].append(k)
            sim["sent_chunks"], sim["cut"] = sent, "audio overlap"
            res[name] = (sim, [" ".join(sim["chunks"][k]["out"] for k in ks) for ks in sent])
            continue
        sim["cut"] = "verbatim anchors"
        sg = J(segp)
        owner = sg["chunk_of_char"]
        sep = "" if t == "ja" else " "
        stream = sep.join(c["out"].strip() for c in sim["chunks"] if c["out"].strip())
        assert len(stream) == len(owner)
        # the chunks a sentence's slice touches, by its non-space characters (a joining
        # space belongs to the following chunk)
        sim["sent_chunks"] = [sorted({owner[k] for k in range(a, b) if not stream[k].isspace()}) if a is not None else []
                              for a, b in sg["spans"]]
        res[name] = (sim, sg["out"])
    if s == "en":
        p = os.path.join(WORK, f"glive_{pattern}", "live", f"en-{t}.sent.json")
        if os.path.exists(p):
            res[LIVE] = (J(p), J(p)["live_out"])
    return res


W = {l: J(os.path.join(UO, "witness", f"{l}.json")) for l in ["en", "es", "fr"]}
SAID_EN = J(os.path.join(UO, "said_en.json"))
flagged = lambda l: {r["i"] for r in W[l] if r.get("cut_off") or r.get("meaning_differs")}

if MODE == "jobs":
    en = J(os.path.join(ROOT, "clips_reg", "en.txt.json"))
    said_en = [SAID_EN.get(str(i), x) for i, x in enumerate(en)]
    jobs, contra = [], []
    for pattern in PATTERNS:
        for d in DIRS:
            s, t = d.split("-")
            P = prepared(pattern, d)
            systems = {k: v[1] for k, v in P.items()}
            src = J(os.path.join(ROOT, f"clips_{pattern}", f"{s}.txt.json"))
            if s == "en":
                jobs.append({"id": f"WRITTEN:{pattern}:{d}", "src": s, "tgt": t, "source": en, "reference": en, "systems": systems})
                jobs.append({"id": f"SAID:{pattern}:{d}", "src": s, "tgt": t, "source": said_en, "reference": said_en, "systems": systems})
            else:
                jobs.append({"id": f"WRITTEN:{pattern}:{d}", "src": s, "tgt": t, "source": src, "reference": en, "systems": systems})
            per = {}
            for name in PHRASE:
                if name in P:
                    sim = P[name][0]
                    per[name] = [[sim["chunks"][k]["out"] for k in ks] for ks in sim["sent_chunks"]]
            contra.append({"id": f"{pattern}:{d}", "src": s, "tgt": t, "source": said_en if s == "en" else src,
                           "reference": said_en if s == "en" else en, "systems": per})
    json.dump(jobs, open(os.path.join(WORK, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(contra, open(os.path.join(WORK, "contra_jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "grading jobs,", len(contra), "contradiction jobs")
    sys.exit()

G = J(os.path.join(WORK, "grades.json")) if os.path.exists(os.path.join(WORK, "grades.json")) else {}
C = J(os.path.join(WORK, "contra.json")) if os.path.exists(os.path.join(WORK, "contra.json")) else {}
q = lambda g: {"q": round(100 * sum(x.get("score", 0) for x in g) / (3 * max(1, len(g))), 1),
               "crit": sum(1 for x in g if x.get("critical")), "n": len(g)}
res = {"grader": "gemini-pro-latest", "tts": J(os.path.join(WORK, "tts.json")), "rows": {}}
rs = os.path.join(WORK, "rec_score.json")   # ../2026-10-whisper-vs-azure/score.py on the streams' finals
if os.path.exists(rs):
    res["recognition"] = [{k: x[k] for k in ("lang", "pattern", "system", "said", "text")} for x in J(rs)]
for k, v in G.items():
    ref, pattern, d = k.split(":")
    s = d.split("-")[0]
    for name, g in v["grades"].items():
        r = res["rows"].setdefault(f"{pattern}:{d}", {}).setdefault(name, {})
        if ref == "WRITTEN":
            r["written"] = q(g)
            if s != "en":
                r["said"] = q([x for x in g if x["i"] not in flagged(s)])
        else:
            r["said"] = q(g)

for pattern in PATTERNS:
    for d in DIRS:
        s, t = d.split("-")
        clips = os.path.join(ROOT, f"clips_{pattern}")
        meta, bnd = bounds(clips, s)
        secs = meta["seconds"]
        P = prepared(pattern, d)
        row = res["rows"].setdefault(f"{pattern}:{d}", {})
        for name, (sim, _) in P.items():
            r = row.setdefault(name, {})
            if name == LIVE:
                first_from_start = [f + (bnd[i][1] - bnd[i][0]) if f is not None else None for i, f in enumerate(sim["first_ms"])]
                r["lat"] = {"phrase_start_to_audio_p50": pct(first_from_start, .5), "phrase_start_to_audio_p90": pct(first_from_start, .9),
                            "sentence_end_to_last_audio_p50": pct(sim["last_ms"], .5), "sentence_end_to_last_audio_p90": pct(sim["last_ms"], .9),
                            "note": "first text of each sentence's translation after the sentence's speech starts; last text after it ends"}
                r["sentences_without_output"] = sum(1 for o in sim["live_out"] if not o.strip())
                continue
            cs = sim["chunks"]
            span = [c["audio"] - c["src_start"] for c in cs if c["out"].strip()]
            span_q = [c["audio_q"] - c["src_start"] for c in cs if c["out"].strip()]
            last, last_q, first_sent = [], [], []
            for i, (a, b) in enumerate(bnd):
                mine = [cs[k] for k in sim["sent_chunks"][i]]
                if mine:
                    last.append(max(c["audio"] for c in mine) - b)
                    last_q.append(max(c["audio_q"] for c in mine) - b)
                    first_sent.append(min(c["audio"] for c in mine) - a)
            cfg = sim["config"]
            pin, pout = PRICE[cfg["mt"]]
            cost = sum(((c.get("prompt_tokens") or 0) * pin + (c.get("completion_tokens") or 0) * pout) / 1e6 for c in cs)
            r["lat"] = {"phrase_start_to_audio_p50": pct(span, .5), "phrase_start_to_audio_p90": pct(span, .9),
                        "sentence_start_to_first_audio_p50": pct(first_sent, .5), "sentence_start_to_first_audio_p90": pct(first_sent, .9),
                        "sentence_end_to_last_audio_p50": pct(last, .5), "sentence_end_to_last_audio_p90": pct(last, .9),
                        "queued_sentence_end_to_last_audio_p50": pct(last_q, .5), "queued_sentence_end_to_last_audio_p90": pct(last_q, .9),
                        "queued_phrase_start_to_audio_p50": pct(span_q, .5)}
            r["sentence_cut"] = sim.get("cut")
            r["chunks"] = len(cs)
            r["chunks_per_sentence"] = round(len(cs) / len(bnd), 2)
            r["mt_wall_p50_ms"] = pct([c["wall_ms"] for c in cs], .5)
            r["revised_tokens"] = sim.get("revised_tokens")
            r["translation_per_hour"] = round(cost * 3600 / secs, 4)
            r["tokens_per_hour"] = {"in": round(sum(c.get("prompt_tokens") or 0 for c in cs) * 3600 / secs),
                                    "out": round(sum(c.get("completion_tokens") or 0 for c in cs) * 3600 / secs)}
            rc = os.path.join(WORK, "rec_cost.json")
            if os.path.exists(rc):
                r["recognition_gpu"] = J(rc).get(cfg["rec"])
            r["sentences_without_output"] = sum(1 for x in P[name][1] if not x.strip())
            r["providers"] = sorted({c["provider"] for c in cs if c.get("provider")})
            calls = sim.get("calls") or cs
            r["calls_per_sentence"] = round(len(calls) / len(bnd), 2)
            r["tokens_per_hour"] = {"in": round(sum(c.get("prompt_tokens") or 0 for c in calls) * 3600 / secs),
                                    "out": round(sum(c.get("completion_tokens") or 0 for c in calls) * 3600 / secs)}
            cj = C.get(f"{pattern}:{d}", {}).get(name)
            if cj:
                n = sum(x.get("chunks", 0) for x in cj)
                w = sum(x.get("wrong", 0) for x in cj)
                r["contradictions"] = {"wrong": w, "chunks": n, "rate": round(w / n, 3) if n else None}
# Each recogniser is graded in its own WORK (one blind call per direction holds that recogniser's
# policies): merge its rows into results.json rather than replace the other's.
out = os.path.join(HERE, "results.json")
if os.path.exists(out):
    old = J(out)
    for k, v in old["rows"].items():
        res["rows"].setdefault(k, {}).update({n: r for n, r in v.items() if n not in res["rows"].get(k, {})})
json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)

# Console table
for pattern in PATTERNS:
    for d in DIRS:
        row = res["rows"].get(f"{pattern}:{d}", {})
        print(f"\n{pattern} {d}")
        for name in SYSTEMS + [LIVE]:
            r = row.get(name)
            if not r:
                continue
            L = r.get("lat", {})
            print(f"  {name:16s} calls/sent {r.get('calls_per_sentence')!s:>5} chunks/sent {r.get('chunks_per_sentence')!s:>5} said {r.get('said', {}).get('q')!s:>5} written {r.get('written', {}).get('q')!s:>5} crit {r.get('written', {}).get('crit')!s:>2} | "
                  f"start->audio {L.get('phrase_start_to_audio_p50')}/{L.get('phrase_start_to_audio_p90')} "
                  f"end->last {L.get('sentence_end_to_last_audio_p50')}/{L.get('sentence_end_to_last_audio_p90')} "
                  f"q {L.get('queued_sentence_end_to_last_audio_p50')} | contra {r.get('contradictions', {}).get('rate')} | $/h {r.get('translation_per_hour')}")
