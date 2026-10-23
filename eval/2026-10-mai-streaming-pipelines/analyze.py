# The pipelines' runs (pipeline.py) turned into recognition scores, latency, one
# blind grading round and cost.
#
#   python3 -I analyze.py jobs  RUNS UNSEEN UNSEEN_OUT        -> RUNS/jobs.json, RUNS/manifest.json
#   python3 -I ../2026-10-whisper-vs-azure/score.py RUNS/manifest.json RUNS/recognition.json
#   GEMINI_API_KEY=... python3 -I ../2026-10-es-pt-live-compare/grade.py RUNS/jobs.json RUNS/grades.json
#   python3 -I analyze.py table RUNS UNSEEN UNSEEN_OUT        -> results.json (here)
#
# UNSEEN is the folder holding clips_reg/ and clips_irr/ (../2026-10-unseen build_clips.py);
# UNSEEN_OUT holds witness/<lang>.json and said_en.json (that round's "what was said").
#
# Each final is given to every read sentence whose speech it overlaps (by 0.3 s or
# more); a sentence's output is its finals' translations joined, in order. Times are against the sentence's
# speech (start and end found from the clip's energy, as ../2026-10-es-pt-live-compare
# segment.py), so every recogniser is measured from the same instant.
import json, os, statistics, sys, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODE, RUNS, UNSEEN, UO = sys.argv[1:5]
LANGS = ["en", "es", "pt", "fr", "ja"]
PATTERNS = ["reg", "irr"]
DIRS = ["en-es", "en-pt", "en-fr", "en-ja", "es-en", "pt-en", "fr-en", "ja-en"]
PIPES = {  # name -> (recogniser, translator)
    "A mai-stream → sol": ("mai", "sol@low"),
    "B mai-stream → qwen3.5-122b": ("mai", "qwen3.5-122b@or"),
    "B mai-stream → qwen3.8-2.4t": ("mai", "qwen3.8-2.4t@or"),
    "C azure-stream → sol": ("azure", "sol@low"),
    "D mai-stream → gemma-4-31b": ("mai", "gemma-4-31b@or"),
}
J = lambda p: json.load(open(p))
run = lambda rec, pat, lang: J(os.path.join(RUNS, f"{rec}_{pat}_{lang}.json"))
clips = lambda pat: os.path.join(UNSEEN, f"clips_{pat}")


def bounds(pat, lang):
    """(start_s, end_s) of each sentence's speech, from the clip's energy."""
    meta = J(os.path.join(clips(pat), f"{lang}.json"))["sentences"]
    with wave.open(os.path.join(clips(pat), f"{lang}.wav")) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)
    out = []
    for s in meta:
        a = int(s["start"] * 16000)
        seg = x[a:int(s["end"] * 16000)]
        n = len(seg) // 320
        rms = np.sqrt((seg[: n * 320].reshape(n, 320) ** 2).mean(axis=1))
        loud = np.where(rms >= 0.2 * np.percentile(rms, 90))[0]
        out.append((s["start"] + loud[0] * 0.02, s["start"] + (loud[-1] + 1) * 0.02))
    return meta, out


def owner(meta, t):
    """Index of the read sentence a time (s) belongs to."""
    k = 0
    for i, s in enumerate(meta):
        if t >= s["start"] - 0.3:
            k = i
    return k


def per_sentence(pat, lang, rec):
    r = run(rec, pat, lang)
    meta, b = bounds(pat, lang)
    # A final belongs to every sentence whose speech it overlaps by 0.3 s or more (or, failing
    # that, to the sentence its middle falls in): a final that runs two sentences together
    # carries both, and the grader treats a neighbour's words in a slot as harmless.
    own = []
    for f in r["finals"]:
        a, z = f["offsetMs"] / 1000, (f["offsetMs"] + f["durationMs"]) / 1000
        hit = {i for i, (s0, s1) in enumerate(b) if min(z, s1) - max(a, s0) >= 0.3}
        own.append(hit or {owner(meta, (a + z) / 2)})
    return r, meta, b, own


def outputs(pat, d):
    s, t = d.split("-")
    res = {}
    for name, (rec, tr) in PIPES.items():
        r, meta, b, own = per_sentence(pat, s, rec)
        by = {(x["final"]): x["out"] for x in r["translations"] if x["translator"] == tr and x["tgt"] == t}
        res[name] = [" ".join(by.get(k, "") for k, o in enumerate(own) if i in o).strip() for i in range(len(meta))]
    return res


