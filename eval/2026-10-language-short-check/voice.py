# Voices: which Azure neural voices exist per language, and whether the first one takes the
# apps' "T8s" pacing (mstts:silence trims plus prosody +8%, eval/2026-10-voice-rate-compact):
# one FLEURS sentence synthesised plain and paced, durations compared, time to first byte timed.
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I voice.py WORK  -> WORK/voices.json
import json, os, sys, time, urllib.request
from xml.sax.saxutils import escape

WORK = sys.argv[1]
KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
LOCALES = {"vi": ["vi-VN"], "fa": ["fa-IR"], "kea": [], "zh": ["zh-CN"], "yue": ["zh-HK"], "ar": ["ar-EG", "ar-SA"],
           "sw": ["sw-KE", "sw-TZ"], "fil": ["fil-PH"], "uk": ["uk-UA"], "tw": [], "hmn": []}


def synth(ssml):
    req = urllib.request.Request(f"https://{REGION}.tts.speech.microsoft.com/cognitiveservices/v1", data=ssml.encode(),
                                 headers={"Ocp-Apim-Subscription-Key": KEY, "Content-Type": "application/ssml+xml",
                                          "X-Microsoft-OutputFormat": "raw-24khz-16bit-mono-pcm", "User-Agent": "langcheck"})
    t0 = time.time()
    r = urllib.request.urlopen(req, timeout=60)
    first = r.read(1)
    ttfb = time.time() - t0
    data = first + r.read()
    return len(data) / 2 / 24000, ttfb


def ssml(locale, voice, text, paced):
    inner = escape(text)
    if paced:
        inner = ('<mstts:silence type="Leading-exact" value="0ms"/><mstts:silence type="Tailing-exact" value="0ms"/>'
                 '<mstts:silence type="Comma-exact" value="100ms"/>' + f'<prosody rate="+8%">{inner}</prosody>')
    return (f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='https://www.w3.org/2001/mstts' "
            f"xml:lang='{locale}'><voice name='{voice}'>{inner}</voice></speak>")


def main():
    req = urllib.request.Request(f"https://{REGION}.tts.speech.microsoft.com/cognitiveservices/voices/list",
                                 headers={"Ocp-Apim-Subscription-Key": KEY})
    voices = json.load(urllib.request.urlopen(req, timeout=60))
    sentences = json.load(open(os.path.join(WORK, "sentences.json")))
    out = {}
    for lang, locs in LOCALES.items():
        found = [v for v in voices if v["Locale"] in locs and "HD" not in v["ShortName"]]
        multi = sorted({v["ShortName"] for v in voices if "Multilingual" in v["ShortName"] and
                        any(l in (v.get("SecondaryLocaleList") or []) for l in locs)})
        entry = {"locales": locs, "voices": [v["ShortName"] for v in found], "multilingual_with_locale": multi[:6]}
        if found and lang in sentences:
            v = found[0]
            text = sentences[lang][0]["text"]
            try:
                d0, t0 = synth(ssml(v["Locale"], v["ShortName"], text, False))
                d1, t1 = synth(ssml(v["Locale"], v["ShortName"], text, True))
                entry["check"] = {"voice": v["ShortName"], "plain_s": round(d0, 2), "paced_s": round(d1, 2),
                                  "ttfb_ms": round(1000 * min(t0, t1))}
            except Exception as e:
                entry["check"] = {"voice": v["ShortName"], "error": str(e)[:160]}
        out[lang] = entry
        print(lang, len(entry["voices"]), entry.get("check"), flush=True)
    json.dump(out, open(os.path.join(WORK, "voices.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
