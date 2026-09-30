# Blind A/B naturalness: Gemini 2.5 Pro listens to the same sentence spoken by
# VoxCPM2 and by the stack's current voice (Kokoro or Piper) and says which
# sounds more like a natural human speaker.   python judge_naturalness.py <dir>
import base64, json, random, sys, os, concurrent.futures as cf, urllib.request, urllib.error
from vertex import endpoint, token
D = sys.argv[1]
NAMES = {"en":"English","es":"Spanish","fr":"French","de":"German","pt":"Portuguese","ru":"Russian","zh":"Mandarin Chinese","ja":"Japanese","km":"Khmer"}
CURRENT = {"en":"Kokoro","es":"Kokoro","fr":"Kokoro","pt":"Kokoro","zh":"Kokoro","ja":"Kokoro","de":"Piper","ru":"Piper","km":"MMS"}
def part(p): return {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(open(p, "rb").read()).decode()}}
def judge(L, i):
    a, b = f"{D}/voxcpm/{L}_{i:02d}.wav", f"{D}/stack/{L}_{i:02d}.wav"
    flip = random.Random(f"{L}{i}").random() < 0.5
    first, second = (b, a) if flip else (a, b)
    prompt = (f"Two recordings of the same {NAMES[L]} sentence, spoken by two different text-to-speech voices. "
              "Judge ONLY how natural and human they sound to a native listener: prosody, rhythm, intonation, voice quality, "
              "pronunciation, artefacts (glitches, robotic tone, clipped or slurred words). Ignore which voice/gender it is. "
              'Return JSON {"A": 1-5, "B": 1-5, "better": "A"|"B"|"tie", "note": "one short reason"} where 5 = indistinguishable from a human speaker.')
    body = {"contents": [{"role": "user", "parts": [{"text": "Recording A:"}, part(first), {"text": "Recording B:"}, part(second), {"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    req = urllib.request.Request(endpoint("gemini-2.5-pro"),
                                 data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    for attempt in range(8):
        try:
            j = json.load(urllib.request.urlopen(req, timeout=300)); break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 7: raise
            import time; time.sleep(10 * (attempt + 1))
    r = json.loads("".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"]))
    vox, cur = (r["B"], r["A"]) if flip else (r["A"], r["B"])
    win = {"tie": "tie", "A": "current" if flip else "voxcpm", "B": "voxcpm" if flip else "current"}[r["better"]]
    return {"lang": L, "i": i, "voxcpm": vox, "current": cur, "winner": win, "note": r.get("note", "")}
jobs = [(L, i) for L in NAMES for i in range(8) if os.path.exists(f"{D}/voxcpm/{L}_{i:02d}.wav") and os.path.exists(f"{D}/stack/{L}_{i:02d}.wav")]
with cf.ThreadPoolExecutor(2) as ex: res = list(ex.map(lambda j: judge(*j), jobs))
json.dump(res, open(f"{D}/naturalness.json", "w"), ensure_ascii=False, indent=1)
for L in NAMES:
    rs = [r for r in res if r["lang"] == L]
    if not rs: continue
    w = sum(r["winner"] == "voxcpm" for r in rs); c = sum(r["winner"] == "current" for r in rs)
    print(f"{L}: VoxCPM2 {sum(r['voxcpm'] for r in rs)/len(rs):.1f} vs {CURRENT[L]} {sum(r['current'] for r in rs)/len(rs):.1f}  (wins {w}-{c}, ties {len(rs)-w-c})")
