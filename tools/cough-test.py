#!/usr/bin/env python3
"""Does a cough make the stack speak?

Two phases against a live server:

  1. COUGHS ONLY — short noise bursts, nothing else. Any audio the server
     returns is a false start: the listener hears a voice begin and stop.
  2. PASSAGE WITH COUGHS — the same reading as coverage-test.py, with a
     cough between sentences. Word coverage must stay complete, proving the
     guard rejects noise and not speech.

Run it on the pod (needs kokoro + the GPU):
    python3 tools/cough-test.py --host 127.0.0.1:8790 --lang es
"""
import argparse, asyncio, json, re, sys
import numpy as np

PASSAGE = [
    "Good morning, and welcome to our service today.",
    "We are glad you have joined us, whether you are here in the building or listening from home.",
    "Please turn with me to the reading for this morning.",
    "The Lord is my shepherd; I shall not want.",
    "He maketh me to lie down in green pastures; he leadeth me beside the still waters.",
    "Yea, though I walk through the valley of the shadow of death, I will fear no evil.",
    "For thou art with me; thy rod and thy staff they comfort me.",
    "Let us pray together before we begin.",
]

SHORT = [
    "Amen.",
    "Yes.",
    "Hallelujah.",
    "Praise the Lord.",
    "Thank you very much.",
]

def norm(t):
    return re.sub(r"[^a-z0-9 ]", " ", t.lower()).split()

def cough(rate=24000, seed=0, voice=None):
    """A cough as the VAD sees one: voiced, not just noise.

    Pure filtered noise does not trip Silero at all (measured: speech_seen
    stays False through six bursts), which is why a cough gets through in the
    first place -- it is a glottal burst with vocal-tract resonance, so it
    looks like speech. Built here from a real synthesised vowel under a
    percussive envelope, with a noise transient for the plosive onset.
    """
    rng = np.random.default_rng(seed)
    n = int(rate * rng.uniform(0.28, 0.45))
    if voice is not None and len(voice) > n:
        start = rng.integers(0, len(voice) - n)
        body = voice[start:start + n].astype("float32").copy()
    else:
        body = rng.normal(0, 1, n).astype("float32")
    burst = rng.normal(0, 1, n).astype("float32")
    a = 0.86
    for i in range(1, n):
        burst[i] = a * burst[i - 1] + (1 - a) * burst[i]
    t = np.arange(n) / rate
    env = np.exp(-t * rng.uniform(9, 15)) * (1 - np.exp(-t * 500))
    mix = (body * 0.75 + burst * 0.45) * env
    peak = float(np.max(np.abs(mix))) or 1.0
    return (mix / peak * 0.8).astype("float32")

