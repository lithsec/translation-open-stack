# Grading for deliberately shorter output. A single faithfulness score would mark a
# concise translation down for dropping words that carried no meaning, so four measures:
#
#   units   Before any translation is seen, the grader lists each English sentence's
#           meaning units (facts, names, numbers, dates, negations, qualifiers,
#           who-did-what) from the "what was said" reference, marking which are
#           essential. The list is fixed and reused for every system. Then, blind and
#           per system, each unit is judged conveyed / missing / distorted.
#   qa      1-2 factual questions per sentence, with answers, written from the
#           reference at the same time as the units. A separate call answers them from
#           the translation alone (it never sees the English), and a third call scores
#           those answers against the reference answers. What a listener comes away knowing.
#   jobs    The usual 0-100 blind side-by-side grade with critical errors
#           (../2026-10-es-pt-live-compare/grade.py), all systems in one round per
#           direction, against the written text and against what was said.
#
#   GEMINI_API_KEY=... python3 -I grading.py units CLIPS_ROOT UNSEEN_OUT WORK
#   GEMINI_API_KEY=... python3 -I grading.py judge CLIPS_ROOT UNSEEN_OUT WORK
#   GEMINI_API_KEY=... python3 -I grading.py qa    CLIPS_ROOT UNSEEN_OUT WORK
#   python3 -I grading.py jobs CLIPS_ROOT UNSEEN_OUT WORK  -> WORK/jobs.json for grade.py
#
# The texts graded are the four distinct outputs (phrase or sentence mode, current or
# concise prompt). The speaking rate does not change the words, so V0/V1/V2 share the
# current-prompt text and V3/V4 the concise text.
import concurrent.futures as cf
import importlib.util, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODE, ROOT, UO, WORK = sys.argv[1:5]
spec = importlib.util.spec_from_file_location("grade", os.path.join(HERE, "..", "2026-10-es-pt-live-compare", "grade.py"))
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
NAMES = {"es": "Spanish", "pt": "Portuguese", "fr": "French"}
TEXTS = ["P8-cur", "P8-con", "S-cur", "S-con"]
DIRS = ["en-es", "en-pt", "en-fr"]
PATTERNS = ["reg", "irr"]
J = lambda p: json.load(open(p))

EN = J(os.path.join(ROOT, "clips_reg", "en.txt.json"))
SAID_D = J(os.path.join(UO, "said_en.json"))
SAID = [SAID_D.get(str(i), x) for i, x in enumerate(EN)]
UNITS_P = os.path.join(WORK, "units.json")


def texts(pattern, d):
    return {name: J(os.path.join(WORK, "seg", name, f"{pattern}_{d}.json"))["out"] for name in TEXTS}


def ask(prompt, check, tries=4):
    for _ in range(tries):
        try:
            res, _ = G.gemini(prompt)
        except json.JSONDecodeError:
            continue
        if check(res):
            return res
    raise SystemExit("grader failed: " + prompt[:80])


def units():
    if os.path.exists(UNITS_P):
        print("units cached")
        return
    p = f"""For each of these {len(SAID)} English sentences (what a speaker actually said), list its meaning units: the facts, names, numbers, dates, negations, qualifiers (e.g. "almost", "most", "only") and who-did-what relations a faithful interpretation must carry. One unit per atomic piece of information, short, in English. Mark a unit essential=false only when it is a minor detail a listener could miss without misunderstanding the sentence.
Also write 1 or 2 factual questions per sentence that a listener who understood it could answer, each with a short reference answer. Questions must be answerable from the sentence alone and should target its key information (numbers, names, who-did-what, negation).

Sentences:
{json.dumps(SAID, ensure_ascii=False, indent=0)}

Return JSON: {{"sentences": [{{"i": 0, "units": [{{"u": "...", "essential": true}}, ...], "questions": [{{"q": "...", "a": "..."}}, ...]}}, ... {len(SAID)} items]}}"""
    res = ask(p, lambda r: isinstance(r, dict) and len(r.get("sentences", [])) == len(SAID))
    json.dump(res, open(UNITS_P, "w"), ensure_ascii=False, indent=1)
    print("units:", sum(len(s["units"]) for s in res["sentences"]), "questions:", sum(len(s["questions"]) for s in res["sentences"]))


