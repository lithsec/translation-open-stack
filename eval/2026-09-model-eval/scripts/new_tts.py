# Kokoro and Piper candidates for the new languages: sentences 0-7, native text.
import io, json, os, sys, time, urllib.request, wave
import numpy as np, soundfile as sf
VOICES = "/workspace/voices"
PIPER = {"ar": ["ar_JO-kareem-medium"], "hi": ["hi_IN-priyamvada-medium", "hi_IN-rohan-medium"], "vi": ["vi_VN-vais1000-medium"],
         "ko": ["ko_KR-kss-medium"], "fa": ["fa_IR-amir-medium", "fa_IR-gyro-medium", "fa_IR-reza_ibrahim-medium"],
         "id": ["id_ID-news_tts-medium"], "tr": ["tr_TR-dfki-medium"], "bn": ["bn_BD-google-medium"],
         "ur": ["ur_PK-fasih-medium", "ur_PK-aegis_female-medium"], "it": ["it_IT-serena-high"], "sw": ["sw_CD-lanfrica-medium"]}
KOKORO = {"hi": ("h", "hf_alpha"), "it": ("i", "if_sara")}
BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
def fetch(v):
    lang, rest = v.split("_", 1); region = v.split("-")[0]; name, q = v.split("-")[1], v.split("-")[2]
    for ext in (".onnx", ".onnx.json"):
        p = f"{VOICES}/{v}{ext}"
        if not os.path.exists(p):
            urllib.request.urlretrieve(f"{BASE}/{lang}/{region}/{name}/{q}/{v}{ext}", p)
from piper import PiperVoice
stats = {}
for L, vs in PIPER.items():
    S = json.load(open(f"src_{L}.json"))
    for v in vs:
        fetch(v); voice = PiperVoice.load(f"{VOICES}/{v}.onnx")
        pt = getattr(voice.config, "phoneme_type", ""); lower = getattr(pt, "value", pt) == "text"
        d = f"tts/piper-{v}"; os.makedirs(d, exist_ok=True); t = time.time(); aud = 0
        for i in range(8):
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w: voice.synthesize_wav(S[i].lower() if lower else S[i], w)
            buf.seek(0); x, sr = sf.read(buf); sf.write(f"{d}/{L}_{i:02d}.wav", x, sr); aud += len(x) / sr
        stats[f"piper-{v}"] = round((time.time() - t) / aud, 3); print(L, v, "rtf", stats[f"piper-{v}"], flush=True)
from kokoro import KPipeline
for L, (code, voice) in KOKORO.items():
    S = json.load(open(f"src_{L}.json")); kp = KPipeline(lang_code=code, repo_id="hexgrad/Kokoro-82M")
    d = f"tts/kokoro-{voice}"; os.makedirs(d, exist_ok=True)
    for i in range(8):
        x = np.concatenate([np.asarray(a) for _, _, a in kp(S[i], voice=voice)]); sf.write(f"{d}/{L}_{i:02d}.wav", x, 24000)
    print(L, "kokoro", voice, flush=True)
json.dump(stats, open("new_tts_stats.json", "w"), indent=1)
