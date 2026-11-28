# Gemini 3.5 Transcribe (Interactions API, v1beta; eval key) on the 24 sentences: one request per sentence, the audio
# inline as 16 kHz mono WAV, language_codes ["km-KH"] (the language is known, as on a phone's Khmer turn). Three at once.
# Times each request from send to answer (network included). Standard only: Private never uses Gemini.
#   GEMINI_API_KEY=... python3 -I gemini_transcribe.py DATA OUT.json [PROBE]
import base64, concurrent.futures as cf, io, json, os, sys, time, urllib.request, wave
D, OUT = sys.argv[1:3]; PROBE = len(sys.argv) > 3; KEY = os.environ["GEMINI_API_KEY"]
S = json.load(open(f"{D}/set.json"))
def wav(f):
    raw = open(f"{D}/km/{f.replace('.wav', '.raw')}", "rb").read(); b = io.BytesIO()
    with wave.open(b, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(raw)
    return b.getvalue(), len(raw) / 32000
def text_of(r):
    if isinstance(r.get("output_text"), str): return r["output_text"]
    out = []  # {"steps": [{"type": "model_output", "content": [{"type": "text", "text": ...}]}]}
    for st in r.get("steps", []) or []:
        if st.get("type") != "model_output": continue
        out += [c["text"] for c in st.get("content", []) if c.get("type") == "text" and isinstance(c.get("text"), str)]
    return "".join(out)
def call(s):
    data, secs = wav(s["km_file"])
    body = {"model": "gemini-3.5-transcribe", "input": [{"type": "audio", "data": base64.b64encode(data).decode(), "mime_type": "audio/wav"}],
            "generation_config": {"transcription_config": {"language_codes": ["km-KH"]}}}
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/interactions", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", "x-goog-api-key": KEY})
    err = ""
    for a in range(4):
        t = time.time()
        try:
            r = json.load(urllib.request.urlopen(req, timeout=120))
            if PROBE: print(json.dumps({k: (v if k != "outputs" else v) for k, v in r.items()}, ensure_ascii=False)[:1500])
            return {"file": s["km_file"], "hyp": text_of(r).strip(), "s": round(time.time() - t, 2), "audio_s": round(secs, 2), "usage": r.get("usage")}
        except urllib.error.HTTPError as e:
            err = f"{e.code} {e.read()[:300]!r}"
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]
        if PROBE: print("error", err); break
        time.sleep(3 * (a + 1))
    return {"file": s["km_file"], "hyp": "", "s": None, "audio_s": round(secs, 2), "error": err}
if PROBE:
    print(call(S[0])); sys.exit()
with cf.ThreadPoolExecutor(3) as ex: rows = list(ex.map(call, S))
json.dump(rows, open(OUT, "w"), ensure_ascii=False, indent=1)
print("done", len(rows), "errors", sum(1 for r in rows if r.get("error")))
