# A third witness for the English clip: Gemini transcribes each read sentence verbatim (what was said,
# not what the text says), and flags recordings that stop mid-sentence.
#   GEMINI_API_KEY=... python3 -I witness.py <clips dir> <out.json>
import base64, io, json, os, sys, wave, concurrent.futures as cf, urllib.request
CL, OUT = sys.argv[1], sys.argv[2]
meta = json.load(open(os.path.join(CL, "en.json")))
gold = json.load(open(os.path.join(CL, "en.txt.json")))
with wave.open(os.path.join(CL, "en.wav")) as w:
    raw = w.readframes(w.getnframes())

def seg(i):
    s = meta["sentences"][i]
    a, b = int((s["start"] - 0.2) * 16000) * 2, int((s["end"] + 0.2) * 16000) * 2
    buf = io.BytesIO()
    with wave.open(buf, "wb") as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(16000); o.writeframes(raw[a:b])
    return base64.b64encode(buf.getvalue()).decode()

def one(i):
    p = ("Transcribe this English recording VERBATIM: exactly the words the speaker says, including misread or "
         "substituted words. Do not correct anything toward what you think the text should be. The speaker may be "
         "reading this text (it can differ from what is said): " + json.dumps(gold[i]) + "\n"
         'Answer JSON: {"said": "...", "cut_off": true|false (the recording stops before the speaker finishes), '
         '"differs": ["each place what is said differs from the text"]}')
    body = {"contents": [{"role": "user", "parts": [{"inlineData": {"mimeType": "audio/wav", "data": seg(i)}}, {"text": p}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-latest:generateContent",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    j = json.load(urllib.request.urlopen(req, timeout=300))
    t = "".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"] if not x.get("thought"))
    return {"i": i, **json.loads(t)}

with cf.ThreadPoolExecutor(6) as ex:
    res = sorted(ex.map(one, range(len(gold))), key=lambda r: r["i"])
json.dump(res, open(OUT, "w"), indent=1, ensure_ascii=False)
for r in res:
    print(r["i"], "CUT" if r.get("cut_off") else "   ", r["said"], "|", "; ".join(r.get("differs", [])))
