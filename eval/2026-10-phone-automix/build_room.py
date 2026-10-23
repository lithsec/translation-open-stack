# A simulated conversation room for Live Translation's phone automixer and PA-reference tests.
#
# Four people round a table (1.2 m x 1.0 m), each with their phone 0.35 m in front of them, all
# speaking English (FLEURS en_us test sentences, CC BY 4.0) so a leak of one person's words into
# another's phone is recognisable in the transcript. Every phone hears every talker:
#   direct path   attenuated by distance (0.35 m / d) and delayed by d / 343 m/s
#   room          a synthetic diffuse tail (RT60 0.5 s, the same level at every phone)
# A room speaker 2.5 m from the table plays the "translations" (Azure TTS of other FLEURS sentences,
# en-US-AvaMultilingualNeural) through its own tail (RT60 0.7 s), 1-2 s after each turn, queued.
# Talkers differ in loudness (+3, 0, -3, -1.5 dB) and phones in gain (+2, 0, -2, +1 dB).
# Scenes: nopa (no PA), pa20 / pa10 / pa0 (PA at -20 / -10 / 0 dB against a talker at their own phone;
# pa0 is a table right under a room speaker).
# Turns: 24 (6 per talker) in random order, gaps -0.4..0.9 s (a quarter overlap the previous turn).
#
# Writes OUT/<scene>/phone<i>.wav (24 kHz mono PCM16), OUT/<scene>/pa_sent.wav (what was SENT to
# the PA, 250 ms before it sounds: the copy the app holds) and OUT/<scene>/meta.json (who said
# what, when; per-phone uplink delay). Texts and audio stay local.
#
#   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I build_room.py REAL_VOICES_DIR OUT
import json, math, os, random, sys, tarfile, urllib.request, wave
import numpy as np

RV, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, RV)
import fetch_audio as fa  # noqa: E402

R = 24000
fa.RATE = R  # to_pcm resamples to this
KEY, REGION = os.environ["AZURE_SPEECH_KEY"].strip(), os.environ["AZURE_SPEECH_REGION"].strip()
rnd = random.Random(2310)
np_rng = np.random.default_rng(2310)

SEATS = [(0.0, 0.0), (1.2, 0.0), (0.0, 1.0), (1.2, 1.0)]
CENTRE = (0.6, 0.5)
PA_POS = (0.6, 3.0)
SELF_D = 0.35
DEVICE_DELAY = 0.25  # PA sent -> sounding (playout buffer)
TALK_DB = -24.0  # mean active speech level of a talker at their own phone
# People are not equally loud and phones are not equally sensitive: per-talker level and per-phone
# gain offsets (dB), so the automixer is not flattered by four identical voices into four identical mics.
TALK_OFFSET = [3.0, 0.0, -3.0, -1.5]
PHONE_GAIN = [2.0, 0.0, -2.0, 1.0]


def phone_pos(i):
    sx, sy = SEATS[i]
    dx, dy = CENTRE[0] - sx, CENTRE[1] - sy
    n = math.hypot(dx, dy)
    return sx + dx / n * SELF_D, sy + dy / n * SELF_D


def tail(rt60, seconds, level_db):
    n = int(seconds * R)
    t = np.arange(n) / R
    env = np.exp(-6.91 * t / rt60)
    x = np_rng.standard_normal(n) * env
    x[: int(0.004 * R)] = 0  # tail starts after the direct sound
    x /= np.sqrt((x ** 2).sum())
    return x * 10 ** (level_db / 20)


def rir(d, rt60, tail_db):
    """Direct sound at distance d (gain SELF_D/d, delay d/343) plus a diffuse tail."""
    h = tail(rt60, rt60 * 1.2, tail_db)
    k = int(round(d / 343 * R))
    out = np.zeros(len(h) + k + 1)
    out[k] += min(1.0, SELF_D / d)
    out[k:k + len(h)] += h
    return out


def conv(x, h):
    n = len(x) + len(h) - 1
    m = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, m) * np.fft.rfft(h, m), m)[:n]


