# ../2026-10-complete-thought-endpointing/tts_timing.py for this run's targets: the voice's time to first audio and
# characters per second (../2026-10-simultaneous-phrases/tts.py, Azure neural TTS over REST, streamed), on 24
# random chunks of this run's sentence and CT (b) Gemma-sol output into each language.
#   en Jenny, km Sreymom, lo Keomany. Azure has no Haitian Creole voice (production voices Haitian Creole with
#   Gemini TTS, or with Coqui or MMS on omni-stt): as a stand-in, the French voice Denise reads the Haitian text.
#   That gives a speaking rate of the right kind but not Gemini TTS's own time to first audio.
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 python3 -I tts_timing.py WORK
import glob, importlib.util, json, os, random, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tts", os.path.join(HERE, "..", "2026-10-simultaneous-phrases", "tts.py"))
tts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tts)
VOICE = {"en": ("en-US", "en-US-JennyNeural"), "km": ("km-KH", "km-KH-SreymomNeural"), "lo": ("lo-LA", "lo-LA-KeomanyNeural"),
         "ht": ("fr-FR", "fr-FR-DeniseNeural")}
tts.VOICE.update(VOICE)
WORK = sys.argv[1]
random.seed(7)
out = {}
for lang in VOICE:
    texts = []
    for p in glob.glob(os.path.join(WORK, "sim", "S-sol-*", f"*_*-{lang}.json")) + \
             glob.glob(os.path.join(WORK, "sim", "ctb-gs-*", f"*_*-{lang}.json")):
        texts += [c["out"] for c in json.load(open(p))["chunks"] if c["out"].strip()]
    sample = random.sample(texts, min(24, len(texts)))
    ttfa, chars, secs = [], 0, 0.0
    for t in sample:
        a, d = tts.speak(t, lang)
        ttfa.append(round(a))
        chars += len(t)
        secs += d
    out[lang] = {"voice": VOICE[lang][1], "ttfa_ms": ttfa, "ttfa_p50": statistics.median(ttfa), "cps": round(chars / secs, 2), "n": len(sample)}
    print(lang, out[lang]["ttfa_p50"], out[lang]["cps"], flush=True)
json.dump(out, open(os.path.join(WORK, "tts.json"), "w"), indent=1)
