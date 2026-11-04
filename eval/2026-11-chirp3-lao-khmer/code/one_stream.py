# Many sentences in ONE Chirp 3 stream (1.5 s pauses), to see whether the first-text delay is a per-stream warm-up.
import json, os, sys, time
from google.cloud import speech_v2
from google.cloud.speech_v2.types import cloud_speech as cs
from google.oauth2.credentials import Credentials
from google.api_core.client_options import ClientOptions
CFG, LOCALE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
D = f"/tmp/rs/chirp/data/{CFG}"
SET = json.load(open(f"{D}/set.json"))[: int(os.environ.get("N", "5"))]
RATE, CHUNK, GAP = 16000, 3200, 1.5
audio, marks = b"", []
for it in SET:
    a = open(f"{D}/pcm/{it['file'].replace('.wav', '.raw')}", "rb").read()
    marks.append([round(len(audio) / 2 / RATE, 2), round((len(audio) + len(a)) / 2 / RATE, 2)])
    audio += a + b"\0" * int(GAP * RATE * 2)
audio += b"\0" * (5 * RATE * 2)
proj = os.environ["GCP_PROJECT"]
client = speech_v2.SpeechClient(credentials=Credentials(token=os.environ["GCP_TOKEN"], quota_project_id=proj),
                                client_options=ClientOptions(api_endpoint="us-speech.googleapis.com"))
cfg = cs.StreamingRecognitionConfig(
    config=cs.RecognitionConfig(explicit_decoding_config=cs.ExplicitDecodingConfig(encoding=cs.ExplicitDecodingConfig.AudioEncoding.LINEAR16, sample_rate_hertz=RATE, audio_channel_count=1),
                                language_codes=[LOCALE], model="chirp_3"),
    streaming_features=cs.StreamingRecognitionFeatures(interim_results=True, enable_voice_activity_events=True))
t0 = [None]
def reqs():
    yield cs.StreamingRecognizeRequest(recognizer=f"projects/{proj}/locations/us/recognizers/_", streaming_config=cfg)
    t0[0] = time.monotonic()
    for i in range(0, len(audio), CHUNK):
        yield cs.StreamingRecognizeRequest(audio=audio[i:i + CHUNK]); time.sleep(0.1)
ev = []
for resp in client.streaming_recognize(requests=reqs()):
    now = round(time.monotonic() - t0[0], 2)
    if resp.speech_event_type: ev.append([now, resp.speech_event_type.name.replace("SPEECH_ACTIVITY_", "")])
    for r in resp.results:
        if r.alternatives: ev.append([now, "FINAL" if r.is_final else "interim", len(r.alternatives[0].transcript)])
json.dump({"marks": marks, "events": ev}, open(OUT, "w"), indent=1)
print("sentence audio (start-end s):", marks)
for e in ev: print(e)
