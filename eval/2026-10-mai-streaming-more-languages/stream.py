# Stream each clip in real time (100 ms chunks, Speech SDK 1.52.0), pinned to the
# language's locale, through one of:
#   mai    MAI-Transcribe-2-Streaming (speech_config.model), East US 2
#   azure  Azure's standard real-time model, East US
# recording every partial and final with its audio offset and arrival time, for
# accuracy (finals) and latency (first partial after a sentence starts, final
# after it ends) in analyze.py.
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 python -I stream.py mai CLIPS OUT lang...
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus  python -I stream.py azure CLIPS OUT lang...
#
# Writes OUT/<system>_<lang>.json: {"finals": [{"text", "offsetMs", "durationMs", "arrivedMs"}],
# "partials": [{"chars", "offsetMs", "arrivedMs"}], "err"}. arrivedMs is from the first audio byte.
import concurrent.futures as cf
import json, os, sys, threading, time, wave
import azure.cognitiveservices.speech as speechsdk

KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
LOCALE = {"vi": "vi-VN", "fa": "fa-IR", "zh": "zh-CN", "ar": "ar-EG", "sw": "sw-KE", "fil": "fil-PH", "uk": "uk-UA"}
SYSTEM, CLIPS, OUT = sys.argv[1:4]
RATE = 16000


def run(lang):
    with wave.open(os.path.join(CLIPS, f"{lang}.wav")) as w:
        pcm = w.readframes(w.getnframes())
    cfg = speechsdk.SpeechConfig(subscription=KEY, region=REGION)
    if SYSTEM == "mai":
        cfg.model = "mai-transcribe-2-streaming"
    cfg.speech_recognition_language = LOCALE[lang]
    cfg.output_format = speechsdk.OutputFormat.Detailed
    push = speechsdk.audio.PushAudioInputStream()
    rec = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=speechsdk.audio.AudioConfig(stream=push))
    finals, partials, err, done, t0 = [], [], [], threading.Event(), [0.0]
    now = lambda: (time.time() - t0[0]) * 1000

    def recognizing(e):
        r = e.result
        if r.text:
            partials.append({"chars": len(r.text), "offsetMs": r.offset / 1e4, "arrivedMs": now()})

    def recognized(e):
        r = e.result
        if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
            finals.append({"text": r.text, "offsetMs": r.offset / 1e4, "durationMs": r.duration / 1e4, "arrivedMs": now()})

    def canceled(e):
        d = e.cancellation_details
        if d.reason == speechsdk.CancellationReason.Error:
            err.append(f"{d.code}: {d.error_details}"[:300])
        done.set()

    rec.recognizing.connect(recognizing)
    rec.recognized.connect(recognized)
    rec.canceled.connect(canceled)
    rec.session_stopped.connect(lambda e: done.set())
    rec.start_continuous_recognition()
    t0[0] = time.time()
    for off in range(0, len(pcm), 3200):
        if err:
            break
        push.write(pcm[off:off + 3200])
        time.sleep(max(0, t0[0] + off / 32000 + 0.1 - time.time()))
    push.write(b"\0" * 64000)
    time.sleep(3.0)
    push.close()
    done.wait(20)
    rec.stop_continuous_recognition()
    json.dump({"lang": lang, "system": SYSTEM, "locale": LOCALE[lang], "err": err[0] if err else "",
               "finals": finals, "partials": partials},
              open(os.path.join(OUT, f"{SYSTEM}_{lang}.json"), "w"), ensure_ascii=False, indent=1)
    print(f"{SYSTEM} {lang}: {'ERROR ' + err[0] if err else str(len(finals)) + ' finals'}", flush=True)


if __name__ == "__main__":
    with cf.ThreadPoolExecutor(2) as ex:   # the account allows only a few concurrent streams
        list(ex.map(run, sys.argv[4:]))
