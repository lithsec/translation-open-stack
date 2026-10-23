# Recognisers on the switch clips, each clip streamed in real time (100 ms chunks):
#   base       Azure continuous language ID between the pair's two locales (as Talk's table talk:
#              DetectContinuous over the universal v2 endpoint, 150 ms segmentation silence,
#              10 s forced cut)
#   az:<lang>  Azure standard real-time pinned to one locale, word timings + confidence
#   mai:<lang> MAI-Transcribe-2-Streaming pinned to one locale (public preview, East US 2)
# Partials and finals are kept with audio offsets and arrival times on the stream clock.
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus MAI_SPEECH_KEY=... MAI_SPEECH_REGION=eastus2 \
#     python -I recognize.py CLIPS OUT
import concurrent.futures as cf
import json, os, sys, threading, time, wave
import azure.cognitiveservices.speech as speechsdk

CLIPS, OUT = sys.argv[1], sys.argv[2]
LOCALE = {"en": "en-US", "es": "es-MX", "fr": "fr-FR", "pt": "pt-BR", "ja": "ja-JP"}
PAIRS = ["es", "fr", "pt", "ja"]
os.makedirs(OUT, exist_ok=True)


def config(kind, lang):
    if kind == "mai":
        cfg = speechsdk.SpeechConfig(subscription=os.environ["MAI_SPEECH_KEY"].strip(), region=os.environ["MAI_SPEECH_REGION"].strip())
        cfg.model = "mai-transcribe-2-streaming"
        cfg.speech_recognition_language = LOCALE[lang]
        return cfg, None
    key, region = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
    if kind == "az":
        cfg = speechsdk.SpeechConfig(subscription=key, region=region)
        cfg.speech_recognition_language = LOCALE[lang]
        cfg.output_format = speechsdk.OutputFormat.Detailed
        cfg.request_word_level_timestamps()
        return cfg, None
    cfg = speechsdk.SpeechConfig(subscription=key, endpoint=f"wss://{region}.stt.speech.microsoft.com/speech/universal/v2")
    cfg.set_property(speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous")
    cfg.set_property(speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "150")
    cfg.set_property_by_name("Speech_SegmentationMaximumTimeMs", "10000")
    cfg.output_format = speechsdk.OutputFormat.Detailed
    auto = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(languages=[LOCALE["en"], LOCALE[lang]])
    return cfg, auto


def run(job):
    clip, kind, lang = job
    out_p = os.path.join(OUT, f"{clip}__{kind}_{lang}.json")
    if os.path.exists(out_p):
        return out_p, "cached"
    with wave.open(os.path.join(CLIPS, f"{clip}.wav")) as w:
        pcm = w.readframes(w.getnframes())
    cfg, auto = config(kind, lang)
    push = speechsdk.audio.PushAudioInputStream()
    ac = speechsdk.audio.AudioConfig(stream=push)
    rec = (speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=ac, auto_detect_source_language_config=auto) if auto
           else speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=ac))
    partials, finals, err, t0 = [], [], [], [0.0]

    def detected(r):
        if not auto:
            return lang
        try:
            return speechsdk.AutoDetectSourceLanguageResult(r).language
        except Exception:
            return None

    def recognizing(e):
        r = e.result
        partials.append({"text": r.text, "offset": r.offset / 1e7, "duration": r.duration / 1e7,
                         "arrived": time.time() - t0[0], "lang": detected(r)})

    def recognized(e):
        r = e.result
        if r.reason != speechsdk.ResultReason.RecognizedSpeech or not r.text:
            return
        f = {"text": r.text, "offset": r.offset / 1e7, "duration": r.duration / 1e7, "arrived": time.time() - t0[0],
             "lang": detected(r)}
        try:
            j = json.loads(r.json)
            nb = (j.get("NBest") or [{}])[0]
            f["confidence"] = nb.get("Confidence")
            f["words"] = [{"w": x.get("Word"), "o": x.get("Offset", 0) / 1e7, "d": x.get("Duration", 0) / 1e7}
                          for x in nb.get("Words") or []]
        except Exception:
            pass
        finals.append(f)

    def canceled(e):
        d = e.cancellation_details
        if d.reason == speechsdk.CancellationReason.Error:
            err.append(f"{d.code}: {d.error_details}"[:300])

    rec.recognizing.connect(recognizing)
    rec.recognized.connect(recognized)
    rec.canceled.connect(canceled)
    rec.start_continuous_recognition()
    t0[0] = time.time()
    for off in range(0, len(pcm), 3200):
        if err:
            break
        push.write(pcm[off:off + 3200])
        time.sleep(max(0, t0[0] + off / 32000 + 0.1 - time.time()))
    push.write(b"\0" * 64000)
    time.sleep(2.5)
    push.close()
    time.sleep(3)
    rec.stop_continuous_recognition()
    json.dump({"clip": clip, "kind": kind, "lang": lang, "err": err[0] if err else "", "partials": partials, "finals": finals},
              open(out_p, "w"), ensure_ascii=False)
    return out_p, ("ERROR " + err[0]) if err else f"{len(finals)} finals"


jobs = []
for x in PAIRS:
    for s in ("S1", "S2", "S3"):
        c = f"{s}_{x}"
        jobs += [(c, "base", x), (c, "az", "en"), (c, "az", x), (c, "mai", "en"), (c, "mai", x)]
    jobs += [(f"ctl_{x}", "base", x), (f"ctl_{x}", "az", x), (f"ctl_{x}", "mai", x), ("ctl_en", "base", x)]
jobs += [("ctl_en", "az", "en"), ("ctl_en", "mai", "en")]
if os.environ.get("ONLY"):  # e.g. ONLY=S1_es  (a smoke run)
    jobs = [j for j in jobs if j[0] == os.environ["ONLY"]]
mai_sem = threading.Semaphore(3)


def guarded(job):
    if job[1] == "mai":
        with mai_sem:
            return run(job)
    return run(job)


with cf.ThreadPoolExecutor(8) as ex:
    for job, (p, msg) in zip(jobs, ex.map(guarded, jobs)):
        print(job, msg, flush=True)
