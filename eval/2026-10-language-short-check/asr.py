# Recognition, one read sentence at a time (each language given, no language ID):
#   azure  Azure fast transcription (transcriptions:transcribe, 2024-11-15), the language's locale
#   mai    MAI-Transcribe-2 (the same API's enhanced mode, 2025-10-15), the language's code
# Omnilingual goes through omni.mjs (the omni-stt service).
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus MAI_KEY=... MAI_REGION=eastus2 \
#     python3 -I asr.py WORK
#
# Writes WORK/asr/<system>_<lang>.json: [{"n", "text", "s", "error"}]. Nothing secret is printed.
import concurrent.futures as cf
import json, os, sys, time, urllib.error, urllib.request, uuid

WORK = sys.argv[1]
AZURE_LOCALE = {"vi": "vi-VN", "fa": "fa-IR", "zh": "zh-CN", "yue": "zh-HK", "ar": "ar-EG",
                "sw": "sw-KE", "fil": "fil-PH", "uk": "uk-UA"}          # no Cape Verdean Creole locale
MAI_LANG = {"vi": "vi", "fa": "fa", "zh": "zh", "yue": "yue", "ar": "ar", "sw": "sw", "fil": "fil", "uk": "uk"}
SYSTEMS = {
    "azure": ("AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "2024-11-15", AZURE_LOCALE, None),
    "mai": ("MAI_KEY", "MAI_REGION", "2025-10-15", MAI_LANG, {"enabled": True, "model": "MAI-Transcribe-2"}),
}


def call(audio, url, key, locale, enhanced):
    bd = uuid.uuid4().hex
    definition = {"locales": [locale]}
    if enhanced:
        definition["enhancedMode"] = enhanced
    body = (f"--{bd}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"u.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + audio + \
           (f"\r\n--{bd}\r\nContent-Disposition: form-data; name=\"definition\"\r\n\r\n"
            + json.dumps(definition) + f"\r\n--{bd}--\r\n").encode()
    err = ""
    for attempt in range(4):
        req = urllib.request.Request(url, data=body, headers={
            "Ocp-Apim-Subscription-Key": key, "Content-Type": f"multipart/form-data; boundary={bd}"})
        t0 = time.time()
        try:
            j = json.load(urllib.request.urlopen(req, timeout=120))
            return " ".join(p.get("text", "") for p in j.get("combinedPhrases", [])).strip(), round(time.time() - t0, 3), ""
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except Exception as e:  # transient
            err = str(e)[:200]
        time.sleep(2 + 3 * attempt)
    return "", None, err


def main():
    sentences = json.load(open(os.path.join(WORK, "sentences.json")))
    os.makedirs(os.path.join(WORK, "asr"), exist_ok=True)
    for name, (kenv, renv, ver, codes, enhanced) in SYSTEMS.items():
        key, region = os.environ[kenv].strip(), os.environ[renv].strip()
        url = f"https://{region}.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version={ver}"
        for lang, rows in sentences.items():
            if lang not in codes:
                continue
            p = os.path.join(WORK, "asr", f"{name}_{lang}.json")
            if os.path.exists(p):
                continue
            def one(r):
                audio = open(os.path.join(WORK, "audio", lang, f"{r['n']:02d}.wav"), "rb").read()
                t, s, e = call(audio, url, key, codes[lang], enhanced)
                return {"n": r["n"], "text": t, "s": s, "error": e or None}
            with cf.ThreadPoolExecutor(4) as ex:
                out = list(ex.map(one, rows))
            json.dump(out, open(p, "w"), ensure_ascii=False, indent=1)
            print(name, lang, "errors:", sum(1 for o in out if o["error"]), (out[0]["error"] or "")[:120], flush=True)


if __name__ == "__main__":
    main()
