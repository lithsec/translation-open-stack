# Speaker-tracking clips with the SAME speakers returning (FLEURS has no speaker ids, so every
# FLEURS utterance in S1-S3 is a different reader). CMU Haitian speech, three speakers:
#   R1  one speaker for ~60 s (false new speakers)
#   R2  two speakers alternating, each returning 4 times (0.2-0.5 s gaps)
#   R3  three speakers in rotation, each returning 3 times
# Utterances trimmed and brought to one level as in build_clips.py.
#   python3 -I build_dia_clips.py OUT   (downloads ~90 CMU utterances into OUT/cmu, local only)
import json, os, random, sys, urllib.request, wave
import numpy as np

OUT = sys.argv[1]
CMU = "http://speech.cs.cmu.edu/haitian/speech/data/cmu_haitian_speech"
R = 16000
os.makedirs(os.path.join(OUT, "cmu"), exist_ok=True)
lines = urllib.request.urlopen(f"{CMU}/etc/txt.done.data", timeout=60).read().decode("utf-8").splitlines()
by = {}
for ln in lines:
    p = ln.strip().split('"')
    if len(p) >= 3:
        u = p[0].strip("( ").strip()
        by.setdefault(u.split("_")[0], []).append(u)
spk = sorted(by, key=lambda k: -len(by[k]))[:3]


def get(u):
    f = os.path.join(OUT, "cmu", u + ".wav")
    if not os.path.exists(f):
        open(f, "wb").write(urllib.request.urlopen(f"{CMU}/wav/{u}.wav", timeout=60).read())
    with wave.open(f) as w:
        assert w.getframerate() == R and w.getnchannels() == 1
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32)
    fr = 320
    e = np.sqrt(np.mean(x[:len(x) // fr * fr].reshape(-1, fr) ** 2, axis=1) + 1e-9)
    on = np.nonzero(e > e.max() * 0.06)[0]
    y = x[max(0, on[0] - 2) * fr:(on[-1] + 3) * fr]
    loud = e[e > e.max() * 0.25]
    return y * (2300.0 / float(np.sqrt(np.mean(loud ** 2))))


pools = {s: list(by[s][:30]) for s in spk}
r = random.Random(5)


def write(name, order):
    out, segs, t = [np.zeros(int(0.8 * R), np.float32)], [], 0.8
    for s in order:
        x = get(pools[s].pop(0))
        segs.append({"start": round(t, 3), "end": round(t + len(x) / R, 3), "spk": s, "lang": "ht"})
        g = r.uniform(0.2, 0.5)
        out += [x, np.zeros(int(g * R), np.float32)]
        t += len(x) / R + g
    out.append(np.zeros(int(1.5 * R), np.float32))
    y = np.clip(np.concatenate(out), -32768, 32767).astype("<i2")
    with wave.open(os.path.join(OUT, name + ".wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(R), w.writeframes(y.tobytes())
    sw = [segs[i]["start"] for i in range(1, len(segs)) if segs[i]["spk"] != segs[i - 1]["spk"]]
    json.dump({"name": name, "segments": segs, "speaker_changes": sw}, open(os.path.join(OUT, name + ".json"), "w"), indent=1)


write("R1", [spk[2]] * 14)
write("R2", [spk[0], spk[1]] * 4)
write("R3", [spk[0], spk[1], spk[2]] * 3)
print(spk)
