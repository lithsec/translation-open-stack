# Real Azure neural text-to-speech for every chunk, as ../2026-10-voice-rate-compact/tts_rates.py, on the
# conversational clips: four variants (V0 current +0%, V2 current +20%, V3 concise +15%, V4 concise +0%),
# phrase mode (P8) and whole sentences (S), five directions, English voice added for the into-English ones.
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I tts_conv.py WORK
# Writes WORK/tts/<variant>-<mode>/conv_<src>-<tgt>.json: per chunk {ttfa_ms, seconds}, and
# WORK/samples/*.wav: each direction's first 3 sentences in phrase mode per variant (not committed).
import concurrent.futures as cf
import hashlib, json, os, sys, time, urllib.error, urllib.request, wave
from xml.sax.saxutils import escape

WORK = sys.argv[1]
KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
VOICE = {"en": ("en-US", "en-US-JennyNeural"), "es": ("es-ES", "es-ES-ElviraNeural"), "pt": ("pt-BR", "pt-BR-FranciscaNeural"), "fr": ("fr-FR", "fr-FR-DeniseNeural")}
VARIANTS = {"V0": ("cur", 0), "V2": ("cur", 20), "V3": ("con", 15), "V4": ("con", 0)}
MODES = {"P8": "P8", "S": "S"}
DIRS = ["en-es", "en-pt", "en-fr", "es-en", "fr-en"]
CACHE = os.path.join(WORK, "tts", "cache")
SAMPLE_SENTENCES = 3


def speak(text, lang, rate):
    """(ttfa_ms, seconds, pcm bytes) for one chunk."""
    h = hashlib.sha1(f"{lang}|{rate}|{text}".encode()).hexdigest()
    meta_p, pcm_p = os.path.join(CACHE, h + ".json"), os.path.join(CACHE, h + ".pcm")
    if os.path.exists(meta_p) and os.path.exists(pcm_p):
        m = json.load(open(meta_p))
        return m["ttfa_ms"], m["seconds"], open(pcm_p, "rb").read()
    loc, voice = VOICE[lang]
    ssml = (f"<speak version='1.0' xml:lang='{loc}'><voice name='{voice}'><prosody rate='{rate:+d}%'>"
            f"{escape(text)}</prosody></voice></speak>")
    for attempt in range(8):
        req = urllib.request.Request(f"https://{REGION}.tts.speech.microsoft.com/cognitiveservices/v1", ssml.encode(),
                                     {"Ocp-Apim-Subscription-Key": KEY, "Content-Type": "application/ssml+xml",
                                      "X-Microsoft-OutputFormat": "raw-24khz-16bit-mono-pcm", "User-Agent": "eval"})
        try:
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=60) as r:
                first = r.read(1)
                ttfa = (time.time() - t0) * 1000
                pcm = first + r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 7:
                raise
            time.sleep(2 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            if attempt == 7:
                raise
            time.sleep(2 * (attempt + 1))
    secs = len(pcm) / 48000.0
    open(pcm_p, "wb").write(pcm)
    json.dump({"ttfa_ms": round(ttfa), "seconds": round(secs, 3)}, open(meta_p, "w"))
    return round(ttfa), round(secs, 3), pcm


def one(job):
    var, mode, pattern, d = job
    prompt, rate = VARIANTS[var]
    tgt = d.split("-")[1]
    sim = json.load(open(os.path.join(WORK, "sim", f"{mode}-{prompt}", f"{pattern}_{d}.json")))
    out_p = os.path.join(WORK, "tts", f"{var}-{mode}", f"{pattern}_{d}.json")
    rows, pcms = [], []
    for c in sim["chunks"]:
        text = c["out"].strip()
        if not text:
            rows.append({"ttfa_ms": 0, "seconds": 0.0})
            pcms.append(b"")
            continue
        ttfa, secs, pcm = speak(text, tgt, rate)
        rows.append({"ttfa_ms": ttfa, "seconds": secs})
        pcms.append(pcm)
    os.makedirs(os.path.dirname(out_p), exist_ok=True)
    json.dump({"variant": var, "mode": mode, "rate": rate, "prompt": prompt, "chunks": rows}, open(out_p, "w"), indent=1)
    if pattern == "conv" and mode == "P8":   # listening samples: first sentences' chunks, in order
        seg = json.load(open(os.path.join(WORK, "seg", f"{mode}-{prompt}", f"{pattern}_{d}.json")))
        owner, spans = seg["chunk_of_char"], seg["spans"][:SAMPLE_SENTENCES]
        lo = min(a for a, _ in spans if a is not None)
        hi = max(b for _, b in spans if b is not None)
        ks = sorted({owner[k] for k in range(lo, hi)})
        wav_p = os.path.join(WORK, "samples", f"{d}_{var}.wav")
        with wave.open(wav_p, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000)
            for k in ks:
                w.writeframes(pcms[k])
    return job, len(rows)


if __name__ == "__main__":
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(os.path.join(WORK, "samples"), exist_ok=True)
    jobs = [(v, m, p, d) for v in VARIANTS for m in MODES for p in ("conv",) for d in DIRS]
    with cf.ThreadPoolExecutor(int(os.environ.get("THREADS", "6"))) as ex:
        for job, n in ex.map(one, jobs):
            print(*job, n, flush=True)
