# Unseen clips: 20 FLEURS test sentences (CC BY 4.0) shared by en, es, fr, ja, km, lo, pt that no
# earlier October clip used, plus 20 unused CMU Haitian Creole utterances. Two pause patterns:
#   reg: 1.0-1.95 s between sentences (as the e2e clips)
#   irr: 0.3-1.2 s, irregular (closer to natural speech)
#   python3 -I build_clips.py <out dir> <real-voices dir> <old clips dir>
import csv, glob, json, os, random, sys, tarfile, urllib.request, wave
import numpy as np

OUT, RV, OLD = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, RV)
import fetch_audio as fa  # noqa: E402  (to_pcm, CMU paths)

FLEURS = {"en": "en_us", "es": "es_419", "fr": "fr_fr", "ja": "ja_jp", "km": "km_kh", "lo": "lo_la", "pt": "pt_br"}
N, RATE = 20, 16000
csv.field_size_limit(10**9)

used_ids = set(json.load(open(os.path.join(RV, "sentences", "fleurs_ids.json"))))
used_txt = set()
for p in glob.glob(os.path.join(OLD, "*.txt.json")) + glob.glob(os.path.join(RV, "sentences", "*.json")):
    try:
        for t in json.load(open(p)):
            if isinstance(t, str):
                used_txt.add(t.strip())
    except Exception:
        pass

rows = {l: fa.fleurs_rows(c) for l, c in FLEURS.items()}
common = sorted(set.intersection(*(set(r) for r in rows.values())), key=int)
pool = [i for i in common if i not in used_ids
        and 6 <= len(rows["en"][i][0][1].split()) <= 25
        and not any(r[1].strip() in used_txt for l in rows for r in rows[l][i])]
rnd = random.Random(2026)
ids = rnd.sample(pool, N)
print(f"{len(common)} common ids, {len(pool)} unused; picked {N}", flush=True)

# English meaning per id: the en_us transcription is lower-cased/raw; FLoRes text is in the TSV
# column 3 (normalised) vs 2 (raw). fleurs_rows keeps column 2 (raw), as the earlier clips did.
meta_all = {"ids": ids}


def gaps(seed, lo, hi, n):
    r = random.Random(seed)
    return [round(r.uniform(lo, hi), 2) for _ in range(n)]


PATTERNS = {"reg": gaps(11, 1.0, 1.95, N + 1), "irr": gaps(12, 0.3, 1.2, N + 1)}


def write(lang, pcms, texts, extra):
    for name, g in PATTERNS.items():
        d = os.path.join(OUT, f"clips_{name}")
        os.makedirs(d, exist_ok=True)
        lead = 1.0
        pcm, marks, t = bytearray(b"\0\0" * int(lead * RATE)), [], lead
        for i, s in enumerate(pcms):
            dur = len(s) / 2 / RATE
            marks.append({"i": i, "start": round(t, 3), "end": round(t + dur, 3)})
            pcm += s + b"\0\0" * int(g[i] * RATE)
            t += dur + g[i]
        with wave.open(os.path.join(d, f"{lang}.wav"), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(bytes(pcm))
        json.dump({"lang": lang, "rate": RATE, "seconds": round(t, 3), "gaps": g[:N], "sentences": marks, **extra},
                  open(os.path.join(d, f"{lang}.json"), "w"), indent=1)
        json.dump(texts, open(os.path.join(d, f"{lang}.txt.json"), "w"), ensure_ascii=False, indent=1)
    print(f"{lang}: {len(pcms)} sentences", flush=True)


for lang, cfg in FLEURS.items():
    want = {}
    for k, i in enumerate(ids):
        recs = rows[lang][i]
        pref = "FEMALE" if k % 2 else "MALE"
        want[i] = next((r for r in recs if r[2].upper() == pref), recs[0])
    names = {r[0]: i for i, r in want.items()}
    got = {}
    with urllib.request.urlopen(f"{fa.HF}/{cfg}/audio/test.tar.gz", timeout=900) as resp:
        with tarfile.open(fileobj=resp, mode="r|gz") as tar:
            for m in tar:
                b = os.path.basename(m.name)
                if b in names and m.isfile():
                    got[names[b]] = fa.to_pcm(tar.extractfile(m).read())
                    if len(got) == len(names):
                        break
    miss = [i for i in ids if i not in got]
    if miss:
        sys.exit(f"{lang}: {len(miss)} missing")
    write(lang, [got[i] for i in ids], [want[i][1] for i in ids],
          {"fleurs_ids": ids, "files": [want[i][0] for i in ids], "genders": [want[i][2] for i in ids]})

# Haitian Creole: CMU utterances not in the earlier 30 (by text), spread over speakers.
old_ht = set(json.load(open(os.path.join(RV, "sentences", "ht.json"))))
lines = fa.get(f"{fa.CMU}/etc/txt.done.data").decode("utf-8").splitlines()
utts = []
for ln in lines:
    p = ln.strip().split('"')
    if len(p) >= 3:
        u, t = p[0].strip("( ").strip(), p[1].strip()
        if 6 <= len(t.split()) <= 25 and t not in old_ht:
            utts.append((u, t))
by = {}
for u in utts:
    by.setdefault(u[0].split("_")[0], []).append(u)
spk = sorted(by)
r = random.Random(2026)
r.shuffle(spk)
chosen = []
while len(chosen) < N:
    for s in spk:
        if by[s] and len(chosen) < N:
            chosen.append(by[s].pop(r.randrange(len(by[s]))))
write("ht", [fa.to_pcm(fa.get(f"{fa.CMU}/wav/{u}.wav")) for u, _ in chosen], [t for _, t in chosen],
      {"cmu_utts": [u for u, _ in chosen]})
json.dump(meta_all, open(os.path.join(OUT, "ids.json"), "w"))
print("done", flush=True)
