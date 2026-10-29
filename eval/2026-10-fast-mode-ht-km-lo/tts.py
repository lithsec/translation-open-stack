# Real voices for every chunk, so the timeline uses measured audio lengths and times to
# first audio.
#   km, lo  Azure native neural voices with the "T8s" pacing of ../2026-10-voice-rate-compact
#           follow-ups: mstts:silence Leading/Tailing-exact 0 ms, Comma-exact 100 ms,
#           prosody +8%, then an energy edge trim keeping 30 ms.
#   ht      Gemini TTS, the model and voice Talk uses for Haitian Creole (gemini-3.8-flash-tts,
#           Kore), streamed (time to first audio is the first audio event); SSML does not apply,
#           so only the edge trim.
# Chunks are joined with 120 ms between phrases and 300 ms after a sentence's last chunk.
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus GEMINI_API_KEY=... python3 -I tts.py check WORK
#   ... python3 -I tts.py run WORK
# check: per voice, a test sentence at 0% vs T8s (does Azure apply the settings?) and the
#        Gemini pace instruction test; picks the faster of each Azure pair.
# run:   WORK/tts/<system>/<pattern>_en-<tgt>.json  (per chunk ttfa_ms, seconds)
import base64, concurrent.futures as cf, glob, hashlib, json, os, sys, time, urllib.request
from xml.sax.saxutils import escape

MODE, WORK = sys.argv[1], sys.argv[2]
CACHE = os.path.join(WORK, "tts", "cache")
SR = 24000
AZ = {"km": ("km-KH", ["km-KH-PisethNeural", "km-KH-SreymomNeural"]), "lo": ("lo-LA", ["lo-LA-ChanthavongNeural", "lo-LA-KeomanyNeural"])}
GEMINI_TTS, GEMINI_VOICE = "gemini-3.8-flash-tts", "Kore"
GAP_PHRASE, GAP_SENTENCE = 0.12, 0.30


def trim(pcm):
    import numpy as np
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    if len(x) < 480:
        return pcm
    f = 240                                   # 10 ms frames
    n = len(x) // f
    rms = np.sqrt((x[: n * f].reshape(n, f) ** 2).mean(axis=1))
    thr = max(0.05 * rms.max(), 150.0)
    on = np.nonzero(rms >= thr)[0]
    if not len(on):
        return pcm
    keep = int(0.03 * SR)
    a, b = max(0, on[0] * f - keep), min(len(x), (on[-1] + 1) * f + keep)
    return x[a:b].astype("<i2").tobytes()


def azure(text, voice, locale, rate=8, t8s=True):
    sil = ('<mstts:silence type="Leading-exact" value="0ms"/><mstts:silence type="Tailing-exact" value="0ms"/>'
           '<mstts:silence type="Comma-exact" value="100ms"/>') if t8s else ""
    ssml = (f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='https://www.w3.org/2001/mstts' "
            f"xml:lang='{locale}'><voice name='{voice}'>{sil}<prosody rate='{rate:+d}%'>{escape(text)}</prosody></voice></speak>")
    req = urllib.request.Request(f"https://{os.environ['AZURE_SPEECH_REGION']}.tts.speech.microsoft.com/cognitiveservices/v1",
                                 ssml.encode(), {"Ocp-Apim-Subscription-Key": os.environ["AZURE_SPEECH_KEY"],
                                                 "Content-Type": "application/ssml+xml",
                                                 "X-Microsoft-OutputFormat": "raw-24khz-16bit-mono-pcm", "User-Agent": "lt-eval"})
    for attempt in range(6):
        try:
            t0 = time.time()
            r = urllib.request.urlopen(req, timeout=60)
            first = r.read(4800)
            ttfa = (time.time() - t0) * 1000
            return first + r.read(), ttfa
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 * (attempt + 1))


def find_audio(v, depth=0):
    if depth > 8 or not isinstance(v, (dict, list)):
        return []
    if isinstance(v, list):
        return [a for x in v for a in find_audio(x, depth + 1)]
    mime = v.get("mime_type") or v.get("mimeType") or ""
    if isinstance(v.get("data"), str) and len(v["data"]) > 100 and (v.get("type") == "audio" or mime.startswith("audio")):
        return [v["data"]]
    return [a for x in v.values() for a in find_audio(x, depth + 1)]


