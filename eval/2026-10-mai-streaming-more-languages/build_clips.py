# One continuous clip per language from fetch.py's 20 FLEURS recordings, joined with
# the regular pause pattern of ../2026-10-unseen (1.0-1.95 s, seed 11) and 1 s of
# lead-in, so each system has to cut the sentences itself as it would live.
#
#   python3 -I build_clips.py WORK      (needs WORK/sentences.json and WORK/audio/)
#
# Writes WORK/clips/<lang>.wav (16 kHz mono) and WORK/clips/<lang>.json:
# {"sentences": [{"i", "id", "start", "end", "text"}]} with times in seconds.
import json, os, random, sys, wave

WORK = sys.argv[1]
RATE = 16000
sentences = json.load(open(os.path.join(WORK, "sentences.json")))
os.makedirs(os.path.join(WORK, "clips"), exist_ok=True)
for lang, rows in sentences.items():
    r = random.Random(11)
    gaps = [round(r.uniform(1.0, 1.95), 2) for _ in range(len(rows) + 1)]
    pcm, meta, t = bytearray(b"\0" * RATE * 2), [], 1.0
    for k, s in enumerate(rows):
        with wave.open(os.path.join(WORK, "audio", lang, f"{s['n']:02d}.wav")) as w:
            assert w.getframerate() == RATE and w.getnchannels() == 1
            a = w.readframes(w.getnframes())
        meta.append({"i": k, "id": s["id"], "start": round(t, 3), "end": round(t + len(a) / 2 / RATE, 3), "text": s["text"]})
        pcm += a
        t += len(a) / 2 / RATE
        g = int(gaps[k] * RATE) * 2
        pcm += b"\0" * g
        t += g / 2 / RATE
    with wave.open(os.path.join(WORK, "clips", f"{lang}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(bytes(pcm))
    json.dump({"lang": lang, "sentences": meta}, open(os.path.join(WORK, "clips", f"{lang}.json"), "w"),
              ensure_ascii=False, indent=1)
    print(lang, len(meta), f"{t:.0f} s", flush=True)
