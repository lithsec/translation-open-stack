# Model sizes and single-thread CPU time per second of audio, on an idle pod (phone feasibility).
#   python footprint.py OUT.json
import json, sys, time
import numpy as np
import torch
from speechbrain.inference.classifiers import EncoderClassifier

torch.set_num_threads(1)
R = 16000
x = np.random.RandomState(0).randn(R * 30).astype(np.float32) * 0.05
out = {}
for name, src in [("voxlingua107_ecapa", "speechbrain/lang-id-voxlingua107-ecapa"), ("spk_ecapa_voxceleb", "speechbrain/spkrec-ecapa-voxceleb")]:
    m = EncoderClassifier.from_hparams(src, savedir=f"/root/m/{name}", run_opts={"device": "cpu"})
    f = m.classify_batch if name.startswith("vox") else m.encode_batch
    params = sum(p.numel() for p in m.mods.parameters())
    res = {"params": int(params), "fp16_MB": round(params * 2 / 1e6, 1)}
    for w in (1.0, 1.5):
        n = int(w * R)
        W = [x[i:i + n] for i in range(0, len(x) - n + 1, R // 4)]   # every 0.25 s
        with torch.no_grad():
            f(torch.from_numpy(W[0][None]))
            t0 = time.time()
            for v in W:
                f(torch.from_numpy(v[None]))
        res[f"cpu1_ms_per_window_{w}s"] = round(1000 * (time.time() - t0) / len(W), 1)
        res[f"cpu1_s_per_audio_s_hop0.25_{w}s"] = round((time.time() - t0) / 30, 3)
    out[name] = res
vad, _ = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)
t0 = time.time()
for i in range(0, len(x) - 512 + 1, 512):
    with torch.no_grad():
        vad(torch.from_numpy(x[i:i + 512]), R)
out["silero_vad"] = {"params": int(sum(p.numel() for p in vad.parameters())), "cpu1_s_per_audio_s": round((time.time() - t0) / 30, 4)}
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(json.dumps(out))
