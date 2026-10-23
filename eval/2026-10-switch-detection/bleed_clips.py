# Phone-bleed clips (open-mic Live Translation: each person's phone is pinned to their language and
# also hears a nearby talker and PA/room audio). Runs on the pod.
#   owners  FLEURS has no speaker ids, so owners come from corpora that have them:
#           English: LibriSpeech test-clean (CC BY 4.0), 4 speakers (2 female, 2 male)
#           Haitian Creole: CMU Haitian speech (the corpus the earlier rounds use), 3 speakers
#           Each owner: an enrolment pool (first ~12 s, never used in the clips) and ~50 s of content.
#   near    another language's FLEURS reader (../switch clips' ctl_* utterances) at -6/-12/-18 dB
#           relative to the owner's speech level, half in the owner's pauses, half overlapping
#   pa      PA/room playback (Azure TTS of FLEURS sentences, the "translated voice", plus FLEURS
#           speech) through a synthetic room response (RT60 ~0.6 s), at -10/-20 dB, near-continuous
#   quiet   every condition again with the owner 6 dB quieter (interferers stay where they were)
# Ground truth per clip: owner and non-owner speech intervals with their text and language.
#
#   python bleed_clips.py LIBRI_DIR CMU_DIR SWITCH_CLIPS PA_DIR OUT
import glob, json, os, random, sys, wave
import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve

LIBRI, CMU, SW, PA, OUT = sys.argv[1:6]
R = 16000
rnd = random.Random(7)
os.makedirs(OUT, exist_ok=True)


