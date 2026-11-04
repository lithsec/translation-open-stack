# Stream FLEURS sentences at real time into Google Chirp 3 or Amazon Transcribe; record the final text and how long
# after the speech ended it arrived. Usage: stream.py chirp|transcribe km_kh|lo_la DATA OUT.json
import asyncio, json, os, sys, time

SVC, CFG, DATA, OUT = sys.argv[1:5]
LOCALE = {"km_kh": "km-KH", "lo_la": "lo-LA", "en_us": "en-US"}[CFG]
RATE, CHUNK = 16000, 3200  # 100 ms of 16-bit mono
TAIL_S = 5.0               # silence streamed after the speech, like a pause before the next sentence
SET = json.load(open(os.path.join(DATA, CFG, "set.json")))[: int(os.environ.get("N", "999"))]
ENDPOINT = os.environ.get("CHIRP_ENDPOINT", "")  # STANDARD | SHORT | SUPERSHORT ("" = the default, as the first run)


def pcm(item):
    return open(os.path.join(DATA, CFG, "pcm", item["file"].replace(".wav", ".raw")), "rb").read()


# ------------------------------------------------------------------ Google Chirp 3 (Speech-to-Text v2, us)
def chirp_one(audio):
    from google.cloud import speech_v2
    from google.cloud.speech_v2.types import cloud_speech as cs
    from google.oauth2.credentials import Credentials
    from google.api_core.client_options import ClientOptions
    proj = os.environ["GCP_PROJECT"]
    creds = Credentials(token=os.environ["GCP_TOKEN"], quota_project_id=proj)
    client = speech_v2.SpeechClient(credentials=creds, client_options=ClientOptions(api_endpoint="us-speech.googleapis.com"))
    cfg = cs.StreamingRecognitionConfig(
        config=cs.RecognitionConfig(
            explicit_decoding_config=cs.ExplicitDecodingConfig(encoding=cs.ExplicitDecodingConfig.AudioEncoding.LINEAR16, sample_rate_hertz=RATE, audio_channel_count=1),
            language_codes=[LOCALE], model="chirp_3"),
        streaming_features=cs.StreamingRecognitionFeatures(
            interim_results=True, enable_voice_activity_events=True,
            **({"endpointing_sensitivity": getattr(cs.StreamingRecognitionFeatures.EndpointingSensitivity, f"ENDPOINTING_SENSITIVITY_{ENDPOINT}")} if ENDPOINT else {})))
    t = {"end": None, "first_partial": None, "start": None}
    silence = b"\0" * CHUNK

    def reqs():
        yield cs.StreamingRecognizeRequest(recognizer=f"projects/{proj}/locations/us/recognizers/_", streaming_config=cfg)
        t["start"] = time.monotonic()
        for i in range(0, len(audio), CHUNK):
            yield cs.StreamingRecognizeRequest(audio=audio[i:i + CHUNK]); time.sleep(0.1)
        t["end"] = time.monotonic()
        for _ in range(int(TAIL_S * 10)):
            yield cs.StreamingRecognizeRequest(audio=silence); time.sleep(0.1)

    finals, final_at = [], []
    t["partials"], t["events"] = [], []
    for resp in client.streaming_recognize(requests=reqs()):
        if resp.speech_event_type:
            t["events"].append([resp.speech_event_type.name.replace("SPEECH_ACTIVITY_", ""), round(time.monotonic() - t["start"], 2)])
        for r in resp.results:
            if r.alternatives and not r.is_final:
                t["partials"].append([round(time.monotonic() - t["start"], 2), len(r.alternatives[0].transcript)])
            if not r.alternatives: continue
            now = time.monotonic()
            if t["first_partial"] is None: t["first_partial"] = now
            if r.is_final:
                finals.append(r.alternatives[0].transcript); final_at.append(now)
    closed = time.monotonic()
    return finals, final_at, t, closed


# ------------------------------------------------------------------ Amazon Transcribe streaming (us-east-2)
async def transcribe_one_async(audio):
    from amazon_transcribe.client import TranscribeStreamingClient
    from amazon_transcribe.handlers import TranscriptResultStreamHandler
    client = TranscribeStreamingClient(region="us-east-2")
    stream = await client.start_stream_transcription(language_code=LOCALE, media_sample_rate_hz=RATE, media_encoding="pcm")
    finals, final_at, t = [], [], {"end": None, "first_partial": None, "start": time.monotonic()}

    class H(TranscriptResultStreamHandler):
        async def handle_transcript_event(self, ev):
            for r in ev.transcript.results:
                if not r.alternatives: continue
                now = time.monotonic()
                if t["first_partial"] is None: t["first_partial"] = now
                if not r.is_partial:
                    finals.append(r.alternatives[0].transcript); final_at.append(now)

    async def send():
        t["start"] = time.monotonic()
        for i in range(0, len(audio), CHUNK):
            await stream.input_stream.send_audio_event(audio_chunk=audio[i:i + CHUNK]); await asyncio.sleep(0.1)
        t["end"] = time.monotonic()
        for _ in range(int(TAIL_S * 10)):
            await stream.input_stream.send_audio_event(audio_chunk=b"\0" * CHUNK); await asyncio.sleep(0.1)
        await stream.input_stream.end_stream()

    await asyncio.gather(send(), H(stream.output_stream).handle_events())
    return finals, final_at, t, time.monotonic()


def run_one(audio):
    if SVC == "chirp": return chirp_one(audio)
    return asyncio.run(transcribe_one_async(audio))


out = []
for item in SET:
    audio = pcm(item)
    try:
        finals, final_at, t, closed = run_one(audio)
        last = final_at[-1] if final_at else None
        out.append({
            "file": item["file"], "ref": item["raw"], "hyp": " ".join(finals).strip(), "speech_s": round(len(audio) / 2 / RATE, 2),
            # The last final's arrival after the speech's audio ended (the tail of silence is still streaming): what a
            # live room waits. None: no final while the stream was open.
            "final_after_end_s": round(last - t["end"], 2) if last and t["end"] else None,
            "last_final_after_start_s": round(last - t["start"], 2) if last else None,
            "first_partial_after_start_s": round(t["first_partial"] - t["start"], 2) if t["first_partial"] else None,
            "partials": t.get("partials"), "events": t.get("events"),
            "finals_after_tail": sum(1 for a in final_at if t["end"] and a - t["end"] > TAIL_S),
        })
    except Exception as e:  # noqa: BLE001 - record and go on
        out.append({"file": item["file"], "ref": item["raw"], "error": f"{type(e).__name__}: {str(e)[:300]}"})
    print(SVC, CFG, len(out), out[-1].get("final_after_end_s"), out[-1].get("error", "")[:120], flush=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
