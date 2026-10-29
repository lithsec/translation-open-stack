# ../2026-10-complete-thought-ht-km-lo/analyze.py for this run's arms and ten directions, unchanged but for:
#   - the arms' names (simulate.py) and the hearing tags: az (Azure standard) and mai;
#   - the references: English sources against what was said, as before; ja, ko, fa and hi against the English FLEURS
#     text of the same ids (<lang>.ref_en.json), leaving out the recordings the witness flagged;
#   - the room decider's calls: its decisions are shared by the room's three targets, so a direction counts a third
#     of each ("shared"); room.py gives the room's own totals.
# That file:
# ../2026-10-complete-thought-endpointing/analyze_ct.py for the ht/km/lo arms and six directions, unchanged but for:
#   - the arms' names (the hearing differs by source language: mai, o3, o3p, o7, o7c; simulate.py);
#   - the references: English sources are graded against what was said, as before; Khmer and Lao against the
#     FLEURS English text, Haitian Creole against the model-made English (make_refs.py), each leaving out the
#     recordings the witness flagged.
# That file:
# ../2026-10-llm-commit-policy-bedrock-de-hi-tr/analyze_policy.py for this run's arms and ten directions:
# the same placement, voice timeline, latency, grading and contradiction jobs, plus
#   - the split-thought jobs (split.py): per read sentence, how many of the chunks spoken for it stop in the
#     middle of a clause;
#   - the longest wait: for each chunk, from when its first source word was spoken to its first audio. A
#     chunk's first word is placed on the read sentence's speech by the chunk's share of that sentence's
#     output (one rule for every arm, from the verbatim cut);
#   - Gemma (and sol) calls per sentence, and the complete-thought arms' fallbacks (flush, force).
# Every arm counts as chunked output for "wrong later" and "split" (a whole-sentence arm's chunks are the
# recogniser's finals, which can split a sentence too).
#
#   python3 -I analyze_ct.py jobs  CLIPS_ROOT UO WORK   -> WORK/jobs.json, contra_jobs.json, split_jobs.json
#   python3 -I analyze_ct.py table CLIPS_ROOT UO WORK   -> results.json
import json, os, statistics, sys
import numpy as np, wave

MODE, ROOT, UO, WORK = sys.argv[1:5]
HERE = os.path.dirname(os.path.abspath(__file__))
DIRS = os.environ.get("DIRS", "en-ja,en-ko,en-fa,en-ur,en-bn,en-ta,ja-en,ko-en,fa-en,hi-en").split(",")
PATTERNS = ["reg", "irr"]
SYSTEMS = [f"{a}-{r}" for r in ("az", "mai") for a in ("S-sol", "S", "ctb", "ctb-gs", "agree", "room", "room-g")]
GRADES = os.environ.get("GRADES", "grades.json")
J = lambda p: json.load(open(p))


def bounds(clips, lang):
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


def timeline(sim, tts, tgt):
    ttfa, cps = tts[tgt]["ttfa_p50"], tts[tgt]["cps"]
    free = 0.0
    for c in sim["chunks"]:
        c["audio"] = c["done"] + ttfa
        c["audio_q"] = max(c["audio"], free)
        free = c["audio_q"] + 1000 * len(c["out"]) / max(cps, 1)


def prepared(pattern, d):
    s, t = d.split("-")
    meta, bnd = bounds(os.path.join(ROOT, f"clips_{pattern}"), s)
    tts = J(os.path.join(WORK, "tts.json"))
    res = {}
    for name in SYSTEMS:
        p = os.path.join(WORK, "sim", name, f"{pattern}_{d}.json")
        segp = os.path.join(WORK, "seg", name, f"{pattern}_{d}.json")
        if not os.path.exists(p) or not os.path.exists(segp):
            continue
        sim = J(p)
        timeline(sim, tts, t)
        sg = J(segp)
        owner = sg["chunk_of_char"]
        stream = ("" if t == "ja" else " ").join(c["out"].strip() for c in sim["chunks"] if c["out"].strip())   # as seg_all.py
        assert len(stream) == len(owner), (name, pattern, d)
        sim["sent_chunks"] = [sorted({owner[k] for k in range(a, b) if not stream[k].isspace()}) if a is not None else []
                              for a, b in sg["spans"]]
        res[name] = (sim, sg["out"])
    return meta, bnd, res


