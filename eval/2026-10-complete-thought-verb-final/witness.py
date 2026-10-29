# ../2026-10-complete-thought-endpointing/witness.py with Korean and Persian in the language names. That file:
# ../2026-10-llm-commit-policy-bedrock-de-hi-tr/witness.py, unchanged. That file:
# ../2026-10-unseen/witness.py with German, Hindi and Turkish added and the model from WITNESS
# (gemini-flash-latest by default; that run used gemini-pro-latest).
#
# Does each recording say what its text says? Gemini transcribes each read sentence verbatim
# (what was said, not what the text says) and flags recordings that stop early or misread.
#   GEMINI_API_KEY=... python3 -I witness.py <clips dir> <lang> <out.json>
import base64, io, json, os, sys, wave, concurrent.futures as cf, urllib.request, time
CL, L, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
NAMES = {"en": "English", "es": "Spanish", "fr": "French", "ja": "Japanese", "km": "Khmer", "lo": "Lao", "pt": "Portuguese", "ht": "Haitian Creole", "de": "German", "hi": "Hindi", "tr": "Turkish", "ko": "Korean", "fa": "Persian"}
MODEL = os.environ.get("WITNESS", "gemini-flash-latest")
meta = json.load(open(os.path.join(CL, f"{L}.json")))
gold = json.load(open(os.path.join(CL, f"{L}.txt.json")))
with wave.open(os.path.join(CL, f"{L}.wav")) as w:
    raw = w.readframes(w.getnframes())

def seg(i):
    s = meta["sentences"][i]
    a, b = max(0, int((s["start"] - 0.2) * 16000)) * 2, int((s["end"] + 0.2) * 16000) * 2
    buf = io.BytesIO()
    with wave.open(buf, "wb") as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(16000); o.writeframes(raw[a:b])
    return base64.b64encode(buf.getvalue()).decode()

def one(i):
    p = (f"Transcribe this {NAMES[L]} recording VERBATIM: exactly the words the speaker says, including misread or "
         "substituted words. Do not correct anything toward what you think the text should be. The speaker may be "
         "reading this text (it can differ from what is said): " + json.dumps(gold[i], ensure_ascii=False) + "\n"
         'Answer JSON: {"said": "...", "cut_off": true|false (the recording stops before the speaker finishes the text), '
         '"meaning_differs": true|false (what is said changes or drops meaning compared with the text; ignore '
         'filler, punctuation, spelling and number formatting), "differs": ["each place what is said differs from the text"]}')
    body = {"contents": [{"role": "user", "parts": [{"inlineData": {"mimeType": "audio/wav", "data": seg(i)}}, {"text": p}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    for k in range(5):
        try:
            req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models/" + MODEL + ":generateContent",
                                         data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
            j = json.load(urllib.request.urlopen(req, timeout=300))
            t = "".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"] if not x.get("thought"))
            return {"i": i, **json.loads(t)}
        except Exception as e:
            time.sleep(5 * (k + 1)); err = e
    return {"i": i, "error": str(err)}

with cf.ThreadPoolExecutor(6) as ex:
    res = sorted(ex.map(one, range(len(gold))), key=lambda r: r["i"])
json.dump(res, open(OUT, "w"), indent=1, ensure_ascii=False)
bad = [r["i"] for r in res if r.get("cut_off") or r.get("meaning_differs")]
print(L, "flagged:", bad, "errors:", [r["i"] for r in res if "error" in r])
