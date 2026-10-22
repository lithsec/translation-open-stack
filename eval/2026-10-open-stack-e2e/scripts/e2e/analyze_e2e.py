# Per-sentence latency, CER and per-sentence transcripts from the stack runs.
#   python3 -I analyze_e2e.py <e2e dir>   -> out/latency.json, out/sentences.json
# Timeline and definitions as eval/2026-10-latency/analyze.py: chunk k delivered at (k+1)*100 ms,
# speech start/end from the audio (20 ms frames >= 20% of the sentence's p90 loudness), first audio =
# first voiced 10 ms frame (RMS > 150) of the chunk, at its arrival.
# Which output belongs to which sentence: the stack sends inputTranscript (what it heard) per
# utterance, then the translation, then the audio. Utterances are aligned to the read sentences by
# text (difflib over the whole clip, as shootout.split_like), constrained to sentences that had
# started before the utterance arrived; an utterance covers every sentence it overlaps by >= 30% of
# the sentence (merged across a pause) and a sentence cut by the 12 s limit takes several utterances.
import difflib, json, os, re, statistics, sys, wave
import numpy as np

E = sys.argv[1]
sys.path.insert(0, os.path.expanduser("~/dev/translation-open-stack/eval/2026-10-real-voices"))
sys.path.insert(0, os.path.expanduser("~/dev/translation-open-stack/eval/2026-10-translator-shootout"))
from judge import cer  # noqa: E402
CL = os.path.join(E, "clips")
RUNS = os.path.join(E, "out", "runs")


def speech_bounds(lang):
    meta = json.load(open(os.path.join(CL, f"{lang}.json")))
    with wave.open(os.path.join(CL, f"{lang}.wav")) as w:
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


def split_like(text, sents):
    gold = " ".join(sents)
    sm = difflib.SequenceMatcher(None, gold, text, autojunk=False)
    ends, pos = [], 0
    for s_ in sents:
        pos += len(s_)
        ends.append(pos)
        pos += 1
    blocks = sm.get_matching_blocks()

    def across(i):
        for a, b, n in blocks:
            if a <= i <= a + n:
                return b + (i - a)
            if a > i:
                return b
        return len(text)
    cuts = [0] + [across(e) for e in ends]
    cuts[-1] = len(text)
    return [text[cuts[k]:cuts[k + 1]].strip() for k in range(len(sents))]


def utterances(events):
    us = []
    for e in events:
        if e["kind"] == "input":
            us.append({"t": e["t"], "heard": e["text"], "texts": [], "auds": []})
        elif e["kind"] == "text" and us:
            us[-1]["texts"].append(e)
        elif e["kind"] == "audio" and us:
            us[-1]["auds"].append(e)
    return us


def assign(us, gold, bounds):
    """sentence indices per utterance"""
    G = " ".join(gold)
    spans, pos = [], 0
    for s in gold:
        spans.append((pos, pos + len(s)))
        pos += len(s) + 1
    H, hs = "", []
    for u in us:
        a = len(H) + (1 if H else 0)
        H = (H + " " + u["heard"]) if H else u["heard"]
        hs.append((a, len(H)))
    sm = difflib.SequenceMatcher(None, G, H, autojunk=False)
    blocks = sm.get_matching_blocks()
    out = []
    for (ha, hb), u in zip(hs, us):
        cover = [0] * len(gold)
        for a, b, n in blocks:
            lo, hi = max(b, ha), min(b + n, hb)
            if hi <= lo:
                continue
            ga, gb = a + (lo - b), a + (hi - b)
            for k, (sa, sb) in enumerate(spans):
                cover[k] += max(0, min(gb, sb) - max(ga, sa))
        ok = [k for k in range(len(gold)) if bounds[k][0] < u["t"]]
        hit = [k for k in ok if cover[k] >= 0.3 * max(1, spans[k][1] - spans[k][0])]
        if not hit:
            best = max(ok, key=lambda k: cover[k], default=None) if ok else None
            if best is not None and cover[best] > 0:
                hit = [best]
            else:  # nothing aligns: the latest sentence that had ended before it arrived
                ended = [k for k in ok if bounds[k][1] < u["t"]]
                hit = [ended[-1]] if ended else ([ok[-1]] if ok else [0])
        out.append(hit)
    return out


