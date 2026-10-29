# Unseen clips for en, km, lo and ht, built as ../2026-10-complete-thought-endpointing/build_clips.py:
#   - en, km, lo: 20 FLEURS test sentences (CC BY 4.0) shared by en_us, km_kh and lo_la, 6-25 English words,
#     drawn with seed 2026 from the ids no earlier clip used. USED is a json list of every FLEURS id named in the
#     earlier evals' clip and result files; the first 30 rows of the km_kh and lo_la test lists (the CTC
#     streaming and duo runs' set) are left out too, and so is any sentence whose text appears in a json file
#     under the ROOTS.
#   - ht: FLEURS has no Haitian Creole. 20 CMU Haitian Creole utterances (speech.cs.cmu.edu/haitian, read
#     speech, free use with its acknowledgement), 6-25 words, spread over speakers, none whose text or
#     utterance id appears in a json file under the ROOTS. Their English reference is model-made (make_refs.py).
#   One recording per sentence, alternating male and female readers (FLEURS), a 1 s lead, and the same two pause
#   patterns as before: reg (1.0-1.95 s between sentences) and irr (0.3-1.2 s), the same seeds.
#   python3 -I build_clips.py OUT RV_DIR USED_JSON ROOT...
import csv, io, json, os, random, sys, tarfile, urllib.request, wave

OUT, RV, USED = sys.argv[1], sys.argv[2], sys.argv[3]
ROOTS = sys.argv[4:]
sys.path.insert(0, RV)
import fetch_audio as fa  # noqa: E402  (fleurs_rows, to_pcm, get, HF, CMU)

FLEURS = {"en": "en_us", "km": "km_kh", "lo": "lo_la"}
N, RATE = 20, 16000
csv.field_size_limit(10**9)

seen_str = set()


def walk(o):
    if isinstance(o, str):
        if len(o) < 2000:
            seen_str.add(o.strip())
    elif isinstance(o, dict):
        for v in o.values():
            walk(v)
    elif isinstance(o, list):
        for v in o:
            walk(v)


for root in ROOTS:
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in ("node_modules", ".git", "venv", ".venv")]
        for f in fn:
            p = os.path.join(dp, f)
            if f.endswith(".json") and os.path.getsize(p) < 30e6:
                try:
                    walk(json.load(open(p)))
                except Exception:
                    pass
print(len(seen_str), "strings in earlier json files", flush=True)

used = set(json.load(open(USED)))
for cfg in ("km_kh", "lo_la"):
    tsv = fa.get(f"{fa.HF}/{cfg}/test.tsv").decode("utf-8")
    used |= {r[0] for r in list(csv.reader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE))[:30]}
rows = {l: fa.fleurs_rows(c) for l, c in FLEURS.items()}
common = sorted(set.intersection(*(set(r) for r in rows.values())), key=int)
pool = [i for i in common if i not in used and 6 <= len(rows["en"][i][0][1].split()) <= 25
        and not any(r[1].strip() in seen_str for l in rows for r in rows[l][i])]
ids = random.Random(2026).sample(pool, N)
print(f"{len(common)} common ids, {len(pool)} unused; picked {N}", flush=True)


def gaps(seed, lo, hi, n):
    r = random.Random(seed)
    return [round(r.uniform(lo, hi), 2) for _ in range(n)]


PATTERNS = {"reg": gaps(11, 1.0, 1.95, N + 1), "irr": gaps(12, 0.3, 1.2, N + 1)}


def write(lang, pcms, texts, extra):
    for name, g in PATTERNS.items():
        d = os.path.join(OUT, f"clips_{name}")
        os.makedirs(d, exist_ok=True)
        pcm, marks, t = bytearray(b"\0\0" * RATE), [], 1.0
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
    print(lang, "done", flush=True)


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
    assert len(got) == N, (lang, len(got))
    write(lang, [got[i] for i in ids], [want[i][1] for i in ids],
          {"fleurs_ids": ids, "files": [want[i][0] for i in ids], "genders": [want[i][2] for i in ids]})

lines = fa.get(f"{fa.CMU}/etc/txt.done.data").decode("utf-8").splitlines()
utts = []
for ln in lines:
    p = ln.strip().split('"')
    if len(p) >= 3:
        u, t = p[0].strip("( ").strip(), p[1].strip()
        if 6 <= len(t.split()) <= 25 and t not in seen_str and u not in seen_str:
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
print(f"ht: {len(utts)} unused utterances, {len({u.split('_')[0] for u, _ in chosen})} speakers", flush=True)
write("ht", [fa.to_pcm(fa.get(f"{fa.CMU}/wav/{u}.wav")) for u, _ in chosen], [t for _, t in chosen],
      {"cmu_utts": [u for u, _ in chosen]})
