# System 1: Whisper large-v3 one read sentence at a time (the gold boundaries from
# build_clips.py), through the stack's own engine (server/engines/whisper.py:
# the pinned revision, float16, beam 1, Silero VAD filter, the non-speech gates).
# The recogniser's best case: no endpointing, no cutting, the language given.
#
#   cd /opt/stack/server && python3 -I .../whisper_sent.py CLIPS OUT lang...
#
# The regular and irregular clips hold the same recordings, so one run per
# language serves both. Writes OUT/whisper_sent_<lang>.json: one text per sentence.
import json, os, sys, time, wave
import numpy as np

sys.path.insert(0, os.getcwd())
from engines.base import Context              # noqa: E402
from engines.whisper import Whisper           # noqa: E402

REVISION = "edaa852ec7e145841d8ffdb056a99866b5f0a478"   # languages.toml [models.whisper]
CLIPS, OUT, LANGS = sys.argv[1], sys.argv[2], sys.argv[3:]

ctx = Context(device="cuda", options={"asr_model": "large-v3", "asr_multi_model": "large-v3",
                                      "asr_revision": REVISION, "asr_multi_revision": REVISION, "xeng": True})
eng = Whisper(ctx)
eng.load()
for lang in LANGS:
    meta = json.load(open(os.path.join(CLIPS, f"{lang}.json")))
    with wave.open(os.path.join(CLIPS, f"{lang}.wav")) as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
    out = []
    for s in meta["sentences"]:
        a, b = int(s["start"] * rate), int(s["end"] * rate)
        t0 = time.time()
        text = eng.transcribe(pcm[a:b], lang)
        out.append({"i": s["i"], "text": text, "s": round(time.time() - t0, 3)})
    json.dump({"lang": lang, "sentences": out}, open(os.path.join(OUT, f"whisper_sent_{lang}.json"), "w"),
              ensure_ascii=False, indent=1)
    print(lang, sum(len(o["text"]) for o in out), "chars", flush=True)
