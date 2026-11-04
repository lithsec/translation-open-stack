# Clips for the 14 languages never run live through the stack: 40 FLEURS test sentences (CC BY 4.0) shared by
# English and all 14, those no earlier round used first (the real-voices ids, the short check's, de-ru-ro's, the
# November sets'), then ids earlier rounds used to make up 40, split into set a (first 20) and set b (next 20), seed 2028. Recordings alternate male and
# female readers where both exist. Regular pauses only (1.0-1.95 s, ../2026-10-de-ru-ro/build_clips.py's).
#   python3 -I build_clips.py <out dir> <real-voices dir> <eval dir>
import concurrent.futures as cf, glob, json, os, random, sys, tarfile, urllib.request, wave

OUT, RV, EV = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, RV)
import fetch_audio as fa  # noqa: E402

FLEURS = {"en": "en_us", "zh": "cmn_hans_cn", "uk": "uk_ua", "vi": "vi_vn", "ar": "ar_eg", "fa": "fa_ir",
          "tl": "fil_ph", "sw": "sw_ke", "it": "it_it", "ko": "ko_kr", "id": "id_id", "tr": "tr_tr",
          "bn": "bn_in", "ur": "ur_pk", "hi": "hi_in"}
N, RATE = 20, 16000

used = set(json.load(open(os.path.join(RV, "sentences", "fleurs_ids.json"))))
sc = json.load(open(os.path.join(EV, "2026-10-language-short-check", "results.json")))["sentences"]
used |= {s["fleurs_id"] for v in sc.values() if isinstance(v, list) for s in v if isinstance(s, dict) and "fleurs_id" in s}
for p in glob.glob(os.path.join(EV, "**", "ids.json"), recursive=True):
    try:
        for v in json.load(open(p)).get("sets", {}).values():
            used |= set(v)
    except Exception:
        pass
used_txt = set()
for p in glob.glob(os.path.join(EV, "**", "*.txt.json"), recursive=True):
    try:
        used_txt |= {t.strip() for t in json.load(open(p)) if isinstance(t, str)}
    except Exception:
        pass

rows = {l: fa.fleurs_rows(c) for l, c in FLEURS.items()}
common = sorted(set.intersection(*(set(r) for r in rows.values())), key=int)
ok = [i for i in common if 6 <= len(rows["en"][i][0][1].split()) <= 25]
fresh = [i for i in ok if i not in used and not any(r[1].strip() in used_txt for l in rows for r in rows[l][i])]
# Only ~20 shared ids are unused by earlier rounds: take those, then fill from ids earlier rounds used (in other
# languages; none of these 14 was run live before, so a repeated English sentence biases nothing here).
rest = [i for i in ok if i not in fresh]
print(f"{len(common)} common ids, {len(ok)} of 6-25 words, {len(fresh)} unused", flush=True)
if len(ok) < 2 * N:
    sys.exit("not enough ids")
rng = random.Random(2028)
ids = rng.sample(fresh, min(len(fresh), 2 * N))
ids += rng.sample(rest, 2 * N - len(ids))
rng.shuffle(ids)
SETS = {"a": ids[:N], "b": ids[N:]}
r = random.Random(11)
GAPS = [round(r.uniform(1.0, 1.95), 2) for _ in range(N + 1)]


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
    want = {}
    for k, i in enumerate(ids):
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
    miss = [i for i in ids if i not in got]
    if miss:
        raise SystemExit(f"{lang}: {len(miss)} missing")
    for st, sids in SETS.items():
        write(lang, st, [got[i] for i in sids], [want[i][1] for i in sids],
              {"fleurs_ids": sids, "files": [want[i][0] for i in sids], "genders": [want[i][2] for i in sids]})
    return lang


with cf.ThreadPoolExecutor(5) as ex:
    for l in ex.map(one, FLEURS):
        print(l, "done", flush=True)
json.dump({"sets": SETS}, open(os.path.join(OUT, "ids.json"), "w"))
print("done", flush=True)
