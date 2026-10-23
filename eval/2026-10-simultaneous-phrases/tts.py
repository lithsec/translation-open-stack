# The voice's timing, measured: Azure neural text-to-speech (REST, streamed), time
# to the first audio byte and the audio's length, on a sample of real chunks from
# the simulation (phrase chunks and whole sentences). Gives the time to first audio
# added to every chunk, and characters per second for the queued timing.
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I tts.py WORK
# Writes WORK/tts.json: {lang: {"ttfa_ms": [...], "cps": float, "n": int}}
import glob, json, os, random, statistics, sys, time, urllib.request
from xml.sax.saxutils import escape

WORK = sys.argv[1]
KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
VOICE = {"en": ("en-US", "en-US-JennyNeural"), "es": ("es-ES", "es-ES-ElviraNeural"), "pt": ("pt-BR", "pt-BR-FranciscaNeural"),
         "fr": ("fr-FR", "fr-FR-DeniseNeural"), "ja": ("ja-JP", "ja-JP-NanamiNeural")}


def speak(text, lang):
    loc, voice = VOICE[lang]
    ssml = f"<speak version='1.0' xml:lang='{loc}'><voice name='{voice}'>{escape(text)}</voice></speak>"
    req = urllib.request.Request(f"https://{REGION}.tts.speech.microsoft.com/cognitiveservices/v1", ssml.encode(),
                                 {"Ocp-Apim-Subscription-Key": KEY, "Content-Type": "application/ssml+xml",
                                  "X-Microsoft-OutputFormat": "raw-24khz-16bit-mono-pcm", "User-Agent": "eval"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as r:
        first = r.read(1)
        ttfa = (time.time() - t0) * 1000
        n = 1 + len(r.read())
    return ttfa, n / 48000.0


def main():
    random.seed(7)
    out = {}
    for lang in VOICE:
        texts = []
        for p in glob.glob(os.path.join(WORK, "sim", "P8-gemma31", f"reg_*-{lang}.json")) + \
                 glob.glob(os.path.join(WORK, "sim", "S-gemma31", f"reg_*-{lang}.json")):
            texts += [c["out"] for c in json.load(open(p))["chunks"] if c["out"].strip()]
        sample = random.sample(texts, min(24, len(texts)))
        ttfa, chars, secs = [], 0, 0.0
        for t in sample:
            a, d = speak(t, lang)
            ttfa.append(round(a))
            chars += len(t)
            secs += d
        out[lang] = {"ttfa_ms": ttfa, "ttfa_p50": statistics.median(ttfa), "cps": round(chars / secs, 2), "n": len(sample)}
        print(lang, out[lang]["ttfa_p50"], out[lang]["cps"], flush=True)
    json.dump(out, open(os.path.join(WORK, "tts.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
