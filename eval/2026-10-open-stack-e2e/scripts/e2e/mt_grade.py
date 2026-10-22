# Error split for the stack runs.
#   python3 -I mt_grade.py <e2e dir> stackmt   # stack translator (sidecar /translate) on transcript and gold
#   python3 -I mt_grade.py <e2e dir> sol       # GPT-5.6-sol @low (Foundry) on the stack transcript
#   python3 -I mt_grade.py <e2e dir> grade     # one blind side-by-side call per direction (GRADER)
#   python3 -I mt_grade.py <e2e dir> table
# Env: STACK_TOKEN (sidecar), FOUNDRY_ENDPOINT/FOUNDRY_KEY/FOUNDRY_DEPLOYMENT, GEMINI_API_KEY. Nothing secret printed.
import concurrent.futures as cf
import json, os, random, statistics, sys, time, urllib.error, urllib.request

E, CMD = sys.argv[1], sys.argv[2]
OUT = os.path.join(E, "out")
CL = os.path.join(E, "clips")
SC = os.environ.get("SIDECAR_URL", "http://localhost:8000")
GRADER = os.environ.get("GRADER", "gemini-pro-latest")
NAMES = {"en": "English", "fr": "French", "es": "Spanish", "ja": "Japanese", "km": "Khmer", "lo": "Lao", "ht": "Haitian Creole"}
S = json.load(open(os.path.join(OUT, "sentences.json")))
REPO = os.path.expanduser("~/dev/translation-open-stack/eval")


def J(p):
    return json.load(open(p))


def reference(d):
    s, t = d.split("-")
    en = J(os.path.join(CL, "en.txt.json"))
    if s == "en" or s in ("es", "ja", "km", "lo"):
        return en
    if s == "fr":
        return J(os.path.join(REPO, "2026-10-translator-shootout", "refs", "meaning_fr.json"))["en"][:20]
    if s == "ht":
        return J(os.path.join(REPO, "2026-10-real-voices", "sentences", "meaning_ht.json"))[:20]


def http(url, body=None, headers=None, timeout=300, tries=6):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "e2e-stack-eval", **(headers or {})})
        try:
            return json.load(urllib.request.urlopen(req, timeout=timeout))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(5 * (attempt + 1))


def save(name, d, outs, extra=None):
    os.makedirs(os.path.join(OUT, "mt", name), exist_ok=True)
    json.dump({"out": outs, **(extra or {})}, open(os.path.join(OUT, "mt", name, f"{d}.json"), "w"), ensure_ascii=False, indent=1)


def stackmt():
    H = {"Authorization": "Bearer " + os.environ["STACK_TOKEN"]}
    for d, v in S.items():
        s, t = d.split("-")
        for name, inp in [("stack-mt:transcript", v["heard_per_sentence"]), ("stack-mt:gold", v["source"])]:
            if os.path.exists(os.path.join(OUT, "mt", name, f"{d}.json")):
                continue
            outs, secs = [], []
            for x in inp:
                if not x.strip():
                    outs.append(""); continue
                r = http(SC + "/translate", {"text": x, "src": s, "tgt": t}, H, timeout=180)
                outs.append(r["text"]); secs.append(r["gpu_s"])
            save(name, d, outs, {"gpu_s": secs})
            print(f"{name} {d}: median {statistics.median(secs or [0]):.2f} s", flush=True)