def pct(v, q):
    v = sorted(v)
    if not v:
        return None
    k = (len(v) - 1) * q
    f = int(k)
    return round(v[f] + (v[min(f + 1, len(v) - 1)] - v[f]) * (k - f))


def stage_lines(name, prev):
    p = os.path.join(RUNS, f"{name}.log.json")
    if not os.path.exists(p):
        return [], prev
    lines = [l for l in json.load(open(p))["lines"] if l.startswith("[stack] utterance") or "dropped" in l]
    # new lines since the previous run's fetch: drop the longest prefix that is a suffix of prev
    k = 0
    for n in range(min(len(prev), len(lines)), 0, -1):
        if lines[:n] == prev[-n:]:
            k = n
            break
    return lines[k:], lines


def parse_stage(l):
    m = re.match(r"\[stack\] utterance ([\d.]+)s speech \| (.*)", l)
    if not m:
        return None
    d = {"speech": float(m.group(1))}
    for k, v in re.findall(r"(\S+) ([\d.]+)s", m.group(2)):
        d[k] = float(v)
    return d


ORDER = ["en-es", "es-en", "en-ja", "ja-en", "en-fr", "fr-en", "en-km", "km-en", "ht-en", "en-ht", "lo-en", "en-lo"]
res, sents, prev = {}, {}, []
for d in ORDER:
    p = os.path.join(RUNS, f"{d}.json")
    if not os.path.exists(p):
        continue
    run = json.load(open(p))
    s, t = d.split("-")
    gold = json.load(open(os.path.join(CL, f"{s}.txt.json")))
    bounds = speech_bounds(s)
    us = utterances(run["events"])
    hit = assign(us, gold, bounds)
    cursor = 0.0
    for e in run["events"]:
        if e["kind"] == "audio":
            e["play"] = max(e["t"], cursor)
            cursor = e["play"] + e["samples"] / e["rate"] * 1000
    rows = []
    for i, (a, b) in enumerate(bounds):
        mine = [u for u, h in zip(us, hit) if i in h]
        r = {"i": i, "speech_start_ms": a, "speech_end_ms": b, "n_utt": len(mine),
             "out": " ".join("".join(x["text"] for x in u["texts"]).strip() for u in mine).strip(),
             "heard": " ".join(u["heard"] for u in mine)}
        texts = [x for u in mine for x in u["texts"] if x["text"].strip()]
        auds = [x for u in mine for x in u["auds"] if "on" in x]
        if texts:
            r["stop_to_first_text_ms"] = round(texts[0]["t"] - b)
        if auds:
            first = auds[0]["t"] + auds[0]["on"]
            r["stop_to_first_audio_ms"] = round(first - b)
            r["start_to_first_audio_ms"] = round(first - a)
            r["stop_to_first_audio_played_ms"] = round(min(x["play"] + x["on"] for x in auds) - b)
            tail = [x for x in mine[-1]["auds"] if "on" in x]
            if tail:
                r["stop_to_tail_audio_ms"] = round(tail[0]["t"] + tail[0]["on"] - b)
            cur, end = 0.0, 0.0
            for x in auds:
                st = max(x["t"], cur)
                cur = st + x["samples"] / x["rate"] * 1000
                end = st + x["off"]
            r["stop_to_audio_end_ms"] = round(end - b)
            r["audio_ms"] = round(sum(x["samples"] / x["rate"] * 1000 for x in auds))
        rows.append(r)
    heard_all = " ".join(u["heard"] for u in us)
    per_sent_tr = split_like(heard_all, gold)
    m = lambda k: {"p50": pct([r[k] for r in rows if k in r], 0.5), "p90": pct([r[k] for r in rows if k in r], 0.9),
                   "n": sum(1 for r in rows if k in r)}
    new, prev = stage_lines(d, prev)
    st = [x for x in map(parse_stage, new) if x]
    speech = sum(x["speech"] for x in st)
    gpu = {}
    gp = os.path.join(RUNS, f"{d}.gpu.json")
    if os.path.exists(gp):
        smp = json.load(open(gp))["samples"]
        if smp:
            gpu = {"name": smp[0][4], "mem_used_mb_max": max(x[1] for x in smp), "mem_used_mb_min": min(x[1] for x in smp),
                   "mem_total_mb": smp[0][2], "util_pct_mean": round(statistics.mean(x[3] for x in smp), 1),
                   "util_pct_max": max(x[3] for x in smp), "samples": len(smp)}
    dropped = sum(1 for l in new if "pipeline behind, dropped" in l)
    stage = {"dropped_utterances": dropped}
    if st:
        def tot(key):
            return sum(x.get(key, 0) for x in st)
        asr = sum(x["asr"] - x.get("lid", 0) for x in st if "asr" in x)
        mt = sum(x["mt"] - x["asr"] for x in st if "mt" in x and "asr" in x)
        stage = {"dropped_utterances": dropped, "utterances_logged": len(st), "speech_s": round(speech, 1), "asr_s": round(asr, 2),
                 "asr_rtf": round(asr / speech, 3) if speech else None, "mt_s": round(mt, 2),
                 "mt_rtf": round(mt / speech, 3) if speech else None,
                 "done_s": round(tot("done"), 2), "pipeline_rtf": round(tot("done") / speech, 3) if speech else None,
                 "asr_median_s": round(statistics.median([x["asr"] - x.get("lid", 0) for x in st if "asr" in x]), 2),
                 "mt_median_s": round(statistics.median([x["mt"] - x["asr"] for x in st if "mt" in x and "asr" in x] or [0]), 2),
                 "first_tts_median_s": round(statistics.median([v - x["mt"] for x in st for k, v in x.items() if k.startswith("tts1[") and "mt" in x] or [0]), 2)}
    res[d] = {"src": s, "tgt": t, "err": run.get("err"), "utterances": len(us),
              "missing_audio": sum(1 for r in rows if "stop_to_first_audio_ms" not in r),
              "cer": cer(" ".join(gold), heard_all),
              "voiced_before_stop": round(sum(1 for r in rows if r.get("stop_to_first_audio_ms", 1) < 0) / len(rows), 2),
              **{k: m(k) for k in ["stop_to_first_audio_ms", "stop_to_tail_audio_ms", "start_to_first_audio_ms",
                                   "stop_to_first_text_ms", "stop_to_audio_end_ms", "stop_to_first_audio_played_ms"]},
              "stage": stage, "gpu": gpu}
    sents[d] = {"source": gold, "heard_per_sentence": per_sent_tr, "live_out": [r["out"] for r in rows], "rows": rows,
                "heard_all": heard_all}
    print(f"{d}: utt {len(us)} CER {res[d]['cer']} stop->first {res[d]['stop_to_first_audio_ms']} tail {res[d]['stop_to_tail_audio_ms']['p50']} "
          f"start->first {res[d]['start_to_first_audio_ms']['p50']} missing {res[d]['missing_audio']} stage {stage.get('asr_rtf')}/{stage.get('mt_median_s')} gpu {gpu.get('mem_used_mb_max')}")
# Pipeline drops ("pipeline behind, dropped") are not recognition errors: for the error split the
# en->X directions take their English transcript from en-es (same audio; the en-es run dropped nothing),
# and each run reports its own drops.
for d in sents:
    if d.startswith("en-") and d != "en-es" and "en-es" in sents:
        sents[d]["heard_per_sentence_own"] = sents[d]["heard_per_sentence"]
        sents[d]["heard_per_sentence"] = sents["en-es"]["heard_per_sentence"]
json.dump(res, open(os.path.join(E, "out", "latency.json"), "w"), indent=1, ensure_ascii=False)
json.dump(sents, open(os.path.join(E, "out", "sentences.json"), "w"), indent=1, ensure_ascii=False)
