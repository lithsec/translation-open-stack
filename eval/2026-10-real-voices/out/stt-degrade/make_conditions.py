# Audio degradation test (2026-10-19): builds the degraded copies of
# audio/<lang>.wav under out/stt-degrade/audio/<condition>/<lang>.wav
# (16 kHz mono s16, the clip's own length; not committed, rebuild with this).
#
#   .venv/bin/python out/stt-degrade/make_conditions.py   (from eval/2026-10-real-voices)
#   needs ffmpeg (libopus, sbc, arnndn), cc (for cvsd.c) and, for rnn_denoise,
#   RNNOISE_MODEL=<path to std.rnnn from github.com/richardpl/arnndn-models>
#
# Conditions (seeded, so rebuilds are identical):
#   clean          the original
#   reverb         convolved with a synthetic hall impulse response: direct
#                  sound + 14 early reflections (7-90 ms) + exponentially
#                  decaying noise tail from 25 ms, three bands with RT60 1.6 s
#                  (<500 Hz), 1.4 s (500-4000 Hz), 0.9 s (>4 kHz); direct-to-
#                  reverberant energy 0 dB (a room mic a few metres off,
#                  outside the critical distance). Measured broadband RT60
#                  (Schroeder, T20) is printed and saved in conditions.json.
#   noise10/noise5 dry speech + noise at 10 / 5 dB SNR. Noise = half HVAC
#                  (pink + brown, equal power) and half babble (the five other
#                  clips of en/ja/km/lo/ht/fr, each level-matched, randomly
#                  rotated, summed). SNR = speech RMS over the sentence marks
#                  vs noise RMS.
#   revnoise10     reverb, then the same noise at 10 dB SNR against the
#                  reverberant speech (noise itself also through the room IR,
#                  so it sounds like it is in the same hall)
#   hfp_nb         Bluetooth HFP narrowband: 300-3400 Hz band-pass (4th order
#                  each side), 8 kHz, real CVSD at 64 kbit/s (cvsd.c, the
#                  Bluetooth spec's coder), back to 16 kHz for the recogniser
#   hfp_wb         Bluetooth HFP wideband: 50-7000 Hz band-pass, mSBC (ffmpeg
#                  sbc encoder, -msbc 1: 16 kHz, bitpool 26, ~60 kbit/s) and back
#   opus12/opus24  libopus VoIP mode at 12 / 24 kbit/s, decoded back
#   revnoise10_hpnorm   revnoise10 + highpass 80 Hz + loudnorm (single pass,
#                  I=-20 LUFS, TP=-2, i.e. a live AGC-like normaliser)
#   revnoise10_afftdn   revnoise10 + afftdn (nr=12 dB, nf=-40, noise tracking)
#   revnoise10_rnn      revnoise10 + arnndn (RNNoise std model, at 48 kHz)
# Mixes that would clip are scaled down to peak 0.98 (gain in conditions.json).
import json, os, subprocess, sys, wave
import numpy as np

HERE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
OUT = os.path.join(HERE, "out", "stt-degrade", "audio")
LANGS = ("en", "ja", "km", "lo", "ht")
BABBLE_POOL = ("en", "ja", "km", "lo", "ht", "fr")
SR = 16000
rng = np.random.default_rng(20261019)
info = {}


def read(path):
    with wave.open(path) as w:
        assert w.getframerate() == SR and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768


def write(path, x, key=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pk = np.max(np.abs(x))
    g = 1.0
    if pk > 0.98:
        g = 0.98 / pk
        x = x * g
    if key:
        info.setdefault("clip_gain", {})[key] = round(float(g), 3)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(np.clip(np.round(x * 32768), -32768, 32767).astype("<i2").tobytes())


def active_rms(x, lang):
    marks = json.load(open(os.path.join(HERE, "audio", f"{lang}.json")))["sentences"]
    seg = np.concatenate([x[int(m["start"] * SR):int(m["end"] * SR)] for m in marks])
    return np.sqrt(np.mean(seg ** 2))


def conv(x, h):
    n = len(x) + len(h) - 1
    N = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, N) * np.fft.rfft(h, N), N)[:len(x)]


def band_noise(n, lo, hi):
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    X[(f < lo) | (f >= hi)] = 0
    return np.fft.irfft(X, n)


def hall_ir():
    L = int(2.6 * SR)
    t = np.arange(L) / SR
    tail = np.zeros(L)
    for lo, hi, rt in ((0, 500, 1.6), (500, 4000, 1.4), (4000, SR / 2 + 1, 0.9)):
        b = band_noise(L, lo, hi)
        b /= np.sqrt(np.mean(b ** 2)) + 1e-12
        tail += b * np.exp(-6.9078 * t / rt) * {500: 1.0, 4000: 1.0}.get(hi, 0.6)
    onset = int(0.025 * SR)
    tail[:onset] = 0
    tail[onset:onset + 160] *= np.linspace(0, 1, 160)  # fade the diffuse tail in
    early = np.zeros(L)
    for d in np.sort(rng.uniform(0.007, 0.09, 14)):
        early[int(d * SR)] += rng.choice([-1, 1]) * 0.7 * np.exp(-d / 0.05)
    # reverberant energy: 30 % early reflections, 70 % diffuse tail
    h = tail / np.sqrt(np.sum(tail ** 2)) * np.sqrt(0.7) + early / np.sqrt(np.sum(early ** 2)) * np.sqrt(0.3)
    h[0] = 1.0  # direct sound; DRR = 1 / (sum of everything else) = 0 dB
    h[1:] *= 1.0 / np.sqrt(np.sum(h[1:] ** 2))
    # Schroeder T20 (-5..-25 dB) extrapolated to 60 dB
    edc = np.cumsum((h ** 2)[::-1])[::-1]
    edc_db = 10 * np.log10(edc / edc[0])
    i5, i25 = np.argmax(edc_db <= -5), np.argmax(edc_db <= -25)
    info["ir"] = {"rt60_T20_s": round(3 * (i25 - i5) / SR, 2),
                  "rt60_T30_s": round(2 * (np.argmax(edc_db <= -35) - i5) / SR, 2),
                  "drr_db": round(float(10 * np.log10(h[0] ** 2 / np.sum(h[1:] ** 2))), 1),
                  "length_s": L / SR}
    return h


