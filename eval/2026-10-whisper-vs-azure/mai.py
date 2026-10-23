# System 5: MAI-Transcribe-2 (public preview), through the Fast Transcription
# API's enhanced mode (learn.microsoft.com, "MAI-Transcribe-2"): definition
# {"locales": [lang], "enhancedMode": {"enabled": true, "model": "MAI-Transcribe-2"}},
# api-version 2025-10-15. Two ways:
#   sentence  one request per read sentence, the gold boundaries of systems 1 and 4
#   clip      the whole clip in one request (it is a batch API), per pause pattern
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I mai.py CLIPS_REG CLIPS_IRR OUT lang...
#
# Writes OUT/mai_sentence_<lang>.json and OUT/mai_clip_<pattern>_<lang>.json, with
# each request's round trip. Nothing secret is printed.
import io, json, os, sys, time, uuid, wave, urllib.request, urllib.error, concurrent.futures as cf

KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
URL = f"https://{REGION}.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15"
CLIPS = {"reg": sys.argv[1], "irr": sys.argv[2]}
OUT, LANGS = sys.argv[3], sys.argv[4:]


def wav_bytes(pcm, rate):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
    return b.getvalue()


def call(audio, lang):
    bd = uuid.uuid4().hex
    definition = {"locales": [lang], "enhancedMode": {"enabled": True, "model": "MAI-Transcribe-2"}}
    body = (f"--{bd}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"u.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + audio + \
           (f"\r\n--{bd}\r\nContent-Disposition: form-data; name=\"definition\"\r\n\r\n"
            + json.dumps(definition) + f"\r\n--{bd}--\r\n").encode()
    err = ""
    for attempt in range(4):
        req = urllib.request.Request(URL, data=body, headers={
            "Ocp-Apim-Subscription-Key": KEY, "Content-Type": f"multipart/form-data; boundary={bd}"})
        t0 = time.time()
        try:
            j = json.load(urllib.request.urlopen(req, timeout=300))
            text = " ".join(p.get("text", "") for p in j.get("combinedPhrases", [])).strip()
            return text, round(time.time() - t0, 3), ""
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except Exception as e:
            err = str(e)[:200]
        time.sleep(2 + 3 * attempt)
    return None, None, err


for lang in LANGS:
    meta = json.load(open(os.path.join(CLIPS["reg"], f"{lang}.json")))
    with wave.open(os.path.join(CLIPS["reg"], f"{lang}.wav")) as w:
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
    jobs = [(s["i"], wav_bytes(pcm[int(s["start"] * rate) * 2:int(s["end"] * rate) * 2], rate)) for s in meta["sentences"]]
    with cf.ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda j: (j[0], *call(j[1], lang)), jobs))
    out = [{"i": i, "text": t or "", "s": s, "error": e or None} for i, t, s, e in res]
    json.dump({"lang": lang, "sentences": out}, open(os.path.join(OUT, f"mai_sentence_{lang}.json"), "w"),
              ensure_ascii=False, indent=1)
    print(lang, "sentence", sum(1 for o in out if o["error"]), "errors", (out[0]["error"] or "")[:200], flush=True)
    for pat, d in CLIPS.items():
        with open(os.path.join(d, f"{lang}.wav"), "rb") as f:
            t, s, e = call(f.read(), lang)
        json.dump({"lang": lang, "pattern": pat, "sentences": [{"i": 0, "text": t or ""}], "s": s, "error": e or None},
                  open(os.path.join(OUT, f"mai_clip_{pat}_{lang}.json"), "w"), ensure_ascii=False, indent=1)
        print(lang, "clip", pat, "ok" if t is not None else "ERROR " + e[:200], s, flush=True)
