# System 4: Azure fast transcription (transcriptions:transcribe, the call Talk's
# /v1/hear makes), one read sentence at a time on the gold boundaries, with the
# sentence's own locale (Talk passes the conversation's candidates; one locale is
# the best case, as system 1 is given the language).
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I azure_fast.py CLIPS OUT lang...
#
# Writes OUT/azure_fast_<lang>.json. Nothing secret is printed.
import io, json, os, sys, time, uuid, wave, urllib.request, concurrent.futures as cf

KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
LOCALE = {"en": "en-US", "es": "es-ES", "pt": "pt-BR", "fr": "fr-FR", "ja": "ja-JP"}
URL = f"https://{REGION}.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2024-11-15"
CLIPS, OUT, LANGS = sys.argv[1], sys.argv[2], sys.argv[3:]


def wav_bytes(pcm, rate):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
    return b.getvalue()


def call(audio, locale):
    bd = uuid.uuid4().hex
    body = (f"--{bd}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"u.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + audio + \
           (f"\r\n--{bd}\r\nContent-Disposition: form-data; name=\"definition\"\r\n\r\n"
            + json.dumps({"locales": [locale]}) + f"\r\n--{bd}--\r\n").encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(URL, data=body, headers={
                "Ocp-Apim-Subscription-Key": KEY, "Content-Type": f"multipart/form-data; boundary={bd}"})
            t0 = time.time()
            j = json.load(urllib.request.urlopen(req, timeout=60))
            return " ".join(p.get("text", "") for p in j.get("combinedPhrases", [])).strip(), time.time() - t0
        except Exception as e:  # 429s and transient errors
            err = str(e)[:120]
            time.sleep(2 + 3 * attempt)
    return None, err


for lang in LANGS:
    meta = json.load(open(os.path.join(CLIPS, f"{lang}.json")))
    with wave.open(os.path.join(CLIPS, f"{lang}.wav")) as w:
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
    jobs = [(s["i"], wav_bytes(pcm[int(s["start"] * rate) * 2:int(s["end"] * rate) * 2], rate)) for s in meta["sentences"]]
    with cf.ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda j: (j[0], *call(j[1], LOCALE[lang])), jobs))
    out = [{"i": i, "text": t if t is not None else "", "error": None if t is not None else s,
            "s": round(s, 3) if t is not None else None} for i, t, s in res]
    json.dump({"lang": lang, "locale": LOCALE[lang], "sentences": out},
              open(os.path.join(OUT, f"azure_fast_{lang}.json"), "w"), ensure_ascii=False, indent=1)
    print(lang, sum(1 for o in out if o["error"]), "errors", flush=True)
