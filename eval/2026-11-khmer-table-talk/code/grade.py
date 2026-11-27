# Blind side-by-side grade, per sentence, of the four translators on each set, against FLEURS's human text.
# gemini-flash-latest (eval key) sees the source as spoken (FLEURS text), the reference and the four answers under
# shuffled labels; scores 0-3 each plus a critical-error flag. Two rounds (different shuffles), three calls at once.
#   GEMINI_API_KEY=... python3 -I grade.py DATA      (reads DATA/set.json, DATA/mt.json; writes DATA/grades.json)
import concurrent.futures as cf, json, os, random, sys, time, urllib.request
D = sys.argv[1]; GRADER = os.environ.get("GRADER", "gemini-flash-latest"); KEY = os.environ["GEMINI_API_KEY"]
S = json.load(open(f"{D}/set.json")); MT = json.load(open(f"{D}/mt.json"))
ARMS = ["sol", "flash", "gemma", "azure"]; NAME = {"en": "English", "km": "Khmer"}
PROMPT = """You are grading live speech translation from {src} into {tgt}. The speaker said one sentence (shown as
written); a recogniser may have misheard it, and a translator produced the {tgt} below.

{src} as said: {said}
Reference {tgt} (human): {ref}

Candidate translations:
{cands}

For each candidate give a score 0-3 for how well a {tgt} listener would understand what the speaker meant:
3 = full meaning, natural; 2 = main meaning, minor errors or omissions; 1 = partial, important errors or omissions;
0 = wrong, missing or misleading. Also flag "critical": true if it states something false or opposite that a listener
would believe. Answer JSON only: {{"A": {{"score": n, "critical": bool}}, "B": ..., "C": ..., "D": ...}}"""
sets = sorted({k.rsplit(":", 1)[0] for k in MT})
jobs = []
for st in sets:
    d = st.split(":")[0]; src, tgt = d.split("-")
    for i, s in enumerate(S):
        jobs.append({"set": st, "i": i, "src": src, "tgt": tgt, "said": s[src], "ref": s[tgt],
                     "answers": {a: (MT.get(f"{st}:{a}") or [None] * len(S))[i]["out"] if (MT.get(f"{st}:{a}") or [None])[i] else "" for a in ARMS}})
def call(j, rnd):
    order = ARMS[:]; random.Random(f"{j['set']}{j['i']}{rnd}").shuffle(order); L = "ABCD"
    cands = "\n".join(f"{L[k]}: {j['answers'][a] or '(nothing)'}" for k, a in enumerate(order))
    body = {"contents": [{"role": "user", "parts": [{"text": PROMPT.format(src=NAME[j["src"]], tgt=NAME[j["tgt"]], said=j["said"], ref=j["ref"], cands=cands)}]}],
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
    fut = {(j["set"], j["i"], r): ex.submit(call, j, r) for j in jobs for r in (1, 2)}
for j in jobs: j["grades"] = {r: fut[(j["set"], j["i"], r)].result() for r in (1, 2)}
json.dump(jobs, open(f"{D}/grades.json", "w"), ensure_ascii=False, indent=1)
print("graded", len(jobs), "errors", sum(1 for j in jobs for g in j["grades"].values() if "error" in g))
