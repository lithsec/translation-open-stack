# Haitian Creole and Lao translators on CORRECT text (no recognition in the
# loop): which open model, if any, could replace MADLAD-400 7B for en->ht,
# ht->en, en->lo and lo->en? Every system gets the same sentences; each set is
# graded blind, side by side, in one round, by one grader.
#
#   python3 htlo.py inputs     # out/inputs.json (FLEURS, September sentences, CMU, optional news clip)
#   (pod)  pod_run.py          # the open models on one 80 GB GPU -> out/mt/<system>/<set>.json
#   python3 htlo.py sol        # GPT-5.6-sol @low on Azure AI Foundry, the cloud bar
#   python3 htlo.py grade      # one blind grading call per chunk of <= 30 sentences
#   python3 htlo.py table      # results.json + the README tables
#
# Environment (nothing secret is printed):
#   GEMINI_API_KEY                 the grader (AI Studio)
#   FOUNDRY_ENDPOINT, FOUNDRY_KEY  Azure AI Foundry resource; FOUNDRY_DEPLOYMENT=gpt-5.6-sol
#   NEWS_DIR                       optional: ref_ht.json / ref_en.json of the five-minute VOA
#                                  Kreyòl clip (../2026-10-continuous-ht); not committed, so its
#                                  sets are skipped without it and only scores are published
import concurrent.futures as cf
import json, os, random, statistics, sys, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SEPT = os.path.join(HERE, "..", "2026-09-model-eval", "sentences")
REAL = os.path.join(HERE, "..", "2026-10-real-voices", "sentences")
OUT = os.path.join(HERE, "out")
GRADER = os.environ.get("GRADER", "gemini-3.1-pro-preview")
NAMES = {"en": "English", "ht": "Haitian Creole", "lo": "Lao"}
FLEURS = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
CHUNK = 30


def J(p):
    return json.load(open(p))


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "htlo-eval"})
    return urllib.request.urlopen(req, timeout=120).read()


def fleurs_text(cfg):
    """FLoRes id -> raw transcription, from FLEURS's test split TSV."""
    rows = {}
    for line in get(f"{FLEURS}/{cfg}/test.tsv").decode("utf-8").splitlines():
        c = line.split("\t")
        if len(c) >= 3:
            rows.setdefault(c[0], c[2].strip())
    return rows


def inputs():
    """Sets: name -> {source, reference (English meaning), src, tgt, public}."""
    S = {}
    en_sept, ht_sept, lo_sept = J(os.path.join(SEPT, "en.json")), J(os.path.join(SEPT, "src_ht.json")), J(os.path.join(SEPT, "src_lo.json"))
    # September: 24 short sentences built to catch critical errors (times, doses, negation).
    S["sept:en-ht"] = {"source": en_sept, "reference": en_sept}
    S["sept:ht-en"] = {"source": ht_sept, "reference": en_sept}
    S["sept:en-lo"] = {"source": en_sept, "reference": en_sept}
    S["sept:lo-en"] = {"source": lo_sept, "reference": en_sept}
    # FLEURS (CC BY 4.0): long news-style FLoRes sentences, professional translations.
    # Not the 30 ids the real-voice rounds used; a fixed seed picks the rest.
    used = set(J(os.path.join(REAL, "fleurs_ids.json")))
    en, lo = fleurs_text("en_us"), fleurs_text("lo_la")
    ids = sorted(i for i in set(en) & set(lo) if i not in used and en[i] and lo[i])
    ids = random.Random(2026).sample(ids, 60)
    S["fleurs:en-lo"] = {"source": [en[i] for i in ids], "reference": [en[i] for i in ids], "ids": ids}
    S["fleurs:lo-en"] = {"source": [lo[i] for i in ids], "reference": [en[i] for i in ids], "ids": ids}
    S["fleurs:en-ht"] = {"source": [en[i] for i in ids[:40]], "reference": [en[i] for i in ids[:40]], "ids": ids[:40]}
    # CMU Haitian Creole speech prompts (read text), English by Gemini 2.5 Pro (../2026-10-real-voices).
    S["cmu:ht-en"] = {"source": J(os.path.join(REAL, "ht.json")), "reference": J(os.path.join(REAL, "meaning_ht.json"))}
    nd = os.environ.get("NEWS_DIR")
    if nd:  # 33 sentences of continuous studio news; Gemini 3.1 Pro's transcript and translation
        ht = [x["ht"] for x in J(os.path.join(nd, "ref_ht.json"))["sentences"]]
        en_n = [x["en"] for x in J(os.path.join(nd, "ref_en.json"))["sentences"]]
        S["news:ht-en"] = {"source": ht, "reference": en_n, "private": True}
        S["news:en-ht"] = {"source": en_n, "reference": en_n, "private": True}
    for k, v in S.items():
        v["src"], v["tgt"] = k.split(":")[1].split("-")
        assert len(v["source"]) == len(v["reference"]), k
    os.makedirs(OUT, exist_ok=True)
    json.dump(S, open(os.path.join(OUT, "inputs.json"), "w"), ensure_ascii=False, indent=1)
    for k, v in S.items():
        print(k, len(v["source"]))


