# Translator shootout on Azure's transcripts: the open stack's translators
# (Hy-MT2 7B NF4, MADLAD-400 7B int8, TranslateGemma 12B) against Azure
# Translator, Gemini 3.5 Flash and GPT-5.6-sol on Azure AI Foundry, every one
# given the SAME sentence text, graded blind side by side in one round.
#
#   python3 shootout.py inputs        # build out/inputs.json from the earlier rounds' transcripts
#   python3 shootout.py translate     # every translator over every direction (cached in out/)
#   python3 shootout.py grade         # one blind grading call per direction -> out/grades.json
#   python3 shootout.py table         # results.json + the README tables
#   ONLY=x python3 shootout.py latency  # single-stream latency sample (2 sentences x 25 directions)
#
# Environment (nothing secret is printed):
#   GEMINI_API_KEY                       Gemini (AI Studio): translators and the grader
#   AZURE_KEY, AZURE_REGION=eastus       Azure Translator (the Foundry resource's key)
#   FOUNDRY_ENDPOINT, FOUNDRY_KEY        Azure AI Foundry resource (https://<your-foundry-resource>...)
#   FOUNDRY_DEPLOYMENT=gpt-5.6-sol       its gpt-5.6-sol deployment name (<deployment>)
#   MT_POD, MT_POD_KEY [HF_TOKEN]        the GPU pod running mt_pod.py
#   LLM_POD, LLM_POD_KEY                 the GPU pod running llm_pod.py (round 2: open reasoning LLMs)
#   ONLY=hymt,madlad                     limit `translate` to these translators
#   THREADS=n                            requests in flight per translator (default: its own)
#   ROUND=2                              grade/table round 2: the open reasoning LLMs beside four
#                                        earlier systems' saved outputs (out/grades-<grader>-round2.json,
#                                        results-round2.json); round 1's files are left alone
import concurrent.futures as cf
import difflib, json, os, random, statistics, sys, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SEPT = os.path.join(HERE, "..", "2026-09-model-eval", "sentences")
SYN = os.path.join(HERE, "..", "2026-10-azure-stt-gemini")
REAL = os.path.join(HERE, "..", "2026-10-real-voices")
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
GRADER = os.environ.get("GRADER", "gemini-3.1-pro-preview")
NAMES = {"en": "English", "zh": "Chinese", "fr": "French", "es": "Spanish", "ja": "Japanese", "ru": "Russian",
         "de": "German", "uk": "Ukrainian", "km": "Khmer", "lo": "Lao", "ht": "Haitian Creole"}
HYMT_LANGS = {"en", "zh", "fr", "es", "ja", "ru", "de", "uk", "km"}  # of these; Hy-MT2 has no lo or ht
AZURE_CODE = {"zh": "zh-Hans"}


def J(p):
    return json.load(open(p))


# ---------------------------------------------------------------- inputs

def group(finals, marks, gold):
    """Azure's finals regrouped into the read sentences: each final goes to the
    sentences its audio overlaps (by at least half of the shorter of the two,
    else to the nearest by midpoint, as text-mt/translate_ht.py does for
    Gladia); a final that covers several sentences (Azure ran on across the
    pause) is cut where those sentences end, aligned to what was read."""
    groups = [[] for _ in marks]
    for f in finals:
        a, b = f["offsetMs"] / 1000, (f["offsetMs"] + f["durationMs"]) / 1000
        hit = [i for i, m in enumerate(marks)
               if min(b, m["end"]) - max(a, m["start"]) >= 0.5 * min(b - a, m["end"] - m["start"])
               or (min(b, m["end"]) - max(a, m["start"])) >= 0.5 * (m["end"] - m["start"])]
        if not hit:
            mid = (a + b) / 2
            hit = [min(range(len(marks)), key=lambda i: 0 if marks[i]["start"] <= mid <= marks[i]["end"]
                       else min(abs(mid - marks[i]["start"]), abs(mid - marks[i]["end"])))]
        if len(hit) == 1:
            groups[hit[0]].append(f["text"])
        else:
            for i, piece in zip(hit, split_like(f["text"], [gold[i] for i in hit])):
                groups[i].append(piece)
    return [" ".join(g).strip() for g in groups]