def hvac(n):
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    f[0] = f[1]
    pink = np.fft.irfft(X / np.sqrt(f), n)
    brown = np.fft.irfft(np.fft.rfft(rng.standard_normal(n)) / f, n)
    pink /= np.sqrt(np.mean(pink ** 2)); brown /= np.sqrt(np.mean(brown ** 2))
    x = pink + brown
    return x / np.sqrt(np.mean(x ** 2))


def babble(lang, n, clips):
    out = np.zeros(n)
    for o in BABBLE_POOL:
        if o == lang:
            continue
        c = clips[o] / active_rms(clips[o], o)
        c = np.roll(np.resize(c, n), int(rng.integers(0, n)))
        out += c
    return out / np.sqrt(np.mean(out ** 2))


def ff(src, dst, *args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src, *args, dst], check=True)


def main():
    clips = {l: read(os.path.join(HERE, "audio", f"{l}.wav")) for l in BABBLE_POOL}
    h = hall_ir()
    print("IR:", info["ir"], flush=True)
    os.makedirs(OUT, exist_ok=True)
    cvsd = os.path.join(OUT, "cvsd")
    subprocess.run(["cc", "-O2", "-o", cvsd, os.path.join(HERE, "out", "stt-degrade", "cvsd.c")], check=True)
    model = os.environ.get("RNNOISE_MODEL")
    tmp = os.path.join(OUT, "_tmp")
    os.makedirs(tmp, exist_ok=True)
    for lang in LANGS:
        x = clips[lang]
        n = len(x)
        s_rms = active_rms(x, lang)
        noise = 0.5 ** 0.5 * hvac(n) + 0.5 ** 0.5 * babble(lang, n, clips)
        noise /= np.sqrt(np.mean(noise ** 2))
        p = lambda c: os.path.join(OUT, c, f"{lang}.wav")
        write(p("clean"), x)
        xr = conv(x, h)
        write(p("reverb"), xr, f"reverb/{lang}")
        for snr in (10, 5):
            write(p(f"noise{snr}"), x + noise * s_rms / 10 ** (snr / 20), f"noise{snr}/{lang}")
        nr = conv(noise, h); nr /= np.sqrt(np.mean(nr ** 2))
        write(p("revnoise10"), xr + nr * active_rms(xr, lang) / 10 ** (10 / 20), f"revnoise10/{lang}")
        # Bluetooth narrowband: band-pass, 8 kHz, CVSD @ 64 kHz bit clock, back to 16 kHz
        c = p("clean")
        nb_in, nb_out = os.path.join(tmp, f"{lang}_64k.raw"), os.path.join(tmp, f"{lang}_64k_cvsd.raw")
        ff(c, nb_in, "-af", "highpass=f=300:poles=2,highpass=f=300:poles=2,lowpass=f=3400:poles=2,lowpass=f=3400:poles=2,"
           "aresample=8000,aresample=64000", "-f", "s16le", "-ac", "1")
        with open(nb_in, "rb") as fi, open(nb_out, "wb") as fo:
            subprocess.run([cvsd], stdin=fi, stdout=fo, check=True)
        os.makedirs(os.path.join(OUT, "hfp_nb"), exist_ok=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "s16le", "-ar", "64000", "-ac", "1",
                        "-i", nb_out, "-af", "lowpass=f=3600:poles=2,lowpass=f=3600:poles=2,aresample=8000,aresample=16000",
                        "-ac", "1", "-c:a", "pcm_s16le", p("hfp_nb")], check=True)
        # Bluetooth wideband: 50-7000 Hz, mSBC
        sbc = os.path.join(tmp, f"{lang}.msbc")
        ff(c, sbc, "-af", "highpass=f=50:poles=2,lowpass=f=7000:poles=2,lowpass=f=7000:poles=2",
           "-ar", "16000", "-ac", "1", "-c:a", "sbc", "-msbc", "1", "-f", "sbc")
        os.makedirs(os.path.join(OUT, "hfp_wb"), exist_ok=True)
        ff(sbc, p("hfp_wb"), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le")
        for kb in (12, 24):
            op = os.path.join(tmp, f"{lang}_{kb}.ogg")
            ff(c, op, "-c:a", "libopus", "-b:a", f"{kb}k", "-application", "voip", "-vbr", "on")
            os.makedirs(os.path.join(OUT, f"opus{kb}"), exist_ok=True)
            ff(op, p(f"opus{kb}"), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le")
        rn = p("revnoise10")
        for cond, af in (("revnoise10_hpnorm", "highpass=f=80,loudnorm=I=-20:TP=-2:LRA=11,aresample=16000"),
                         ("revnoise10_afftdn", "afftdn=nr=12:nf=-40:tn=1"),
                         ("revnoise10_rnn", f"aresample=48000,arnndn=m={model},aresample=16000" if model else None)):
            if not af:
                print(f"{cond}: skipped (set RNNOISE_MODEL)")
                continue
            os.makedirs(os.path.join(OUT, cond), exist_ok=True)
            ff(rn, p(cond), "-af", af, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le")
        print(lang, "done", flush=True)
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    json.dump(info, open(os.path.join(HERE, "out", "stt-degrade", "conditions.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
