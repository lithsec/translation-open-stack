# One streaming setup for both recognisers, both clip sets: the November round's stt_azure.py settings (Speech SDK,
# the clip fed at real time in 100 ms chunks, 2 s of silence after it, the language pinned, Detailed output, the
# recogniser's display text), on the same machine, the same day, the same SDK.
#
#   REC=azure AZURE_SPEECH_KEY=<Lithos-Speech> AZURE_SPEECH_REGION=eastus  python3 -I stream.py JOBS.json OUT RUN
#   REC=mai   AZURE_SPEECH_KEY=<Lithos-Speech-eus2> AZURE_SPEECH_REGION=eastus2 python3 -I stream.py JOBS.json OUT RUN
#
# JOBS.json: [{"id": "oct-en", "wav": ".../en.wav", "locale": "en-US"}, ...]. Writes OUT/<RUN>/<REC>/<id>.json with
# the finals (text, offsets, arrival) and whatever model / version fields the service returned in the result JSON.
# Three streams at a time per recogniser (production shares these limits). Nothing secret is printed.
import concurrent.futures as cf, json, os, sys, time, wave
import azure.cognitiveservices.speech as speechsdk

KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
REC = os.environ["REC"]
JOBS, OUT, RUN = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3]
TOP = ("Id", "RecognitionStatus", "Offset", "Duration", "Channel", "DisplayText", "NBest", "SpeakerId", "Type",
       "PrimaryLanguage")


def run(job):
    p = os.path.join(OUT, RUN, REC, f"{job['id']}.json")
    if os.path.exists(p) and not json.load(open(p))["err"]:
        return
    with wave.open(job["wav"]) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        pcm = w.readframes(w.getnframes())
    cfg = speechsdk.SpeechConfig(subscription=KEY, region=REGION)
    if REC == "mai":
        cfg.model = "mai-transcribe-2-streaming"
    cfg.speech_recognition_language = job["locale"]
    cfg.output_format = speechsdk.OutputFormat.Detailed
    push = speechsdk.audio.PushAudioInputStream()
    rec = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=speechsdk.audio.AudioConfig(stream=push))
    finals, err, extra, t0 = [], [], {}, [0.0]

    def recognized(e):
        r = e.result
        if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
            finals.append({"text": r.text, "offsetMs": r.offset / 1e4, "durationMs": r.duration / 1e4,
                           "arrivedMs": (time.time() - t0[0]) * 1000})
            try:   # any field beyond the usual ones (a model name or version, if the service sends one)
                j = json.loads(r.json)
                for k, v in j.items():
                    if k not in TOP:
                        extra.setdefault(k, v if isinstance(v, (str, int, float)) else json.dumps(v)[:200])
            except Exception:
                pass

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
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump({"id": job["id"], "recogniser": REC, "region": REGION, "locale": job["locale"],
               "sdk": speechsdk.__version__, "audio_s": round(len(pcm) / 32000, 1), "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "err": err[0] if err else "", "extra_fields": extra, "finals": finals},
              open(p, "w"), ensure_ascii=False, indent=1)
    print(f"{RUN} {REC} {job['id']}: {'ERROR ' + err[0] if err else str(len(finals)) + ' finals'} extra={sorted(extra)}",
          flush=True)


if __name__ == "__main__":
    with cf.ThreadPoolExecutor(3) as ex:
        list(ex.map(run, JOBS))
