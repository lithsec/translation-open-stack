# Hears the Khmer FLEURS sentences through OpenRouter's /api/v1/audio/transcriptions, one model, one sentence a call,
# with language=km (NOLANG=1: no language, the model detects it). Output: [{file, hyp, s, audio_s}].
#   OPENROUTER_API_KEY=... [NOLANG=1] python3 -I or_transcribe.py MODEL DATA OUT.json
import io, json, os, sys, time, wave, urllib.request, uuid, base64
M, D, OUT = sys.argv[1:4]
S = json.load(open(f"{D}/set.json")); KEY = os.environ["OPENROUTER_API_KEY"]
def wav(f):
    raw = open(f"{D}/km/{f.replace('.wav', '.raw')}", "rb").read(); b = io.BytesIO()
    with wave.open(b, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(raw)
    return b.getvalue(), len(raw) / 32000
def call(audio):
    bd = uuid.uuid4().hex; parts = []
    for k, v in (("model", M),) + ((("language", "km"),) if not os.environ.get("NOLANG") else ()):
        parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + audio + b"\r\n")
    parts.append(f"--{bd}--\r\n".encode())
    req = urllib.request.Request("https://openrouter.ai/api/v1/audio/transcriptions", data=b"".join(parts), method="POST",
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": f"multipart/form-data; boundary={bd}"})
    with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())
rows = []
probe = len(sys.argv) > 4
for s in (S[:1] if probe else S):
    a, sec = wav(s["km_file"]); t = time.time(); err = None; h = ""
    try:
        j = call(a); h = j.get("text", "")
        if probe: print({k: (v if k != "text" else f"<{len(v)} chars>") for k, v in j.items()})
    except urllib.error.HTTPError as e: err = f"{e.code} {e.read()[:300]!r}"
    except Exception as e: err = str(e)[:200]
    rows.append({"file": s["km_file"], "hyp": h, "s": round(time.time() - t, 2), "audio_s": round(sec, 2)} | ({"error": err} if err else {}))
    if err: print(s["km_file"], err)
json.dump(rows, open(OUT, "w"), ensure_ascii=False, indent=1)
print(M, "done", len(rows), "errors", sum(1 for r in rows if "error" in r))
