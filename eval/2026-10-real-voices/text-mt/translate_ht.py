# Haitian Creole -> English with TEXT translators, on two inputs:
#   gladia: Gladia's live transcript of the real speakers, regrouped into the
#           30 read sentences by where each piece fell in the clip (so the
#           translator sees whole sentences, not Gladia's 97 fragments);
#   gold:   the text the speakers actually read (the translator's ceiling).
# Graded blind with the same grader and prompt as judge.py.
#
#   GOOGLE_CLOUD_PROJECT=... python3 text-mt/translate_ht.py
# NOTE: the English references were written by Gemini 2.5 Pro, so Gemini
# translators may be flattered; the grade says so.
import json, os, random, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "..", "2026-09-model-eval", "scripts"))
import vertex  # noqa: E402
import urllib.error


def gemini(*a, **k):
    # gcloud tokens last an hour and vertex.py keeps the first one: refresh on 401.
    try:
        return vertex.gemini(*a, **k)
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
inputs = {"gold": src, "gladia": gladia, "omnilingual": omni}


def gem(model, sents, context):
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
        return gemini(p, model=model, json_out=False).strip() if s.strip() else ""
    with cf.ThreadPoolExecutor(6) as ex:
        return list(ex.map(one, range(len(sents))))


TRANSLATORS = {
    "gemini-2.5-flash": lambda s: gem("gemini-2.5-flash", s, False),
    "gemini-2.5-flash+ctx": lambda s: gem("gemini-2.5-flash", s, True),
    "gemini-2.5-flash-lite": lambda s: gem("gemini-2.5-flash-lite", s, False),
}

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

Return JSON: {{"A": [{{"i": 0, "score": 3, "critical": false, "note": "..."}}, ... {len(src)} items], "B": [...], ...}} with a short note only when score < 3 or critical."""
    res = gemini(prompt)
    for L, m in names.items():
        g = {x["i"]: x for x in res.get(L, [])}
        full = sum(1 for i in range(len(src)) if g.get(i, {}).get("score") == 3)
        mean = sum(g.get(i, {}).get("score", 0) for i in range(len(src))) / (3 * len(src))
        crit = sum(1 for x in g.values() if x.get("critical"))
        results[f"{inp}__{m}"] = {"fully_correct": round(full / len(src), 3), "mean_score": round(mean, 3), "critical": crit}
json.dump(results, open(os.path.join(OUT, "grades.json"), "w"), indent=1)
for k, v in sorted(results.items()):
    print(f"{k:40s} fully correct {v['fully_correct']:.0%}  mean {v['mean_score']:.0%}  critical {v['critical']}")
