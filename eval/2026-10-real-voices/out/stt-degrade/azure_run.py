# Azure Speech real-time STT (eastus) over every out/stt-degrade/audio/<cond>/<lang>.wav,
# fed exactly as ../../azure_stt.py does (100 ms chunks at real time, 2 s of
# silence at the end), three clips at once.
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus \
#     .venv/bin/python out/stt-degrade/azure_run.py [cond ...]   (from eval/2026-10-real-voices)
#
# Writes out/stt-degrade/raw/azure/<cond>/<lang>.json (same shape as out/stt/).
# A clip already done without error is skipped. Nothing secret is printed.
import json, os, sys, threading, time, wave
from concurrent.futures import ThreadPoolExecutor
import azure.cognitiveservices.speech as speechsdk

HERE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
AUD = os.path.join(HERE, "out", "stt-degrade", "audio")
RAW = os.path.join(HERE, "out", "stt-degrade", "raw", "azure")
KEY = os.environ["AZURE_SPEECH_KEY"].strip()
REGION = os.environ.get("AZURE_SPEECH_REGION", "eastus").strip()
LOCALE = {"en": "en-US", "ja": "ja-JP", "km": "km-KH", "lo": "lo-LA"}
ONLY = os.environ.get("LANGS", "").split() or list(LOCALE)
CONDS = ["clean", "reverb", "noise10", "noise5", "revnoise10", "hfp_nb", "hfp_wb", "opus12", "opus24",
         "revnoise10_hpnorm", "revnoise10_afftdn", "revnoise10_rnn"]


def run(cond, lang):
    out = os.path.join(RAW, cond, f"{lang}.json")
    with wave.open(os.path.join(AUD, cond, f"{lang}.wav")) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
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
    push.write(b"\0" * 64000)
    time.sleep(2.5)
    push.close()
    time.sleep(3)
    rec.stop_continuous_recognition()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"cond": cond, "lang": lang, "locale": LOCALE[lang], "region": REGION, "err": err[0] if err else "",
               "audio_s": len(pcm) / 32000, "finals": finals}, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"{time.strftime('%H:%M:%S')} azure {cond}/{lang}: " + (f"ERROR {err[0]}" if err else f"{len(finals)} finals"), flush=True)


if __name__ == "__main__":
    conds = sys.argv[1:] or CONDS
    todo = []
    for c in conds:
        for l in ONLY:
            p = os.path.join(RAW, c, f"{l}.json")
            if os.path.exists(p) and not json.load(open(p))["err"]:
                continue
            todo.append((c, l))
    print(f"{len(todo)} clips", flush=True)
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(lambda a: run(*a), todo))
