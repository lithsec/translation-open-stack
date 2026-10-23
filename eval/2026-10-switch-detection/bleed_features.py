# Features for the bleed clips (pod): speaker embeddings (speechbrain/spkrec-ecapa-voxceleb) on 1.0 s
# and 1.5 s windows every 0.25 s, VoxLingua107 log-posteriors on 1.0 s windows every 0.25 s, and the
# owner enrolment embeddings from the first 3, 5 and 10 s of each owner's enrolment audio.
#   python bleed_features.py CLIPS OUT
import glob, json, os, sys
import numpy as np
import soundfile as sf
import torch
from speechbrain.inference.classifiers import EncoderClassifier

CLIPS, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
R, HOP = 16000, 0.25
LANGS = ["en", "es", "fr", "pt", "ja", "ht"]
dev = "cuda"
lid = EncoderClassifier.from_hparams("speechbrain/lang-id-voxlingua107-ecapa", savedir="/root/m/vl107", run_opts={"device": dev})
spk = EncoderClassifier.from_hparams("speechbrain/spkrec-ecapa-voxceleb", savedir="/root/m/ecapa", run_opts={"device": dev})
idx = {l.split(":")[0].strip(): i for i, l in lid.hparams.label_encoder.ind2lab.items()}
cols = [idx[l] for l in LANGS]


def wins(x, w, hop=HOP):
    n = int(w * R)
    ends = np.arange(n, len(x) + 1, int(hop * R))
    return ends / R, np.stack([x[e - n:e] for e in ends])


def embed(W):
    out = []
    for i in range(0, len(W), 128):
        with torch.no_grad():
            e = spk.encode_batch(torch.from_numpy(W[i:i + 128]).float()).squeeze(1)
        out.append(torch.nn.functional.normalize(e, dim=-1).cpu().numpy())
    return np.concatenate(out)


enrol = {}
for f in sorted(glob.glob(os.path.join(CLIPS, "enrol_*.wav"))):
    x, _ = sf.read(f, dtype="float32")
    oid = os.path.basename(f)[6:-4]
    enrol[oid] = {}
    for secs in (3, 5, 10):
        y = x[:secs * R]
        for w in (1.0, 1.5):
            _, W = wins(y, w, 0.5)
            m = embed(W).mean(axis=0)
            enrol[oid][f"{secs}s_{w}"] = (m / np.linalg.norm(m)).round(5).tolist()
        # one whole-segment embedding as well
        with torch.no_grad():
            e = spk.encode_batch(torch.from_numpy(y[None]).float()).squeeze().cpu().numpy()
        enrol[oid][f"{secs}s_whole"] = (e / np.linalg.norm(e)).round(5).tolist()
json.dump(enrol, open(os.path.join(OUT, "_enrol.json"), "w"))
for f in sorted(glob.glob(os.path.join(CLIPS, "bleed_*.wav"))):
    name = os.path.basename(f)[:-4]
    x, _ = sf.read(f, dtype="float32")
    res = {}
    for w in (1.0, 1.5):
        t, W = wins(x, w)
        res[f"t{w}"] = t
        res[f"emb{w}"] = embed(W).astype(np.float16)
    t, W = wins(x, 1.0)
    lp = []
    for i in range(0, len(W), 128):
        with torch.no_grad():
            lp.append(lid.classify_batch(torch.from_numpy(W[i:i + 128]).float())[0].cpu().numpy()[:, cols])
    res["vl_t"], res["vl"] = t, np.concatenate(lp).astype(np.float32)
    np.savez_compressed(os.path.join(OUT, name + ".npz"), **res)
    print(name, flush=True)