# ---------------------------------------------------------------- cloud bar

def http(url, body=None, headers=None, timeout=300, tries=6):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                               "User-Agent": "htlo-eval", **(headers or {})})
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
    # The translator shootout's LLM prompt (../2026-10-translator-shootout), here for correct text.
    a, b = NAMES[src], NAMES[tgt]
    return (f"Translate this {a} sentence into natural {b}. Keep numbers, names and negation exact. "
            f"Output only the {b}.\nSentence: {s}")


def sol():
    D = J(os.path.join(OUT, "inputs.json"))
    url = os.environ["FOUNDRY_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions"
    name = "gpt-5.6-sol@low"
    os.makedirs(os.path.join(OUT, "mt", name), exist_ok=True)

    def one(s, src, tgt):
        body = {"model": os.environ.get("FOUNDRY_DEPLOYMENT", "gpt-5.6-sol"),
                "messages": [{"role": "user", "content": prompt(s, src, tgt)}], "reasoning_effort": "low"}
        t0 = time.time()
        try:
            j = http(url, body, {"api-key": os.environ["FOUNDRY_KEY"]}, timeout=120)
            out = (j["choices"][0]["message"]["content"] or "").strip()
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            out = ""  # content filter: a blank
        return out, round(time.time() - t0, 3)

    for k, v in D.items():
        p = os.path.join(OUT, "mt", name, k.replace(":", "_") + ".json")
        if os.path.exists(p):
            continue
        with cf.ThreadPoolExecutor(6) as ex:
            r = list(ex.map(lambda s: one(s, v["src"], v["tgt"]), v["source"]))
        json.dump({"out": [x[0] for x in r], "wall_s": [x[1] for x in r]}, open(p, "w"), ensure_ascii=False, indent=1)
        print(name, k, flush=True)


# ---------------------------------------------------------------- grading

def gemini(text, model, max_tokens=65536):
    gen = {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"}
    j = http(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
             {"contents": [{"role": "user", "parts": [{"text": text}]}], "generationConfig": gen},
             {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, timeout=900, tries=8)
    t = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought"))
    return json.loads(t)


def systems_for(k):
    sys_ = {}
    root = os.path.join(OUT, "mt")
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name, k.replace(":", "_") + ".json")
        if os.path.exists(p):
            sys_[name] = J(p)["out"]
    return sys_


def grade_chunk(k, v, lo, hi):
    src, tgt = v["src"], v["tgt"]
    systems = {n: o[lo:hi] for n, o in systems_for(k).items()}
    labels = list(systems)
    random.Random(f"{k}/{lo}").shuffle(labels)
    names = {chr(65 + i): m for i, m in enumerate(labels)}
    blocks = [f"### System {L}\n" + json.dumps(systems[m], ensure_ascii=False) for L, m in names.items()]
    n = hi - lo
    # The translator shootout's (run12) rubric, unchanged.
    p = f"""You are an expert {NAMES[src]}->{NAMES[tgt]} translation evaluator. Grade each system's translation of each of the {n} source sentences (each system gives a list aligned to the sources).
The intended meaning of every sentence is given by its English reference, which is authoritative.

Score each sentence per system:
3 = meaning fully correct and natural; 2 = meaning correct but awkward or unidiomatic; 1 = partly wrong, or something important omitted or added; 0 = wrong meaning, wrong language, garbled, or missing.
Also set critical=true when a number, time, date, dose, amount, negation, or who-did-what is wrong (even if the rest is fine).

Source sentences ({NAMES[src]}):
{json.dumps(v["source"][lo:hi], ensure_ascii=False)}

Reference meaning (English):
{json.dumps(v["reference"][lo:hi], ensure_ascii=False)}

Translations into {NAMES[tgt]}:
{chr(10).join(blocks)}

Return JSON: {{"A": [{{"i": 0, "score": 3, "critical": false, "note": "..."}}, ... {n} items], "B": [...], ...}} with a note of at most 8 words only when score < 3 or critical."""
    for _ in range(4):
        try:
            res = gemini(p, GRADER)
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
        if isinstance(res, dict) and all(isinstance(res.get(L), list) and len(res[L]) >= n - 1 for L in names):
            return {names[L]: [dict(x, i=x["i"] + lo) for x in res[L] if isinstance(x, dict) and "i" in x] for L in names}
    raise SystemExit(f"grader failed on {k} {lo}-{hi}")


def grade():
    D = J(os.path.join(OUT, "inputs.json"))
    gp = os.path.join(OUT, f"grades-{GRADER}.json")
    if os.path.exists(gp):
        sys.exit(f"{gp} exists: one round only (delete it to grade everything again, together)")
    jobs = [(k, v, lo, min(lo + CHUNK, len(v["source"]))) for k, v in D.items()
            for lo in range(0, len(v["source"]), CHUNK)]
    with cf.ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda j: (j[0], grade_chunk(*j)), jobs))
    G = {}
    for k, r in res:
        for name, items in r.items():
            G.setdefault(k, {}).setdefault(name, []).extend(items)
    json.dump(G, open(gp, "w"), ensure_ascii=False, indent=1)
    print("graded", len(jobs), "chunks with", GRADER)


