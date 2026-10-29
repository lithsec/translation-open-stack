# MAI-Transcribe-2-Streaming, two follow-up runs on the unseen clips (../2026-10-unseen),
# streamed in real time in 100 ms chunks with the Speech SDK 1.52.0, as
# ../2026-10-whisper-vs-azure/mai_stream.py:
#
#   sent   each gold sentence as its own session (its span from the clip's
#          <lang>.json, plus 0.3 s either side, with 0.5 s of silence before and
#          after), so the model never has to cut a sentence itself
#   pin    the whole clip with speech_config.speech_recognition_language set
#          (a locale), to see whether pinning the language changes the result;
#          PIN=<locale> overrides the clip's own locale (a control: pin English
#          audio to French and see whether the output follows)
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 \
#     python -I stream.py sent|pin CLIPS OUT lang...
#
# Writes OUT/mai_sent_<lang>.json ({"sentences": [{"i", "text"}]}) or
# OUT/mai_pin<-locale>_<lang>.json ({"finals": [{"text", "offsetMs", ...}]}).
import concurrent.futures as cf
import json, os, sys, threading, time, wave
import azure.cognitiveservices.speech as speechsdk

KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
LOCALE = {"en": "en-US", "es": "es-ES", "pt": "pt-BR", "fr": "fr-FR", "ja": "ja-JP"}
MODE, CLIPS, OUT = sys.argv[1:4]
RATE = 16000


def stream(pcm, locale=None):
    """One session: pcm streamed in real time; returns (finals, error)."""
    cfg = speechsdk.SpeechConfig(subscription=KEY, region=REGION)
    cfg.model = "mai-transcribe-2-streaming"
    cfg.output_format = speechsdk.OutputFormat.Detailed
    if locale:
        cfg.speech_recognition_language = locale
    push = speechsdk.audio.PushAudioInputStream()
    rec = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=speechsdk.audio.AudioConfig(stream=push))
    finals, err, done = [], [], threading.Event()

    def recognized(e):
        r = e.result
        if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
            finals.append({"text": r.text, "offsetMs": r.offset / 1e4, "durationMs": r.duration / 1e4})

    def canceled(e):
        d = e.cancellation_details
        if d.reason == speechsdk.CancellationReason.Error:
            err.append(f"{d.code}: {d.error_details}"[:300])
        done.set()

    rec.recognized.connect(recognized)
    rec.canceled.connect(canceled)
    rec.session_stopped.connect(lambda e: done.set())
    rec.start_continuous_recognition()
    t0 = time.time()
    for off in range(0, len(pcm), 3200):
        if err:
            break
        push.write(pcm[off:off + 3200])
        time.sleep(max(0, t0 + off / 32000 + 0.1 - time.time()))
    push.write(b"\0" * 64000)
    time.sleep(2.0)
    push.close()
    done.wait(15)
    rec.stop_continuous_recognition()
    return finals, (err[0] if err else "")


def clip(lang):
    with wave.open(os.path.join(CLIPS, f"{lang}.wav")) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1
        return w.readframes(w.getnframes())


def sent(lang):
    pcm, meta = clip(lang), json.load(open(os.path.join(CLIPS, f"{lang}.json")))
    sil = b"\0" * (RATE * 2 // 2)   # 0.5 s

    def one(s):
        a = max(0, int((s["start"] - 0.3) * RATE)) * 2
        b = min(len(pcm), int((s["end"] + 0.3) * RATE) * 2)
        finals, err = stream(sil + pcm[a:b] + sil)
        return {"i": s["i"], "text": " ".join(f["text"] for f in finals), "pieces": len(finals), "err": err}

    with cf.ThreadPoolExecutor(3) as ex:   # the account allows only a few concurrent streams
        rows = list(ex.map(one, meta["sentences"]))
    json.dump({"lang": lang, "model": "mai-transcribe-2-streaming", "mode": "sentence sessions", "sentences": rows},
              open(os.path.join(OUT, f"mai_sent_{lang}.json"), "w"), ensure_ascii=False, indent=1)
    print(f"sent {lang}: {sum(r['pieces'] for r in rows)} pieces, errors {sum(bool(r['err']) for r in rows)}", flush=True)


def pin(lang):
    locale = os.environ.get("PIN") or LOCALE[lang]
    finals, err = stream(clip(lang), locale)
    tag = "" if not os.environ.get("PIN") else "-" + locale
    json.dump({"lang": lang, "model": "mai-transcribe-2-streaming", "pinned": locale, "err": err, "finals": finals},
              open(os.path.join(OUT, f"mai_pin{tag}_{lang}.json"), "w"), ensure_ascii=False, indent=1)
    print(f"pin {locale} {lang}: {'ERROR ' + err if err else str(len(finals)) + ' finals'}", flush=True)


if __name__ == "__main__":
    langs = sys.argv[4:]
    if MODE == "sent":
        for l in langs:
            sent(l)
    else:
        with cf.ThreadPoolExecutor(2) as ex:
            list(ex.map(pin, langs))
