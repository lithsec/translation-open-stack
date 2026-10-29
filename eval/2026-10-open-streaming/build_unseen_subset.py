# The unseen clips of ../2026-10-unseen/build_clips.py for a subset of its languages,
# with the FLEURS ids that run picked (its results.json "fleurs_ids") instead of
# re-drawing them (the draw depends on earlier clip folders that are not in the repo).
# Same reader choice (alternating male/female), same trimming, same gaps.
#   python3 -I build_unseen_subset.py OUT RV_DIR UNSEEN_RESULTS_JSON en es fr
import json, os, sys, tarfile, urllib.request, wave

OUT, RV, RES = sys.argv[1], sys.argv[2], sys.argv[3]
LANGS = sys.argv[4:]
sys.path.insert(0, RV)
import fetch_audio as fa  # noqa: E402

FLEURS = {"en": "en_us", "es": "es_419", "fr": "fr_fr", "ja": "ja_jp", "km": "km_kh", "lo": "lo_la", "pt": "pt_br"}
RATE = 16000
res = json.load(open(RES))
ids = res["fleurs_ids"]
N = len(ids)


def gaps(seed, lo, hi, n):
    import random
    r = random.Random(seed)
    return [round(r.uniform(lo, hi), 2) for _ in range(n)]


PATTERNS = {"reg": gaps(11, 1.0, 1.95, N + 1), "irr": gaps(12, 0.3, 1.2, N + 1)}
for k, g in PATTERNS.items():
    assert g[:N] == res["gaps_s"][k], (k, "gaps differ from the unseen run")

for lang in LANGS:
    rows = fa.fleurs_rows(FLEURS[lang])
    want = {}
    for k, i in enumerate(ids):
        recs = rows[i]
        pref = "FEMALE" if k % 2 else "MALE"
        want[i] = next((r for r in recs if r[2].upper() == pref), recs[0])
    names = {r[0]: i for i, r in want.items()}
    got = {}
    with urllib.request.urlopen(f"{fa.HF}/{FLEURS[lang]}/audio/test.tar.gz", timeout=900) as resp:
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
