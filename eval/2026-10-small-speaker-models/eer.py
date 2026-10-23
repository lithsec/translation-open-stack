# Owner-versus-other separation per language: EER of 3 s vs 3 s trials.
#   LibriSpeech (en) and CMU (ht) have speaker ids: target = two different utterances of one speaker,
#   non-target = different speakers (same gender for LibriSpeech).
#   FLEURS (en/es/fr/pt/ja/lo/km) has no speaker ids: target = first 3 s vs last 3 s of one
#   recording (same session, easier), non-target = different recordings of the same listed gender
#   (may now and then be the same reader, which is harsher). Treat FLEURS EERs as relative.
#   python eer.py DATA OUT.json model [model ...]
import glob, itertools, json, os, random, sys, wave
import numpy as np
import models as MD

D, OUT = sys.argv[1:3]
R, L = 16000, 3 * 16000
rnd = random.Random(5)


def rd(f):
    with wave.open(f) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
        sr = w.getframerate()
    if sr != R:
        x = np.interp(np.arange(0, len(x), sr / R), np.arange(len(x)), x).astype(np.float32)
    return x


def eer(tg, nt):
    s = np.concatenate([tg, nt]); y = np.concatenate([np.ones(len(tg)), np.zeros(len(nt))])
    o = np.argsort(-s); y = y[o]
    tpr = np.cumsum(y) / y.sum(); fpr = np.cumsum(1 - y) / (1 - y).sum()
    i = np.argmin(np.abs((1 - tpr) - fpr))
    return round(100 * float(((1 - tpr[i]) + fpr[i]) / 2), 2)


sets = {}
# FLEURS
for lang in ([] if os.environ.get("ONLY") and "fleurs" not in os.environ["ONLY"] else ["en", "es", "fr", "pt", "ja", "lo", "km"]):
    meta = json.load(open(f"{D}/fleurs/{lang}/meta.json"))[:40]
    items = []
    for m in meta:
        x = rd(f"{D}/fleurs/{lang}/{m['file']}")
        if len(x) >= int(6.5 * R):
            items.append((m["gender"], x[int(0.25 * R):int(0.25 * R) + L], x[-L - int(0.25 * R):-int(0.25 * R)]))
    sets[f"fleurs_{lang}"] = ("halves", items)
# LibriSpeech
spk_g = {}
for ln in open(glob.glob(f"{D}/libri/**/SPEAKERS.TXT", recursive=True)[0]):
    p = [s.strip() for s in ln.split("|")]
    if not ln.startswith(";") and len(p) >= 3 and p[2] == "test-clean":
        spk_g[p[0]] = p[1]
lib = []
for s in sorted(spk_g)[:int(os.environ.get("LIBRI_N", "16"))]:
    fs = sorted(glob.glob(f"{D}/libri/LibriSpeech/test-clean/{s}/*/*.flac"))
    import soundfile as sf
    n = 0
    for f in fs:
        x, _ = sf.read(f, dtype="float32")
        if len(x) >= L + R // 2:
            lib.append((s, spk_g[s], x[R // 4:R // 4 + L])); n += 1
        if n >= int(os.environ.get("LIBRI_UTTS", "6")):
            break
sets["libri_en"] = ("ids", lib)
# CMU Haitian
cmu = []
for f in sorted(glob.glob(f"{D}/cmu/wav/*.wav")):
    x = rd(f)
    if len(x) >= 2 * R:
        cmu.append((os.path.basename(f).split("_")[0], "?", x[:L]))
by = {}
for it in cmu:
    by.setdefault(it[0], []).append(it)
sets["cmu_ht"] = ("ids", [it for s in by for it in by[s][:8]])

ONLY = os.environ.get("ONLY")
if ONLY:
    sets = {k: v for k, v in sets.items() if k in ONLY.split(",")}
res = {k: {"n": None} for k in sets}
for name in sys.argv[3:]:
    m = MD.load(name)
    for k, (kind, items) in sets.items():
        if kind == "halves":
            A = m.embed([i[1] for i in items]); B = m.embed([i[2] for i in items])
            tg = (A * B).sum(1)
            nt = [float(A[i] @ B[j]) for i, j in itertools.permutations(range(len(items)), 2) if items[i][0] == items[j][0]]
            res[k]["n"] = f"{len(tg)} target / {len(nt)} non-target"
        else:
            E = m.embed([i[2] for i in items])
            tg, nt = [], []
            for i, j in itertools.combinations(range(len(items)), 2):
                same = items[i][0] == items[j][0]
                if same:
                    tg.append(float(E[i] @ E[j]))
                elif items[i][1] == items[j][1]:
                    nt.append(float(E[i] @ E[j]))
            res[k]["n"] = f"{len(tg)} target / {len(nt)} non-target, {len({i[0] for i in items})} speakers"
        res[k][name] = eer(np.array(tg), np.array(nt))
    print(name, {k: v[name] for k, v in res.items()}, flush=True)
json.dump(res, open(OUT, "w"), indent=1)