def judge_one(job):
    pattern, d, name = job
    t = d.split("-")[1]
    out_p = os.path.join(WORK, "judge", f"{pattern}_{d}_{name}.json")
    if os.path.exists(out_p):
        return job, "cached"
    U = J(UNITS_P)["sentences"]
    tr = texts(pattern, d)[name]
    items = [{"i": i, "english": SAID[i], "units": [u["u"] for u in U[i]["units"]], "translation": tr[i]} for i in range(len(SAID))]
    p = f"""You are checking a live interpretation from English into {NAMES[t]}, one sentence at a time. For each sentence you get the English, a fixed list of its meaning units, and the {NAMES[t]} interpretation of that sentence (it may be shorter than a literal translation on purpose; shorter is fine). A sentence's interpretation can also carry a few words of a neighbouring sentence; ignore those.

For every unit decide:
- "conveyed": a {NAMES[t]} listener would get this information right (wording may differ, it may be condensed);
- "missing": the information is not there;
- "distorted": the interpretation says something different or wrong about it (wrong number, name, negation, qualifier, or who-did-what).

Sentences:
{json.dumps(items, ensure_ascii=False, indent=0)}

Return JSON: {{"sentences": [{{"i": 0, "labels": ["conveyed", "missing", ...one per unit, in order]}}, ... {len(items)} items]}}"""
    ok = lambda r: isinstance(r, dict) and len(r.get("sentences", [])) == len(items) and all(
        len(s.get("labels", [])) == len(U[s["i"]]["units"]) for s in r["sentences"])
    res = ask(p, ok)
    os.makedirs(os.path.dirname(out_p), exist_ok=True)
    json.dump(res, open(out_p, "w"), ensure_ascii=False, indent=1)
    return job, "judged"


def qa_one(job):
    pattern, d, name = job
    t = d.split("-")[1]
    out_p = os.path.join(WORK, "qa", f"{pattern}_{d}_{name}.json")
    if os.path.exists(out_p):
        return job, "cached"
    U = J(UNITS_P)["sentences"]
    tr = texts(pattern, d)[name]
    qs = [{"i": i, "k": k, "q": q["q"]} for i in range(len(SAID)) for k, q in enumerate(U[i]["questions"])]
    # the listener: the interpretation only, as a numbered transcript; never the English
    transcript = "\n".join(f"[{i}] {x}" for i, x in enumerate(tr))
    p1 = f"""Here is a transcript of what a {NAMES[t]} interpreter said aloud, sentence by sentence (numbered). Answer each question using ONLY this transcript. Question i refers to transcript sentence [i] (its neighbours may help). Answer briefly in English. If the transcript does not say, answer "not stated". Do not use outside knowledge.

Transcript ({NAMES[t]}):
{transcript}

Questions:
{json.dumps(qs, ensure_ascii=False, indent=0)}

Return JSON: {{"answers": [{{"i": 0, "k": 0, "answer": "..."}}, ... one per question]}}"""
    ans = ask(p1, lambda r: isinstance(r, dict) and len(r.get("answers", [])) == len(qs))["answers"]
    key = {(a["i"], a["k"]): a["answer"] for a in ans}
    pairs = [{"i": q["i"], "k": q["k"], "question": q["q"], "reference_answer": U[q["i"]]["questions"][q["k"]]["a"],
              "listener_answer": key.get((q["i"], q["k"]), "not stated")} for q in qs]
    random.Random(f"{pattern}{d}{name}").shuffle(pairs)
    p2 = f"""Score each listener answer against the reference answer. "correct" = same information (wording may differ); "partial" = right in part, or vaguer but not wrong; "wrong" = contradicts the reference; "unanswered" = "not stated" or no real answer.

{json.dumps(pairs, ensure_ascii=False, indent=0)}

Return JSON: {{"scores": [{{"i": 0, "k": 0, "score": "correct"}}, ... one per item]}}"""
    sc = ask(p2, lambda r: isinstance(r, dict) and len(r.get("scores", [])) == len(pairs))["scores"]
    os.makedirs(os.path.dirname(out_p), exist_ok=True)
    json.dump({"pairs": pairs, "scores": sc}, open(out_p, "w"), ensure_ascii=False, indent=1)
    return job, "scored"


def jobs():
    out = []
    for pattern in PATTERNS:
        for d in DIRS:
            t = d.split("-")[1]
            sy = texts(pattern, d)
            out.append({"id": f"WRITTEN:{pattern}:{d}", "src": "en", "tgt": t, "source": EN, "reference": EN, "systems": sy})
            out.append({"id": f"SAID:{pattern}:{d}", "src": "en", "tgt": t, "source": SAID, "reference": SAID, "systems": sy})
    json.dump(out, open(os.path.join(WORK, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(out), "grading jobs")


if __name__ == "__main__":
    if MODE == "units":
        units()
    elif MODE == "jobs":
        jobs()
    else:
        fn = {"judge": judge_one, "qa": qa_one}[MODE]
        todo = [(p, d, n) for p in PATTERNS for d in DIRS for n in TEXTS]
        with cf.ThreadPoolExecutor(6) as ex:
            for job, msg in ex.map(fn, todo):
                print(*job, msg, flush=True)
