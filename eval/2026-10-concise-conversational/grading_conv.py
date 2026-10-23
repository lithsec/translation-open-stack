# Grading for the conversational round, as ../2026-10-voice-rate-compact/grading.py, generalised to
# three source languages. The source truth is what was said (witness transcripts); for Spanish and
# French sources the English meaning reference is a Gemini translation of what was said, made once
# before any system output is seen (ref_<lang>.json).
#   GEMINI_API_KEY=... python3 -I grading_conv.py refs|units|judge|qa|jobs CLIPS WORK
import concurrent.futures as cf, importlib.util, json, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
MODE, CLIPS, WORK = sys.argv[1:4]
spec = importlib.util.spec_from_file_location("grade", os.path.join(HERE, "..", "2026-10-es-pt-live-compare", "grade.py"))
G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)
NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French"}
TEXTS = ["P8-cur", "P8-con", "S-cur", "S-con"]
DIRS = ["en-es", "en-pt", "en-fr", "es-en", "fr-en"]
J = lambda p: json.load(open(p))
SAID = {l: J(os.path.join(CLIPS, f"{l}.txt.json")) for l in ("en", "es", "fr")}
REF_P = lambda l: os.path.join(WORK, f"ref_{l}.json")
UNITS_P = lambda l: os.path.join(WORK, f"units_{l}.json")

def ask(prompt, check, tries=4):
    for _ in range(tries):
        try:
            res, _ = G.gemini(prompt)
        except json.JSONDecodeError:
            continue
        if check(res):
            return res
    raise SystemExit("grader failed: " + prompt[:80])

def ref(l):
    return SAID["en"] if l == "en" else J(REF_P(l))

def texts(d):
    return {n: J(os.path.join(WORK, "seg", n, f"conv_{d}.json"))["out"] for n in TEXTS}

def refs():
    for l in ("es", "fr"):
        if os.path.exists(REF_P(l)): continue
        src = SAID[l]
        p = f"""Translate each of these {len(src)} {NAMES[l]} sentences (a verbatim transcript of spontaneous speech) into faithful English. Keep every fact, name, number, negation and qualifier; render hesitations and repairs only where they carry meaning. One English entry per sentence, same order.

{json.dumps(src, ensure_ascii=False, indent=0)}

Return JSON: {{"english": ["...", ... exactly {len(src)} strings]}}"""
        r = ask(p, lambda r: isinstance(r, dict) and len(r.get("english", [])) == len(src))
        json.dump(r["english"], open(REF_P(l), "w"), ensure_ascii=False, indent=1)
        print("ref", l)

def units():
    for l in ("en", "es", "fr"):
        if os.path.exists(UNITS_P(l)): continue
        R = ref(l)
        p = f"""For each of these {len(R)} English sentences (what a speaker actually said in spontaneous speech, in English or translated into English), list its meaning units: the facts, names, numbers, dates, negations, qualifiers (e.g. "almost", "most", "only") and who-did-what relations a faithful interpretation must carry. One unit per atomic piece of information, short, in English. Filler, hesitations and false starts are not units. Mark a unit essential=false only when it is a minor detail a listener could miss without misunderstanding the sentence. A sentence that is only filler or a backchannel may have no units.
Also write 1 or 2 factual questions per sentence that a listener who understood it could answer, each with a short reference answer (none for a sentence with no units). Questions must be answerable from the sentence alone and should target its key information.

Sentences:
{json.dumps(R, ensure_ascii=False, indent=0)}

Return JSON: {{"sentences": [{{"i": 0, "units": [{{"u": "...", "essential": true}}, ...], "questions": [{{"q": "...", "a": "..."}}, ...]}}, ... {len(R)} items]}}"""
        res = ask(p, lambda r: isinstance(r, dict) and len(r.get("sentences", [])) == len(R))
        json.dump(res, open(UNITS_P(l), "w"), ensure_ascii=False, indent=1)
        print("units", l, sum(len(s["units"]) for s in res["sentences"]), "questions", sum(len(s["questions"]) for s in res["sentences"]))

