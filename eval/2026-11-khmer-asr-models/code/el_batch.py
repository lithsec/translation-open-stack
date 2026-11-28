# ElevenLabs batch STT direct (POST /v1/speech-to-text), one sentence a call, 3 at once.
#   ELEVENLABS_API_KEY=... python3 -I el_batch.py MODEL DATA OUT.json
import io, json, os, sys, time, wave, uuid, urllib.request, concurrent.futures as cf
M, D, OUT = sys.argv[1:4]; KEY = os.environ["ELEVENLABS_API_KEY"]
S = json.load(open(f"{D}/set.json"))
def wav(f):
    raw = open(f"{D}/km/{f.replace('.wav', '.raw')}", "rb").read(); b = io.BytesIO()
    with wave.open(b, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(raw)
    return b.getvalue(), len(raw) / 32000
def one(s):
    a, sec = wav(s["km_file"]); bd = uuid.uuid4().hex; parts = []
    for k, v in (("model_id", M), ("language_code", "km"), ("tag_audio_events", "false")):
        parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + a + b"\r\n" + f"--{bd}--\r\n".encode())
    req = urllib.request.Request("https://api.elevenlabs.io/v1/speech-to-text", data=b"".join(parts), method="POST",
                                 headers={"xi-api-key": KEY, "Content-Type": f"multipart/form-data; boundary={bd}"})
    t = time.time()
    try:
        j = json.load(urllib.request.urlopen(req, timeout=90)); return {"file": s["km_file"], "hyp": j.get("text", ""), "lang": j.get("language_code"), "s": round(time.time() - t, 2), "audio_s": round(sec, 2)}
    except urllib.error.HTTPError as e: return {"file": s["km_file"], "hyp": "", "error": f"{e.code} {e.read()[:200]!r}", "s": round(time.time() - t, 2)}
with cf.ThreadPoolExecutor(3) as ex: rows = list(ex.map(one, S))
json.dump(rows, open(OUT, "w"), ensure_ascii=False, indent=1)
print(M, "done", len(rows), "errors", [r["error"] for r in rows if "error" in r][:2])
