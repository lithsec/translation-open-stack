# Azure live speech-to-text on the held-out clips (../2026-10-held-out, regular
# pauses), fed in real time in 100 ms chunks, then regrouped into the read
# sentences by audio offset (../2026-10-translator-shootout/shootout.py group).
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus \
#     ../2026-10-azure-stt-gemini/.venv/bin/python -I stt_azure.py CLIPS OUT en es pt
#
# CLIPS = clips_reg from build_clips.py; writes OUT/stt/<lang>.json (finals with
# offsets and arrival times) and OUT/stt/<lang>.sent.json (one transcript per
# read sentence). Nothing secret is printed.
import json, os, sys, threading, time, wave
import azure.cognitiveservices.speech as speechsdk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-translator-shootout"))
from shootout import group  # noqa: E402

KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
LOCALE = {"en": "en-US", "es": "es-ES", "pt": "pt-BR"}
CLIPS, OUT = sys.argv[1], sys.argv[2]


def run(lang):
    with wave.open(os.path.join(CLIPS, f"{lang}.wav")) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        pcm = w.readframes(w.getnframes())
    cfg = speechsdk.SpeechConfig(subscription=KEY, region=REGION)
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
    meta = json.load(open(os.path.join(CLIPS, f"{lang}.json")))
    gold = json.load(open(os.path.join(CLIPS, f"{lang}.txt.json")))
    os.makedirs(os.path.join(OUT, "stt"), exist_ok=True)
    json.dump({"lang": lang, "locale": LOCALE[lang], "err": err[0] if err else "", "finals": finals},
              open(os.path.join(OUT, "stt", f"{lang}.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(group(finals, meta["sentences"], gold), open(os.path.join(OUT, "stt", f"{lang}.sent.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"{lang}: {'ERROR ' + err[0] if err else str(len(finals)) + ' finals'}", flush=True)


if __name__ == "__main__":
    # Two at a time: the account allows only a few concurrent transcriptions.
    langs = sys.argv[3:]
    for i in range(0, len(langs), 2):
        ts = [threading.Thread(target=run, args=(l,)) for l in langs[i:i + 2]]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
