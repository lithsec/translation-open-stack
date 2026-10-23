# Azure real-time diarization (Speech SDK ConversationTranscriber) on the same clips, fed in real time:
#   dia_pin   pinned to English (speaker labels only; the text of other languages is not used);
#             the all-Haitian R clips are pinned to French instead
#   dia_lid   with continuous language ID between the pair's two locales, if the service accepts it
# Records every final's speakerId, text, language, offset, duration and arrival time.
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python -I diarize.py OUT CLIP.wav[:pair] ...  (or @LISTFILE)
import concurrent.futures as cf
import json, os, sys, time, wave
import azure.cognitiveservices.speech as speechsdk

OUT = sys.argv[1]
LOCALE = {"en": "en-US", "es": "es-MX", "fr": "fr-FR", "pt": "pt-BR", "ja": "ja-JP"}
KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
os.makedirs(OUT, exist_ok=True)


def run(wav, pair, mode):
    name = os.path.basename(wav)[:-4]
    out_p = os.path.join(OUT, f"{name}__{mode}.json")
    if os.path.exists(out_p):
        return "cached"
    with wave.open(wav) as w:
        pcm = w.readframes(w.getnframes())
    auto = None
    if mode == "dia_lid":
        cfg = speechsdk.SpeechConfig(subscription=KEY, endpoint=f"wss://{REGION}.stt.speech.microsoft.com/speech/universal/v2")
        cfg.set_property(speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous")
        auto = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(languages=[LOCALE["en"], LOCALE[pair]])
    else:
        cfg = speechsdk.SpeechConfig(subscription=KEY, region=REGION)
        # labels only: English, except the all-Haitian R clips (pair "ht-only"), pinned to French so
        # the recogniser keeps producing segments to label (Azure has no Haitian Creole locale)
        cfg.speech_recognition_language = "fr-FR" if pair == "ht-only" else "en-US"
    cfg.set_property(speechsdk.PropertyId.SpeechServiceResponse_DiarizeIntermediateResults, "true")
    cfg.output_format = speechsdk.OutputFormat.Detailed
    push = speechsdk.audio.PushAudioInputStream()
    ac = speechsdk.audio.AudioConfig(stream=push)
    tr = (speechsdk.transcription.ConversationTranscriber(speech_config=cfg, audio_config=ac, auto_detect_source_language_config=auto)
          if auto else speechsdk.transcription.ConversationTranscriber(speech_config=cfg, audio_config=ac))
    partials, finals, err, t0 = [], [], [], [0.0]

    def lang_of(r):
        if not auto:
            return "fr-FR" if pair == "ht-only" else "en-US"
        try:
            return speechsdk.AutoDetectSourceLanguageResult(r).language
        except Exception:
            return None

    def transcribing(e):
        r = e.result
        partials.append({"spk": r.speaker_id, "text": r.text, "offset": r.offset / 1e7, "duration": r.duration / 1e7,
                         "arrived": time.time() - t0[0], "lang": lang_of(r)})

    def transcribed(e):
        r = e.result
        if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
            finals.append({"spk": r.speaker_id, "text": r.text, "offset": r.offset / 1e7, "duration": r.duration / 1e7,
                           "arrived": time.time() - t0[0], "lang": lang_of(r)})

    def canceled(e):
        d = e.cancellation_details
        if d.reason == speechsdk.CancellationReason.Error:
            err.append(f"{d.code}: {d.error_details}"[:300])

    tr.transcribing.connect(transcribing)
    tr.transcribed.connect(transcribed)
    tr.canceled.connect(canceled)
    tr.start_transcribing_async().get()
    t0[0] = time.time()
    for off in range(0, len(pcm), 3200):
        if err:
            break
        push.write(pcm[off:off + 3200])
        time.sleep(max(0, t0[0] + off / 32000 + 0.1 - time.time()))
    push.write(b"\0" * 64000)
    time.sleep(2.5)
    push.close()
    time.sleep(4)
    tr.stop_transcribing_async().get()
    json.dump({"clip": name, "mode": mode, "pair": pair, "err": err[0] if err else "", "partials": partials, "finals": finals},
              open(out_p, "w"), ensure_ascii=False)
    return ("ERROR " + err[0]) if err else f"{len(finals)} finals, speakers {sorted({f['spk'] for f in finals})}"


jobs = []
args = sys.argv[2:]
if len(args) == 1 and args[0].startswith("@"):   # a file with one CLIP.wav[:pair] per line
    args = [ln.strip() for ln in open(args[0][1:]) if ln.strip()]
for a in args:
    wav, _, pair = a.partition(":")
    for mode in (("dia_pin", "dia_lid") if pair in LOCALE and pair != "en" else ("dia_pin",)):
        jobs.append((wav, pair, mode))
with cf.ThreadPoolExecutor(8) as ex:
    for j, msg in zip(jobs, ex.map(lambda j: run(*j), jobs)):
        print(os.path.basename(j[0]), j[2], msg, flush=True)