def trim(x):
    fr = 320
    e = np.sqrt(np.mean(x[:len(x) // fr * fr].reshape(-1, fr) ** 2, axis=1) + 1e-12)
    on = np.nonzero(e > e.max() * 0.06)[0]
    return x[max(0, on[0] - 2) * fr:(on[-1] + 3) * fr]


def level(x):
    fr = 320
    e = np.sqrt(np.mean(x[:len(x) // fr * fr].reshape(-1, fr) ** 2, axis=1) + 1e-12)
    loud = e[e > e.max() * 0.25]
    return float(np.sqrt(np.mean(loud ** 2)))


def norm(x, target=0.07):
    return x * (target / level(x))


# Owners -----------------------------------------------------------------------------------------
owners = []
spk_gender = {}
for ln in open(glob.glob(os.path.join(LIBRI, "**", "SPEAKERS.TXT"), recursive=True)[0]):
    if ln.startswith(";"):
        continue
    p = [s.strip() for s in ln.split("|")]
    if len(p) >= 3 and p[2] == "test-clean":
        spk_gender[p[0]] = p[1]
spks = sorted(s for s in spk_gender if os.path.isdir(os.path.join(LIBRI, "LibriSpeech", "test-clean", s)))
pick = [s for s in spks if spk_gender[s] == "F"][:2] + [s for s in spks if spk_gender[s] == "M"][:2]
for s in pick:
    utts = []
    for tf in sorted(glob.glob(os.path.join(LIBRI, "LibriSpeech", "test-clean", s, "*", "*.trans.txt"))):
        d = os.path.dirname(tf)
        for ln in open(tf):
            u, t = ln.strip().split(" ", 1)
            x, sr = sf.read(os.path.join(d, u + ".flac"), dtype="float32")
            assert sr == R
            utts.append((norm(trim(x)), t.lower()))
    owners.append({"id": f"en-{s}{spk_gender[s]}", "lang": "en", "utts": utts})
lines = open(os.path.join(CMU, "txt.done.data"), encoding="utf-8").read().splitlines()
by = {}
for ln in lines:
    p = ln.strip().split('"')
    if len(p) >= 3:
        u = p[0].strip("( ").strip()
        by.setdefault(u.split("_")[0], []).append((u, p[1].strip()))
for spk in sorted(by, key=lambda k: -len(by[k]))[:3]:
    utts = []
    for u, t in by[spk][:30]:
        f = os.path.join(CMU, "wav", u + ".wav")
        if not os.path.exists(f):
            continue
        x, sr = sf.read(f, dtype="float32")
        if x.ndim > 1:
            x = x.mean(axis=1)
        if sr != R:
            x = np.interp(np.arange(0, len(x), sr / R), np.arange(len(x)), x).astype(np.float32)
        utts.append((norm(trim(x)), t))
    owners.append({"id": f"ht-{spk}", "lang": "ht", "utts": utts})

# Interferers --------------------------------------------------------------------------------------
def fleurs(lang):
    meta = json.load(open(os.path.join(SW, f"ctl_{lang}.json")))
    with wave.open(os.path.join(SW, f"ctl_{lang}.wav")) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
    return [(norm(x[int(s["start"] * R):int(s["end"] * R)]), s["text"], lang) for s in meta["segments"]]


OTHER = {"en": ["es", "fr", "pt", "ja"], "ht": ["en", "fr", "es"]}
near_pool = {l: fleurs(l) for l in ["en", "es", "fr", "pt", "ja"]}
pa_items = []
for f in sorted(glob.glob(os.path.join(PA, "*.wav"))):
    x, sr = sf.read(f, dtype="float32")
    pa_items.append((norm(trim(x)), None, os.path.basename(f).split("_")[0]))
ir_t = np.arange(int(0.8 * R)) / R
ir = np.random.RandomState(3).randn(len(ir_t)).astype(np.float32) * np.exp(-6.9 * ir_t / 0.6)
ir[0] = 1.0
ir /= np.sqrt(np.sum(ir ** 2))


def room(x):
    return fftconvolve(x, ir)[:len(x) + len(ir) // 2].astype(np.float32)


# Clips --------------------------------------------------------------------------------------------
CONDS = [("near", -6), ("near", -12), ("near", -18), ("pa", -10), ("pa", -20)]
manifest = []
for o in owners:
    pool, enrol, t = list(o["utts"]), [], 0.0
    while t < 12.0 and pool:  # the enrolment pool: never in the clips
        u = pool.pop(0)
        enrol.append(u[0])
        t += len(u[0]) / R
    enrol = np.concatenate(enrol)
    sf.write(os.path.join(OUT, f"enrol_{o['id']}.wav"), enrol, R, subtype="PCM_16")
    content = []
    t = 0.0
    while t < 50.0 and pool:
        u = pool.pop(0)
        content.append(u)
        t += len(u[0]) / R
    for kind, db in CONDS:
        for quiet in (0, -6):
            r = random.Random(f"{o['id']}{kind}{db}{quiet}")
            g_owner = 10 ** (quiet / 20)
            g_int = 10 ** (db / 20)
            # owner timeline with 1.0-2.5 s pauses
            segs, cur = [], 1.0
            for x, text in content:
                segs.append({"who": "owner", "lang": o["lang"], "start": cur, "end": cur + len(x) / R, "text": text, "x": x * g_owner})
                cur += len(x) / R + r.uniform(1.0, 2.5)
            total = cur + 1.0
            ints = []
            if kind == "near":
                langs = OTHER[o["lang"]]
                items = [it for l in langs for it in near_pool[l]]
                r.shuffle(items)
                k = 0
                for i, s in enumerate(segs):
                    if k >= len(items):
                        break
                    x, text, lang = items[k]
                    k += 1
                    if i % 2 == 0:   # in the pause after this owner utterance
                        st = s["end"] + 0.2
                    else:            # overlapping the end of this owner utterance
                        st = max(s["start"], s["end"] - r.uniform(0.8, 2.0))
                    ints.append({"who": "near", "lang": lang, "start": st, "end": st + len(x) / R, "text": text, "x": x * g_int})
            else:
                items = pa_items + [it for l in OTHER[o["lang"]] for it in near_pool[l]]
                r.shuffle(items)
                st, k = 0.5, 0
                while st < total - 1.0:
                    x, text, lang = items[k % len(items)]
                    k += 1
                    y = room(x) * g_int
                    ints.append({"who": "pa", "lang": lang, "start": st, "end": st + len(x) / R, "text": text, "x": y})
                    st += len(y) / R + r.uniform(0.5, 1.5)
            total = max([total] + [i["start"] + len(i["x"]) / R for i in ints]) + 0.5
            mix = np.zeros(int(total * R) + 1, np.float32)
            for s in segs + ints:
                a = int(s["start"] * R)
                mix[a:a + len(s["x"])] += s["x"][:len(mix) - a]
            mix += np.random.RandomState(1).randn(len(mix)).astype(np.float32) * 0.0005  # room floor
            name = f"bleed_{o['id']}_{kind}{-db}_q{-quiet}"
            sf.write(os.path.join(OUT, name + ".wav"), np.clip(mix, -1, 1), R, subtype="PCM_16")
            json.dump({"name": name, "owner": o["id"], "owner_lang": o["lang"], "kind": kind, "db": db, "quiet": quiet,
                       "segments": [{k2: (round(v, 3) if isinstance(v, float) else v) for k2, v in s.items() if k2 != "x"}
                                    for s in sorted(segs + ints, key=lambda s: s["start"])]},
                      open(os.path.join(OUT, name + ".json"), "w"), ensure_ascii=False)
            manifest.append(name)
print(len(owners), "owners", len(manifest), "clips")