def gemini(text):
    body = {"model": GEMINI_TTS, "store": False, "input": [{"type": "user_input", "content": [{"type": "text", "text": text}]}],
            "response_format": {"type": "audio", "mime_type": "audio/l16", "sample_rate": SR},
            "generation_config": {"speech_config": [{"voice": GEMINI_VOICE}]}, "stream": True}
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/interactions", json.dumps(body).encode(),
                                 {"content-type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"], "accept": "text/event-stream"})
    for attempt in range(6):
        try:
            t0 = time.time()
            r = urllib.request.urlopen(req, timeout=120)
            pcm, ttfa = b"", None
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except ValueError:
                    continue
                for a in find_audio(ev):
                    if ttfa is None:
                        ttfa = (time.time() - t0) * 1000
                    pcm += base64.b64decode(a)
            if pcm:
                return pcm, ttfa
        except Exception:
            if attempt == 5:
                raise
        time.sleep(3 * (attempt + 1))
    raise RuntimeError("no audio")


def synth(text, tgt, voice):
    h = hashlib.sha1(f"{tgt}|{voice}|{text}".encode()).hexdigest()
    mp, pp = os.path.join(CACHE, h + ".json"), os.path.join(CACHE, h + ".pcm")
    if os.path.exists(mp):
        return json.load(open(mp))
    pcm, ttfa = gemini(text) if tgt == "ht" else azure(text, voice, AZ[tgt][0])
    pcm = trim(pcm)
    m = {"ttfa_ms": round(ttfa), "seconds": round(len(pcm) / 2 / SR, 3)}
    os.makedirs(CACHE, exist_ok=True)
    json.dump(m, open(mp, "w"))
    return m


def check():
    tests = {"km": "ប្រធានាធិបតីបានប្រកាសថា កងទ័ពនឹងចាកចេញពីប្រទេស នៅចុងឆ្នាំនេះ។",
             "lo": "ປະທານາທິບໍດີໄດ້ປະກາດວ່າ ທະຫານຈະອອກຈາກປະເທດ ໃນທ້າຍປີນີ້.",
             "ht": "Prezidan an te anonse ke twoup yo ap kite peyi a, nan fen ane sa a."}
    out = {}
    for tgt, (loc, voices) in AZ.items():
        for v in voices:
            a, _ = azure(tests[tgt], v, loc, rate=0, t8s=False)
            b, tb = azure(tests[tgt], v, loc, rate=8, t8s=True)
            out[v] = {"plain_s": round(len(a) / 2 / SR, 2), "t8s_s": round(len(b) / 2 / SR, 2),
                      "t8s_trimmed_s": round(len(trim(b)) / 2 / SR, 2), "ttfa_ms": round(tb)}
    a, ta = gemini(tests["ht"])
    b, tb = gemini("Read this briskly, at a quick natural pace: " + tests["ht"])
    out["gemini-plain"] = {"s": round(len(a) / 2 / SR, 2), "trimmed_s": round(len(trim(a)) / 2 / SR, 2), "ttfa_ms": round(ta)}
    out["gemini-brisk-instruction"] = {"s": round(len(b) / 2 / SR, 2), "trimmed_s": round(len(trim(b)) / 2 / SR, 2), "ttfa_ms": round(tb)}
    json.dump(out, open(os.path.join(WORK, "voice_check.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


def pick(tgt):
    if tgt == "ht":
        return GEMINI_VOICE
    c = json.load(open(os.path.join(WORK, "voice_check.json")))
    return min(AZ[tgt][1], key=lambda v: c[v]["t8s_trimmed_s"])


def run_one(path):
    s = json.load(open(path))
    tgt = s["dir"].split("-")[1]
    voice = pick(tgt)
    out = os.path.join(WORK, "tts", s["system"], os.path.basename(path))
    if os.path.exists(out):
        return out, "cached"
    rows = []
    for c in s["chunks"]:
        txt = c["out"].strip()
        rows.append(synth(txt, tgt, voice) if txt else {"ttfa_ms": 0, "seconds": 0.0})
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"voice": voice, "rows": rows}, open(out, "w"), indent=1)
    return out, f"{len(rows)} chunks, {voice}"


if __name__ == "__main__":
    if MODE == "check":
        check()
    else:
        paths = sorted(glob.glob(os.path.join(WORK, "sim", "*", "*.json")))
        with cf.ThreadPoolExecutor(int(os.environ.get("THREADS", "6"))) as ex:
            for p, msg in ex.map(run_one, paths):
                print(os.path.relpath(p, WORK), msg, flush=True)
