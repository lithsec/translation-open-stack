# A live session, simulated: one clip streamed in real time (100 ms chunks) to a
# recogniser, and every final translated the moment it arrives, with the previous
# two finals as context, by each translator at once. Arrival and completion times
# are recorded against the stream's clock.
#
#   recogniser mai    MAI-Transcribe-2-Streaming (public preview), Speech SDK 1.52.0,
#                     speech_config.model = "mai-transcribe-2-streaming", no language
#                     given (it detects it). East US 2: our East US resources refuse it.
#   recogniser azure  Azure standard real-time recognition, the clip's locale given
#                     (as ../2026-10-whisper-vs-azure system 3).
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=... OPENROUTER_API_KEY=... \
#   FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=... \
#     python -I pipeline.py mai|azure CLIPS OUT TAG lang...
#
# Writes OUT/<recogniser>_<TAG>_<lang>.json: partials, finals, and per final the
# translations with their completion times.
import concurrent.futures as cf
import json, os, sys, threading, time, urllib.error, urllib.request, wave
import azure.cognitiveservices.speech as speechsdk

REC, CLIPS, OUT, TAG = sys.argv[1:5]
KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
LOCALE = {"en": "en-US", "es": "es-ES", "pt": "pt-BR", "fr": "fr-FR", "ja": "ja-JP"}
NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French", "ja": "Japanese"}
TARGETS = {"en": ["es", "pt", "fr", "ja"], "es": ["en"], "pt": ["en"], "fr": ["en"], "ja": ["en"]}
OPENROUTER = {"qwen3.5-122b@or": "qwen/qwen3.5-122b-a10b", "qwen3.8-2.4t@or": "qwen/qwen3.8-2.4t-a95b",
              "gemma-4-31b@or": "google/gemma-4-31b-it"}
# Reasoning off, except where the endpoint refuses that ("Reasoning is mandatory"): low.
REASONING = {"qwen3.8-2.4t@or": {"effort": "low"}}
TRANSLATORS = {"mai": ["sol@low", *OPENROUTER], "azure": ["sol@low"]}[REC]
POOL = cf.ThreadPoolExecutor(48)


def prompt(s, src, tgt, ctx):
    """The translator shootout's prompt (../2026-10-translator-shootout/shootout.py), plus the
    previous two finals as context, as Talk's routes pass what was just said."""
    a, b = NAMES[src], NAMES[tgt]
    c = f"Previous sentences, for context only (do not translate them): {' '.join(ctx)}\n" if ctx else ""
    return (f"Translate this {a} sentence, transcribed from live speech (it may contain recognition errors), "
            f"into natural {b}. Keep numbers, names and negation exact. Output only the {b}.\n{c}Sentence: {s}")


def post(url, body, headers, tries=6):
    data = json.dumps(body).encode()
    for attempt in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, data, {"Content-Type": "application/json", **headers}), timeout=60)), attempt
        except urllib.error.HTTPError as e:
            if e.code not in (408, 429, 500, 502, 503, 504) or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(1.5 * (attempt + 1))


def translate(name, s, src, tgt, ctx):
    p = prompt(s, src, tgt, ctx)
    if name == "sol@low":
        url = os.environ["FOUNDRY_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions"
        j, retries = post(url, {"model": os.environ["FOUNDRY_DEPLOYMENT"], "messages": [{"role": "user", "content": p}],
                                "reasoning_effort": "low"}, {"api-key": os.environ["FOUNDRY_KEY"]})
        u = j.get("usage") or {}
        return {"out": (j["choices"][0]["message"].get("content") or "").strip(), "provider": "foundry", "retries": retries,
                "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"), "cost": None}
    body = {"model": OPENROUTER[name], "messages": [{"role": "user", "content": p}], "max_tokens": 1024, "temperature": 0,
            "usage": {"include": True}, "reasoning": REASONING.get(name, {"enabled": False}),
            "provider": {"zdr": True, "data_collection": "deny"}}
    for blank in range(3):
        j, retries = post("https://openrouter.ai/api/v1/chat/completions", body,
                          {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
        text = ((j.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if text:
            break
    u = j.get("usage") or {}
    return {"out": text, "provider": j.get("provider"), "retries": retries + blank, "prompt_tokens": u.get("prompt_tokens"),
            "completion_tokens": u.get("completion_tokens"),
            "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"), "cost": u.get("cost")}


def run(lang):
    with wave.open(os.path.join(CLIPS, f"{lang}.wav")) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        pcm = w.readframes(w.getnframes())
    cfg = speechsdk.SpeechConfig(subscription=KEY, region=REGION)
    if REC == "mai":
        cfg.model = "mai-transcribe-2-streaming"
    else:
        cfg.speech_recognition_language = LOCALE[lang]
    cfg.output_format = speechsdk.OutputFormat.Detailed
    push = speechsdk.audio.PushAudioInputStream()
    rec = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=speechsdk.audio.AudioConfig(stream=push))
    partials, finals, futs, err, t0 = [], [], [], [], [0.0]
    now = lambda: (time.time() - t0[0]) * 1000

    def job(name, i, s, tgt, ctx):
        try:
            r = translate(name, s, lang, tgt, ctx)
        except Exception as e:   # recorded, scored as a blank
            r = {"out": "", "error": str(e)[:200]}
        r.update({"final": i, "translator": name, "tgt": tgt, "doneMs": now()})
        return r

    def recognizing(e):
        r = e.result
        if r.text:
            partials.append({"offsetMs": r.offset / 1e4, "arrivedMs": now(), "chars": len(r.text)})

    def recognized(e):
        r = e.result
        if r.reason != speechsdk.ResultReason.RecognizedSpeech or not r.text:
            return
        i = len(finals)
        ctx = [f["text"] for f in finals[-2:]]
        finals.append({"text": r.text, "offsetMs": r.offset / 1e4, "durationMs": r.duration / 1e4, "arrivedMs": now(),
                       "detected": r.properties.get(speechsdk.PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult, "")})
        for tgt in TARGETS[lang]:
            for name in TRANSLATORS:
                futs.append(POOL.submit(job, name, i, r.text, tgt, ctx))

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
    tr = [f.result() for f in futs]
    json.dump({"recogniser": REC, "lang": lang, "pattern": TAG, "err": err[0] if err else "", "partials": partials,
               "finals": finals, "translations": tr},
              open(os.path.join(OUT, f"{REC}_{TAG}_{lang}.json"), "w"), ensure_ascii=False, indent=1)
    blanks = sum(1 for t in tr if not t["out"])
    print(f"{REC} {TAG} {lang}: {'ERROR ' + err[0] if err else f'{len(finals)} finals, {len(tr)} translations, {blanks} blank'}", flush=True)


if __name__ == "__main__":
    langs = sys.argv[5:]
    for i in range(0, len(langs), 2):   # two streams at a time per resource
        ts = [threading.Thread(target=run, args=(l,)) for l in langs[i:i + 2]]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    POOL.shutdown()
