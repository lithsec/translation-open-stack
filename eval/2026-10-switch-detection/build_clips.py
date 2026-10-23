# Language-switch test clips, cut from the unseen October clips (../2026-10-unseen and the full
# stack's second set; FLEURS, CC BY 4.0; Haitian Creole from CMU). Each utterance is trimmed to
# its speech (energy) and brought to one level, then joined so the ground-truth switch time is the next speech onset.
#
#   S1  "same voice": English and the other language alternate with a 0.12 s gap, the two
#       readers matched on gender (FLEURS has no bilingual speakers: an approximation).
#   S2  two speakers: opposite genders, gaps cycling 0 / 0.1 / 0.2 / 0.3 s.
#   S3  fast back-and-forth: 16 turns of 1-3 s (each the start of an utterance, cut at its
#       quietest 50 ms between 1 and 3 s), gaps 0.05-0.3 s. No text reference.
#   ctl one language only (8 utterances, 0.3 s gaps): false switches and plain accuracy.
#
#   python3 -I build_clips.py OUT SET_A_CLIPS SET_B_CLIPS
import json, os, random, sys, wave
import numpy as np

OUT, SETS, RATE = sys.argv[1], sys.argv[2:4], 16000
PAIRS = ["es", "fr", "pt", "ja", "ht"]


def load(lang):
    utts = []
    for k, d in enumerate(SETS):
        meta = json.load(open(os.path.join(d, f"{lang}.json")))
        texts = json.load(open(os.path.join(d, f"{lang}.txt.json")))
        with wave.open(os.path.join(d, f"{lang}.wav")) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32)
        g = meta.get("genders") or ["?"] * len(texts)
        for s, t, gen in zip(meta["sentences"], texts, g):
            seg = x[int(s["start"] * RATE):int(s["end"] * RATE)]
            fr = 320  # 20 ms
            e = np.sqrt(np.mean(seg[:len(seg) // fr * fr].reshape(-1, fr) ** 2, axis=1) + 1e-9)
            if e.max() < 5:
                continue
            on = np.nonzero(e > e.max() * 0.06)[0]
            a, b = max(0, on[0] - 2) * fr, min(len(seg), (on[-1] + 3) * fr)
            y = seg[a:b]
            # Every utterance at one speech level (about -23 dBFS RMS over its loud frames): level
            # jumps between readers are a different problem (../2026-10-quiet-after-loud).
            loud = e[e > e.max() * 0.25]
            y = y * (2300.0 / float(np.sqrt(np.mean(loud ** 2))))
            utts.append({"pcm": y, "text": t, "gender": gen.upper(), "src": f"set{'ab'[k]}:{s['i']}"})
    return utts


def cut_short(u, r):
    """The start of an utterance, 1-3 s long, cut at its quietest 50 ms frame in that range."""
    x, fr = u["pcm"], 800
    lo, hi = RATE, min(3 * RATE, len(x) - fr)
    if hi <= lo:
        return x
    e = [np.sqrt(np.mean(x[i:i + fr] ** 2)) for i in range(lo, hi, fr)]
    i = lo + int(np.argmin(e)) * fr + fr // 2
    return x[:i]


def write(name, parts):
    """parts: list of (pcm, lang, speaker, text|None, gap_after)."""
    lead, out, segs, t = 0.8, [np.zeros(int(0.8 * RATE), np.float32)], [], 0.8
    for pcm, lang, spk, text, gap in parts:
        d = len(pcm) / RATE
        segs.append({"start": round(t, 3), "end": round(t + d, 3), "lang": lang, "spk": spk, "text": text})
        out += [pcm, np.zeros(int(gap * RATE), np.float32)]
        t += d + gap
    out.append(np.zeros(int(1.5 * RATE), np.float32))
    y = np.clip(np.concatenate(out), -32768, 32767).astype("<i2")
    with wave.open(os.path.join(OUT, f"{name}.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(y.tobytes())
    sw = [round(segs[i]["start"], 3) for i in range(1, len(segs)) if segs[i]["lang"] != segs[i - 1]["lang"]]
    json.dump({"name": name, "seconds": round(len(y) / RATE, 3), "segments": segs, "switches": sw},
              open(os.path.join(OUT, f"{name}.json"), "w"), ensure_ascii=False, indent=1)
    return len(sw)


os.makedirs(OUT, exist_ok=True)
en = load("en")
r = random.Random(2026)
ctl_en = [u for u in en][:8]
write("ctl_en", [(u["pcm"], "en", "en0", u["text"], 0.3) for u in ctl_en])
summary = {}
for x in PAIRS:
    xs = load(x)
    pool_en = en[8:]
    r.shuffle(pool_en)
    pool_x = list(xs)
    r.shuffle(pool_x)
    write(f"ctl_{x}", [(u["pcm"], x, f"{x}0", u["text"], 0.3) for u in pool_x[:8]])
    px, pe = pool_x[8:], list(pool_en)

    def take(pool, gender=None, not_gender=None):
        for i, u in enumerate(pool):
            if (gender is None or u["gender"] == gender) and (not_gender is None or u["gender"] != not_gender):
                return pool.pop(i)
        return pool.pop(0)

    # S1: matched gender, 0.12 s gaps, starting in English
    g = "MALE" if x != "ht" else None
    s1 = []
    for k in range(8):
        u = take(pe, g) if k % 2 == 0 else take(px, g)
        s1.append((u["pcm"], "en" if k % 2 == 0 else x, "A" if x != "ht" else ("A" if k % 2 == 0 else "B"), u["text"], 0.12))
    n1 = write(f"S1_{x}", s1)
    # S2: opposite genders, gaps cycling
    s2 = []
    for k in range(8):
        u = take(pe, "MALE") if k % 2 == 0 else take(px, None, "MALE") if x != "ht" else take(px)
        s2.append((u["pcm"], "en" if k % 2 == 0 else x, "A" if k % 2 == 0 else "B", u["text"], [0, 0.1, 0.2, 0.3][k % 4]))
    n2 = write(f"S2_{x}", s2)
    # S3: fast turns, start-of-utterance pieces, no text reference
    s3 = []
    for k in range(16):
        u = take(pe) if k % 2 == 0 else take(px)
        s3.append((cut_short(u, r), "en" if k % 2 == 0 else x, "A" if k % 2 == 0 else "B", None, round(r.uniform(0.05, 0.3), 2)))
    n3 = write(f"S3_{x}", s3)
    summary[x] = {"S1": n1, "S2": n2, "S3": n3}
print(json.dumps(summary))
