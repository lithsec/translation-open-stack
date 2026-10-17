# Source audio for the Azure STT -> Gemini round: the 24 test sentences of
# eval/2026-09-model-eval, spoken the way September's were (macOS voices; Meta
# MMS where macOS has none), joined with 0.8 s pauses into one clip per
# language, plus the time each sentence starts and ends in that clip.
#
#   python3 make_audio.py en ja zh            # macOS voices, no Python deps
#   .venv/bin/python make_audio.py km lo ht   # MMS: needs torch, transformers, scipy
#
# Writes audio/<lang>.wav (16 kHz mono s16) and audio/<lang>.json.
import json, os, subprocess, sys, tempfile, wave

HERE = os.path.dirname(os.path.abspath(__file__))
SENT = os.path.join(HERE, "..", "2026-09-model-eval", "sentences")
OUT = os.path.join(HERE, "audio")
SAY = {"en": "Samantha", "ja": "Kyoko", "zh": "Tingting"}
MMS = {"km": "facebook/mms-tts-khm", "lo": "facebook/mms-tts-lao", "ht": "facebook/mms-tts-hat"}
RATE, GAP = 16000, 0.8


def sentences(lang):
    f = "en.json" if lang == "en" else f"src_{lang}.json"
    return json.load(open(os.path.join(SENT, f)))


def say_pcm(lang, text):
    with tempfile.TemporaryDirectory() as d:
        aiff, wav = os.path.join(d, "s.aiff"), os.path.join(d, "s.wav")
        subprocess.run(["say", "-v", SAY[lang], "-o", aiff, text], check=True)
        subprocess.run(["sox", aiff, "-r", str(RATE), "-c", "1", "-b", "16", wav], check=True)
        with wave.open(wav) as w:
            return w.readframes(w.getnframes())


_mms = {}
def mms_pcm(lang, text):
    import numpy as np, torch
    from transformers import VitsModel, AutoTokenizer
    if lang not in _mms:
        _mms[lang] = (VitsModel.from_pretrained(MMS[lang]), AutoTokenizer.from_pretrained(MMS[lang]))
    model, tok = _mms[lang]
    with torch.no_grad():
        wav = model(**tok(text, return_tensors="pt")).waveform[0].numpy()
    sr = model.config.sampling_rate
    if sr != RATE:  # MMS speaks at 16 kHz already; resample only if a checkpoint differs
        from scipy.signal import resample_poly
        wav = resample_poly(wav, RATE, sr)
    return (np.clip(wav, -1, 1) * 32767).astype("<i2").tobytes()


def build(lang):
    pcm, marks, t = bytearray(), [], 0.0
    silence = b"\0\0" * int(GAP * RATE)
    pcm += silence
    t += GAP
    for i, text in enumerate(sentences(lang)):
        s = say_pcm(lang, text) if lang in SAY else mms_pcm(lang, text)
        dur = len(s) / 2 / RATE
        marks.append({"i": i, "start": round(t, 3), "end": round(t + dur, 3)})
        pcm += s + silence
        t += dur + GAP
    os.makedirs(OUT, exist_ok=True)
    with wave.open(os.path.join(OUT, f"{lang}.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(bytes(pcm))
    json.dump({"lang": lang, "rate": RATE, "seconds": round(t, 3), "sentences": marks},
              open(os.path.join(OUT, f"{lang}.json"), "w"), indent=1)
    print(f"{lang}: {len(marks)} sentences, {t:.1f} s", flush=True)


if __name__ == "__main__":
    for lang in sys.argv[1:] or ["en", "ja", "zh"]:
        build(lang)
