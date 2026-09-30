# Blind naturalness of every candidate voice per language: Gemini 2.5 Pro hears the same sentence from each
# candidate (shuffled, unlabelled) and rates how human each sounds, 1-5. Sentences 1-4.
import base64, glob, json, os, random, sys, urllib.request, urllib.error, time, concurrent.futures as cf
from vertex import endpoint, token
D = sys.argv[1]
NAMES = {"ar": "Arabic", "hi": "Hindi", "vi": "Vietnamese", "ko": "Korean", "tl": "Tagalog", "fa": "Persian", "id": "Indonesian",
         "tr": "Turkish", "bn": "Bengali", "ur": "Urdu", "it": "Italian", "sw": "Swahili"}
def cands(L): return sorted(d for d in glob.glob(f"{D}/tts/*") if os.path.exists(f"{d}/{L}_01.wav"))
def part(p): return {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(open(p, "rb").read()).decode()}}
def ask(body):
    req = urllib.request.Request(endpoint("gemini-2.5-pro"),
                                 data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    for a in range(8):
        try: return json.load(urllib.request.urlopen(req, timeout=300))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or a == 7: raise
            time.sleep(15 * (a + 1))
def judge(L, i):
    cs = cands(L); order = cs[:]; random.Random(f"{L}{i}").shuffle(order)
    labels = [chr(65 + k) for k in range(len(order))]
    parts = []
    for lab, d in zip(labels, order): parts += [{"text": f"Recording {lab}:"}, part(f"{d}/{L}_{i:02d}.wav")]
    parts.append({"text": f"These are the same {NAMES[L]} sentence spoken by different text-to-speech voices. Rate ONLY how natural and human each sounds to a native listener "
                          "(prosody, rhythm, pronunciation, artefacts), 1-5 where 5 = indistinguishable from a human. "
                          f'Return JSON {{{", ".join(f"\"{l}\": 1-5" for l in labels)}, "note": "one short reason"}}.'})
    j = ask({"contents": [{"role": "user", "parts": parts}], "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}})
    r = json.loads("".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"]))
    return L, {os.path.basename(d): r[lab] for lab, d in zip(labels, order)}
jobs = [(L, i) for L in NAMES for i in (1, 2, 3, 4) if len(cands(L)) > 1]
with cf.ThreadPoolExecutor(2) as ex: got = list(ex.map(lambda j: judge(*j), jobs))
out = {}
for L, r in got:
    for k, v in r.items(): out.setdefault(L, {}).setdefault(k, []).append(v)
res = {L: {k: round(sum(v) / len(v), 2) for k, v in r.items()} for L, r in out.items()}
json.dump(res, open(f"{D}/new_voice_naturalness.json", "w"), indent=1)
for L, r in res.items(): print(L, r)
