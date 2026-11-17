# Talk English continuous-speech clips: the 40 English FLEURS sentences of ../2026-11-talk-soniox (sets a and b,
# results/ids.json; rebuild them first with its build_clips.py ... results/ids.json en), cut out of its clips at
# their sentence marks and joined again with three pause patterns, as the German itseg check (2026-10-26):
#   paused     1.0-1.95 s between sentences (the round's own gaps, seed 11: the same audio as its clips)
#   irregular  0.3-1.2 s (seed 12, as ../2026-10-de-ru-ro irr)
#   nonstop    0.05-0.2 s (seed 13): under Talk's 300 ms English segmentation silence, so a sentence end is not a
#              pause the recogniser can end on
#   python3 -I build_styles.py <talk-soniox clips root> <out root>
# Writes <out>/clips_<set>_<style>/en.wav (16 kHz mono), en.json (sentence marks) and en.txt.json (FLEURS text).
import json, os, random, sys, wave

SRC, OUT = sys.argv[1], sys.argv[2]
RATE, N = 16000, 20
STYLES = {"paused": (11, 1.0, 1.95), "irregular": (12, 0.3, 1.2), "nonstop": (13, 0.05, 0.2)}

for st in ["a", "b"]:
    d = os.path.join(SRC, f"clips_{st}")
    meta = json.load(open(os.path.join(d, "en.json")))
    gold = json.load(open(os.path.join(d, "en.txt.json")))
    with wave.open(os.path.join(d, "en.wav")) as w:
        pcm = w.readframes(w.getnframes())
    sents = [pcm[int(m["start"] * RATE) * 2:int(m["end"] * RATE) * 2] for m in meta["sentences"]]
    for name, (seed, lo, hi) in STYLES.items():
        r = random.Random(seed)
        gaps = [round(r.uniform(lo, hi), 2) for _ in range(N + 1)]
        out, marks, t = bytearray(b"\0\0" * RATE), [], 1.0
        for i, s in enumerate(sents):
            dur = len(s) / 2 / RATE
            marks.append({"i": i, "start": round(t, 3), "end": round(t + dur, 3)})
            out += s + b"\0\0" * int(gaps[i] * RATE)
            t += dur + gaps[i]
        o = os.path.join(OUT, f"clips_{st}_{name}")
        os.makedirs(o, exist_ok=True)
        with wave.open(os.path.join(o, "en.wav"), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(bytes(out))
        json.dump({"lang": "en", "rate": RATE, "seconds": round(t, 3), "style": name, "gaps": gaps[:N], "sentences": marks,
                   "fleurs_ids": meta.get("fleurs_ids")}, open(os.path.join(o, "en.json"), "w"), indent=1)
        json.dump(gold, open(os.path.join(o, "en.txt.json"), "w"), ensure_ascii=False, indent=1)
        print(f"{st} {name}: {t:.1f} s", flush=True)
