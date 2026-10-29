# Unseen clips for en, ja, ko, fa and hi, built as ../2026-10-complete-thought-ht-km-lo/build_clips.py: per language,
# 20 FLEURS test sentences (CC BY 4.0) with 6-25 English words, drawn with seed 2026 from the ids no earlier clip used.
# Only 18 unused ids are shared by all five languages, so each language draws its own 20 from the ids it shares with
# en_us (the English FLEURS text is the into-English reference); the English clip draws from en_us alone. USED is a json list of every FLEURS id named in the earlier evals' clip and
# result files; any sentence whose text appears in a json file under the ROOTS is left out too. The English clip is
# the source of all six out-of-English directions (en->ja, ko, fa, ur, bn, ta), which are graded against what was
# said in English, so ur, bn and ta need no audio. One recording per sentence, alternating male and female readers,
# a 1 s lead, and the same two pause patterns as before: reg (1.0-1.95 s between sentences) and irr (0.3-1.2 s),
# the same seeds.
#   python3 -I build_clips.py OUT RV_DIR USED_JSON ROOT...
import json, os, random, sys, tarfile, urllib.request, wave

OUT, RV, USED = sys.argv[1], sys.argv[2], sys.argv[3]
ROOTS = sys.argv[4:]
sys.path.insert(0, RV)
import fetch_audio as fa  # noqa: E402  (fleurs_rows, to_pcm, HF)

FLEURS = {"en": "en_us", "ja": "ja_jp", "ko": "ko_kr", "fa": "fa_ir", "hi": "hi_in"}
N, RATE = 20, 16000
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
rows = {l: fa.fleurs_rows(c) for l, c in FLEURS.items()}
IDS = {}
for lang in FLEURS:
    common = sorted(set(rows[lang]) & set(rows["en"]), key=int)
    pool = [i for i in common if i not in used and 6 <= len(rows["en"][i][0][1].split()) <= 25
            and not any(r[1].strip() in seen_str for l in {lang, "en"} for r in rows[l][i])]
    IDS[lang] = random.Random(2026).sample(pool, N)
    print(f"{lang}: {len(common)} ids shared with en, {len(pool)} unused; picked {N}", flush=True)


def gaps(seed, lo, hi, n):
    r = random.Random(seed)
    return [round(r.uniform(lo, hi), 2) for _ in range(n)]


PATTERNS = {"reg": gaps(11, 1.0, 1.95, N + 1), "irr": gaps(12, 0.3, 1.2, N + 1)}

for lang, cfg in FLEURS.items():
    ids = IDS[lang]
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
    pcms, texts = [got[i] for i in ids], [want[i][1] for i in ids]
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
        json.dump({"lang": lang, "rate": RATE, "seconds": round(t, 3), "gaps": g[:N], "sentences": marks,
                   "fleurs_ids": ids, "files": [want[i][0] for i in ids], "genders": [want[i][2] for i in ids]},
                  open(os.path.join(d, f"{lang}.json"), "w"), indent=1)
        json.dump(texts, open(os.path.join(d, f"{lang}.txt.json"), "w"), ensure_ascii=False, indent=1)
        if lang != "en":   # the into-English reference: the English FLEURS text of the same ids
            json.dump([rows["en"][i][0][1] for i in ids], open(os.path.join(d, f"{lang}.ref_en.json"), "w"),
                      ensure_ascii=False, indent=1)
    print(lang, "done", flush=True)