# ---------------------------------------------------------------- table

DIRS = ["en-ht", "ht-en", "en-lo", "lo-en"]


def table():
    D = J(os.path.join(OUT, "inputs.json"))
    G = J(os.path.join(OUT, f"grades-{GRADER}.json"))
    meta = J(os.path.join(HERE, "systems.json"))
    R = {"grader": GRADER, "sets": {}, "directions": {}, "systems": meta}
    names = sorted({n for k in G for n in G[k]})
    for k, v in D.items():
        n = len(v["source"])
        R["sets"][k] = {"n": n, "private_text": bool(v.get("private"))}
        for name in names:
            if name not in G.get(k, {}):
                continue
            g = {x["i"]: x for x in G[k][name]}
            R["sets"][k][name] = {"points": sum(g.get(i, {}).get("score", 0) for i in range(n)),
                                  "critical": sum(1 for x in g.values() if x.get("critical")),
                                  "score": round(sum(g.get(i, {}).get("score", 0) for i in range(n)) / (3 * n), 3)}
    for d in DIRS:
        sets = [k for k in D if k.endswith(":" + d)]
        R["directions"][d] = {"sets": sets, "n": sum(len(D[k]["source"]) for k in sets)}
        for name in names:
            got = [R["sets"][k][name] for k in sets if name in R["sets"][k]]
            if len(got) != len(sets):
                continue  # did not run every set of this direction
            pts, n = sum(x["points"] for x in got), R["directions"][d]["n"]
            R["directions"][d][name] = {"score": round(pts / (3 * n), 3), "critical": sum(x["critical"] for x in got)}
    for name in names:  # speed and memory on our pod; OpenRouter's round trip only as a label
        m = meta.setdefault(name, {})
        pod = m.get("pod_timing", name)
        lat, tok, rt = [], [], []
        for k in D:
            for root, key in (("mt", None), ("timing", None)):
                p = os.path.join(OUT, root, pod, k.replace(":", "_") + ".json")
                if os.path.exists(p):
                    r = J(p)
                    lat += [t for t in r.get("single_s", []) if t]
                    tok += [t for t in r.get("tok_s", []) if t]
            p = os.path.join(OUT, "mt", name, k.replace(":", "_") + ".json")
            if os.path.exists(p):
                rt += [t for t in J(p).get("or_round_trip_s", J(p).get("wall_s", [])) if t]
        pm = None
        for root in ("mt", "timing"):
            if os.path.exists(os.path.join(OUT, root, pod, "meta.json")):
                pm = J(os.path.join(OUT, root, pod, "meta.json"))
        m["pod_p50_s"] = round(statistics.median(lat), 2) if lat else None
        m["pod_p90_s"] = round(sorted(lat)[int(0.9 * (len(lat) - 1))], 2) if lat else None
        m["pod_tok_per_s"] = round(statistics.median(tok), 1) if tok else None
        m["api_round_trip_p50_s"] = round(statistics.median(rt), 2) if rt and "@or" in name or name.startswith("gpt-5.6") and rt else None
        if pm:
            m["vram"] = (f"{pm['weights_gib']:.0f} GiB weights" if pm.get("weights_gib")
                         else f"{pm['vram_peak_mb'] / 1024:.0f} GiB peak" if pm.get("vram_peak_mb") else None)
    json.dump(R, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
    rows = ["| System | Licence | " + " | ".join(DIRS) + " | A100 p50 / p90 s | A100 tok/s | Memory |",
            "|---" * (len(DIRS) + 5) + "|"]
    for name in sorted(names, key=lambda x: -statistics.mean(
            [R["directions"][d].get(x, {}).get("score", 0) for d in DIRS])):
        m = meta.get(name, {})
        cells = []
        for d in DIRS:
            x = R["directions"][d].get(name)
            cells.append(f"{100 * x['score']:.0f} ({x['critical']})" if x else "n/a")
        lat = f"{m.get('pod_p50_s')} / {m.get('pod_p90_s')}" if m.get("pod_p50_s") else "-"
        api = f" (API {m['api_round_trip_p50_s']})" if m.get("api_round_trip_p50_s") else ""
        rows.append(f"| {m.get('label', name)} | {m.get('licence', '?')} | " + " | ".join(cells)
                    + f" | {lat}{api} | {m.get('pod_tok_per_s') or '-'} | {m.get('vram') or '-'} |")
    print("\n".join(rows))
    print()
    srow = ["| Set | n | " + " | ".join(meta.get(x, {}).get("short", x) for x in names) + " |", "|---" * (len(names) + 2) + "|"]
    for k in D:
        srow.append(f"| {k} | {R['sets'][k]['n']} | " + " | ".join(
            f"{100 * R['sets'][k][x]['score']:.0f} ({R['sets'][k][x]['critical']})" if x in R["sets"][k] else "n/a" for x in names) + " |")
    print("\n".join(srow))


if __name__ == "__main__":
    {"inputs": inputs, "sol": sol, "grade": grade, "table": table}[sys.argv[1]]()
