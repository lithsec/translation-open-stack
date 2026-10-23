# Interferer pools for bleed_clips.py from the streamed FLEURS test files (files 40-47 of each
# language; 0-39 are kept for the speaker trials): ctl_<lang>.wav (0.3 s gaps) + ctl_<lang>.json.
#   python make_ctl.py FLEURS_DIR OUT
import json, os, sys, wave
import numpy as np
FD, OUT = sys.argv[1:3]
R = 16000
os.makedirs(OUT, exist_ok=True)
for lang in ["en", "es", "fr", "pt", "ja"]:
    meta = json.load(open(os.path.join(FD, lang, "meta.json")))[40:48]
    pcm, segs, t = [np.zeros(int(0.3 * R), np.int16)], [], 0.3
    for m in meta:
        with wave.open(os.path.join(FD, lang, m["file"])) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), "<i2")
        segs.append({"start": round(t, 3), "end": round(t + len(x) / R, 3), "text": m["text"]})
        pcm += [x, np.zeros(int(0.3 * R), np.int16)]
        t += len(x) / R + 0.3
    with wave.open(os.path.join(OUT, f"ctl_{lang}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(R); w.writeframes(np.concatenate(pcm).tobytes())
    json.dump({"segments": segs}, open(os.path.join(OUT, f"ctl_{lang}.json"), "w"), ensure_ascii=False)
print("ok")
