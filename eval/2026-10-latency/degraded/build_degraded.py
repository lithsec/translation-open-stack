# Builds the degraded-audio clips for the live-route comparison: the first
# 15 sentences of the latency round's clips (../build_clips.py: en, es, ht,
# km; the same FLoRes sentences, same seeded pauses), each in five
# conditions, with the Oct 19 STT degradation pipeline
# (../../2026-10-real-voices/out/stt-degrade/make_conditions.py) imported and
# reused as is: the same seeded hall impulse response, the same HVAC recipe,
# the same babble pool (the real-voices clips) and the same CVSD coder.
#
#   <real-voices>/.venv/bin/python build_degraded.py <real-voices dir> <20-sentence clips> <out dir>
#
# Writes <out>/<condition>/{<lang>.wav,<lang>.json,<lang>.txt.json} and
# <out>/refs.json ({"<src>-<tgt>": [reference per sentence]}). Conditions:
#   clean          the clip
#   room-mic       make_conditions "revnoise10": hall reverb (RT60 1.5 s, DRR
#                  0 dB, a mic a few metres off) + HVAC/babble noise at 10 dB
#                  SNR, the noise also through the hall
#   noise-10dB     make_conditions "noise10": dry speech + the same noise mix
#   bt-narrowband  make_conditions "hfp_nb": 300-3400 Hz, 8 kHz, CVSD 64 kbit/s
#   hall-reverb    make_conditions "reverb"
# The noise is regenerated for each clip's length with the same recipe (not
# the same samples as Oct 19: those clips had 30 sentences). Spanish was not
# in the Oct 19 pool: its babble is the pool minus French (5 talkers, as for
# the others).
import json, os, subprocess, sys, wave
import numpy as np

RV, SRC, OUT = (os.path.abspath(a) for a in sys.argv[1:4])
N, SR = 15, 16000
sys.path.insert(0, os.path.join(RV, "out", "stt-degrade"))
import make_conditions as M  # noqa: E402  (seeds its rng at import)

LANGS = ("en", "es", "ht", "km")
DIRS = {"en-es": "es", "es-en": "en", "en-ja": "ja", "km-en": "en", "ht-en": "ht_meaning_en"}


def main():
    h = M.hall_ir()  # first rng use, as in make_conditions.main(): the identical IR
    print("IR:", M.info["ir"], flush=True)
    pool = {l: M.read(os.path.join(RV, "audio", f"{l}.wav")) for l in M.BABBLE_POOL}
    cvsd = os.path.join(OUT, "_cvsd")
    os.makedirs(OUT, exist_ok=True)
    subprocess.run(["cc", "-O2", "-o", cvsd, os.path.join(RV, "out", "stt-degrade", "cvsd.c")], check=True)
    gains = {}
    for lang in LANGS:
        meta = json.load(open(os.path.join(SRC, f"{lang}.json")))
        marks = meta["sentences"][:N]
        cut = marks[-1]["end"] + meta["gaps"][N - 1]  # sentence 15 and its pause
        x = M.read(os.path.join(SRC, f"{lang}.wav"))[: int(round(cut * SR))]
        n = len(x)
        seg = np.concatenate([x[int(m["start"] * SR):int(m["end"] * SR)] for m in marks])
        s_rms = np.sqrt(np.mean(seg ** 2))
        others = [o for o in M.BABBLE_POOL if o != lang and not (lang == "es" and o == "fr")]
        bab = np.zeros(n)
        for o in others:
            c = pool[o] / M.active_rms(pool[o], o)
            bab += np.roll(np.resize(c, n), int(M.rng.integers(0, n)))
        bab /= np.sqrt(np.mean(bab ** 2))
        noise = 0.5 ** 0.5 * M.hvac(n) + 0.5 ** 0.5 * bab
        noise /= np.sqrt(np.mean(noise ** 2))
        xr = M.conv(x, h)
        nr = M.conv(noise, h); nr /= np.sqrt(np.mean(nr ** 2))
        segr = np.concatenate([xr[int(m["start"] * SR):int(m["end"] * SR)] for m in marks])
        conds = {
            "clean": x,
            "hall-reverb": xr,
            "noise-10dB": x + noise * s_rms / 10 ** 0.5,
            "room-mic": xr + nr * np.sqrt(np.mean(segr ** 2)) / 10 ** 0.5,
        }
        for c, y in conds.items():
            d = os.path.join(OUT, c)
            M.info["clip_gain"] = {}
            M.write(os.path.join(d, f"{lang}.wav"), y, "g")
            gains[f"{c}/{lang}"] = M.info["clip_gain"]["g"]
        # Bluetooth HFP narrowband, exactly make_conditions' chain.
        c = os.path.join(OUT, "clean", f"{lang}.wav")
        a, b = os.path.join(OUT, f"_{lang}_64k.raw"), os.path.join(OUT, f"_{lang}_cvsd.raw")
        M.ff(c, a, "-af", "highpass=f=300:poles=2,highpass=f=300:poles=2,lowpass=f=3400:poles=2,lowpass=f=3400:poles=2,"
             "aresample=8000,aresample=64000", "-f", "s16le", "-ac", "1")
        with open(a, "rb") as fi, open(b, "wb") as fo:
            subprocess.run([cvsd], stdin=fi, stdout=fo, check=True)
        os.makedirs(os.path.join(OUT, "bt-narrowband"), exist_ok=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "s16le", "-ar", "64000", "-ac", "1",
                        "-i", b, "-af", "lowpass=f=3600:poles=2,lowpass=f=3600:poles=2,aresample=8000,aresample=16000",
                        "-ac", "1", "-c:a", "pcm_s16le", os.path.join(OUT, "bt-narrowband", f"{lang}.wav")], check=True)
        os.remove(a), os.remove(b)
        texts = json.load(open(os.path.join(SRC, f"{lang}.txt.json")))[:N]
        m2 = {**meta, "seconds": round(n / SR, 3), "gaps": meta["gaps"][:N], "sentences": marks}
        for c in ("clean", "hall-reverb", "noise-10dB", "room-mic", "bt-narrowband"):
            p = os.path.join(OUT, c)
            # The harness reads a 44-byte header: make sure ffmpeg's output has one.
            with wave.open(os.path.join(p, f"{lang}.wav")) as w:
                fr = w.readframes(w.getnframes())
                assert w.getframerate() == SR and w.getnchannels() == 1
            with wave.open(os.path.join(p, f"{lang}.wav"), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(fr[: n * 2])
            json.dump(m2, open(os.path.join(p, f"{lang}.json"), "w"), indent=1)
            json.dump(texts, open(os.path.join(p, f"{lang}.txt.json"), "w"), ensure_ascii=False, indent=1)
        print(lang, f"{n / SR:.0f} s", flush=True)
    os.remove(cvsd)
    r = json.load(open(os.path.join(SRC, "refs.json")))
    json.dump({d: r[k][:N] for d, k in DIRS.items()}, open(os.path.join(OUT, "refs.json"), "w"), ensure_ascii=False, indent=1)
    json.dump({"ir": M.info["ir"], "clip_gain": gains}, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "conditions.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
