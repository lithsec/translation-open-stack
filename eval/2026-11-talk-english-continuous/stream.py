# Streams the style clips (build_styles.py) to Azure Speech at real time in 100 ms chunks, with Talk's English
# settings (LithosSpike/AzureStreamHub.swift on lithos-translate-app main: segmentation silence 300 ms for English,
# AzureSegmentation.silenceMs; forced cut at 20 s, AzureSegmentation.forcedTimeoutMs), pinned to en-US:
#   RECOGNISER=azure  Azure's standard model
#   RECOGNISER=mai    MAI-Transcribe-2-Streaming (speech_config.model, as AzureStreamHub.maiModel; MAI ignores the
#                     silence setting, test-routes-design.md)
# Both on the eastus2 resource (Lithos-Speech-eus2: MAI is served there; the standard model is the same everywhere).
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 RECOGNISER=mai python3 -I stream.py <styles root> <out>
# Writes <out>/<recogniser>/<set>_<style>.json: finals with offsets, durations and arrival times, and per-sentence
# transcripts (../2026-10-translator-shootout/shootout.py group). Three streams at a time. Nothing secret printed.
import concurrent.futures as cf, json, os, sys, time, wave
import azure.cognitiveservices.speech as speechsdk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-translator-shootout"))
from shootout import group  # noqa: E402

KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
REC = os.environ.get("RECOGNISER", "azure")
SILENCE_MS, FORCED_MS = 300, 20000
# SEGMENTATION=default: the SDK's own segmentation (a control: what ../2026-11-talk-soniox ran), written to
# <out>/<recogniser>-default/.
DEFAULT = os.environ.get("SEGMENTATION", "") == "default"
TAG = REC + ("-default" if DEFAULT else "")
ROOT, OUT = sys.argv[1], sys.argv[2]
CLIPS = sorted(d for d in os.listdir(ROOT) if d.startswith("clips_"))


def run(clip):
    name = clip.removeprefix("clips_")
    p = os.path.join(OUT, TAG, f"{name}.json")
    if os.path.exists(p) and not json.load(open(p))["err"]:
        return
    d = os.path.join(ROOT, clip)
    with wave.open(os.path.join(d, "en.wav")) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        pcm = w.readframes(w.getnframes())
    cfg = speechsdk.SpeechConfig(subscription=KEY, region=REGION)
    if REC == "mai":
        cfg.model = "mai-transcribe-2-streaming"
    cfg.speech_recognition_language = "en-US"
    cfg.output_format = speechsdk.OutputFormat.Detailed
    if not DEFAULT:
        cfg.set_property(speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, str(SILENCE_MS))
        cfg.set_property(speechsdk.PropertyId.Speech_SegmentationMaximumTimeMs, str(FORCED_MS))
    push = speechsdk.audio.PushAudioInputStream()
    rec = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=speechsdk.audio.AudioConfig(stream=push))
    finals, partials, err, t0 = [], [], [], [0.0]

    def recognized(e):
        r = e.result
        if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
            finals.append({"text": r.text, "offsetMs": r.offset / 1e4, "durationMs": r.duration / 1e4,
                           "arrivedMs": (time.time() - t0[0]) * 1000})

    def recognizing(e):
        partials.append((time.time() - t0[0]) * 1000)

    def canceled(e):
        x = e.cancellation_details
        if x.reason == speechsdk.CancellationReason.Error:
            err.append(f"{x.code}: {x.error_details}"[:300])

    rec.recognized.connect(recognized)
    rec.recognizing.connect(recognizing)
    rec.canceled.connect(canceled)
    rec.start_continuous_recognition()
    t0[0] = time.time()
    for off in range(0, len(pcm), 3200):
        if err:
            break
        push.write(pcm[off:off + 3200])
        time.sleep(max(0, t0[0] + off / 32000 + 0.1 - time.time()))
    push.write(b"\0" * 64000)   # 2 s of silence, as the app's 1 s gate tail and more
    time.sleep(2.5)
    push.close()
    time.sleep(3)
    rec.stop_continuous_recognition()
    meta = json.load(open(os.path.join(d, "en.json")))
    gold = json.load(open(os.path.join(d, "en.txt.json")))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump({"clip": name, "recogniser": TAG, "locale": "en-US", "silenceMs": None if DEFAULT else SILENCE_MS,
               "forcedMs": None if DEFAULT else FORCED_MS,
               "err": err[0] if err else "", "partials": len(partials), "firstPartialMs": partials[0] if partials else None,
               "finals": finals, "sentences": group(finals, meta["sentences"], gold)},
              open(p, "w"), ensure_ascii=False, indent=1)
    print(f"{TAG} {name}: {'ERROR ' + err[0] if err else str(len(finals)) + ' finals'}", flush=True)


if __name__ == "__main__":
    with cf.ThreadPoolExecutor(3) as ex:
        list(ex.map(run, CLIPS))
