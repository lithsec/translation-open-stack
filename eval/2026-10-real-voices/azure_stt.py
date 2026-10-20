# Azure live speech-to-text on audio/<lang>.wav, fed in real time (100 ms
# chunks), so "when did each final arrive" is what a room would see. Python
# because the Node SDK never reached Azure on Node 26 (no reply even to a
# wrong key), while this one answers at once.
#
#   .venv/bin/python azure_stt.py en ja zh km lo ht
#
# Key and region from the environment: AZURE_SPEECH_KEY (or SPEECH_KEY,
# AZURE_SPEECH_SUBSCRIPTION_KEY) and AZURE_SPEECH_REGION (or SPEECH_REGION,
# AZURE_REGION). Nothing secret is printed.
# Writes out/stt/<lang>.json: each final with its text, lexical form, where it
# sits in the clip (offset/duration) and when it arrived (ms since start).
import json, os, sys, threading, time, wave
import azure.cognitiveservices.speech as speechsdk

def env(*names):
    return next((os.environ[n].strip() for n in names if os.environ.get(n, "").strip()), None)

KEY = env("AZURE_SPEECH_KEY", "SPEECH_KEY", "AZURE_SPEECH_SUBSCRIPTION_KEY", "AZURE_COGNITIVE_KEY")
REGION = env("AZURE_SPEECH_REGION", "SPEECH_REGION", "AZURE_REGION", "AZURE_COGNITIVE_REGION")
LOCALE = {"en": "en-US", "ja": "ja-JP", "zh": "zh-CN", "km": "km-KH", "lo": "lo-LA", "ht": "ht-HT", "fr": "fr-FR"}


def run(lang):
    with wave.open(f"audio/{lang}.wav") as w:
        pcm = w.readframes(w.getnframes())
    cfg = speechsdk.SpeechConfig(subscription=KEY, region=REGION)
    cfg.speech_recognition_language = LOCALE[lang]
    cfg.output_format = speechsdk.OutputFormat.Detailed
    push = speechsdk.audio.PushAudioInputStream()
    rec = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=speechsdk.audio.AudioConfig(stream=push))
    finals, err, t0 = [], [], [0.0]

    def recognized(e):
        r = e.result
        if r.reason != speechsdk.ResultReason.RecognizedSpeech or not r.text:
            return
        try:
            lexical = json.loads(r.json)["NBest"][0].get("Lexical", "")
        except Exception:
            lexical = ""
        finals.append({"text": r.text, "lexical": lexical, "offsetMs": r.offset / 1e4,
                       "durationMs": r.duration / 1e4, "arrivedMs": (time.time() - t0[0]) * 1000})

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
    push.write(b"\0" * 64000)  # 2 s of silence so the last sentence closes
    time.sleep(2.5)
    push.close()
    time.sleep(3)
    rec.stop_continuous_recognition()
    os.makedirs("out/stt", exist_ok=True)
    json.dump({"lang": lang, "locale": LOCALE[lang], "err": err[0] if err else "", "finals": finals},
              open(f"out/stt/{lang}.json", "w"), ensure_ascii=False, indent=1)
    lag = sorted(f["arrivedMs"] - (f["offsetMs"] + f["durationMs"]) for f in finals)
    med = round(lag[len(lag) // 2]) if lag else None
    print(f"{lang} ({LOCALE[lang]}): " + (f"ERROR {err[0]}" if err else f"{len(finals)} finals, final arrives ~{med} ms after the words end"), flush=True)


if __name__ == "__main__":
    if not KEY or not REGION:
        sys.exit("Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION (see the header for other names it accepts).")
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    # A language already transcribed (no error) is kept; ht-HT isn't an Azure
    # locale, so asking again only repeats the refusal.
    todo = []
    for l in sys.argv[1:]:
        try:
            prev = json.load(open(f"out/stt/{l}.json"))
            if not prev["err"] or "language" in prev["err"]:
                print(f"{l}: kept ({'done' if not prev['err'] else 'not an Azure language'})", flush=True)
                continue
        except FileNotFoundError:
            pass
        todo.append(l)
    # Two at a time: the account allows only a few concurrent transcriptions
    # (six at once got 4429 "parallel requests exceeded" for three of them).
    for i in range(0, len(todo), 2):
        threads = [threading.Thread(target=run, args=(l,)) for l in todo[i:i + 2]]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
