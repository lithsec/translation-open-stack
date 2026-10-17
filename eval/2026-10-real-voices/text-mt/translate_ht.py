# Haitian Creole -> English with TEXT translators, on two inputs:
#   gladia: Gladia's live transcript of the real speakers, regrouped into the
#           30 read sentences by where each piece fell in the clip (so the
#           translator sees whole sentences, not Gladia's 97 fragments);
#   gold:   the text the speakers actually read (the translator's ceiling).
# Graded blind with the same grader and prompt as judge.py.
#
#   GOOGLE_CLOUD_PROJECT=... python3 text-mt/translate_ht.py
#   GEMINI_API_KEY=... EVAL_BACKEND=aistudio python3 text-mt/translate_ht.py
#     (no gcloud: Gemini through AI Studio. Gemini 2.5 Pro is closed to new
#     AI Studio keys, so the grader is GRADER, default gemini-3.1-pro-preview,
#     and its grades go to grades-<grader>.json: compare within one run only.
#     Translators needing Google Cloud must already be in out/.)
#   INPUTS=omnilingual,gold limits which transcripts are translated and graded.
# NOTE: the English references were written by Gemini 2.5 Pro, so Gemini
# translators may be flattered; the grade says so.
import json, os, random, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "..", "2026-09-model-eval", "scripts"))
import vertex  # noqa: E402
import urllib.error


AISTUDIO = os.environ.get("EVAL_BACKEND") == "aistudio"
GRADER = os.environ.get("GRADER") or ("gemini-3.1-pro-preview" if AISTUDIO else "gemini-2.5-pro")


def aistudio(prompt, model="gemini-2.5-pro", json_out=True, thinking=None):
    import time
    import urllib.request
    gen = {"temperature": 0, "maxOutputTokens": 32000, **({"responseMimeType": "application/json"} if json_out else {}),
           **({"thinkingConfig": {"thinkingLevel": thinking}} if thinking else {})}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen}).encode(),
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"], "Content-Type": "application/json"})
    for attempt in range(8):
        try:
            j = json.load(urllib.request.urlopen(req, timeout=300)); break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 503) or attempt == 7: raise
            time.sleep(10 * (attempt + 1))
    t = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought"))
    return json.loads(t) if json_out else t


def gemini(*a, thinking=None, **k):
    # gcloud tokens last an hour and vertex.py keeps the first one: refresh on 401.
    # An answer with no content (Gemini declined, e.g. Chirp's 7,000-character
    # looped "sentence") counts as a blank translation.
    if AISTUDIO:
        try:
            return aistudio(*a, thinking=thinking, **k)
        except KeyError:
            return ""
    if thinking:
        raise SystemExit("thinking levels need EVAL_BACKEND=aistudio")
    try:
        return vertex.gemini(*a, **k)
    except KeyError:
        return ""
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        vertex._tok = None
        return vertex.gemini(*a, **k)
OUT = os.path.join(HERE, "text-mt", "out")
os.makedirs(OUT, exist_ok=True)

src = json.load(open(os.path.join(HERE, "sentences", "ht.json")))
ref = json.load(open(os.path.join(HERE, "sentences", "meaning_ht.json")))
marks = json.load(open(os.path.join(HERE, "audio", "ht.json")))["sentences"]
finals = json.load(open(os.path.join(HERE, "out", "stt-gladia", "ht.json")))["finals"]
groups = [[] for _ in marks]
for f in finals:
    mid = (f["offsetMs"] + f["durationMs"] / 2) / 1000
    k = min(range(len(marks)), key=lambda i: 0 if marks[i]["start"] <= mid <= marks[i]["end"] else min(abs(mid - marks[i]["start"]), abs(mid - marks[i]["end"])))
    groups[k].append(f["text"])
gladia = [" ".join(g) for g in groups]


def split_like(text, sents):
    """A transcript with no sentence breaks (the stack's), cut where the read
    sentences end: align it to the read text character by character and map
    each sentence's end across. Fair while the transcript is close (6% CER)."""
    import difflib
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


omni = split_like(json.load(open(os.path.join(HERE, "out", "stack", "ht-en.json")))["heard"], src)
# Only transcripts good enough to be worth translating (the user's call,
# 2026-10-17): Gladia (19% CER, words wrong) and Gemini Live (49%, heard as
# French) are left out.
inputs = {"gold": src, "omnilingual": omni}
_pro = os.path.join(OUT, "stt__gemini-2.5-pro.json")
if os.path.exists(_pro):
    inputs["gemini-2.5-pro-stt"] = json.load(open(_pro))
_chirp = os.path.join(OUT, "stt__chirp_3.json")
if os.path.exists(_chirp):
    inputs["chirp3"] = json.load(open(_chirp))


def gem(model, sents, context, thinking=None):
    """One call per sentence, as a live pipeline would; with context, the two
    sentences before it are shown (already spoken) to resolve pronouns etc."""
    import concurrent.futures as cf

    def one(i):
        s = sents[i]
        prev = " ".join(sents[max(0, i - 2):i]) if context else ""
        p = ("Translate this Haitian Creole sentence, transcribed from live speech (it may contain recognition errors), "
             "into natural English. Keep numbers, names and negation exact. Output only the English.\n"
             + (f"Earlier sentences, for context only (do not translate): {prev}\n" if prev else "")
             + f"Sentence: {s}")
        return gemini(p, model=model, json_out=False, thinking=thinking).strip() if s.strip() else ""
    with cf.ThreadPoolExecutor(6) as ex:
        return list(ex.map(one, range(len(sents))))


