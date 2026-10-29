# ../2026-10-llm-commit-policy-bedrock-de-hi-tr/build_clips.py with Spanish and French added. Unseen clips for
# en, es, de, hi, tr, fr: 20 FLEURS test sentences (CC BY 4.0) shared by the six
# languages that no earlier clip used (USED: a json list of every FLEURS id named in the earlier
# evals' clip and result files), 6-25 English words, drawn with seed 2026. Otherwise exactly
# ../2026-10-unseen/build_clips.py: one recording per sentence, alternating male and female
# readers, the same trimming, a 1 s lead, and the two pause patterns:
#   reg: 1.0-1.95 s between sentences; irr: 0.3-1.2 s (same seeds, so the same gaps).
#   python3 -I build_clips.py OUT RV_DIR USED_JSON
import json, os, random, sys, tarfile, urllib.request, wave

OUT, RV, USED = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, RV)
import fetch_audio as fa  # noqa: E402  (fleurs_rows, to_pcm, HF)

FLEURS = {"en": "en_us", "es": "es_419", "de": "de_de", "hi": "hi_in", "tr": "tr_tr", "fr": "fr_fr"}
N, RATE = 20, 16000
used = set(json.load(open(USED)))
rows = {l: fa.fleurs_rows(c) for l, c in FLEURS.items()}
common = sorted(set.intersection(*(set(r) for r in rows.values())), key=int)
pool = [i for i in common if i not in used and 6 <= len(rows["en"][i][0][1].split()) <= 25]
ids = random.Random(2026).sample(pool, N)
print(f"{len(common)} common ids, {len(pool)} unused; picked {N}", flush=True)


def gaps(seed, lo, hi, n):
    r = random.Random(seed)
    return [round(r.uniform(lo, hi), 2) for _ in range(n)]


PATTERNS = {"reg": gaps(11, 1.0, 1.95, N + 1), "irr": gaps(12, 0.3, 1.2, N + 1)}

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
    print(lang, "done", flush=True)
