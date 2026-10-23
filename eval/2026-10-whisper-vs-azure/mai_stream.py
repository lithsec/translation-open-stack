# System 6: MAI-Transcribe-2-Streaming (public preview), streamed in real time in
# 100 ms chunks exactly as system 3 (azure_stream.py), with the Speech SDK 1.52.0
# and speech_config.model = "mai-transcribe-2-streaming". No language is given: the
# model detects it, and each final's detected language is kept.
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus \
#     ../2026-10-azure-stt-gemini/.venv/bin/python -I mai_stream.py CLIPS OUT TAG lang...
#
# Writes OUT/mai_stream_<TAG>_<lang>.json: the finals with audio offsets.
import json, os, sys, threading, time, wave
import azure.cognitiveservices.speech as speechsdk

KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
LOCALE = {"en": "en-US", "es": "es-ES", "pt": "pt-BR", "fr": "fr-FR", "ja": "ja-JP"}
CLIPS, OUT, TAG = sys.argv[1], sys.argv[2], sys.argv[3]


def run(lang):
    with wave.open(os.path.join(CLIPS, f"{lang}.wav")) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        pcm = w.readframes(w.getnframes())
    ep = os.environ.get("AZURE_SPEECH_ENDPOINT")   # the resource's own endpoint, if routing needs it
    cfg = speechsdk.SpeechConfig(subscription=KEY, endpoint=ep) if ep else speechsdk.SpeechConfig(subscription=KEY, region=REGION)
    cfg.model = os.environ.get("MAI_MODEL", "mai-transcribe-2-streaming")
    cfg.output_format = speechsdk.OutputFormat.Detailed
    push = speechsdk.audio.PushAudioInputStream()
    rec = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=speechsdk.audio.AudioConfig(stream=push))
    finals, err, t0 = [], [], [0.0]

    def recognized(e):
        r = e.result
        if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
            detected = r.properties.get(speechsdk.PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult, "")
            if not detected:
                try:
                    j = json.loads(r.json)
                    detected = j.get("PrimaryLanguage", {}).get("Language") or j.get("Language") or ""
                except Exception:
                    detected = ""
            finals.append({"text": r.text, "offsetMs": r.offset / 1e4, "durationMs": r.duration / 1e4,
                           "arrivedMs": (time.time() - t0[0]) * 1000, "detected": detected})

    def canceled(e):
        d = e.cancellation_details
        if d.reason == speechsdk.CancellationReason.Error:
            err.append(f"{d.code}: {d.error_details}"[:300])

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
    json.dump({"lang": lang, "model": "mai-transcribe-2-streaming", "err": err[0] if err else "", "finals": finals},
              open(os.path.join(OUT, f"mai_stream_{TAG}_{lang}.json"), "w"), ensure_ascii=False, indent=1)
    print(f"{TAG} {lang}: {'ERROR ' + err[0] if err else str(len(finals)) + ' finals'}", flush=True)


if __name__ == "__main__":
    langs = sys.argv[4:]
    for i in range(0, len(langs), 2):   # two at a time: the account allows only a few concurrent streams
        ts = [threading.Thread(target=run, args=(l,)) for l in langs[i:i + 2]]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
