# Azure standard speech-to-text on the clips (build_clips.py), fed at real time in 100 ms chunks, finals regrouped
# into the read sentences by audio offset (../2026-10-translator-shootout/shootout.py group). The recogniser of
# the baseline routes: Azure for hybrid-gemma, and the stand-in for MAI (mai-gemma), which the server's resolver
# treats as the same measurement (lithos-server src/routes/resolver.ts measures()). Locales: Talk's table
# (LithosSpike/AzureStreamHub.swift locales, the server's AZURE_LOCALES).
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I stt_azure.py CLIPS_ROOT OUT [lang ...]
#   RECOGNISER=mai AZURE_SPEECH_KEY=<Lithos-Speech-eus2> AZURE_SPEECH_REGION=eastus2 python3 -I stt_azure.py ...
#
# RECOGNISER=mai: MAI-Transcribe-2-Streaming (speech_config.model "mai-transcribe-2-streaming", as Talk's
# AzureStreamHub.maiModel and ../2026-10-mai-streaming-more-languages/stream.py), pinned to the same locale, on the
# eastus2 resource; written to OUT/stt_mai/ instead of OUT/stt/. Three streams at a time (shared with production).
#
# Writes OUT/stt/<set>/<lang>.json (finals with offsets and arrival times) and <lang>.sent.json (one transcript
# per read sentence). Nothing secret is printed.
import concurrent.futures as cf, json, os, sys, time, wave
import azure.cognitiveservices.speech as speechsdk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-translator-shootout"))
from shootout import group  # noqa: E402

KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
LOCALE = {"en": "en-US", "es": "es-MX", "pt": "pt-BR", "fr": "fr-FR", "de": "de-DE", "zh": "zh-CN", "vi": "vi-VN",
          "ar": "ar-SA", "fa": "fa-IR", "tl": "fil-PH", "uk": "uk-UA", "ko": "ko-KR", "ru": "ru-RU", "hi": "hi-IN",
          "it": "it-IT"}
CLIPS, OUT = sys.argv[1], sys.argv[2]
REC = os.environ.get("RECOGNISER", "azure")


def run(lang, st):
    clips = os.path.join(CLIPS, f"clips_{st}")
    p = os.path.join(OUT, "stt" if REC == "azure" else "stt_mai", st, f"{lang}.json")
    if os.path.exists(p) and not json.load(open(p))["err"]:
        return
    with wave.open(os.path.join(clips, f"{lang}.wav")) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        pcm = w.readframes(w.getnframes())
    cfg = speechsdk.SpeechConfig(subscription=KEY, region=REGION)
    if REC == "mai":
        cfg.model = "mai-transcribe-2-streaming"
    cfg.speech_recognition_language = LOCALE[lang]
    cfg.output_format = speechsdk.OutputFormat.Detailed
    push = speechsdk.audio.PushAudioInputStream()
    rec = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=speechsdk.audio.AudioConfig(stream=push))
    finals, err, t0 = [], [], [0.0]

    def recognized(e):
        r = e.result
        if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
            finals.append({"text": r.text, "offsetMs": r.offset / 1e4, "durationMs": r.duration / 1e4,
                           "arrivedMs": (time.time() - t0[0]) * 1000})

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
    meta = json.load(open(os.path.join(clips, f"{lang}.json")))
    gold = json.load(open(os.path.join(clips, f"{lang}.txt.json")))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump({"lang": lang, "set": st, "recogniser": REC, "locale": LOCALE[lang], "err": err[0] if err else "", "finals": finals},
              open(p, "w"), ensure_ascii=False, indent=1)
    json.dump(group(finals, meta["sentences"], gold), open(p.replace(".json", ".sent.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"{st} {lang}: {'ERROR ' + err[0] if err else str(len(finals)) + ' finals'}", flush=True)


if __name__ == "__main__":
    langs = sys.argv[3:] or list(LOCALE)
    with cf.ThreadPoolExecutor(3) as ex:
        list(ex.map(lambda a: run(*a), [(l, st) for l in langs for st in ["a", "b"]]))
