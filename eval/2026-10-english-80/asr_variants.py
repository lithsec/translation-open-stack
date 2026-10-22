"""English recognition variants on the stack's own pieces (offline, on the pod).
Pieces: the cutting loop of eval/2026-10-pauses/sweep.py at the given turn rules (piece a/e times
from out.json). Each piece through faster-whisper large-v3 with the stack's options, then variants:
beam 5; previous piece's text as prompt; Whisper's own VAD filter off.
    python3 asr_variants.py <clips> <sweep out.json> <setting> <out.json>"""
import json, os, sys, wave
import numpy as np
from faster_whisper import WhisperModel
CL, SW, SET, OUT = sys.argv[1:5]
pieces = json.load(open(SW))["res"][SET]["en"]
with wave.open(os.path.join(CL, "en.wav")) as w:
    x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
m = WhisperModel("large-v3", device="cuda", compute_type="float16")
base = dict(beam_size=1, condition_on_previous_text=False, no_speech_threshold=0.6, temperature=0,
            vad_filter=True, vad_parameters=dict(min_silence_duration_ms=300))
V = {"stack": {}, "beam5": {"beam_size": 5}, "novad": {"vad_filter": False},
     "prompt": {"prompt": True}, "beam5_prompt": {"beam_size": 5, "prompt": True},
     "beam5_novad": {"beam_size": 5, "vad_filter": False}}
res = {}
for name, v in V.items():
    out, prev = [], ""
    for p in pieces:
        seg = x[int(p["a"] * 16000):int(p["e"] * 16000)]
        o = dict(base, **{k: val for k, val in v.items() if k != "prompt"})
        if v.get("prompt") and prev:
            o["initial_prompt"] = prev[-200:]
        if not o["vad_filter"]:
            o.pop("vad_parameters")
        segs, _ = m.transcribe(seg, language="en", **o)
        t = " ".join(s.text.strip() for s in segs).strip()
        out.append({"a": p["a"], "e": p["e"], "text": t})
        prev = t
    res[name] = out
    print(name, " | ".join(q["text"][:40] for q in out[:3]), flush=True)
json.dump(res, open(OUT, "w"), indent=1, ensure_ascii=False)