W = {l: J(os.path.join(UO, "witness", f"{l}.json")) for l in LANGS}
SAID_EN = J(os.path.join(UO, "said_en.json"))
en_text = J(os.path.join(clips("reg"), "en.txt.json"))
said_en = [SAID_EN.get(str(i), x) for i, x in enumerate(en_text)]
flagged = lambda l: {x["i"] for x in W[l] if x.get("cut_off") or x.get("meaning_differs")}

if MODE == "jobs":
    jobs = []
    for pat in PATTERNS:
        for d in DIRS:
            s, t = d.split("-")
            o = outputs(pat, d)
            if s == "en":
                jobs.append({"id": f"{pat}:WRITTEN:{d}", "src": s, "tgt": t, "source": en_text, "reference": en_text, "systems": o})
                jobs.append({"id": f"{pat}:SAID:{d}", "src": s, "tgt": t, "source": said_en, "reference": said_en, "systems": o})
            else:
                jobs.append({"id": f"{pat}:WRITTEN:{d}", "src": s, "tgt": t,
                             "source": J(os.path.join(clips(pat), f"{s}.txt.json")), "reference": en_text, "systems": o})
    json.dump(jobs, open(os.path.join(RUNS, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    refs = {l: {"said": os.path.join(UO, "witness", f"{l}.json"), "text": os.path.join(clips("reg"), f"{l}.txt.json")} for l in LANGS}
    man = {"refs": refs, "runs": [{"lang": l, "pattern": p, "system": rec, "kind": "finals", "path": os.path.join(RUNS, f"{rec}_{p}_{l}.json")}
                                  for rec in ("mai", "azure") for p in PATTERNS for l in LANGS]}
    json.dump(man, open(os.path.join(RUNS, "manifest.json"), "w"), indent=1)
    print(len(jobs), "jobs;", len(man["runs"]), "recognition runs")
    sys.exit()


def pct(v, p):
    v = sorted(x for x in v if x is not None)
    return round(v[min(len(v) - 1, int(p * len(v)))]) if v else None


STOP = {"en": {"the", "and", "of", "to", "is", "in", "that", "it", "was", "for"},
        "es": {"el", "la", "de", "que", "y", "los", "las", "en", "es", "por"},
        "pt": {"o", "a", "de", "que", "e", "os", "as", "em", "não", "do", "da", "uma"},
        "fr": {"le", "la", "de", "et", "les", "des", "est", "un", "une", "que", "du"}}


def guess(text):
    """The language a final is written in: kana/kanji -> ja, else the language whose
    common words it uses most. A rough check, only to spot wrong-language finals."""
    if any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for ch in text):
        return "ja"
    w = [x.strip(".,;:!?¿¡\"'«»").lower() for x in text.split()]
    sc = {l: sum(x in s for x in w) for l, s in STOP.items()}
    best = max(sc, key=sc.get)
    return best if sc[best] else None


G = J(os.path.join(RUNS, "grades.json"))
q = lambda g: {"q": round(100 * sum(x.get("score", 0) for x in g) / (3 * max(1, len(g))), 1),
               "crit": sum(1 for x in g if x.get("critical")), "n": len(g)}
res = {"grader": "gemini-pro-latest", "quality": {}, "recognition": {}, "latency": {}, "languages": {}, "cost_per_hour": {}, "providers": {}}
for k, v in G.items():
    pat, ref, d = k.split(":")
    s = d.split("-")[0]
    for name, g in v["grades"].items():
        r = res["quality"].setdefault(pat, {}).setdefault(d, {}).setdefault(name, {})
        if ref == "WRITTEN":
            r["written"] = q(g)
            if s != "en":
                r["said"] = q([x for x in g if x["i"] not in flagged(s)])
        else:
            r["said"] = q(g)

for x in J(os.path.join(RUNS, "recognition.json")):
    res["recognition"].setdefault(x["pattern"], {}).setdefault(x["lang"], {})[x["system"]] = {
        "said": x["said"], "written": x["text"], "dropped": len(x["dropped"]), "missing_starts": len(x["missing_starts"])}

SOL = (4.40, 22.0)   # ../2026-10-translation-cost: list $ per M input / output tokens (reasoning billed as output)
for pat in PATTERNS:
    for lang in LANGS:
        for rec in ("mai", "azure"):
            r, meta, b, own = per_sentence(pat, lang, rec)
            fin, tr = r["finals"], r["translations"]
            secs = J(os.path.join(clips(pat), f"{lang}.json"))["seconds"]
            # end of speech -> the sentence's last final
            covered = set().union(*own) if own else set()
            eos_final = [max(f["arrivedMs"] for f, o in zip(fin, own) if i in o) - 1000 * b[i][1] if i in covered else None
                         for i in range(len(meta))]
            # speech start -> first partial of the sentence: the first partial to arrive after its
            # speech starts and after the previous sentence's last final (MAI's partials carry
            # no offset, so both recognisers are timed by arrival alone)
            first = []
            for i in range(len(meta)):
                after = max([1000 * b[i][0]] + [f["arrivedMs"] for f, o in zip(fin, own) if i - 1 in o and i not in o])
                nxt = 1000 * b[i + 1][0] if i + 1 < len(meta) else 1e12
                ps = [p["arrivedMs"] for p in r["partials"] if after <= p["arrivedMs"] < nxt]
                first.append(min(ps) - 1000 * b[i][0] if ps else None)
            L = res["latency"].setdefault(pat, {}).setdefault(lang, {}).setdefault(rec, {})
            L["eos_to_final"] = {"p50": pct(eos_final, .5), "p90": pct(eos_final, .9)}
            L["speech_start_to_first_partial"] = {"p50": pct(first, .5), "p90": pct(first, .9)}
            L["sentences_without_final"] = sum(1 for i in range(len(meta)) if i not in covered)
            L["finals_spanning_sentences"] = sum(1 for o in own if len(o) > 1)
            L["finals"] = len(fin)
            for name, (rr, trn) in PIPES.items():
                if rr != rec:
                    continue
                for tgt in sorted({x["tgt"] for x in tr}):
                    xs = [x for x in tr if x["translator"] == trn and x["tgt"] == tgt]
                    live = [x for x in xs if not x.get("filled_offline")]   # calls that succeeded during the run
                    done = [max((x["doneMs"] for x in live if i in own[x["final"]]), default=None)
                            if all(not x.get("filled_offline") for x in xs if i in own[x["final"]]) else None
                            for i in range(len(meta))]
                    tot = [d - 1000 * b[i][1] if d is not None else None for i, d in enumerate(done)]
                    mt = [x["doneMs"] - fin[x["final"]]["arrivedMs"] for x in live]
                    d = f"{lang}-{tgt}"
                    res["latency"][pat].setdefault(d, {})[name] = {
                        "eos_to_translation_p50": pct(tot, .5), "eos_to_translation_p90": pct(tot, .9),
                        "translation_call_p50": pct(mt, .5), "translation_call_p90": pct(mt, .9),
                        "calls": len(xs), "failed_live": sum(1 for x in xs if x.get("filled_offline")),
                        "blank_after_fill": sum(1 for x in xs if not x["out"]), "retried": sum(1 for x in xs if x.get("retries"))}
                    if trn == "sol@low":
                        usd = sum(SOL[0] * (x.get("prompt_tokens") or 0) + SOL[1] * (x.get("completion_tokens") or 0) for x in xs) / 1e6
                    else:
                        usd = sum(x.get("cost") or 0 for x in xs)
                    res["cost_per_hour"].setdefault(pat, {}).setdefault(d, {})[name] = round(usd * 3600 / secs, 4)
                    prov = sorted({x.get("provider") for x in xs if x.get("provider")})
                    res["providers"].setdefault(name, set()).update(prov)
            if rec == "mai":
                g = [guess(f["text"]) for f in fin]
                res["languages"].setdefault(pat, {})[lang] = {
                    "detected_field_values": sorted({f.get("detected", "") for f in fin}),
                    "finals": len(fin), "wrong_language_finals": sum(1 for x in g if x and x != lang)}
res["providers"] = {k: sorted(v) for k, v in res["providers"].items()}
# Azure Retail Prices API (prices.azure.com), eastus and eastus2, 2026-10-23: "S1 Speech To Text"
# 1.00 USD/hour; "MAI-Transcribe-2 AzSp Audio" 0.54 USD/hour (no separate streaming meter is listed,
# so which meter streaming bills to is assumed, not confirmed).
REC_PRICE = {"mai": 0.54, "azure": 1.00}
res["recognition_price_per_hour"] = {"mai-transcribe-2-streaming": REC_PRICE["mai"], "azure standard real-time": REC_PRICE["azure"],
                                     "source": "Azure Retail Prices API, list pay-as-you-go, 2026-10-23"}
json.dump(res, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
for pat in PATTERNS:
    print("==", pat)
    for d in DIRS:
        print(d, {n.split(" ", 1)[0] + n.split("→")[1][:12]: (v.get("written", {}).get("q"), v.get("said", {}).get("q"), v.get("written", {}).get("crit"))
                  for n, v in res["quality"].get(pat, {}).get(d, {}).items()})
