# Bleed features per speaker model, in the layout bleed_analyze.py reads (one FEAT dir per model):
#   _enrol.json  owner enrolment embeddings from the first 3/5/10 s (1.0/1.5 s windows every 0.5 s,
#                mean; and the whole segment)
#   <clip>.npz   t1.0/emb1.0, t1.5/emb1.5 (windows every 0.25 s), vl_t/vl (VoxLingua107, shared)
#   *_rms.npy    20 ms RMS (shared)
#   python feats_models.py CLIPS VLDIR OUTBASE model [model ...]
import glob, json, os, shutil, sys
import numpy as np
import soundfile as sf
import models as MD

CLIPS, VL, OB = sys.argv[1:4]
R, HOP = 16000, 0.25
WINS = [float(v) for v in os.environ.get("WINS", "1.0,1.5").split(",")]


def wins(x, w, hop=HOP):
    n = int(w * R)
    ends = np.arange(n, len(x) + 1, int(hop * R))
    return ends / R, [x[e - n:e] for e in ends]


for name in sys.argv[4:]:
    out = os.path.join(OB, name)
    os.makedirs(out, exist_ok=True)
    m = MD.load(name)
    enrol = {}
    for f in sorted(glob.glob(os.path.join(CLIPS, "enrol_*.wav"))):
        x, _ = sf.read(f, dtype="float32")
        oid = os.path.basename(f)[6:-4]
        enrol[oid] = {}
        for secs in (3, 5, 10):
            y = x[:secs * R]
            for w in WINS:
                _, W = wins(y, w, 0.5)
                e = m.embed(W).mean(axis=0)
                enrol[oid][f"{secs}s_{w}"] = (e / np.linalg.norm(e)).round(5).tolist()
            e = m.embed([y])[0]
            enrol[oid][f"{secs}s_whole"] = e.round(5).tolist()
    json.dump(enrol, open(os.path.join(out, "_enrol.json"), "w"))
    for f in sorted(glob.glob(os.path.join(CLIPS, "bleed_*.wav"))):
        nm = os.path.basename(f)[:-4]
        x, _ = sf.read(f, dtype="float32")
        res = {}
        for w in WINS:
            t, W = wins(x, w)
            res[f"t{w}"] = t
            res[f"emb{w}"] = m.embed(W).astype(np.float16)
        v = np.load(os.path.join(VL, nm + ".npz"))
        res["vl_t"], res["vl"] = v["vl_t"], v["vl"]
        np.savez_compressed(os.path.join(out, nm + ".npz"), **res)
    for f in glob.glob(os.path.join(VL, "*_rms.npy")):
        shutil.copy(f, out)
    print(name, "done", flush=True)
