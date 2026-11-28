# Blind side-by-side grade, per sentence, of sol's English from each recogniser's Khmer (and from the FLEURS text
# itself), against FLEURS's human English: ../../2026-11-khmer-table-talk/code/grade.py's prompt and scale, with one
# label per recogniser (A-H) instead of per translator. gemini-flash-latest (eval key), two rounds with different
# shuffles, three calls at once. The baselines (perfect text, Transcribe, Azure) are that eval's stored sol
# translations (its runs/mt.json), graded again here beside the new ones so all scores share one grading.
#   GEMINI_API_KEY=... python3 -I grade.py DATA     (DATA/set.json, DATA/mt.json; writes DATA/grades.json)
import concurrent.futures as cf, json, os, random, sys, time, urllib.request
D = sys.argv[1]; GRADER = os.environ.get("GRADER", "gemini-flash-latest"); KEY = os.environ["GEMINI_API_KEY"]
S = json.load(open(f"{D}/set.json")); MT = json.load(open(f"{D}/mt.json"))
ARMS = [k.split(":")[1] for k in MT if k.startswith("km-en:") and k.endswith(":sol")]
L = "ABCDEFGHIJ"[: len(ARMS)]
PROMPT = """You are grading live speech translation from Khmer into English. The speaker said one sentence (shown as
written); a recogniser may have misheard it, and a translator produced the English below.

Khmer as said: {said}
Reference English (human): {ref}

Candidate translations:
{cands}

For each candidate give a score 0-3 for how well an English listener would understand what the speaker meant:
3 = full meaning, natural; 2 = main meaning, minor errors or omissions; 1 = partial, important errors or omissions;
0 = wrong, missing or misleading. Also flag "critical": true if it states something false or opposite that a listener
would believe. Answer JSON only: {{{fmt}}}"""
FMT = ", ".join(f'"{x}": {{"score": n, "critical": bool}}' for x in L)
jobs = [{"i": i, "said": s["km"], "ref": s["en"], "answers": {a: (MT[f"km-en:{a}:sol"][i] or {}).get("out", "") for a in ARMS}} for i, s in enumerate(S)]
def call(j, rnd):
    order = ARMS[:]; random.Random(f"km-en{j['i']}{rnd}").shuffle(order)
    cands = "\n".join(f"{L[k]}: {j['answers'][a] or '(nothing)'}" for k, a in enumerate(order))
    body = {"contents": [{"role": "user", "parts": [{"text": PROMPT.format(said=j["said"], ref=j["ref"], cands=cands, fmt=FMT)}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{GRADER}:generateContent",
                                 data=json.dumps(body).encode(), headers={"content-type": "application/json", "x-goog-api-key": KEY})
    err = ""
    for a in range(5):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=120))
            g = json.loads(r["candidates"][0]["content"]["parts"][0]["text"])
            return {x: g[L[k]] for k, x in enumerate(order)}
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]; time.sleep(3 * (a + 1))
    return {"error": err}
with cf.ThreadPoolExecutor(3) as ex:
    fut = {(j["i"], r): ex.submit(call, j, r) for j in jobs for r in (1, 2)}
for j in jobs: j["grades"] = {r: fut[(j["i"], r)].result() for r in (1, 2)}
json.dump(jobs, open(f"{D}/grades.json", "w"), ensure_ascii=False, indent=1)
print("arms", ARMS, "graded", len(jobs), "errors", sum(1 for j in jobs for g in j["grades"].values() if "error" in g))
