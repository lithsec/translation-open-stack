"""Level and Silero speech probability per read sentence, raw and as the VAD
sees it through audio_in.QuietBoost. Runs where the stack runs:

    SERVER_DIR=/opt/stack/server python3 levels.py <clips> en es ...
"""
import copy, json, os, sys, wave
import numpy as np
CL = os.path.abspath(sys.argv[1])
sys.path.insert(0, os.environ.get("SERVER_DIR", "/opt/stack/server"))
os.chdir(os.environ.get("SERVER_DIR", "/opt/stack/server"))
import torch  # noqa: E402
import server as SV  # noqa: E402
from audio_in import BLOCK, QuietBoost, vad_block  # noqa: E402

vad = torch.hub.load(f"{SV.MODELS['vad']['repo']}:{SV.MODELS['vad']['ref']}", "silero_vad", trust_repo=True)[0]
for lang in sys.argv[2:]:
    with wave.open(os.path.join(CL, f"{lang}.wav")) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
    probs = {}
    for name, boost in (("raw", lambda b: b), ("boost", QuietBoost())):
        v = copy.deepcopy(vad)
        v.reset_states()
        probs[name] = np.array([vad_block(v, boost(x[i:i + BLOCK])) for i in range(0, len(x) - BLOCK + 1, BLOCK)])
    t = np.arange(len(probs["raw"])) * BLOCK / 16000
    for s in json.load(open(os.path.join(CL, f"{lang}.json")))["sentences"]:
        m = (t >= s["start"]) & (t < s["end"])
        seg = x[int(s["start"] * 16000):int(s["end"] * 16000)]
        print(f"{lang} {s['i']:2d} peak {20 * np.log10(np.abs(seg).max() + 1e-9):6.1f} dBFS  "
              f"speech>0.5 raw {(probs['raw'][m] > 0.5).mean():.2f} boosted {(probs['boost'][m] > 0.5).mean():.2f}")
