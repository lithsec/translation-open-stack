# One live-style clip per language, as ../2026-10-complete-thought-ht-km-lo/build_clips.py: 20 FLEURS test sentences
# (CC BY 4.0) shared with en_us (6-25 English words, <= 25 s), drawn with seed 2026, alternating male/female readers,
# each trimmed of its silence (fetch_audio.to_pcm), a 1 s lead and the "reg" pauses (1.0-1.95 s, seed 11).
#   python3 -I build_clips.py OUT lang:fleurs_cfg ...
import json, os, random, sys, tarfile, urllib.request
sys.path.insert(0, "/Users/sstone/dev/translation-open-stack/eval/2026-10-real-voices")
import fetch_audio as fa  # noqa: E402

OUT = sys.argv[1]
N, RATE = 20, 16000
en = fa.fleurs_rows("en_us")
gaps = (lambda r: [round(r.uniform(1.0, 1.95), 2) for _ in range(N + 1)])(random.Random(11))
for spec in sys.argv[2:]:
    lang, cfg = spec.split(":")
    rows = fa.fleurs_rows(cfg)
    pool = sorted([i for i in rows if i in en and 6 <= len(en[i][0][1].split()) <= 25], key=int)
    ids = random.Random(2026).sample(pool, N)
    want = {}
    for k, i in enumerate(ids):
        pref = "FEMALE" if k % 2 else "MALE"
        want[i] = next((r for r in rows[i] if r[2].upper() == pref), rows[i][0])
    names = {r[0]: i for i, r in want.items()}
    got = {}
    with urllib.request.urlopen(f"{fa.HF}/{cfg}/audio/test.tar.gz", timeout=1800) as resp:
        with tarfile.open(fileobj=resp, mode="r|gz") as tar:
            for m in tar:
                b = os.path.basename(m.name)
                if b in names and m.isfile():
                    got[names[b]] = fa.to_pcm(tar.extractfile(m).read())
                    if len(got) == N: break
    assert len(got) == N, (lang, len(got))
    d = os.path.join(OUT, lang); os.makedirs(d, exist_ok=True)
    pcm, marks, t = bytearray(b"\0\0" * RATE), [], 1.0
    for k, i in enumerate(ids):
        s = got[i]; dur = len(s) / 2 / RATE
        marks.append({"i": k, "start": round(t, 3), "end": round(t + dur, 3)})
        pcm += s + b"\0\0" * int(gaps[k] * RATE)
        t += dur + gaps[k]
    open(f"{d}/clip.raw", "wb").write(bytes(pcm))
    json.dump({"lang": lang, "cfg": cfg, "seconds": round(t, 3), "gaps": gaps[:N], "sentences": marks, "fleurs_ids": ids,
               "files": [want[i][0] for i in ids], "text": [want[i][1] for i in ids], "en": [en[i][0][1] for i in ids]},
              open(f"{d}/clip.json", "w"), ensure_ascii=False, indent=1)
    print(lang, f"{t:.1f}s", flush=True)