def sol():
    url = os.environ["FOUNDRY_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions"

    def one(x, s, t):
        if not x.strip():
            return "", {}
        p = (f"Translate this {NAMES[s]} sentence, transcribed from live speech (it may contain recognition errors), "
             f"into natural {NAMES[t]}. Keep numbers, names and negation exact. Output only the {NAMES[t]}.\nSentence: {x}")
        try:
            j = http(url, {"model": os.environ["FOUNDRY_DEPLOYMENT"], "messages": [{"role": "user", "content": p}],
                           "reasoning_effort": "low"}, {"api-key": os.environ["FOUNDRY_KEY"]}, timeout=120)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                return "", {"refused": True}
            raise
        return (j["choices"][0]["message"]["content"] or "").strip(), j.get("usage", {})
    for d, v in S.items():
        if os.path.exists(os.path.join(OUT, "mt", "sol:transcript", f"{d}.json")):
            continue
        s, t = d.split("-")
        with cf.ThreadPoolExecutor(3) as ex:
            rs = list(ex.map(lambda x: one(x, s, t), v["heard_per_sentence"]))
        save("sol:transcript", d, [r[0] for r in rs], {"usage": [r[1] for r in rs]})
        print("sol", d, flush=True)


SYSTEMS = ["live", "stack-mt:transcript", "stack-mt:gold", "sol:transcript"]


def outputs(d):
    o = {"live": S[d]["live_out"]}
    for n in SYSTEMS[1:]:
        p = os.path.join(OUT, "mt", n, f"{d}.json")
        if os.path.exists(p):
            o[n] = J(p)["out"]
    return o


def gemini(text):
    gen = {"temperature": 0, "maxOutputTokens": 65536, "responseMimeType": "application/json"}
    j = http(f"https://generativelanguage.googleapis.com/v1beta/models/{GRADER}:generateContent",
             {"contents": [{"role": "user", "parts": [{"text": text}]}], "generationConfig": gen},
             {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, timeout=600, tries=6)
    t = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought"))
    return json.loads(t), j.get("usageMetadata", {})


def grade_one(d):
    s, t = d.split("-")
    systems = outputs(d)
    labels = list(systems)
    random.Random(d).shuffle(labels)
    names = {chr(65 + i): m for i, m in enumerate(labels)}
    blocks = [f"### System {L}\n" + json.dumps(systems[m], ensure_ascii=False) for L, m in names.items()]
    src = S[d]["source"]
    n = len(src)
    p = f"""You are an expert {NAMES[s]}->{NAMES[t]} translation evaluator. Grade each system's translation of each of the {n} source sentences (each system gives a list aligned to the sources).
The intended meaning of every sentence is given by its English reference, which is authoritative.
Some systems worked from live speech recognition, and a live system's entry for a sentence can also contain its neighbour's words when the speaker did not pause between them: grade whether THIS sentence's meaning is conveyed, and treat an extra neighbouring sentence as harmless.

Score each sentence per system:
3 = meaning fully correct and natural; 2 = meaning correct but awkward or unidiomatic; 1 = partly wrong, or something important omitted or added; 0 = wrong meaning, wrong language, garbled, or missing.
Also set critical=true when a number, time, date, dose, amount, negation, or who-did-what is wrong (even if the rest is fine).

Source sentences ({NAMES[s]}):
{json.dumps(src, ensure_ascii=False)}

Reference meaning (English):
{json.dumps(reference(d), ensure_ascii=False)}

Translations into {NAMES[t]}:
{chr(10).join(blocks)}

Return JSON: {{"A": [{{"i": 0, "score": 3, "critical": false, "note": "..."}}, ... {n} items], "B": [...], ...}} with a note of at most 8 words only when score < 3 or critical."""
    for _ in range(4):
        try:
            res, usage = gemini(p)
        except json.JSONDecodeError:
            continue
        if isinstance(res, dict) and all(isinstance(res.get(L), list) and len(res[L]) >= n - 1 for L in names):
            return d, {"grades": {names[L]: res[L] for L in names}, "usage": usage, "labels": names}
    raise SystemExit(f"grader failed on {d}")


def grade():
    gp = os.path.join(OUT, f"grades-{GRADER}.json")
    if os.path.exists(gp):
        sys.exit(f"{gp} exists")
    with cf.ThreadPoolExecutor(4) as ex:
        G = dict(ex.map(grade_one, list(S)))
    json.dump(G, open(gp, "w"), ensure_ascii=False, indent=1)
    print("graded", len(G))


def table():
    G = J(os.path.join(OUT, f"grades-{GRADER}.json"))
    res = {}
    for d, g in G.items():
        res[d] = {}
        for sys_, rows in g["grades"].items():
            n = len(S[d]["source"])
            sc = sum(r.get("score", 0) for r in rows[:n]) / (3 * n)
            res[d][sys_] = {"score": round(100 * sc), "critical": sum(1 for r in rows[:n] if r.get("critical")),
                            "full": sum(1 for r in rows[:n] if r.get("score") == 3)}
    json.dump(res, open(os.path.join(OUT, "quality.json"), "w"), indent=1)
    for d, r in res.items():
        print(d, "  ".join(f"{k} {v['score']}% ({v['critical']})" for k, v in r.items()))


{"stackmt": stackmt, "sol": sol, "grade": grade, "table": table}[CMD]()
