# Copied from ../2026-10-language-short-check/grade.py (German, Russian, Romanian, Spanish and French added). Blind side-by-side grading, the e2e-stack grader (mt_grade.py grade_one: same rubric and prompt,
# gemini-pro-latest on AI Studio, temperature 0, systems shuffled under letters, one call per direction).
#   GEMINI_API_KEY=... python3 -I grade.py jobs.json grades.json
# jobs: [{"id","src","tgt","source":[...],"reference":[...],"systems":{name:[...]}}]
import concurrent.futures as cf
import json, os, random, sys, time, urllib.error, urllib.request

GRADER = os.environ.get("GRADER", "gemini-pro-latest")
NAMES = {"en": "English", "vi": "Vietnamese", "fa": "Persian", "kea": "Cape Verdean Creole", "zh": "Mandarin Chinese",
         "yue": "Cantonese", "ar": "Arabic", "sw": "Swahili", "fil": "Filipino (Tagalog)", "uk": "Ukrainian", "tw": "Twi (Akan)",
         "de": "German", "ru": "Russian", "ro": "Romanian", "es": "Spanish", "fr": "French"}


def http(url, body, headers, timeout=600, tries=6):
    data = json.dumps(body).encode()
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
        try:
            return json.load(urllib.request.urlopen(req, timeout=timeout))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(5 * (attempt + 1))


def gemini(text):
    gen = {"temperature": 0, "maxOutputTokens": 65536, "responseMimeType": "application/json"}
    j = http(f"https://generativelanguage.googleapis.com/v1beta/models/{GRADER}:generateContent",
             {"contents": [{"role": "user", "parts": [{"text": text}]}], "generationConfig": gen},
             {"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    t = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought"))
    return json.loads(t), j.get("usageMetadata", {})


def grade_one(job):
    s, t = job["src"], job["tgt"]
    systems = job["systems"]
    labels = list(systems)
    random.Random(job["id"]).shuffle(labels)
    names = {chr(65 + i): m for i, m in enumerate(labels)}
    blocks = [f"### System {L}\n" + json.dumps(systems[m], ensure_ascii=False) for L, m in names.items()]
    src = job["source"]
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
{json.dumps(job["reference"], ensure_ascii=False)}

Translations into {NAMES[t]}:
{chr(10).join(blocks)}

Return JSON: {{"A": [{{"i": 0, "score": 3, "critical": false, "note": "..."}}, ... {n} items], "B": [...], ...}} with a note of at most 8 words only when score < 3 or critical."""
    for _ in range(4):
        try:
            res, usage = gemini(p)
        except json.JSONDecodeError:
            continue
        if isinstance(res, dict) and all(isinstance(res.get(L), list) and len(res[L]) >= n - 1 for L in names):
            print("graded", job["id"], usage.get("promptTokenCount"), usage.get("candidatesTokenCount"), usage.get("thoughtsTokenCount"), flush=True)
            return job["id"], {"grades": {names[L]: res[L] for L in names}, "usage": usage, "labels": names}
    raise SystemExit(f"grader failed on {job['id']}")


def main():
    jobs = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    G = json.load(open(out)) if os.path.exists(out) else {}
    todo = [j for j in jobs if j["id"] not in G]
    with cf.ThreadPoolExecutor(4) as ex:
        for k, v in ex.map(grade_one, todo):
            G[k] = v
            json.dump(G, open(out, "w"), ensure_ascii=False, indent=1)
    print("graded", len(G))


if __name__ == "__main__":
    main()