def judge_one(job):
    d, name = job; s, t = d.split("-")
    out_p = os.path.join(WORK, "judge", f"{d}_{name}.json")
    if os.path.exists(out_p): return job, "cached"
    U = J(UNITS_P(s))["sentences"]; R = ref(s); tr = texts(d)[name]
    items = [{"i": i, "source_meaning_in_english": R[i], "units": [u["u"] for u in U[i]["units"]], "interpretation": tr[i]} for i in range(len(R))]
    p = f"""You are checking a live interpretation from {NAMES[s]} into {NAMES[t]}, one sentence at a time. For each sentence you get the speaker's meaning (in English), a fixed list of its meaning units, and the {NAMES[t]} interpretation of that sentence (it may be shorter than a literal translation on purpose, and drop filler; shorter is fine). A sentence's interpretation can also carry a few words of a neighbouring sentence; ignore those.

For every unit decide:
- "conveyed": a {NAMES[t]} listener would get this information right (wording may differ, it may be condensed);
- "missing": the information is not there;
- "distorted": the interpretation says something different or wrong about it (wrong number, name, negation, qualifier, or who-did-what).

Sentences:
{json.dumps(items, ensure_ascii=False, indent=0)}

Return JSON: {{"sentences": [{{"i": 0, "labels": ["conveyed", "missing", ...one per unit, in order]}}, ... {len(items)} items]}}"""
    ok = lambda r: isinstance(r, dict) and len(r.get("sentences", [])) == len(items) and all(len(x.get("labels", [])) == len(U[x["i"]]["units"]) for x in r["sentences"])
    res = ask(p, ok)
    os.makedirs(os.path.dirname(out_p), exist_ok=True); json.dump(res, open(out_p, "w"), ensure_ascii=False, indent=1)
    return job, "judged"

def qa_one(job):
    d, name = job; s, t = d.split("-")
    out_p = os.path.join(WORK, "qa", f"{d}_{name}.json")
    if os.path.exists(out_p): return job, "cached"
    U = J(UNITS_P(s))["sentences"]; tr = texts(d)[name]
    qs = [{"i": i, "k": k, "q": q["q"]} for i in range(len(U)) for k, q in enumerate(U[i]["questions"])]
    transcript = "\n".join(f"[{i}] {x}" for i, x in enumerate(tr))
    p1 = f"""Here is a transcript of what a {NAMES[t]} interpreter said aloud, sentence by sentence (numbered). Answer each question using ONLY this transcript. Question i refers to transcript sentence [i] (its neighbours may help). Answer briefly in English. If the transcript does not say, answer "not stated". Do not use outside knowledge.

Transcript ({NAMES[t]}):
{transcript}

Questions:
{json.dumps(qs, ensure_ascii=False, indent=0)}

Return JSON: {{"answers": [{{"i": 0, "k": 0, "answer": "..."}}, ... one per question]}}"""
    ans = ask(p1, lambda r: isinstance(r, dict) and len(r.get("answers", [])) == len(qs))["answers"]
    key = {(a["i"], a["k"]): a["answer"] for a in ans}
    pairs = [{"i": q["i"], "k": q["k"], "question": q["q"], "reference_answer": U[q["i"]]["questions"][q["k"]]["a"], "listener_answer": key.get((q["i"], q["k"]), "not stated")} for q in qs]
    random.Random(f"{d}{name}").shuffle(pairs)
    p2 = f"""Score each listener answer against the reference answer. "correct" = same information (wording may differ); "partial" = right in part, or vaguer but not wrong; "wrong" = contradicts the reference; "unanswered" = "not stated" or no real answer.

{json.dumps(pairs, ensure_ascii=False, indent=0)}

Return JSON: {{"scores": [{{"i": 0, "k": 0, "score": "correct"}}, ... one per item]}}"""
    sc = ask(p2, lambda r: isinstance(r, dict) and len(r.get("scores", [])) == len(pairs))["scores"]
    os.makedirs(os.path.dirname(out_p), exist_ok=True); json.dump({"pairs": pairs, "scores": sc}, open(out_p, "w"), ensure_ascii=False, indent=1)
    return job, "scored"

def jobs():
    out = []
    for d in DIRS:
        s, t = d.split("-")
        out.append({"id": f"SAID:conv:{d}", "src": s, "tgt": t, "source": SAID[s], "reference": ref(s), "systems": texts(d)})
    json.dump(out, open(os.path.join(WORK, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(out), "grading jobs")

if __name__ == "__main__":
    if MODE in ("refs", "units", "jobs"):
        {"refs": refs, "units": units, "jobs": jobs}[MODE]()
    else:
        fn = {"judge": judge_one, "qa": qa_one}[MODE]
        with cf.ThreadPoolExecutor(6) as ex:
            for job, msg in ex.map(fn, [(d, n) for d in DIRS for n in TEXTS]): print(*job, msg, flush=True)
