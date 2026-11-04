# One continuous Chirp 3 stream (default endpointing) over a rebuilt October Lao clip, real time, 100 ms pieces.
import json, os, sys, time
from google.cloud import speech_v2
from google.cloud.speech_v2.types import cloud_speech as cs
from google.oauth2.credentials import Credentials
from google.api_core.client_options import ClientOptions
LANG = sys.argv[1]; LOCALE = sys.argv[2]
D = f"/tmp/rs/chirp/data/asia/{LANG}"
audio = open(f"{D}/clip.raw", "rb").read() + b"\0" * (5 * 16000 * 2)
proj = os.environ["GCP_PROJECT"]
client = speech_v2.SpeechClient(credentials=Credentials(token=os.environ["GCP_TOKEN"], quota_project_id=proj),
                                client_options=ClientOptions(api_endpoint="us-speech.googleapis.com"))
cfg = cs.StreamingRecognitionConfig(
    config=cs.RecognitionConfig(explicit_decoding_config=cs.ExplicitDecodingConfig(encoding=cs.ExplicitDecodingConfig.AudioEncoding.LINEAR16, sample_rate_hertz=16000, audio_channel_count=1),
                                language_codes=[LOCALE], model="chirp_3"),
    streaming_features=cs.StreamingRecognitionFeatures(interim_results=True, enable_voice_activity_events=True))
t0 = [None]
def reqs():
    yield cs.StreamingRecognizeRequest(recognizer=f"projects/{proj}/locations/us/recognizers/_", streaming_config=cfg)
    t0[0] = time.monotonic()
    # Paced by the clock, not by sleeping after each piece: sleeps add their overhead and drift behind real time.
    for k, i in enumerate(range(0, len(audio), 3200)):
        yield cs.StreamingRecognizeRequest(audio=audio[i:i + 3200])
        lag = t0[0] + (k + 1) * 0.1 - time.monotonic()
        if lag > 0: time.sleep(lag)
ev = []
for resp in client.streaming_recognize(requests=reqs()):
    now = round(time.monotonic() - t0[0], 2)
    if resp.speech_event_type:
        off = resp.speech_event_offset.total_seconds() if resp.speech_event_offset else None
        ev.append({"t": now, "type": resp.speech_event_type.name.replace("SPEECH_ACTIVITY_", ""), "offset": off})
    for r in resp.results:
        if r.alternatives:
            ev.append({"t": now, "type": "final" if r.is_final else "interim", "text": r.alternatives[0].transcript,
                       "end_offset": r.result_end_offset.total_seconds() if r.result_end_offset else None})
json.dump(ev, open(f"/tmp/rs/chirp/runs/asia_{LANG}_chirp.json", "w"), ensure_ascii=False, indent=1)
print(LANG, "events", len(ev), "finals", sum(e["type"] == "final" for e in ev))
