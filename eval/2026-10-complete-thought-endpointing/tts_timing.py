# ../2026-10-llm-commit-policy-bedrock-de-hi-tr/tts_timing.py with Spanish (Elvira) and French (Denise) added.
# The voice's timing for these targets: ../2026-10-simultaneous-phrases/tts.py's measurement
# (Azure neural TTS over REST, streamed: time to first audio byte, characters per second), on 24
# random chunks of this run's Phrase <=8 and Sentence output into each language.
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I tts_timing.py WORK
# Writes WORK/tts.json
import glob, importlib.util, json, os, random, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tts", os.path.join(HERE, "..", "2026-10-simultaneous-phrases", "tts.py"))
tts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tts)
VOICE = {"en": ("en-US", "en-US-JennyNeural"), "es": ("es-ES", "es-ES-ElviraNeural"), "fr": ("fr-FR", "fr-FR-DeniseNeural"), "de": ("de-DE", "de-DE-KatjaNeural"),
         "hi": ("hi-IN", "hi-IN-SwaraNeural"), "tr": ("tr-TR", "tr-TR-EmelNeural")}
tts.VOICE.update(VOICE)
WORK = sys.argv[1]
random.seed(7)
out = {}
for lang in VOICE:
    texts = []
    for p in glob.glob(os.path.join(WORK, "sim", "P8-mai", f"reg_*-{lang}.json")) + \
             glob.glob(os.path.join(WORK, "sim", "S-mai", f"reg_*-{lang}.json")):
        texts += [c["out"] for c in json.load(open(p))["chunks"] if c["out"].strip()]
    sample = random.sample(texts, min(24, len(texts)))
    ttfa, chars, secs = [], 0, 0.0
    for t in sample:
        a, d = tts.speak(t, lang)
        ttfa.append(round(a))
        chars += len(t)
        secs += d
    out[lang] = {"ttfa_ms": ttfa, "ttfa_p50": statistics.median(ttfa), "cps": round(chars / secs, 2), "n": len(sample)}
    print(lang, out[lang]["ttfa_p50"], out[lang]["cps"], flush=True)
json.dump(out, open(os.path.join(WORK, "tts.json"), "w"), indent=1)
