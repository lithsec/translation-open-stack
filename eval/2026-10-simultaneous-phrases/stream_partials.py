# Stream a clip at real time (100 ms chunks) to an Azure Speech recogniser and keep
# EVERY partial ("recognizing") and final, with its arrival time, so the phrase
# policies in simulate.py can be replayed against the recogniser's real timeline.
# Finals carry word-level offsets (where the recogniser returns them).
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 MODEL=mai-transcribe-2-streaming \
#     <venv with azure-cognitiveservices-speech==1.52.0>/bin/python -I stream_partials.py CLIPS OUT TAG lang...
#   (MODEL empty: Azure's standard real-time model, with the language's locale)
#
# Writes OUT/<TAG>_<lang>.json: {"partials": [{"t", "text", "offsetMs"}], "finals": [...]}
# t = ms since the first audio chunk was sent (the clip's own clock).
import json, os, sys, threading, time, wave
import azure.cognitiveservices.speech as speechsdk

KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
MODEL = os.environ.get("MODEL", "").strip()
LOCALE = {"en": "en-US", "es": "es-ES", "pt": "pt-BR", "fr": "fr-FR", "ja": "ja-JP"}
CLIPS, OUT, TAG = sys.argv[1], sys.argv[2], sys.argv[3]


def words_of(r):
    try:
        j = json.loads(r.json)
        nb = (j.get("NBest") or [{}])[0]
        return [{"w": w.get("Word"), "offsetMs": w.get("Offset", 0) / 1e4, "durationMs": w.get("Duration", 0) / 1e4}
                for w in nb.get("Words") or []]
    except Exception:
        return []


def run(lang):
    with wave.open(os.path.join(CLIPS, f"{lang}.wav")) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        pcm = w.readframes(w.getnframes())
    cfg = speechsdk.SpeechConfig(subscription=KEY, region=REGION)
    if MODEL:
        cfg.model = MODEL
    else:
        cfg.speech_recognition_language = LOCALE[lang]
    cfg.output_format = speechsdk.OutputFormat.Detailed
    cfg.request_word_level_timestamps()
    push = speechsdk.audio.PushAudioInputStream()
    rec = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=speechsdk.audio.AudioConfig(stream=push))
    partials, finals, err, t0 = [], [], [], [0.0]
    now = lambda: round((time.time() - t0[0]) * 1000, 1)

    def recognizing(e):
        r = e.result
        if r.text:
            partials.append({"t": now(), "text": r.text, "offsetMs": r.offset / 1e4})

    def recognized(e):
        r = e.result
        if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
            finals.append({"t": now(), "text": r.text, "offsetMs": r.offset / 1e4, "durationMs": r.duration / 1e4,
                           "words": words_of(r)})

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
    json.dump({"lang": lang, "model": MODEL or "standard", "err": err[0] if err else "",
               "partials": partials, "finals": finals},
              open(os.path.join(OUT, f"{TAG}_{lang}.json"), "w"), ensure_ascii=False, indent=1)
    print(f"{TAG} {lang}: {'ERROR ' + err[0] if err else f'{len(partials)} partials, {len(finals)} finals'}", flush=True)


if __name__ == "__main__":
    ts = [threading.Thread(target=run, args=(l,)) for l in sys.argv[4:]]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
