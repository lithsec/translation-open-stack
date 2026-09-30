# Today's stack voices for the same 24 sentences (via the stack's own Pipeline), plus MMS for Haitian Creole.
import json, os, sys, wave, numpy as np
sys.path.insert(0, "/workspace/translation-open-stack/server")
import server
LANGS = ["km", "es", "pt", "fr", "en", "de", "ru", "zh", "ja", "ht"]
pipe = server.Pipeline(LANGS, kokoro=True, coqui=True, mms=True, mt_ct2="/workspace/mt/madlad7b-ct2",
                       voices_dir="/workspace/voices")
def save(path, pcm16):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm16)
for L in LANGS:
    os.makedirs("tts/stack", exist_ok=True)
    for i, s in enumerate(json.load(open("en.json" if L == "en" else f"src_{L}.json"))):
        pcm = pipe.synthesise(s, L)
        if pcm: save(f"tts/stack/{L}_{i:02d}.wav", pcm)
        if L == "ht":
            os.makedirs("tts/mms", exist_ok=True)
            m = pipe._synthesise_mms(s, "ht")
            if m: save(f"tts/mms/ht_{i:02d}.wav", m)
    print(L, "done", flush=True)