def split_like(text, sents):
    """An unbroken transcript (Omnilingual's) cut where the read sentences end
    (text-mt/translate_ht.py's split_like)."""
    gold = " ".join(sents)
    sm = difflib.SequenceMatcher(None, gold, text, autojunk=False)
    ends, pos = [], 0
    for s_ in sents:
        pos += len(s_)
        ends.append(pos)
        pos += 1

    def across(i):
        for a, b, n in sm.get_matching_blocks():
            if a <= i <= a + n:
                return b + (i - a)
            if a > i:
                return b
        return len(text)
    cuts = [0] + [across(e) for e in ends]
    cuts[-1] = len(text)
    return [text[cuts[k]:cuts[k + 1]].strip() for k in range(len(sents))]


def build_inputs():
    """Directions: <set>:<src>-<tgt>; set syn = September's 24 sentences in
    synthetic voices (../2026-10-azure-stt-gemini), real = FLEURS/CMU readers
    (../2026-10-real-voices). Each: input (what the translator gets, one per
    sentence), source (what was read) and reference (the English meaning)."""
    D = {}
    en = J(os.path.join(SEPT, "en.json"))

    def azure(root, lang, gold):
        st = J(os.path.join(root, "out", "stt", f"{lang}.json"))
        assert not st["err"], (root, lang, st["err"])
        return group(st["finals"], J(os.path.join(root, "audio", f"{lang}.json"))["sentences"], gold)
    syn_en = azure(SYN, "en", en)
    for t in ["ja", "zh", "km", "lo", "ht", "es", "fr", "ru", "de", "uk"]:
        D[f"syn:en-{t}"] = {"input": syn_en, "source": en, "reference": en, "stt": "azure en-US"}
    for s in ["ja", "zh", "km", "lo"]:
        D[f"syn:{s}-en"] = {"input": azure(SYN, s, J(os.path.join(SEPT, f"src_{s}.json"))), "source": J(os.path.join(SEPT, f"src_{s}.json")), "reference": en,
                            "stt": f"azure {J(os.path.join(SYN, 'out', 'stt', f'{s}.json'))['locale']}"}
    src_ht = J(os.path.join(SEPT, "src_ht.json"))
    D["syn:ht-en"] = {"input": split_like(J(os.path.join(SYN, "out", "stack", "ht-en.json"))["heard"], src_ht),
                      "source": src_ht, "reference": en, "stt": "omnilingual (open stack)"}

    rs = lambda n: J(os.path.join(REAL, "sentences", n))
    ren = rs("en.json")
    real_en = azure(REAL, "en", ren)
    for t in ["ja", "km", "lo", "ht", "fr"]:
        D[f"real:en-{t}"] = {"input": real_en, "source": ren, "reference": ren, "stt": "azure en-US"}
    for s in ["ja", "km", "lo"]:
        D[f"real:{s}-en"] = {"input": azure(REAL, s, rs(f"{s}.json")), "source": rs(f"{s}.json"), "reference": rs(f"meaning_{s}.json"),
                             "stt": "azure"}
    D["real:fr-en"] = {"input": azure(REAL, "fr", rs("fr.json")), "source": rs("fr.json"),
                       "reference": J(os.path.join(HERE, "refs", "meaning_fr.json"))["en"], "stt": "azure fr-FR"}
    rht = rs("ht.json")
    D["real:ht-en"] = {"input": split_like(J(os.path.join(REAL, "out", "stack", "ht-en.json"))["heard"], rht),
                       "source": rht, "reference": rs("meaning_ht.json"),
                       "stt": "omnilingual (open stack); reference written by Gemini 2.5 Pro"}
    for k, v in D.items():
        assert len(v["input"]) == len(v["source"]) == len(v["reference"]), k
        v["empty_inputs"] = sum(1 for x in v["input"] if not x.strip())
    json.dump(D, open(os.path.join(OUT, "inputs.json"), "w"), ensure_ascii=False, indent=1)
    for k, v in D.items():
        print(f"{k:14s} {len(v['input'])} sentences, {v['empty_inputs']} empty after regrouping ({v['stt']})")


