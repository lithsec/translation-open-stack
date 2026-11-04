# Blind side-by-side grade of the four Lao->English arms, per read sentence, against FLEURS's human English.
# Each arm's pieces go to the sentence their midpoint falls in. Gemini (eval key) sees the Lao (FLEURS text), the
# reference English and the four answers under shuffled labels; scores 0-3 each plus a critical-error flag. Two rounds.
#   GEMINI_API_KEY=... python3 -I grade.py OUT.json
import json, os, random, sys, urllib.request, concurrent.futures as cf


GRADER = os.environ.get("GRADER", "gemini-flash-latest")
KEY = os.environ["GEMINI_API_KEY"]
OUT = sys.argv[1]
NAME = {"ja": "Japanese", "vi": "Vietnamese", "zh": "Mandarin Chinese", "ko": "Korean", "hi": "Hindi"}
LANGS = sys.argv[2:]
base_of = lambda l: "mai" if l in ("ja", "vi", "zh") else "azure"

jobs = []
for lang in LANGS:
    c = json.load(open(f"/tmp/rs/chirp/data/asia/{lang}/clip.json"))
    res = json.load(open(f"/tmp/rs/chirp/runs/mt_asia_{lang}.json"))
    arms = ["chirp-gemma", f"{base_of(lang)}-gemma"]
    S = c["sentences"]
    starts = [s["start"] for s in S]
    def sent_of(p):
        mid = (p["start"] + p["end"]) / 2
        return max([i for i in range(len(S)) if starts[i] - 0.5 <= mid] or [0])
    per = {a: [[] for _ in S] for a in arms}
    for a in arms:
        for p in res[a]:
            per[a][sent_of(p)].append(p)
    for i, s in enumerate(S):
        jobs.append({"lang": lang, "pat": lang, "i": i, "lo": c["text"][i], "ref": c["en"][i], "arms": arms,
                     "answers": {a: " ".join(p["en"] for p in per[a][i]).strip() for a in arms},
                     "ready_after_end_s": {a: (round(max(p["done"] for p in per[a][i]) - s["end"], 2) if per[a][i] else None) for a in arms}})

PROMPT = """You are grading live speech translation from {name} into English. The speaker read one sentence aloud; a speech
recogniser transcribed it and a translator produced English, possibly in several pieces joined together.

{name} as read: {lo}
Reference English (human): {ref}

Candidate translations:
{cands}

For each candidate give a score 0-3 for how well a listener would understand what the speaker meant:
3 = full meaning, natural; 2 = main meaning, minor errors or omissions; 1 = partial, important errors or omissions;
0 = wrong, missing or misleading. Also flag "critical": true if it states something false or opposite that a listener
would believe. Content belonging to a neighbouring sentence is not an error by itself; judge only this sentence's meaning.
Answer JSON only: {{"A": {{"score": n, "critical": bool}}, "B": {{"score": n, "critical": bool}}}}"""


def call(job, rnd):
    order = job["arms"][:]
    random.Random(f"{job['pat']}{job['i']}{rnd}").shuffle(order)
    labels = "AB"
    cands = "\n".join(f"{labels[k]}: {job['answers'][a] or '(nothing)'}" for k, a in enumerate(order))
    body = {"contents": [{"role": "user", "parts": [{"text": PROMPT.format(name=NAME[job["lang"]], lo=job["lo"], ref=job["ref"], cands=cands)}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{GRADER}:generateContent",
                                 data=json.dumps(body).encode(), headers={"content-type": "application/json", "x-goog-api-key": KEY})
    for attempt in range(4):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=120))
            g = json.loads(r["candidates"][0]["content"]["parts"][0]["text"])
            return {a: g[labels[k]] for k, a in enumerate(order)}
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]
    return {"error": err}


with cf.ThreadPoolExecutor(6) as ex:
    futs = {(j["pat"], j["i"], rnd): ex.submit(call, j, rnd) for j in jobs for rnd in (1, 2)}
for j in jobs:
    j["grades"] = {rnd: futs[(j["pat"], j["i"], rnd)].result() for rnd in (1, 2)}
json.dump(jobs, open(OUT, "w"), ensure_ascii=False, indent=1)

import statistics as st
for lang in LANGS:
    J = [j for j in jobs if j["lang"] == lang]
    for a in J[0]["arms"]:
        sc = [g[a]["score"] for j in J for g in j["grades"].values() if a in g]
        crit = sum(bool(j["grades"][1].get(a, {}).get("critical")) for j in J)
        ready = sorted(j["ready_after_end_s"][a] for j in J if j["ready_after_end_s"][a] is not None)
        p = lambda v, f: v[min(len(v) - 1, int(f * len(v)))] if v else None
        print(f"{lang} {a:12} quality {100 * sum(sc) / (3 * len(sc)):5.1f}  critical {crit:2d}  ready p50 {p(ready, .5)} p90 {p(ready, .9)}")
