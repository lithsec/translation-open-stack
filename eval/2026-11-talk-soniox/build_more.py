# More clips for the Russian and Hindi "which hearing" rerun: four more sets of 20 FLEURS test sentences (CC BY 4.0),
# c d e f, built exactly as build_clips.py builds a and b (regular pauses 1.0-1.95 s from the same seed, readers
# alternating male and female where both exist, 6-25 English words), from ids no eval in this repo has used (every
# eval/**/ids.json and ../2026-10-real-voices/sentences/fleurs_ids.json). Each language draws its own ids from those
# it shares with English (so the English reference exists; en, ru and hi together have too few unused ones): the
# two languages' sentences differ. Hindi has only 73 unused: its last 7 are ids other evals used (never this one's
# sets a and b). Seed 2031.
#   python3 -I build_more.py <out dir> <real-voices dir> <eval dir> [ids_more.json]
# Writes <out>/clips_{c,d,e,f}/{ru,hi}.wav + .json + .txt.json, {ru,hi}.ref.json (the English reference text of
# that language's sentences: no English audio)
# and <out>/ids_more.json. With ids_more.json (results/ids_more.json) the sets are read from it, not drawn.
import concurrent.futures as cf, glob, json, os, random, sys, tarfile, urllib.request, wave

OUT, RV, EV = sys.argv[1], sys.argv[2], sys.argv[3]
FIXED = json.load(open(sys.argv[4]))["sets"] if len(sys.argv) > 4 else None
sys.path.insert(0, RV)
import fetch_audio as fa  # noqa: E402

FLEURS = {"en": "en_us", "ru": "ru_ru", "hi": "hi_in", "pt": "pt_br"}
# LANGS=pt for the Portuguese rerun (default ru,hi: the Russian and Hindi one, unchanged).
AUDIO = os.environ.get("LANGS", "ru,hi").split(",")
NAMES = ["c", "d", "e", "f"]
N, RATE = 20, 16000

used = set(json.load(open(os.path.join(RV, "sentences", "fleurs_ids.json"))))
for p in glob.glob(os.path.join(EV, "**", "ids*.json"), recursive=True):
    try:
        for v in json.load(open(p)).get("sets", {}).values():
            used |= set(v)
    except Exception:
        pass

rows = {l: fa.fleurs_rows(FLEURS[l]) for l in ["en", *AUDIO]}
SETS = {}
for lang in AUDIO:
    common = sorted(set(rows["en"]) & set(rows[lang]), key=int)
    ok = [i for i in common if 6 <= len(rows["en"][i][0][1].split()) <= 25]
    fresh = [i for i in ok if i not in used]
    print(f"{lang}: {len(common)} ids shared with en, {len(ok)} of 6-25 words, {len(fresh)} unused", flush=True)
    if FIXED:
        SETS[lang] = FIXED[lang]
        continue
    # Unused ids first; if too few (Hindi: 73), the rest from ids other evals used but this one's sets a and b didn't.
    rng, need = random.Random(2031), N * len(NAMES)
    ids = rng.sample(fresh, min(need, len(fresh)))
    if len(ids) < need:
        mine = {i for v in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "ids.json")))["sets"].values() for i in v}
        ids += rng.sample([i for i in ok if i not in fresh and i not in mine], need - len(ids))
        print(f"{lang}: {len(fresh)} unused + {need - len(fresh)} used elsewhere, not in sets a and b", flush=True)
        rng.shuffle(ids)
    SETS[lang] = {s: ids[k * N:(k + 1) * N] for k, s in enumerate(NAMES)}
r = random.Random(11)
GAPS = [round(r.uniform(1.0, 1.95), 2) for _ in range(N + 1)]   # build_clips.py's pauses


def write(lang, st, pcms, texts, extra):
    d = os.path.join(OUT, f"clips_{st}")
    os.makedirs(d, exist_ok=True)
    pcm, marks, t = bytearray(b"\0\0" * RATE), [], 1.0
    for i, s in enumerate(pcms):
        dur = len(s) / 2 / RATE
        marks.append({"i": i, "start": round(t, 3), "end": round(t + dur, 3)})
        pcm += s + b"\0\0" * int(GAPS[i] * RATE)
        t += dur + GAPS[i]
    with wave.open(os.path.join(d, f"{lang}.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(bytes(pcm))
    json.dump({"lang": lang, "rate": RATE, "seconds": round(t, 3), "gaps": GAPS[:N], "sentences": marks, **extra},
              open(os.path.join(d, f"{lang}.json"), "w"), indent=1)
    json.dump(texts, open(os.path.join(d, f"{lang}.txt.json"), "w"), ensure_ascii=False, indent=1)


def one(lang):
    ALL = [i for s in NAMES for i in SETS[lang][s]]
    want = {}
    for k, i in enumerate(ALL):
        recs = rows[lang][i]
        pref = "FEMALE" if k % 2 else "MALE"
        want[i] = next((x for x in recs if x[2].upper() == pref), recs[0])
    names = {x[0]: i for i, x in want.items()}
    got = {}
    with urllib.request.urlopen(f"{fa.HF}/{FLEURS[lang]}/audio/test.tar.gz", timeout=1800) as resp:
        with tarfile.open(fileobj=resp, mode="r|gz") as tar:
            for m in tar:
                b = os.path.basename(m.name)
                if b in names and m.isfile():
                    got[names[b]] = fa.to_pcm(tar.extractfile(m).read())
                    if len(got) == len(names):
                        break
    miss = [i for i in ALL if i not in got]
    if miss:
        raise SystemExit(f"{lang}: {len(miss)} missing")
    for st in NAMES:
        sids = SETS[lang][st]
        write(lang, st, [got[i] for i in sids], [want[i][1] for i in sids],
              {"fleurs_ids": sids, "files": [want[i][0] for i in sids], "genders": [want[i][2] for i in sids]})
    return lang


os.makedirs(OUT, exist_ok=True)
json.dump({"sets": SETS}, open(os.path.join(OUT, "ids_more.json"), "w"))
for lang in AUDIO:   # the English reference text of each language's sentences
    for st in NAMES:
        os.makedirs(os.path.join(OUT, f"clips_{st}"), exist_ok=True)
        json.dump([rows["en"][i][0][1] for i in SETS[lang][st]], open(os.path.join(OUT, f"clips_{st}", f"{lang}.ref.json"), "w"),
                  ensure_ascii=False, indent=1)
with cf.ThreadPoolExecutor(len(AUDIO)) as ex:
    for l in ex.map(one, AUDIO):
        print(l, "done", flush=True)
print("done", flush=True)
