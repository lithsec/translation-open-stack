# Which speech-to-text hears the CMU Haitian Creole speakers best, against
# the verified text each speaker read (CER on lowercased letters and digits,
# as judge.py measures "heard"):
#   live, from earlier runs: Gladia (out/stt-gladia), Gemini Live's input
#   transcript (out/live), the open stack = Meta Omnilingual ASR (out/stack);
#   batch, here: Gemini 2.5 Pro / Flash transcribing each sentence's audio on Vertex.
#
#   GOOGLE_CLOUD_PROJECT=... python3 text-mt/stt_compare.py
import base64, io, json, os, sys, wave
import concurrent.futures as cf
import urllib.error, urllib.request
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "..", "2026-09-model-eval", "scripts"))
sys.path.insert(0, HERE)
import vertex  # noqa: E402
from judge import cer  # noqa: E402
OUT = os.path.join(HERE, "text-mt", "out")
src = json.load(open(os.path.join(HERE, "sentences", "ht.json")))
marks = json.load(open(os.path.join(HERE, "audio", "ht.json")))["sentences"]
with wave.open(os.path.join(HERE, "audio", "ht.wav")) as w:
    rate, pcm = w.getframerate(), w.readframes(w.getnframes())


def clip(m):
    a, b = int((m["start"] - 0.2) * rate) * 2, int((m["end"] + 0.2) * rate) * 2
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate), w.writeframes(pcm[max(0, a):b])
    return base64.b64encode(buf.getvalue()).decode()


def transcribe(model, m):
    body = {"contents": [{"role": "user", "parts": [
        {"inlineData": {"mimeType": "audio/wav", "data": clip(m)}},
        {"text": "Transcribe this Haitian Creole speech verbatim in standard Haitian Creole orthography. Output only the transcript."}]}],
        "generationConfig": {"temperature": 0}}
    for attempt in range(4):
        if attempt:
            vertex._tok = None
        req = urllib.request.Request(vertex.endpoint(model), data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {vertex.token()}", "Content-Type": "application/json"})
        try:
            j = json.load(urllib.request.urlopen(req, timeout=300))
            return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"]).strip()
        except urllib.error.HTTPError as e:
            if e.code not in (401, 429, 503):
                raise
        except (TimeoutError, urllib.error.URLError):
            pass
    return ""


def chirp3(m):
    """Google Cloud Speech-to-Text v2, Chirp 3, language left to auto-detect:
    it rejects ht-HT by name in every region (2026-10-17) yet hears it."""
    body = {"config": {"autoDecodingConfig": {}, "model": "chirp_3", "languageCodes": ["auto"]}, "content": clip(m)}
    url = f"https://us-speech.googleapis.com/v2/projects/{vertex.project()}/locations/us/recognizers/_:recognize"
    for attempt in range(4):
        if attempt:
            vertex._tok = None
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {vertex.token()}", "Content-Type": "application/json", "x-goog-user-project": vertex.project()})
        try:
            j = json.load(urllib.request.urlopen(req, timeout=120))
            return " ".join(r["alternatives"][0].get("transcript", "") for r in j.get("results", []) if r.get("alternatives")).strip()
        except urllib.error.HTTPError as e:
            if e.code not in (401, 429, 503):
                raise
        except (TimeoutError, urllib.error.URLError):
            pass
    return ""


p3 = os.path.join(OUT, "stt__chirp_3.json")
if not os.path.exists(p3):
    with cf.ThreadPoolExecutor(6) as ex:
        json.dump(list(ex.map(chirp3, marks)), open(p3, "w"), ensure_ascii=False, indent=1)

gold = " ".join(src)
rows = {}
for model in ("gemini-2.5-pro", "gemini-2.5-flash"):
    p = os.path.join(OUT, f"stt__{model}.json")
    if not os.path.exists(p):
        with cf.ThreadPoolExecutor(6) as ex:
            json.dump(list(ex.map(lambda m: transcribe(model, m), marks)), open(p, "w"), ensure_ascii=False, indent=1)
    rows[f"{model} (batch, per sentence)"] = " ".join(json.load(open(p)))
rows["Google Chirp 3, auto language (batch, per sentence)"] = " ".join(json.load(open(p3)))
rows["Gladia Solaria-1 (live)"] = " ".join(f["text"] for f in json.load(open(os.path.join(HERE, "out", "stt-gladia", "ht.json")))["finals"])
rows["Meta Omnilingual ASR (open stack, live)"] = json.load(open(os.path.join(HERE, "out", "stack", "ht-en.json")))["heard"]
live = json.load(open(os.path.join(HERE, "out", "live", "ht-en.json")))
rows["Gemini Live (its input transcript)"] = live.get("heard") or " ".join(t.get("heard", "") for t in live.get("turns", []))
res = {k: cer(gold, v) for k, v in rows.items()}
json.dump(res, open(os.path.join(OUT, "stt_cer.json"), "w"), indent=1)
for k, v in sorted(res.items(), key=lambda kv: kv[1]):
    print(f"{v:6.1%}  {k}")
