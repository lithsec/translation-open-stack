# Azure alone: Azure's speech translation on audio/<src>.wav, fed in real time,
# into every target at once (one recogniser per clip, as the app runs it), plus
# how long Azure's voice takes to start speaking a sentence.
#
#   .venv/bin/python azure_translate.py en ja zh km lo
#
# English goes into ja, km, lo, ht; every other clip into English. Key and
# region from the environment, as azure_stt.py. Writes out/azure/<src>-<tgt>.json
# in the shape gemini_live.mjs writes (turns with the time each one arrived,
# ms since the clip started) plus voice_first_audio_ms: Azure's neural voice,
# time from asking to the first audio, on the first five sentences.
import json, os, sys, threading, time, wave
import azure.cognitiveservices.speech as speechsdk
from azure_stt import KEY, REGION, LOCALE

TRANSLATOR = {"zh": "zh-Hans"}  # Azure translator codes where they differ
TARGETS = {"en": ["es", "pt", "fr", "km", "lo", "ht"]}
VOICE_LOCALE = {"en": "en-US", "es": "es-MX", "pt": "pt-BR", "fr": "fr-FR", "ja": "ja-JP", "zh": "zh-CN", "km": "km-KH", "lo": "lo-LA"}  # no ht voice


def voice_latency(tgt, sentences):
    """ms from speak request to first audio chunk, Azure's default voice for the locale."""
    if tgt not in VOICE_LOCALE or not sentences:
        return None
    cfg = speechsdk.SpeechConfig(subscription=KEY, region=REGION)
    cfg.speech_synthesis_language = VOICE_LOCALE[tgt]
    cfg.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm)
    synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    out = []
    for text in sentences[:5]:
        first = [None]
        t0 = time.time()
        def chunk(e, first=first, t0=t0):
            if first[0] is None:
                first[0] = (time.time() - t0) * 1000
        synth.synthesizing.connect(chunk)
        r = synth.speak_text_async(text).get()
        synth.synthesizing.disconnect_all()
        if r.reason == speechsdk.ResultReason.SynthesizingAudioCompleted and first[0] is not None:
            out.append(round(first[0]))
    return sorted(out)[len(out) // 2] if out else None


def run(src):
    targets = TARGETS.get(src, ["en"])
    with wave.open(f"audio/{src}.wav") as w:
        pcm = w.readframes(w.getnframes())
    cfg = speechsdk.translation.SpeechTranslationConfig(subscription=KEY, region=REGION)
    cfg.speech_recognition_language = LOCALE[src]
    for t in targets:
        cfg.add_target_language(TRANSLATOR.get(t, t))
    push = speechsdk.audio.PushAudioInputStream()
    rec = speechsdk.translation.TranslationRecognizer(translation_config=cfg, audio_config=speechsdk.audio.AudioConfig(stream=push))
    turns = {t: [] for t in targets}
    err, t0 = [], [0.0]

    def recognized(e):
        r = e.result
        if r.reason != speechsdk.ResultReason.TranslatedSpeech:
            return
        at = (time.time() - t0[0]) * 1000
        for t in targets:
            said = r.translations.get(TRANSLATOR.get(t, t), "")
            if said:
                turns[t].append({"audioAt": at, "said": said, "source": r.text})

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
    os.makedirs("out/azure", exist_ok=True)
    for t in targets:
        lat = None if err else voice_latency(t, [x["said"] for x in turns[t]])
        json.dump({"direction": f"{src}-{t}", "mode": "azure", "err": err[0] if err else "",
                   "turns": turns[t], "voice_first_audio_ms": lat},
                  open(f"out/azure/{src}-{t}.json", "w"), ensure_ascii=False, indent=1)
        print(f"azure {src}-{t}: " + (f"ERROR {err[0]}" if err else
              f"{len(turns[t])} sentences, voice starts ~{lat} ms after asking" if lat is not None else
              f"{len(turns[t])} sentences, no Azure voice for {t} (captions only)"), flush=True)


if __name__ == "__main__":
    if not KEY or not REGION:
        sys.exit("Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION.")
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    # Keep what already ran; two clips at a time (the account's concurrency limit).
    todo = []
    for src in sys.argv[1:]:
        done = all(os.path.exists(f"out/azure/{src}-{t}.json") and not json.load(open(f"out/azure/{src}-{t}.json"))["err"]
                   for t in TARGETS.get(src, ["en"]))
        if done:
            print(f"{src}: kept (done)", flush=True)
        else:
            todo.append(src)
    for i in range(0, len(todo), 2):
        threads = [threading.Thread(target=run, args=(s,)) for s in todo[i:i + 2]]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
