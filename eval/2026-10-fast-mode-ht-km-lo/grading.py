# Grading, as ../2026-10-voice-rate-compact/grading.py and ../2026-10-concise-conversational:
#   units   fixed meaning units and listener questions, written from the "what was said"
#           English before any translation was seen. Reused: the read clip's from the
#           voice-rate round (UNITS_READ), the meeting excerpt's from the conversational
#           round (UNITS_CONV).
#   judge   per system, blind: each unit conveyed / missing / distorted.
#   qa      a listener answers the questions from the translation alone (never the English),
#           a separate call scores the answers.
#   jobs    the 0-100 blind side-by-side round (../2026-10-es-pt-live-compare/grade.py), all
#           four systems in one call per target and clip: against what was said, and for the
#           read clips also against the written text.
#   contra  phrase systems' chunks per sentence, judged against the finished sentence
#           (../2026-10-simultaneous-phrases/contradictions.py).
#
#   GEMINI_API_KEY=... UNITS_READ=... UNITS_CONV=... python3 -I grading.py judge|qa|jobs|contra ROOT SAID_EN WORK
import concurrent.futures as cf
import importlib.util, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODE, ROOT, SAID_P, WORK = sys.argv[1:5]
spec = importlib.util.spec_from_file_location("grade", os.path.join(HERE, "..", "2026-10-es-pt-live-compare", "grade.py"))
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
NAMES = {"ht": "Haitian Creole", "km": "Khmer", "lo": "Lao"}
SYSTEMS = ["P8-sol", "P8-gemma31", "S-sol", "S-gemma31"]
PATTERNS = ["reg", "irr", "conv"]
TARGETS = ["ht", "km", "lo"]
J = lambda p: json.load(open(p))

WRITTEN = J(os.path.join(ROOT, "clips_reg", "en.txt.json"))
_said = J(SAID_P)
SAID_READ = [_said.get(str(i), x) for i, x in enumerate(WRITTEN)]
SAID_CONV = J(os.path.join(ROOT, "clips_conv", "en.txt.json"))


def said(pattern):
    return SAID_CONV if pattern == "conv" else SAID_READ


def units(pattern):
    return J(os.environ["UNITS_CONV" if pattern == "conv" else "UNITS_READ"])["sentences"]


def seg(name, pattern, t):
    return J(os.path.join(WORK, "seg", name, f"{pattern}_en-{t}.json"))


def ask(prompt, check, tries=4):
    for _ in range(tries):
        try:
            res, _ = G.gemini(prompt)
        except json.JSONDecodeError:
            continue
        if check(res):
            return res
    raise SystemExit("grader failed: " + prompt[:80])


def judge_one(job):
    pattern, t, name = job
    out_p = os.path.join(WORK, "judge", f"{pattern}_en-{t}_{name}.json")
    if os.path.exists(out_p):
        return job, "cached"
    U, SA, tr = units(pattern), said(pattern), seg(name, pattern, t)["out"]
    items = [{"i": i, "english": SA[i], "units": [u["u"] for u in U[i]["units"]], "translation": tr[i]} for i in range(len(SA))]
    p = f"""You are checking a live interpretation from English into {NAMES[t]}, one sentence at a time. For each sentence you get the English, a fixed list of its meaning units, and the {NAMES[t]} interpretation of that sentence. A sentence's interpretation can also carry a few words of a neighbouring sentence; ignore those.

For every unit decide:
- "conveyed": a {NAMES[t]} listener would get this information right (wording may differ);
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
    pattern, t, name = job
    out_p = os.path.join(WORK, "qa", f"{pattern}_en-{t}_{name}.json")
    if os.path.exists(out_p):
        return job, "cached"
    U, SA, tr = units(pattern), said(pattern), seg(name, pattern, t)["out"]
    qs = [{"i": i, "k": k, "q": q["q"]} for i in range(len(SA)) for k, q in enumerate(U[i]["questions"])]
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
    random.Random(f"{pattern}{t}{name}").shuffle(pairs)
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
        for t in TARGETS:
            sy = {n: seg(n, pattern, t)["out"] for n in SYSTEMS}
            out.append({"id": f"SAID:{pattern}:en-{t}", "src": "en", "tgt": t, "source": said(pattern), "reference": said(pattern), "systems": sy})
            if pattern != "conv":
                out.append({"id": f"WRITTEN:{pattern}:en-{t}", "src": "en", "tgt": t, "source": WRITTEN, "reference": WRITTEN, "systems": sy})
    json.dump(out, open(os.path.join(WORK, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(out), "grading jobs")


def contra_jobs():
    out = []
    for pattern in PATTERNS:
        for t in TARGETS:
            sy = {}
            for n in ("P8-sol", "P8-gemma31"):
                sim = J(os.path.join(WORK, "sim", n, f"{pattern}_en-{t}.json"))
                sg = seg(n, pattern, t)
                per = []
                for a, b in sg["spans"]:
                    if a is None:
                        per.append([])
                        continue
                    ks = sorted({sg["chunk_of_char"][c] for c in range(a, min(b, len(sg["chunk_of_char"])))})
                    per.append([sim["chunks"][k]["out"] for k in ks])
                sy[n] = per
            out.append({"id": f"{pattern}:en-{t}", "src": "en", "tgt": t, "source": said(pattern), "reference": said(pattern), "systems": sy})
    json.dump(out, open(os.path.join(WORK, "contra_jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(out), "contradiction jobs")


if __name__ == "__main__":
    if MODE == "jobs":
        jobs()
    elif MODE == "contra":
        contra_jobs()
    else:
        fn = {"judge": judge_one, "qa": qa_one}[MODE]
        todo = [(p, t, n) for p in PATTERNS for t in TARGETS for n in SYSTEMS]
        with cf.ThreadPoolExecutor(6) as ex:
            for job, msg in ex.map(fn, todo):
                print(*job, msg, flush=True)