def active_rms(x):
    fr = R // 50
    e = np.sqrt(np.mean(x[: len(x) // fr * fr].reshape(-1, fr) ** 2, axis=1) + 1e-12)
    loud = e[e > e.max() * 0.25]
    return float(np.sqrt(np.mean(loud ** 2)))


def to_float(pcm):
    return np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768


def tts(text):
    ssml = ("<speak version='1.0' xml:lang='en-US'><voice name='en-US-AvaMultilingualNeural'>"
            + text.replace("&", "and").replace("<", "").replace(">", "") + "</voice></speak>")
    req = urllib.request.Request(f"https://{REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
                                 data=ssml.encode(), headers={
                                     "Ocp-Apim-Subscription-Key": KEY, "Content-Type": "application/ssml+xml",
                                     "X-Microsoft-OutputFormat": "raw-24khz-16bit-mono-pcm", "User-Agent": "lt-eval"})
    return to_float(urllib.request.urlopen(req, timeout=60).read())


def write(path, x):
    y = np.clip(np.round(x * 32768), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(R); w.writeframes(y.tobytes())


# --- sentences: 24 for the talkers (6 each, one gender per talker), 24 more for the PA ------------
rows = fa.fleurs_rows("en_us")
ids = sorted(rows, key=int)
rnd.shuffle(ids)
by_g = {"FEMALE": [], "MALE": []}
pa_text = []
for i in ids:
    f, text, g = rows[i][0]
    if not (8 <= len(text.split()) <= 22):
        continue
    if g in by_g and len(by_g[g]) < 12:
        by_g[g].append((i, f, text))
    elif len(pa_text) < 24:
        pa_text.append(text)
    if all(len(v) == 12 for v in by_g.values()) and len(pa_text) == 24:
        break
talker_utts = [by_g["FEMALE"][:6], by_g["MALE"][:6], by_g["FEMALE"][6:], by_g["MALE"][6:]]
need = {f for t in talker_utts for (_, f, _) in t}
audio = {}
print(f"downloading {len(need)} FLEURS files", flush=True)
with urllib.request.urlopen(f"{fa.HF}/en_us/audio/test.tar.gz", timeout=900) as resp:
    with tarfile.open(fileobj=resp, mode="r|gz") as tar:
        for m in tar:
            base = os.path.basename(m.name)
            if base in need:
                audio[base] = to_float(fa.to_pcm(tar.extractfile(m).read()))
                if len(audio) == len(need):
                    break
print("tts", flush=True)
pa_audio = [tts(t) for t in pa_text]

# --- the timeline --------------------------------------------------------------------------------
order = [(ti, k) for ti in range(4) for k in range(6)]
rnd.shuffle(order)
turns, t = [], 1.0
for ti, k in order:
    i, f, text = talker_utts[ti][k]
    x = audio[f]
    x = x / active_rms(x) * 10 ** ((TALK_DB + TALK_OFFSET[ti]) / 20)
    turns.append({"src": ti, "start": t, "end": t + len(x) / R, "text": text, "x": x})
    t = t + len(x) / R + rnd.uniform(-0.4, 0.9)
pa_turns, pa_free = [], 0.0
for k, tr in enumerate(turns):
    start = max(tr["end"] + rnd.uniform(1.0, 2.0), pa_free)
    y = pa_audio[k]
    pa_turns.append({"src": "pa", "start": start, "end": start + len(y) / R, "text": pa_text[k], "x": y})
    pa_free = start + len(y) / R + 0.3
total = max(pa_turns[-1]["end"], turns[-1]["end"]) + 2.0
N = int(total * R)

# --- render every phone --------------------------------------------------------------------------
phones = [phone_pos(i) for i in range(4)]
uplink = [round(rnd.uniform(0.12, 0.20), 3) for _ in range(4)]
paths = [[rir(math.dist(SEATS[s], phones[p]), 0.5, -12) for s in range(4)] for p in range(4)]
pa_paths = [rir(math.dist(PA_POS, phones[p]), 0.7, -6) for p in range(4)]
pa_dry = np.zeros(N)
for pt in pa_turns:
    a = int(pt["start"] * R)
    pa_dry[a:a + len(pt["x"])] += pt["x"][: max(0, N - a)]
# The PA's level at the phones: set so its active level at a phone is X dB under TALK_DB.
pa_at = [conv(pa_dry, pa_paths[p])[:N] for p in range(4)]
pa_unit = np.mean([active_rms(x) for x in pa_at])
talk_at = []
for p in range(4):
    y = np.zeros(N)
    for tr in turns:
        a = int(tr["start"] * R)
        z = conv(tr["x"], paths[p][tr["src"]])
        y[a:a + len(z)] += z[: max(0, N - a)]
    talk_at.append(y)
noise = [np_rng.standard_normal(N) * 10 ** (-62 / 20) for _ in range(4)]

meta_turns = [{"src": tr["src"], "start": round(tr["start"], 3), "end": round(tr["end"], 3), "text": tr["text"]}
              for tr in turns]
meta_pa = [{"src": "pa", "start": round(pt["start"], 3), "end": round(pt["end"], 3), "text": pt["text"]}
           for pt in pa_turns]
for scene, pa_db in (("nopa", None), ("pa20", -20.0), ("pa10", -10.0), ("pa0", 0.0)):
    d = os.path.join(OUT, scene)
    os.makedirs(d, exist_ok=True)
    g = 0.0 if pa_db is None else 10 ** ((TALK_DB + pa_db) / 20) / pa_unit
    for p in range(4):
        write(os.path.join(d, f"phone{p}.wav"), (talk_at[p] + g * pa_at[p]) * 10 ** (PHONE_GAIN[p] / 20) + noise[p])
    # The copy we SENT: the dry TTS, DEVICE_DELAY before it sounded, at the level sent (full scale-ish).
    sent = np.zeros(N)
    k = int(DEVICE_DELAY * R)
    sent[: N - k] = pa_dry[k:] * (0 if pa_db is None else 1.0)
    write(os.path.join(d, "pa_sent.wav"), sent * 10 ** (-6 / 20) / max(1e-9, np.abs(sent).max() or 1))
    json.dump({"scene": scene, "pa_db": pa_db, "rate": R, "uplink_s": uplink, "device_delay_s": DEVICE_DELAY,
               "turns": meta_turns, "pa": meta_pa if pa_db is not None else [],
               "talk_offset_db": TALK_OFFSET, "phone_gain_db": PHONE_GAIN,
               "attenuation_db": [[round(20 * math.log10(min(1, SELF_D / math.dist(SEATS[s], phones[p]))), 1)
                                   for s in range(4)] for p in range(4)]},
              open(os.path.join(d, "meta.json"), "w"), indent=1)
    print(scene, "written", flush=True)
