# Blind A/B grade of condensed passages, as a listener hears them: what was already spoken, then the passage, then
# the next piece. A rewrite the app would not use (not 5% shorter, empty) is graded as the app would speak it: the
# original pieces. Gemini (eval key), two rounds with the labels swapped. Scores 1-5:
#   join_in   how smoothly the passage follows on from what was already spoken (no restarted sentence, no repeat,
#             no missing link word)
#   join_out  how smoothly the next piece follows the passage
#   natural   how natural and fluent the passage sounds spoken aloud
#   faithful  everything the original pieces said is still there, nothing added or changed
# plus flags: repeats (repeats or re-says something already spoken), added (adds or changes content).
#   GEMINI_API_KEY=... python3 -I grade.py pt es
import json, os, random, sys, urllib.request, concurrent.futures as cf

KEY = os.environ["GEMINI_API_KEY"]
GRADER = os.environ.get("GRADER", "gemini-flash-latest")
NAME = {"pt": "Portuguese", "es": "Spanish"}
DIMS = ["join_in", "join_out", "natural", "faithful"]

PROMPT = """You are judging speech that a live interpreter's voice will say aloud in {L}. Listeners hear, in order:
1. ALREADY SPOKEN (they have just heard this): {spoken}
2. one of the two candidate passages below
3. NEXT (said straight after the passage): {next}

The ORIGINAL pieces the passage shortens (for checking that nothing is lost): {original}

Candidate A: {a}
Candidate B: {b}

For each candidate, score 1-5 (5 best):
- join_in: how smoothly it follows on from ALREADY SPOKEN (penalise restarting a sentence already under way, repeating
  or re-saying what was spoken, a missing link word)
- join_out: how smoothly NEXT follows it
- natural: how natural and fluent it sounds spoken aloud
- faithful: every fact, name, number and negation of the ORIGINAL kept, nothing added or changed
and flags: repeats (true if it repeats or re-says something from ALREADY SPOKEN), added (true if it adds or changes
content). Being shorter is expected and is not a fault.
Answer JSON only: {{"A": {{"join_in": n, "join_out": n, "natural": n, "faithful": n, "repeats": bool, "added": bool}}, "B": {{...}}}}"""


def spoken_as(arm):
    return arm["text"] if arm["verdict"] == "condensed" else None


def call(job, rnd):
    swap = (rnd == 2) ^ (random.Random(f"{job['lang']}{job['k']}").random() < 0.5)
    first, second = ("B", "A") if swap else ("A", "B")
    txt = {x: spoken_as(job[x]) or job["original"] for x in ("A", "B")}
    body = {"contents": [{"role": "user", "parts": [{"text": PROMPT.format(L=NAME[job["lang"]], spoken=" ".join(job["spoken"]), next=job["next"],
            original=" | ".join(p["text"] for p in job["run"]), a=txt[first], b=txt[second])}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{GRADER}:generateContent",
                                 data=json.dumps(body).encode(), headers={"content-type": "application/json", "x-goog-api-key": KEY})
    err = ""
    for _ in range(4):
        try:
            g = json.loads(json.load(urllib.request.urlopen(req, timeout=120))["candidates"][0]["content"]["parts"][0]["text"])
            return {first: g["A"], second: g["B"]}
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]
    return {"error": err}


jobs = []
for lang in sys.argv[1:]:
    for k, r in enumerate(json.load(open(f"/tmp/rs/cond/runs/condense_{lang}.json"))):
        jobs.append({**r, "lang": lang, "k": k})
with cf.ThreadPoolExecutor(6) as ex:
    futs = {(j["lang"], j["k"], rnd): ex.submit(call, j, rnd) for j in jobs for rnd in (1, 2)}
for j in jobs:
    j["grades"] = {rnd: futs[(j["lang"], j["k"], rnd)].result() for rnd in (1, 2)}
json.dump(jobs, open("/tmp/rs/cond/runs/grades.json", "w"), ensure_ascii=False, indent=1)

# ---------------------------------------------------------------- summary
med = lambda v: sorted(v)[len(v) // 2] if v else None
for lang in sys.argv[1:]:
    J = [j for j in jobs if j["lang"] == lang]
    print(f"\n== {lang}: {len(J)} runs")
    for arm in ("A", "B"):
        kept = sum(j[arm]["verdict"] == "condensed" for j in J)
        ratio = [len(j[arm]["text"]) / len(j["original"]) for j in J if j[arm]["verdict"] == "condensed"]
        ms = [j[arm]["ms"] for j in J]
        line = f"{arm}: kept {kept}/{len(J)}, length {100 * sum(ratio) / max(1, len(ratio)):.0f}% of original, call p50 {med(ms)} ms"
        for d in DIMS:
            v = [g[arm][d] for j in J for g in j["grades"].values() if arm in g]
            line += f" | {d} {sum(v) / max(1, len(v)):.2f}"
        rep = sum(bool(g[arm].get("repeats")) for j in J for g in j["grades"].values() if arm in g)
        add = sum(bool(g[arm].get("added")) for j in J for g in j["grades"].values() if arm in g)
        print(line + f" | repeats {rep} added {add} (of {2 * len(J)} gradings)")
    for d in DIMS:
        diff = [sum(g["B"][d] - g["A"][d] for g in j["grades"].values() if "A" in g) / 2 for j in J]
        R = random.Random(1)
        bs = sorted(sum(R.choice(diff) for _ in diff) / len(diff) for _ in range(5000))
        print(f"   B - A {d:9}: {sum(diff) / len(diff):+.2f} (95% {bs[125]:+.2f} to {bs[4875]:+.2f})")
    for sub, cond in (("continues a sentence", lambda j: j["continues"]), ("ends mid-sentence", lambda j: j["endsCut"])):
        S = [j for j in J if cond(j)]
        if S:
            d = [sum(g["B"]["join_in" if sub.startswith("cont") else "join_out"] - g["A"]["join_in" if sub.startswith("cont") else "join_out"] for g in j["grades"].values() if "A" in g) / 2 for j in S]
            print(f"   runs that {sub} ({len(S)}): B - A on that join {sum(d) / len(d):+.2f}")