def google_nmt(sents):
    """Cloud Translation v3, the standard model (its LLM model refuses ht->en)."""
    import urllib.request
    url = f"https://translation.googleapis.com/v3/projects/{vertex.project()}/locations/us-central1:translateText"
    body = {"contents": [s or "-" for s in sents], "sourceLanguageCode": "ht", "targetLanguageCode": "en",
            "model": f"projects/{vertex.project()}/locations/us-central1/models/general/nmt"}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {vertex.token()}", "Content-Type": "application/json", "x-goog-user-project": vertex.project()})
    out = [t["translatedText"] for t in json.load(urllib.request.urlopen(req, timeout=120))["translations"]]
    return [o if s.strip() else "" for o, s in zip(out, sents)]


def azure_translator(sents):
    """Azure Translator (text; 'no-trace': it keeps nothing), key and region
    from AZURE_TRANSLATOR_KEY1 / AZURE_TRANSLATOR_REGION (default eastus)."""
    import urllib.request
    key = os.environ["AZURE_TRANSLATOR_KEY1"]
    region = os.environ.get("AZURE_TRANSLATOR_REGION", "eastus")
    req = urllib.request.Request(
        "https://api.cognitive.microsofttranslator.com/translate?api-version=3.0&from=ht&to=en",
        data=json.dumps([{"Text": s or "-"} for s in sents]).encode(),
        headers={"Ocp-Apim-Subscription-Key": key, "Ocp-Apim-Subscription-Region": region, "Content-Type": "application/json"})
    out = [r["translations"][0]["text"] for r in json.load(urllib.request.urlopen(req, timeout=120))]
    return [o if s.strip() else "" for o, s in zip(out, sents)]


TRANSLATORS = {
    "google-translate": google_nmt,
    **({"azure-translator": azure_translator} if os.environ.get("AZURE_TRANSLATOR_KEY1") else {}),
    "gemini-2.5-flash": lambda s: gem("gemini-2.5-flash", s, False),
    "gemini-2.5-flash+ctx": lambda s: gem("gemini-2.5-flash", s, True),
    "gemini-3.5-flash": lambda s: gem("gemini-3.5-flash", s, False),
    "gemini-3.5-flash-lite": lambda s: gem("gemini-3.5-flash-lite", s, False),
    # Thinking "low", as the app runs them (AI Studio only).
    **({f"{m}@low": (lambda m: lambda s: gem(m, s, False, "low"))(m)
        for m in ("gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash")} if AISTUDIO else {}),
    **({"gemini-3.5-flash@medium": lambda s: gem("gemini-3.5-flash", s, False, "medium")} if AISTUDIO else {}),
}
if os.environ.get("INPUTS"):
    inputs = {k: v for k, v in inputs.items() if k in os.environ["INPUTS"].split(",")}

for inp, sents in inputs.items():
    for name, fn in TRANSLATORS.items():
        p = os.path.join(OUT, f"{inp}__{name}.json")
        if not os.path.exists(p):
            json.dump(fn(sents), open(p, "w"), ensure_ascii=False, indent=1)
            print("translated", inp, name, flush=True)

# Blind grade, one call per input so systems on the same input are compared side by side.
results = {}
for inp in inputs:
    systems = {n: json.load(open(os.path.join(OUT, f"{inp}__{n}.json"))) for n in TRANSLATORS}
    labels = list(systems); random.Random(inp).shuffle(labels)
    names = {chr(65 + i): m for i, m in enumerate(labels)}
    blocks = [f"### System {L}\n" + json.dumps(systems[m], ensure_ascii=False) for L, m in names.items()]
    prompt = f"""You are an expert Haitian Creole->English translation evaluator. Grade each system's translation of each of the {len(src)} source sentences (each system gives a list aligned to the sources).
The intended meaning of every sentence is given by its English reference, which is authoritative.

Score each sentence per system:
3 = meaning fully correct and natural; 2 = meaning correct but awkward or unidiomatic; 1 = partly wrong, or something important omitted or added; 0 = wrong meaning, wrong language, garbled, or missing.
Also set critical=true when a number, time, date, dose, amount, negation, or who-did-what is wrong (even if the rest is fine).

Source sentences (Haitian Creole):
{json.dumps(src, ensure_ascii=False)}

Reference meaning (English):
{json.dumps(ref, ensure_ascii=False)}

Translations into English:
{chr(10).join(blocks)}

Return JSON: {{"A": [{{"i": 0, "score": 3, "critical": false, "note": "..."}}, ... {len(src)} items], "B": [...], ...}} with a note of at most 8 words only when score < 3 or critical."""
    for _ in range(3):  # the grader once answered with a bare list, once ran out of room: ask again
        try:
            res = gemini(prompt, model=GRADER)
        except json.JSONDecodeError:
            continue
        if isinstance(res, dict) and all(isinstance(res.get(L), list) for L in names):
            break
    for L, m in names.items():
        g = {x["i"]: x for x in res.get(L, [])}
        full = sum(1 for i in range(len(src)) if g.get(i, {}).get("score") == 3)
        mean = sum(g.get(i, {}).get("score", 0) for i in range(len(src))) / (3 * len(src))
        crit = sum(1 for x in g.values() if x.get("critical"))
        results[f"{inp}__{m}"] = {"fully_correct": round(full / len(src), 3), "mean_score": round(mean, 3), "critical": crit}
json.dump(results, open(os.path.join(OUT, "grades.json" if GRADER == "gemini-2.5-pro" else f"grades-{GRADER}.json"), "w"), indent=1)
print("grader:", GRADER)
for k, v in sorted(results.items()):
    print(f"{k:40s} fully correct {v['fully_correct']:.0%}  mean {v['mean_score']:.0%}  critical {v['critical']}")
