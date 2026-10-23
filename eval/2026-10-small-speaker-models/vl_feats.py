# VoxLingua107 log-posteriors (1 s windows every 0.25 s, the six languages) and 20 ms RMS for every
# bleed clip and enrolment, once; shared by every speaker model's FEAT dir.
#   python vl_feats.py CLIPS OUT
import glob, os, sys
import numpy as np
import soundfile as sf
import torch
from speechbrain.inference.classifiers import EncoderClassifier
CLIPS, OUT = sys.argv[1:3]
os.makedirs(OUT, exist_ok=True)
R = 16000
LANGS = ["en", "es", "fr", "pt", "ja", "ht"]
lid = EncoderClassifier.from_hparams("speechbrain/lang-id-voxlingua107-ecapa", savedir="/w/models/vl107", run_opts={"device": "cpu"})
idx = {l.split(":")[0].strip(): i for i, l in lid.hparams.label_encoder.ind2lab.items()}
cols = [idx[l] for l in LANGS]
for f in sorted(glob.glob(os.path.join(CLIPS, "*.wav"))):
    x, _ = sf.read(f, dtype="float32")
    nm = os.path.basename(f)[:-4]
    n = len(x) // 320 * 320
    np.save(os.path.join(OUT, nm + "_rms.npy"), np.sqrt(np.mean(x[:n].reshape(-1, 320) ** 2, axis=1) + 1e-12).astype(np.float32))
    if not nm.startswith("bleed_"):
        continue
    ends = np.arange(R, len(x) + 1, R // 4)
    W = np.stack([x[e - R:e] for e in ends])
    lp = []
    for i in range(0, len(W), 128):
        with torch.no_grad():
            lp.append(lid.classify_batch(torch.from_numpy(W[i:i + 128]).float())[0].numpy()[:, cols])
    np.savez_compressed(os.path.join(OUT, nm + ".npz"), vl_t=ends / R, vl=np.concatenate(lp).astype(np.float32))
print("ok")
