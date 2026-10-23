# Frame-level signals for every clip, on a GPU pod (models: Apache-2.0 / MIT, none gated):
#   vad      Silero VAD speech probability per 32 ms
#   vl05/vl1 VoxLingua107 ECAPA (speechbrain/lang-id-voxlingua107-ecapa) log-posteriors for
#            en, es, fr, pt, ja, ht on 0.5 s / 1.0 s windows, 0.25 s hop (window END times)
#   wh1/wh2  Whisper small (faster-whisper) language probabilities on 1 s / 2 s windows, same hop
#   spk      speechbrain/spkrec-ecapa-voxceleb: cosine similarity between the 1 s window just
#            before each hop time and the 1 s window just after (low = speaker change), and
#            between consecutive 1 s windows
# plus model sizes and single-thread CPU time per second of audio (phone feasibility).
#
#   python features.py CLIPS OUT
import glob, json, os, sys, time, wave
import numpy as np
import torch

CLIPS, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
LANGS = ["en", "es", "fr", "pt", "ja", "ht"]
R, HOP = 16000, 0.25
dev = "cuda" if torch.cuda.is_available() else "cpu"

from speechbrain.inference.classifiers import EncoderClassifier
lid = EncoderClassifier.from_hparams("speechbrain/lang-id-voxlingua107-ecapa", savedir="/root/m/vl107", run_opts={"device": dev})
spk = EncoderClassifier.from_hparams("speechbrain/spkrec-ecapa-voxceleb", savedir="/root/m/ecapa", run_opts={"device": dev})
labs = lid.hparams.label_encoder.ind2lab
idx = {}
for i, l in labs.items():
    code = l.split(":")[0].strip()
    if code in LANGS:
        idx[code] = i
assert set(idx) == set(LANGS), idx
from faster_whisper import WhisperModel
wh = WhisperModel("small", device=dev, compute_type="float16" if dev == "cuda" else "int8")
vad_model, _ = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)


def windows(x, w):
    n = int(w * R)
    ends = np.arange(n, len(x) + 1, int(HOP * R))
    return ends, np.stack([x[e - n:e] for e in ends])


def vl(x, w):
    ends, W = windows(x, w)
    out = []
    for i in range(0, len(W), 128):
        with torch.no_grad():
            lp = lid.classify_batch(torch.from_numpy(W[i:i + 128]).float())[0]  # log-posteriors (B, 107)
        out.append(lp.cpu().numpy()[:, [idx[l] for l in LANGS]])
    return (ends / R).round(3).tolist(), np.concatenate(out).round(3).tolist()


def whisper(x, w):
    ends, W = windows(x, w)
    rows = []
    for seg in W:
        _, _, allp = wh.detect_language(seg)
        d = dict(allp)
        rows.append([round(float(d.get(l, 0.0)), 4) for l in LANGS])
    return (ends / R).round(3).tolist(), rows


def emb(W):
    out = []
    for i in range(0, len(W), 128):
        with torch.no_grad():
            e = spk.encode_batch(torch.from_numpy(W[i:i + 128]).float()).squeeze(1)
        out.append(torch.nn.functional.normalize(e, dim=-1).cpu().numpy())
    return np.concatenate(out)


def speaker(x):
    n, h = R, int(HOP * R)
    starts = np.arange(0, len(x) - n + 1, h)
    E = emb(np.stack([x[s:s + n] for s in starts]))
    t, across, consec = [], [], []
    for k in range(len(starts)):
        mid = starts[k] + n  # boundary between window k (ending here) and window k+4 (starting here)
        j = k + int(n / h)
        if j < len(starts):
            t.append(round(mid / R, 3))
            across.append(round(float(E[k] @ E[j]), 4))
            consec.append(round(float(E[k] @ E[k + 1]), 4) if k + 1 < len(starts) else None)
    return t, across, consec


def vad(x):
    p, fr = [], 512
    vad_model.reset_states()
    for i in range(0, len(x) - fr + 1, fr):
        with torch.no_grad():
            p.append(round(float(vad_model(torch.from_numpy(x[i:i + fr]).float(), R)), 3))
    return p


for wav in sorted(glob.glob(os.path.join(CLIPS, "*.wav"))):
    name = os.path.basename(wav)[:-4]
    with wave.open(wav) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
    t0 = time.time()
    res = {"name": name, "langs": LANGS, "hop": HOP}
    res["vad"] = {"frame_s": 512 / R, "p": vad(x)}
    for w_, k in [(0.5, "vl05"), (1.0, "vl1")]:
        t, v = vl(x, w_)
        res[k] = {"t": t, "logp": v}
    for w_, k in [(1.0, "wh1"), (2.0, "wh2")]:
        t, v = whisper(x, w_)
        res[k] = {"t": t, "p": v}
    t, a, c = speaker(x)
    res["spk"] = {"t": t, "across": a, "consec": c}
    json.dump(res, open(os.path.join(OUT, f"{name}.json"), "w"))
    print(f"{name}: {len(x) / R:.1f} s in {time.time() - t0:.1f} s", flush=True)

# Footprint: parameters and single-thread CPU time per second of audio.
torch.set_num_threads(1)
foot = {}
x = np.random.RandomState(0).randn(R * 20).astype(np.float32) * 0.05
for name, m in [("voxlingua107_ecapa", lid), ("spk_ecapa_voxceleb", spk)]:
    params = sum(p.numel() for p in m.mods.parameters())
    m.mods.to("cpu"); m.device = "cpu"
    for mod in m.mods.values():
        mod.to("cpu")
    W = np.stack([x[i:i + R] for i in range(0, len(x) - R + 1, R)])  # 1 s windows, no overlap
    f = (lambda b: m.classify_batch(b)) if name.startswith("vox") else (lambda b: m.encode_batch(b))
    with torch.no_grad():
        f(torch.from_numpy(W[:2]))
        t0 = time.time()
        for k in range(len(W)):
            f(torch.from_numpy(W[k:k + 1]))
        dt = time.time() - t0
    foot[name] = {"params": int(params), "cpu1_s_per_audio_s_1s_windows": round(dt / len(W), 4)}
vm = vad_model
t0 = time.time()
vm.reset_states()
for i in range(0, len(x) - 512 + 1, 512):
    with torch.no_grad():
        vm(torch.from_numpy(x[i:i + 512]), R)
foot["silero_vad"] = {"params": int(sum(p.numel() for p in vm.parameters())), "cpu1_s_per_audio_s": round((time.time() - t0) / 20, 4)}
json.dump(foot, open(os.path.join(OUT, "_footprint.json"), "w"), indent=1)
print(json.dumps(foot), flush=True)
