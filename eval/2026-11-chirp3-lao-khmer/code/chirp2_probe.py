# Does chirp_2 stream Lao (us-central1)? One FLEURS sentence; prints the first results or the error.
import json, os, time
from google.cloud import speech_v2
from google.cloud.speech_v2.types import cloud_speech as cs
from google.oauth2.credentials import Credentials
from google.api_core.client_options import ClientOptions
proj = os.environ["GCP_PROJECT"]; LOC = os.environ.get("LOC", "us-central1"); LANG = os.environ.get("LANG_CODE", "lo-LA")
client = speech_v2.SpeechClient(credentials=Credentials(token=os.environ["GCP_TOKEN"], quota_project_id=proj),
                                client_options=ClientOptions(api_endpoint=f"{LOC}-speech.googleapis.com"))
cfg = cs.StreamingRecognitionConfig(config=cs.RecognitionConfig(
    explicit_decoding_config=cs.ExplicitDecodingConfig(encoding=cs.ExplicitDecodingConfig.AudioEncoding.LINEAR16, sample_rate_hertz=16000, audio_channel_count=1),
    language_codes=[LANG], model="chirp_2"), streaming_features=cs.StreamingRecognitionFeatures(interim_results=True))
s = json.load(open("data/lo_la/set.json"))[0]
audio = open("data/lo_la/pcm/" + s["file"].replace(".wav", ".raw"), "rb").read()
def reqs():
    yield cs.StreamingRecognizeRequest(recognizer=f"projects/{proj}/locations/{LOC}/recognizers/_", streaming_config=cfg)
    for i in range(0, len(audio), 3200):
        yield cs.StreamingRecognizeRequest(audio=audio[i:i + 3200]); time.sleep(0.1)
try:
    n = 0
    for resp in client.streaming_recognize(requests=reqs()):
        for r in resp.results:
            if r.alternatives: n += 1; print("final" if r.is_final else "interim", r.alternatives[0].transcript[:60])
    print("results", n)
except Exception as e:
    print(type(e).__name__, str(e)[:400])
