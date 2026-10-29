# German, Russian and Romanian clips: 40 FLEURS test sentences (CC BY 4.0) shared by en, de, ru and ro
# that no earlier clip set used (the real-voices ids, and every earlier clip's text), split into set a
# (the first 20) and set b (the next 20), seed 2027. Each language's recordings alternate male and female
# readers. As ../2026-10-unseen/build_clips.py:
#   reg: 1.0-1.95 s between sentences; irr: 0.3-1.2 s (set a only, for German's turn test)
# Also writes each sentence alone (sent/<lang>/<set><n>.wav) for per-sentence recognition.
#   python3 -I build_clips.py <out dir> <real-voices dir> <old clips dir or "">
import csv, glob, json, os, random, sys, tarfile, urllib.request, wave

OUT, RV, OLD = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, RV)
import fetch_audio as fa  # noqa: E402  (to_pcm, fleurs_rows)

FLEURS = {"en": "en_us", "de": "de_de", "ru": "ru_ru", "ro": "ro_ro"}
N, RATE = 20, 16000
csv.field_size_limit(10**9)

used_ids = set(json.load(open(os.path.join(RV, "sentences", "fleurs_ids.json"))))
used_txt = set()
for p in (glob.glob(os.path.join(OLD, "**", "*.txt.json"), recursive=True) if OLD else []) + glob.glob(os.path.join(RV, "sentences", "*.json")):
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
ids = random.Random(2027).sample(pool, 2 * N)
SETS = {"a": ids[:N], "b": ids[N:]}
print(f"{len(common)} common ids, {len(pool)} unused; picked {2 * N}", flush=True)


def gaps(seed, lo, hi, n):
    r = random.Random(seed)
    return [round(r.uniform(lo, hi), 2) for _ in range(n)]


PATTERNS = {"reg": gaps(11, 1.0, 1.95, N + 1), "irr": gaps(12, 0.3, 1.2, N + 1)}


def write(lang, st, pcms, texts, extra):
    for name, g in PATTERNS.items():
        if name == "irr" and not (st == "a" and lang in ("de", "en")):
            continue
        d = os.path.join(OUT, f"clips_{st}_{name}")
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
    sd = os.path.join(OUT, "sent", lang)
    os.makedirs(sd, exist_ok=True)
    for i, s in enumerate(pcms):
        with wave.open(os.path.join(sd, f"{st}{i:02d}.wav"), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(s)
    print(f"{lang} {st}: {len(pcms)} sentences", flush=True)


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
    for st, sids in SETS.items():
        write(lang, st, [got[i] for i in sids], [want[i][1] for i in sids],
              {"fleurs_ids": sids, "files": [want[i][0] for i in sids], "genders": [want[i][2] for i in sids]})
json.dump({"sets": SETS}, open(os.path.join(OUT, "ids.json"), "w"))
print("done", flush=True)
