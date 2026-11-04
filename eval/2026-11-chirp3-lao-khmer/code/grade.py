# Blind side-by-side grade of the four Lao->English arms, per read sentence, against FLEURS's human English.
# Each arm's pieces go to the sentence their midpoint falls in. Gemini (eval key) sees the Lao (FLEURS text), the
# reference English and the four answers under shuffled labels; scores 0-3 each plus a critical-error flag. Two rounds.
#   GEMINI_API_KEY=... python3 -I grade.py OUT.json
import json, os, random, sys, urllib.request, concurrent.futures as cf

sys.path.insert(0, "/Users/sstone/dev/translation-open-stack/eval/2026-10-real-voices")
import fetch_audio as fa  # noqa: E402

GRADER = os.environ.get("GRADER", "gemini-flash-latest")
KEY = os.environ["GEMINI_API_KEY"]
OUT = sys.argv[1]
en_rows = fa.fleurs_rows("en_us")
ARMS = ["chirp-sol", "chirp-gemma", "omni-sol", "omni-gemma"]

jobs = []
for pat in ("reg", "irr"):
    lay = json.load(open(f"/tmp/rs/chirp/data/oct_lo/{pat}/lo.json"))
    lo_txt = json.load(open(f"/tmp/rs/chirp/data/oct_lo/{pat}/lo.txt.json"))
    res = json.load(open(f"/tmp/rs/chirp/runs/mt_lo_{pat}.json"))
    S = lay["sentences"]
    starts = [s["start"] for s in S] + [1e9]
    def sent_of(p):
        mid = (p["start"] + p["end"]) / 2
        return max(i for i in range(len(S)) if starts[i] - 0.5 <= mid) if mid >= starts[0] - 0.5 else 0
    per = {a: [[] for _ in S] for a in ARMS}
    for a in ARMS:
        for p in res[a]:
            per[a][sent_of(p)].append(p)
    for i, s in enumerate(S):
        ref = en_rows[lay["fleurs_ids"][i]][0][1]
        jobs.append({"pat": pat, "i": i, "lo": lo_txt[i], "ref": ref,
                     "answers": {a: " ".join(p["en"] for p in per[a][i]).strip() for a in ARMS},
                     # When the sentence's last words were ready in English, after its speech ended (voice not included).
                     "ready_after_end_s": {a: (round(max(p["done"] for p in per[a][i]) - s["end"], 2) if per[a][i] else None) for a in ARMS}})

PROMPT = """You are grading live speech translation from Lao into English. The speaker read one sentence aloud; a speech
recogniser transcribed it and a translator produced English, possibly in several pieces joined together.

Lao as read: {lo}
Reference English (human): {ref}

Candidate translations:
{cands}

For each candidate give a score 0-3 for how well a listener would understand what the speaker meant:
3 = full meaning, natural; 2 = main meaning, minor errors or omissions; 1 = partial, important errors or omissions;
0 = wrong, missing or misleading. Also flag "critical": true if it states something false or opposite that a listener
would believe. Content belonging to a neighbouring sentence is not an error by itself; judge only this sentence's meaning.
Answer JSON only: {{"A": {{"score": n, "critical": bool}}, "B": ..., "C": ..., "D": ...}}"""


def call(job, rnd):
    order = ARMS[:]
    random.Random(f"{job['pat']}{job['i']}{rnd}").shuffle(order)
    labels = "ABCD"
    cands = "\n".join(f"{labels[k]}: {job['answers'][a] or '(nothing)'}" for k, a in enumerate(order))
    body = {"contents": [{"role": "user", "parts": [{"text": PROMPT.format(lo=job["lo"], ref=job["ref"], cands=cands)}]}],
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

# Summary
import statistics as st
print(f"{'arm':12} {'quality%':>8} {'r1':>6} {'r2':>6} {'critical':>8} {'ready p50':>9} {'p90':>6}")
for a in ARMS:
    r = {1: [], 2: []}; crit = 0; ready = []
    for j in jobs:
        for rnd in (1, 2):
            g = j["grades"][rnd].get(a)
            if g: r[rnd].append(g["score"]); crit += bool(g.get("critical")) and rnd == 1
        if j["ready_after_end_s"][a] is not None: ready.append(j["ready_after_end_s"][a])
    q = lambda xs: 100 * sum(xs) / (3 * len(xs)) if xs else float("nan")
    ready.sort()
    p = lambda v, f: v[min(len(v) - 1, int(f * len(v)))] if v else None
    print(f"{a:12} {q(r[1] + r[2]):8.1f} {q(r[1]):6.1f} {q(r[2]):6.1f} {crit:8d} {p(ready, .5):9} {p(ready, .9):6}")