# ---------------------------------------------------------------- translators

def http(url, body=None, headers=None, timeout=300, tries=6):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                               "User-Agent": "translator-shootout", **(headers or {})})
        try:
            return json.load(urllib.request.urlopen(req, timeout=timeout))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(5 * (attempt + 1))


def prompt(s, src, tgt):
    # translate_ht.py's prompt, with the languages filled in.
    a, b = NAMES[src], NAMES[tgt]
    return (f"Translate this {a} sentence, transcribed from live speech (it may contain recognition errors), "
            f"into natural {b}. Keep numbers, names and negation exact. Output only the {b}.\nSentence: {s}")


def gemini(text, model, thinking=None, json_out=False, max_tokens=8000):
    gen = {"temperature": 0, "maxOutputTokens": max_tokens,
           **({"responseMimeType": "application/json"} if json_out else {}),
           **({"thinkingConfig": {"thinkingLevel": thinking}} if thinking else {})}
    j = http(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
             {"contents": [{"role": "user", "parts": [{"text": text}]}], "generationConfig": gen},
             {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, timeout=600, tries=8)
    try:
        t = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought"))
    except (KeyError, IndexError):
        return {} if json_out else ""  # declined: a blank
    return json.loads(t) if json_out else t.strip()


def foundry(s, src, tgt):
    url = os.environ["FOUNDRY_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions"
    body = {"model": os.environ.get("FOUNDRY_DEPLOYMENT", "gpt-5.6-sol"), "messages": [{"role": "user", "content": prompt(s, src, tgt)}],
            "reasoning_effort": "low"}
    try:
        j = http(url, body, {"api-key": os.environ["FOUNDRY_KEY"]}, timeout=120)
    except urllib.error.HTTPError as e:
        if e.code == 400:  # Azure's content filter refused: scored as a blank
            print(f"  foundry refused ({src}-{tgt}): {e.read().decode(errors='replace')[:160]}", flush=True)
            return ""
        raise
    return (j["choices"][0]["message"]["content"] or "").strip()


def azure_translator(s, src, tgt):
    r = http(f"https://api.cognitive.microsofttranslator.com/translate?api-version=3.0"
             f"&from={AZURE_CODE.get(src, src)}&to={AZURE_CODE.get(tgt, tgt)}", [{"Text": s}],
             {"Ocp-Apim-Subscription-Key": os.environ["AZURE_KEY"],
              "Ocp-Apim-Subscription-Region": os.environ.get("AZURE_REGION", "eastus")}, timeout=60)
    return r[0]["translations"][0]["text"]


def pod(model):
    def one(s, src, tgt):
        base = f"https://{os.environ['MT_POD']}-8000.proxy.runpod.net"
        hdr = {"Authorization": f"Bearer {os.environ['MT_POD_KEY']}"}
        r = http(base + "/translate", {"model": model, "text": s, "src": src, "tgt": tgt}, hdr, timeout=120)
        return r["text"], r["gpu_s"]
    return one


LLM_SAMPLING = {  # each model card's recommended sampling for its reasoning mode
    "gpt-oss": {"temperature": 1.0, "top_p": 1.0},
    "qwen": {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0},
}


def llm(model, family, effort=None, max_tokens=4096):
    """An open reasoning LLM on the vLLM pod (llm_pod.py): the shared LLM prompt
    as one user message, one sentence per call; the pod strips the reasoning."""
    def one(s, src, tgt):
        body = {"messages": [{"role": "user", "content": prompt(s, src, tgt)}], "max_tokens": max_tokens,
                **LLM_SAMPLING[family]}
        if family == "gpt-oss":
            body["reasoning_effort"] = effort
        elif family == "qwen":
            body["chat_template_kwargs"] = {"enable_thinking": True, "reasoning_effort": effort}
        base = f"https://{os.environ['LLM_POD']}-8000.proxy.runpod.net"
        r = http(base + "/chat", body, {"Authorization": f"Bearer {os.environ['LLM_POD_KEY']}"}, timeout=900)
        u = r.get("usage") or {}
        return r["text"], r["gpu_s"], {"completion_tokens": u.get("completion_tokens"), "finish": r.get("finish")}
    return one


# name -> (function(sentence, src, tgt) -> text or (text, gpu_s[, extra]), supports(src, tgt), threads)
TRANSLATORS = {
    "hymt2-7b-nf4": (pod("hymt"), lambda s, t: s in HYMT_LANGS and t in HYMT_LANGS, 1),
    "madlad-7b-int8": (pod("madlad"), lambda s, t: True, 1),
    "translategemma-12b": (pod("tgemma"), lambda s, t: True, 1),
    "azure-translator": (azure_translator, lambda s, t: True, 4),
    "gemini-3.5-flash@medium": (lambda x, s, t: gemini(prompt(x, s, t), "gemini-3.5-flash", "medium"), lambda s, t: True, 4),
    "gemini-3.5-flash": (lambda x, s, t: gemini(prompt(x, s, t), "gemini-3.5-flash"), lambda s, t: True, 4),
    "foundry-gpt-5.6-sol@low": (foundry, lambda s, t: True, 3),
    # round 2: open-weight reasoning LLMs (llm_pod.py serves one at a time)
    "gpt-oss-120b@low": (llm("gpt-oss-120b", "gpt-oss", "low"), lambda s, t: True, 1),
    "gpt-oss-120b@medium": (llm("gpt-oss-120b", "gpt-oss", "medium"), lambda s, t: True, 1),
    "gpt-oss-20b@low": (llm("gpt-oss-20b", "gpt-oss", "low"), lambda s, t: True, 1),
    "qwen3.8-27b-fp8@low": (llm("qwen3.8-27b-fp8", "qwen", "low"), lambda s, t: True, 1),
}
OPEN = ["hymt2-7b-nf4", "madlad-7b-int8", "translategemma-12b"]
ROUND1 = ["hymt2-7b-nf4", "madlad-7b-int8", "translategemma-12b", "azure-translator", "gemini-3.5-flash@medium",
          "gemini-3.5-flash", "foundry-gpt-5.6-sol@low"]
ROUND2 = ["gpt-oss-120b@low", "gpt-oss-120b@medium", "gpt-oss-20b@low", "qwen3.8-27b-fp8@low", "hymt2-7b-nf4", "madlad-7b-int8", "gemini-3.5-flash@medium",
          "foundry-gpt-5.6-sol@low"]
ROUND = os.environ.get("ROUND", "1")
SYSTEMS = ROUND2 if ROUND == "2" else ROUND1
SUFFIX = "-round2" if ROUND == "2" else ""


def translate():
    D = J(os.path.join(OUT, "inputs.json"))
    only = os.environ.get("ONLY", "").split(",") if os.environ.get("ONLY") else list(TRANSLATORS)
    for name in only:
        fn, ok, threads = TRANSLATORS[name]
        threads = int(os.environ.get("THREADS", threads))
        for d, v in D.items():
            src, tgt = d.split(":")[1].split("-")
            p = os.path.join(OUT, "mt", name, f"{d.replace(':', '_')}.json")
            if not ok(src, tgt) or os.path.exists(p):
                continue
            os.makedirs(os.path.dirname(p), exist_ok=True)

            def run(x):
                if not x.strip():
                    return "", None, None, {}
                t0 = time.time()
                r = fn(x, src, tgt)
                wall = round(time.time() - t0, 3)
                if not isinstance(r, tuple):
                    return r, wall, None, {}
                return r[0], wall, r[1], (r[2] if len(r) > 2 else {})
            with cf.ThreadPoolExecutor(threads) as ex:
                res = list(ex.map(run, v["input"]))
            rec = {"out": [r[0] for r in res], "wall_s": [r[1] for r in res], "gpu_s": [r[2] for r in res]}
            for k in sorted({k for r in res for k in r[3]}):
                rec[k] = [r[3].get(k) for r in res]
            if threads > 1:
                rec["in_flight"] = threads
            json.dump(rec, open(p, "w"), ensure_ascii=False, indent=1)
            print(f"{name:26s} {d}", flush=True)


def latency():
    """Single-stream latency for translators whose full pass ran several requests
    in flight: the first two non-empty sentences of every direction, one at a
    time (50 calls) -> out/latency/<name>.json."""
    D = J(os.path.join(OUT, "inputs.json"))
    for name in os.environ["ONLY"].split(","):
        fn, ok, _ = TRANSLATORS[name]
        res = []
        for d, v in D.items():
            src, tgt = d.split(":")[1].split("-")
            for x in [x for x in v["input"] if x.strip()][:2]:
                r = fn(x, src, tgt)
                res.append({"direction": d, "gpu_s": r[1], **(r[2] if len(r) > 2 else {})})
        os.makedirs(os.path.join(OUT, "latency"), exist_ok=True)
        json.dump(res, open(os.path.join(OUT, "latency", f"{name}.json"), "w"), indent=1)
        print(f"{name}: single-stream median {statistics.median(r['gpu_s'] for r in res):.2f} s over {len(res)}")


# ---------------------------------------------------------------- grading

def outputs(d):
    sys_ = {}
    for name in SYSTEMS:
        p = os.path.join(OUT, "mt", name, f"{d.replace(':', '_')}.json")
        if os.path.exists(p):
            sys_[name] = J(p)
    return sys_


def grade_one(d, v):
    src, tgt = d.split(":")[1].split("-")
    systems = {n: r["out"] for n, r in outputs(d).items()}
    labels = list(systems)
    random.Random(d).shuffle(labels)
    names = {chr(65 + i): m for i, m in enumerate(labels)}
    blocks = [f"### System {L}\n" + json.dumps(systems[m], ensure_ascii=False) for L, m in names.items()]
    n = len(v["source"])
    # run12's prompt (text-mt/translate_ht.py), with the direction filled in.
    p = f"""You are an expert {NAMES[src]}->{NAMES[tgt]} translation evaluator. Grade each system's translation of each of the {n} source sentences (each system gives a list aligned to the sources).
The intended meaning of every sentence is given by its English reference, which is authoritative.

Score each sentence per system:
3 = meaning fully correct and natural; 2 = meaning correct but awkward or unidiomatic; 1 = partly wrong, or something important omitted or added; 0 = wrong meaning, wrong language, garbled, or missing.
Also set critical=true when a number, time, date, dose, amount, negation, or who-did-what is wrong (even if the rest is fine).

Source sentences ({NAMES[src]}):
{json.dumps(v["source"], ensure_ascii=False)}

Reference meaning (English):
{json.dumps(v["reference"], ensure_ascii=False)}

Translations into {NAMES[tgt]}:
{chr(10).join(blocks)}

Return JSON: {{"A": [{{"i": 0, "score": 3, "critical": false, "note": "..."}}, ... {n} items], "B": [...], ...}} with a note of at most 8 words only when score < 3 or critical."""
    for _ in range(4):
        try:
            res = gemini(p, GRADER, json_out=True, max_tokens=65536)
        except json.JSONDecodeError:
            continue
        if isinstance(res, dict) and all(isinstance(res.get(L), list) and len(res[L]) >= n - 1 for L in names):
            return d, {names[L]: res[L] for L in names}
    raise SystemExit(f"grader failed on {d}")


def grade():
    D = J(os.path.join(OUT, "inputs.json"))
    gp = os.path.join(OUT, f"grades-{GRADER}{SUFFIX}.json")
    if os.path.exists(gp):
        sys.exit(f"{gp} exists: one round only (delete it to grade everything again, together)")
    with cf.ThreadPoolExecutor(5) as ex:
        G = dict(ex.map(lambda kv: grade_one(*kv), D.items()))
    json.dump(G, open(gp, "w"), ensure_ascii=False, indent=1)
    print("graded", len(G), "directions with", GRADER)


# ---------------------------------------------------------------- table

GROUPS = {  # README group averages: the mean of the directions' scores, total critical errors
    "Into English: ja, zh, km, fr (6)": ["syn:ja-en", "syn:zh-en", "syn:km-en", "real:ja-en", "real:km-en", "real:fr-en"],
    "Out of English: ja, zh, km, es, fr, ru, de, uk (11)": [f"syn:en-{t}" for t in ["ja", "zh", "km", "es", "fr", "ru", "de", "uk"]]
    + ["real:en-ja", "real:en-km", "real:en-fr"],
    "Lao, both ways (4)": ["syn:en-lo", "syn:lo-en", "real:en-lo", "real:lo-en"],
    "Haitian Creole, both ways (4)": ["syn:en-ht", "syn:ht-en", "real:en-ht", "real:ht-en"],
}
SHORT = {"hymt2-7b-nf4": "Hy-MT2", "madlad-7b-int8": "MADLAD", "translategemma-12b": "TGemma 12B",
         "azure-translator": "Azure Tr.", "gemini-3.5-flash@medium": "Flash @med", "gemini-3.5-flash": "Flash default",
         "foundry-gpt-5.6-sol@low": "sol @low", "gpt-oss-120b@low": "oss-120b @low",
         "gpt-oss-120b@medium": "oss-120b @med", "gpt-oss-20b@low": "oss-20b @low",
         "qwen3.8-27b-fp8@low": "Qwen3.8-27B @low"}


def table():
    D = J(os.path.join(OUT, "inputs.json"))
    G = J(os.path.join(OUT, f"grades-{GRADER}{SUFFIX}.json"))
    R = {"grader": GRADER, "round": ROUND, "directions": {}}
    for d, v in D.items():
        n = len(v["source"])
        row = {}
        for name, r in outputs(d).items():
            g = {x["i"]: x for x in G[d][name]}
            lat = [t for t in r["wall_s"] if t is not None]
            gpu = [t for t in r["gpu_s"] if t is not None]
            row[name] = {"score": round(sum(g.get(i, {}).get("score", 0) for i in range(n)) / (3 * n), 3),
                         "fully_correct": round(sum(1 for i in range(n) if g.get(i, {}).get("score") == 3) / n, 3),
                         "critical": sum(1 for x in g.values() if x.get("critical")),
                         "median_s": round(statistics.median(lat), 2) if lat else None,
                         "p90_s": round(sorted(lat)[int(0.9 * (len(lat) - 1))], 2) if lat else None,
                         "median_gpu_s": round(statistics.median(gpu), 2) if gpu else None}
            if "completion_tokens" in r:
                tok = [t for t in r["completion_tokens"] if t is not None]
                row[name]["median_completion_tokens"] = statistics.median(tok) if tok else None
                row[name]["truncated"] = sum(1 for f in r.get("finish", []) if f == "length")
                row[name]["blank_outputs"] = sum(1 for x, o in zip(v["input"], r["out"]) if x.strip() and not o.strip())
            if r.get("in_flight"):
                row[name]["in_flight"] = r["in_flight"]
        R["directions"][d] = {"sentences": n, "stt": v["stt"], "empty_inputs": v["empty_inputs"], "systems": row}
    cols = [c for c in SYSTEMS if any(c in x["systems"] for x in R["directions"].values())]
    R["groups"], R["overall"], R["latency"] = {}, {}, {}
    for c in cols:
        R["groups"][c] = {}
        for gname, ds in list(GROUPS.items()) + [("All 25 directions", list(D))]:
            xs = [R["directions"][d]["systems"].get(c) for d in ds]
            if all(xs):
                R["groups"][c][gname] = {"score": round(statistics.mean(x["score"] for x in xs), 3),
                                         "critical": sum(x["critical"] for x in xs)}
        if "All 25 directions" in R["groups"][c]:
            R["overall"][c] = R["groups"][c]["All 25 directions"]
        meds = [x["systems"][c]["median_gpu_s"] if x["systems"][c]["median_gpu_s"] is not None else x["systems"][c]["median_s"]
                for x in R["directions"].values() if c in x["systems"]]
        R["latency"][c] = {"median_over_directions_s": round(statistics.median(meds), 2),
                           "range_s": [min(meds), max(meds)]}
        lp = os.path.join(OUT, "latency", f"{c}.json")
        if os.path.exists(lp):  # single-stream sample (`latency`)
            L = J(lp)
            g = sorted(x["gpu_s"] for x in L)
            R["latency"][c]["single_stream"] = {"n": len(g), "median_s": round(statistics.median(g), 2),
                                                "p90_s": round(g[int(0.9 * (len(g) - 1))], 2),
                                                "median_completion_tokens": statistics.median(x["completion_tokens"] for x in L)}
    json.dump(R, open(os.path.join(HERE, f"results{SUFFIX}.json"), "w"), indent=1)

    print("| Direction | " + " | ".join(SHORT[c] for c in cols) + " |")
    print("|---" * (len(cols) + 1) + "|")
    for d, x in R["directions"].items():
        s = x["systems"]
        best = max(v["score"] for v in s.values())
        cells = []
        for c in cols:
            if c not in s:
                cells.append("n/a")
                continue
            v = s[c]
            t = f"{v['score']:.0%} ({v['critical']})"
            cells.append(f"**{t}**" if v["score"] == best else t)
        print(f"| {d} | " + " | ".join(cells) + " |")
    print("\n| Group | " + " | ".join(SHORT[c] for c in cols) + " |")
    print("|---" * (len(cols) + 1) + "|")
    for gname in list(GROUPS) + ["All 25 directions"]:
        vals = {c: R["groups"][c].get(gname) for c in cols}
        best = max(v["score"] for v in vals.values() if v)
        cells = []
        for c in cols:
            v = vals[c]
            t = f"{v['score']:.0%} ({v['critical']})" if v else "n/a"
            cells.append(f"**{t}**" if v and v["score"] == best else t)
        print(f"| {gname} | " + " | ".join(cells) + " |")
    print("\nMedian latency per sentence, s (pod models: time on the pod; APIs: round trip)")
    print("| Direction | " + " | ".join(SHORT[c] for c in cols) + " |")
    print("|---" * (len(cols) + 1) + "|")
    for d, x in R["directions"].items():
        s = x["systems"]
        cells = []
        for c in cols:
            v = s.get(c)
            if not v:
                cells.append("n/a")
            elif v["median_gpu_s"] is not None:
                cells.append(f"{v['median_gpu_s']:.2f}")
            else:
                cells.append(f"{v['median_s']:.2f}")
        print(f"| {d} | " + " | ".join(cells) + " |")
    print("| median over directions | " + " | ".join(f"{R['latency'][c]['median_over_directions_s']:.2f}" for c in cols) + " |")
    ss = lambda c, k: f"{R['latency'][c]['single_stream'][k]}" if "single_stream" in R["latency"][c] else "-"
    print("| single stream, median (50) | " + " | ".join(ss(c, "median_s") for c in cols) + " |")
    print("| single stream, p90 (50) | " + " | ".join(ss(c, "p90_s") for c in cols) + " |")
    print("| completion tokens, median (50) | " + " | ".join(ss(c, "median_completion_tokens") for c in cols) + " |")


if __name__ == "__main__":
    {"inputs": build_inputs, "translate": translate, "latency": latency, "grade": grade, "table": table}[sys.argv[1]]()