W = {l: J(os.path.join(UO, "witness", f"{l}.json")) for l in ["en", "ja", "ko", "fa", "hi"]}
SAID_EN = J(os.path.join(UO, "said_en.json"))
flagged = lambda l: {r["i"] for r in W[l] if r.get("cut_off") or r.get("meaning_differs")}

if MODE == "jobs":
    en = J(os.path.join(ROOT, "clips_reg", "en.txt.json"))
    said_en = [SAID_EN.get(str(i), x) for i, x in enumerate(en)]
    jobs, contra, split = [], [], []
    for pattern in PATTERNS:
        for d in DIRS:
            s, t = d.split("-")
            _, _, P = prepared(pattern, d)
            systems = {k: v[1] for k, v in P.items()}
            src = J(os.path.join(ROOT, f"clips_{pattern}", f"{s}.txt.json"))
            if s == "en":
                jobs.append({"id": f"SAID:{pattern}:{d}", "src": s, "tgt": t, "source": said_en, "reference": said_en, "systems": systems})
            else:
                ref = J(os.path.join(ROOT, f"clips_{pattern}", f"{s}.ref_en.json"))
                jobs.append({"id": f"WRITTEN:{pattern}:{d}", "src": s, "tgt": t, "source": src, "reference": ref, "systems": systems})
            per = {name: [[sim["chunks"][k]["out"] for k in ks] for ks in sim["sent_chunks"]] for name, (sim, _) in P.items()}
            ref = said_en if s == "en" else J(os.path.join(ROOT, f"clips_{pattern}", f"{s}.ref_en.json"))
            item = {"id": f"{pattern}:{d}", "src": s, "tgt": t, "source": said_en if s == "en" else src,
                    "reference": ref, "systems": per}
            contra.append(item)
            split.append(item)
    json.dump(jobs, open(os.path.join(WORK, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(contra, open(os.path.join(WORK, "contra_jobs.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(split, open(os.path.join(WORK, "split_jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "grading jobs,", len(contra), "contradiction/split jobs")
    sys.exit()

opt = lambda f: J(os.path.join(WORK, f)) if os.path.exists(os.path.join(WORK, f)) else {}
G, C, SP = opt(GRADES), opt("contra.json"), opt("split.json")
res = {"grader": "gemini-flash-latest", "grades": GRADES, "tts": J(os.path.join(WORK, "tts.json")), "rows": {}}
for k, v in G.items():
    ref, pattern, d = k.split(":")[:3]
    s = d.split("-")[0]
    for name, g in v["grades"].items():
        r = res["rows"].setdefault(f"{pattern}:{d}", {}).setdefault(name, {})
        keep = [x for x in g if s == "en" or x["i"] not in flagged(s)]
        r["said"] = {"q": round(100 * sum(x.get("score", 0) for x in keep) / (3 * max(1, len(keep))), 1),
                     "crit": sum(1 for x in keep if x.get("critical")), "n": len(keep)}
        r["scores"] = {x["i"]: x.get("score", 0) for x in keep}

for pattern in PATTERNS:
    for d in DIRS:
        s, t = d.split("-")
        meta, bnd, P = prepared(pattern, d)
        secs = meta["seconds"]
        row = res["rows"].setdefault(f"{pattern}:{d}", {})
        for name, (sim, outs) in P.items():
            r = row.setdefault(name, {})
            cs = sim["chunks"]
            last, last_q, first, waits = [], [], [], []
            for i, (a, b) in enumerate(bnd):
                mine = [cs[k] for k in sim["sent_chunks"][i]]
                if not mine:
                    continue
                last.append(max(c["audio"] for c in mine) - b)
                last_q.append(max(c["audio_q"] for c in mine) - b)
                first.append(min(c["audio"] for c in mine) - a)
                tot = sum(len(c["out"]) for c in mine) or 1
                pos = 0
                for c in mine:
                    waits.append(c["audio"] - (a + (b - a) * pos / tot))
                    pos += len(c["out"])
            calls = sim.get("calls") or cs
            real = [c for c in calls if c.get("wall_ms", 0) > 0 or c.get("prompt_tokens")]
            r["lat"] = {"first_p50": pct(first, .5), "first_p90": pct(first, .9), "first_max": pct(first, 1),
                        "last_p50": pct(last, .5), "last_p90": pct(last, .9), "queued_last_p50": pct(last_q, .5),
                        "longest_wait": pct(waits, 1), "wait_p90": pct(waits, .9)}
            r["chunks_per_sentence"] = round(len(cs) / len(bnd), 2)
            share = lambda c: 1 / c.get("shared", 1)
            r["calls_per_sentence"] = round(sum(share(c) for c in real) / len(bnd), 2)
            by = {}
            for c in real:
                m = c.get("mt") or sim["config"]["mt"]
                by[m] = by.get(m, 0) + share(c)
            r["calls_by_model_per_sentence"] = {k: round(v / len(bnd), 2) for k, v in by.items()}
            r["call_wall_ms"] = [c["wall_ms"] for c in real]
            r["call_wall_ms_by_kind"] = {}
            for c in real:
                r["call_wall_ms_by_kind"].setdefault(f"{c.get('mt') or sim['config']['mt']}:{c.get('kind', 'sentence')}", []).append(c["wall_ms"])
            r["tokens_per_hour"] = {"in": round(sum((c.get("prompt_tokens") or 0) * share(c) for c in real) * 3600 / secs),
                                    "out": round(sum((c.get("completion_tokens") or 0) * share(c) for c in real) * 3600 / secs)}
            r["fallbacks"] = {k: sum(1 for c in cs if c.get("kind") == k) for k in ("flush", "force")}
            r["thoughts"] = sum(1 for c in cs if c.get("kind") in ("ct", "flush", "force"))
            r["sentences_without_output"] = sum(1 for x in outs if not x.strip())
            cj = C.get(f"{pattern}:{d}", {}).get(name)
            if cj:
                n = sum(x.get("chunks", 0) for x in cj)
                w = sum(x.get("wrong", 0) for x in cj)
                r["contradictions"] = {"wrong": w, "chunks": n, "rate": round(w / n, 3) if n else None}
            sj = SP.get(f"{pattern}:{d}", {}).get(name)
            if sj:
                fl = flagged(s) if s != "en" else set()
                items = [x for x in sj if x.get("i") not in fl]
                split_sent = {x["i"] for x in items if x.get("split", 0) > 0}
                r["split"] = {"chunks": sum(x.get("chunks", 0) for x in items), "split": sum(x.get("split", 0) for x in items),
                              "sentences": len(items), "sentences_split": len(split_sent)}
                sc = r.get("scores") or {}
                whole = [v for i, v in sc.items() if int(i) not in split_sent]
                r["whole_thought_q"] = round(100 * sum(whole) / (3 * len(whole)), 1) if whole else None
                r["whole_thought_n"] = len(whole)
json.dump(res, open(os.path.join(HERE, os.environ.get("RESULTS", "results.json")), "w"), ensure_ascii=False, indent=1)
for k, row in res["rows"].items():
    print(k)
    for name, r in row.items():
        L = r.get("lat", {})
        print(f"  {name:14s} q {r.get('said', {}).get('q')!s:>5} crit {r.get('said', {}).get('crit')!s:>2} first {L.get('first_p50')} "
              f"last {L.get('last_p50')}/{L.get('last_p90')} wait {L.get('longest_wait')} calls {r.get('calls_per_sentence')} "
              f"wrong {r.get('contradictions', {}).get('rate')} split {r.get('split', {}).get('sentences_split')} fb {r.get('fallbacks')}")