def real_coughs(d, rate=24000):
    """Load recorded coughs (ESC-50 class 24) and keep only the energetic part.

    Synthesised coughs do not work: filtered noise and even a vowel under a
    percussive envelope both leave Silero at speech_seen=False, while real
    coughs demonstrably reach ASR in the field. So the stimulus has to be a
    recording.
    """
    import glob, os
    from scipy.io import wavfile
    from scipy.signal import resample_poly
    out = []
    for f in sorted(glob.glob(os.path.join(d, "*.wav"))):
        sr, x = wavfile.read(f)
        x = x.astype("float32")
        if x.ndim > 1:
            x = x.mean(axis=1)
        peak = float(np.max(np.abs(x))) or 1.0
        x = x / peak
        if sr != rate:
            from math import gcd
            g = gcd(int(sr), rate)
            x = resample_poly(x, rate // g, int(sr) // g)
        # keep the span that actually contains the cough
        env = np.convolve(np.abs(x), np.ones(int(rate * 0.02)) / (rate * 0.02), "same")
        loud = np.flatnonzero(env > 0.08)
        if len(loud):
            a0 = max(0, loud[0] - int(rate * 0.05))
            a1 = min(len(x), loud[-1] + int(rate * 0.10))
            x = x[a0:a1]
        out.append((os.path.basename(f), (x * 0.9).astype("float32")))
    return out


def speak(sentences, rate=24000):
    import torch
    from kokoro import KPipeline
    pipe = KPipeline(lang_code="a", device="cuda" if torch.cuda.is_available() else "cpu")
    out = {}
    for s in sentences:
        chunks = [a for _, _, a in pipe(s, voice="am_michael")]
        out[s] = np.concatenate([c.detach().cpu().numpy() if hasattr(c, "detach")
                                 else np.asarray(c) for c in chunks]).astype("float32")
    return out

async def run(host, lang, pcm, rate, room, tail=14):
    import websockets
    heard, translated, audio_bytes = [], [], 0
    url = f"ws://{host}/translate?lang={lang}&src=auto&room={room}"
    async with websockets.connect(url, max_size=2**24, open_timeout=20) as ws:
        async def rx():
            nonlocal audio_bytes
            async for m in ws:
                if isinstance(m, bytes):
                    audio_bytes += len(m); continue
                d = json.loads(m)
                if d.get("type") == "inputTranscript": heard.append(d["text"])
                if d.get("type") == "transcript": translated.append(d.get("delta", ""))
        task = asyncio.create_task(rx())
        raw = (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()
        frame = int(rate / 10) * 2
        for i in range(0, len(raw), frame):
            await ws.send(raw[i:i + frame]); await asyncio.sleep(0.1)
        for _ in range(30):
            await ws.send(np.zeros(frame // 2, dtype="<i2").tobytes()); await asyncio.sleep(0.1)
        await asyncio.sleep(tail)
        task.cancel()
    return " ".join(heard), " ".join(translated), audio_bytes

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1:8790")
    ap.add_argument("--lang", default="es")
    ap.add_argument("--rate", type=int, default=24000)
    ap.add_argument("--phase", choices=["1", "2", "3", "4", "all"], default="all")
    ap.add_argument("--coughs", default="/workspace/coughs",
                    help="directory of recorded cough wavs (ESC-50 class 24)")
    a = ap.parse_args()
    rate, ok = a.rate, True

    if a.phase in ("1", "all"):
        clips = real_coughs(a.coughs, rate)
        if not clips:
            print(f"no cough wavs in {a.coughs} — cannot test the guard"); sys.exit(2)
        seq = [np.zeros(int(rate * 0.5), dtype="float32")]
        for name, c in clips:
            seq += [c, np.zeros(int(rate * 1.8), dtype="float32")]
        h, t, nbytes = asyncio.run(run(a.host, a.lang, np.concatenate(seq), rate, "coughonly"))
        print(f"\n=== PHASE 1: {len(clips)} recorded coughs, no speech ===")
        for name, c in clips:
            print(f"  {name}  {len(c) / rate:.2f}s")
        print(f"  heard      : {h.strip()[:160] or '(nothing)'}")
        print(f"  translated : {t.strip()[:160] or '(nothing)'}")
        print(f"  audio out  : {nbytes} bytes ({nbytes / 2 / rate:.2f}s)")
        if nbytes:
            print(f"  FAIL: coughs produced {nbytes / 2 / rate:.2f}s of audio — "
                  f"that is the voice that starts and stops."); ok = False

    if a.phase in ("2", "all"):
        voices = speak(PASSAGE, rate)
        clips = real_coughs(a.coughs, rate) if a.phase == "2" else real_coughs(a.coughs, rate)
        gap = np.zeros(int(rate * 0.8), dtype="float32")
        mixed = []
        for i, sent in enumerate(PASSAGE):
            mixed += [voices[sent], gap]
            if i % 2 == 1 and clips:
                mixed += [clips[i % len(clips)][1], gap]
        h, t, _ = asyncio.run(run(a.host, a.lang, np.concatenate(mixed), rate, "coughmixed"))
        want, got = norm(" ".join(PASSAGE)), set(norm(h))
        missing = [w for w in want if w not in got]
        dropped = [x for x in PASSAGE
                   if sum(w in got for w in norm(x)) < max(1, len(norm(x)) // 2)]
        print("\n=== PHASE 2: the reading, with a real cough after every second sentence ===")
        print(f"  heard      : {h.strip()[:200]}")
        print(f"  {a.lang:<11}: {t.strip()[:200]}")
        print(f"  coverage   : {len(want) - len(missing)}/{len(want)} words "
              f"({100 * (len(want) - len(missing)) / max(1, len(want)):.1f}%)")
        print(f"  sentences dropped: {len(dropped)}/{len(PASSAGE)}")
        for x in dropped:
            print(f"    MISSING: {x}")
        if dropped:
            print("  FAIL: the guard ate real speech."); ok = False

    if a.phase in ("3", "all"):
        # Where does the guard actually cut? Short genuine utterances are the
        # risk: a congregation says "Amen" and means it.
        shorts = speak(SHORT, rate)
        print("\n=== PHASE 3: short genuine utterances — which survive? ===")
        for phrase in SHORT:
            clip = shorts[phrase]
            seq = np.concatenate([np.zeros(int(rate * 0.4), dtype="float32"), clip])
            h, t, nbytes = asyncio.run(
                run(a.host, a.lang, seq, rate, "short" + re.sub(r"\W", "", phrase),
                    tail=10))
            verdict = "spoken" if nbytes else "DROPPED"
            print(f"  {phrase:<24} {len(clip) / rate:.2f}s  "
                  f"heard={h.strip()[:32]!r:<36} -> {verdict}")

    if a.phase in ("4", "all"):
        # The service case: English is established FIRST, then someone coughs.
        # This is the one that matters -- a cough with no prior speech has no
        # established language to be sceptical against.
        clips = real_coughs(a.coughs, rate)
        voices = speak(["Good morning, and welcome to our service today."], rate)
        seq = [voices["Good morning, and welcome to our service today."],
               np.zeros(int(rate * 1.0), dtype="float32")]
        for _, c in clips:
            seq += [c, np.zeros(int(rate * 1.8), dtype="float32")]
        h, t, _ = asyncio.run(run(a.host, a.lang, np.concatenate(seq), rate, "coughafter"))
        foreign = re.findall(r"[\u0600-\u06ff\u1780-\u17ff\u0e80-\u0eff"
                             r"\u4e00-\u9fff\u3040-\u30ff]", h)
        print("\n=== PHASE 4: English established, then coughs ===")
        print(f"  heard      : {h.strip()[:200]}")
        print(f"  {a.lang:<11}: {t.strip()[:200]}")
        print(f"  foreign-script characters after English: {len(foreign)}")
        if foreign:
            print(f"  FAIL: a cough still re-routed the language: {''.join(foreign)[:40]}")
            ok = False

    if not ok:
        sys.exit(1)
    print("\nPASS")

if __name__ == "__main__":
    main()
