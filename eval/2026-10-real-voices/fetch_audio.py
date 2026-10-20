# Real voices for the October comparison, instead of synthetic speech:
#
#   FLEURS (google/fleurs, CC BY 4.0): the same FLoRes sentences read by native
#   speakers in English, Japanese, Khmer and Lao. Every sentence has the same
#   id in every language, so English is the reference meaning for the others
#   and each language's own text is the reference for English into it.
#   Haitian Creole isn't in FLEURS.
#
#   CMU Haitian Creole speech (speech.cs.cmu.edu/haitian, 1997-98, 150 native
#   speakers, read sentences; free use with the acknowledgement in its COPYING).
#   It has no English translations, so make_refs.py writes them (Gemini 2.5
#   Pro) and the grade says so.
#
#   python3 fetch_audio.py          # ~1.6 GB streamed; only the chosen clips kept
#
# Writes audio/<lang>.wav (16 kHz mono, the sentences joined with 0.8 s pauses),
# audio/<lang>.json (where each sentence starts and ends) and
# sentences/<lang>.json (what was said, in order).
import csv, io, json, os, random, subprocess, sys, tarfile, tempfile, urllib.request, wave

HERE = os.path.dirname(os.path.abspath(__file__))
N, RATE, GAP = 30, 16000, 0.8
FLEURS = {"en": "en_us", "ja": "ja_jp", "km": "km_kh", "lo": "lo_la"}
HF = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
CMU = "http://speech.cs.cmu.edu/haitian/speech/data/cmu_haitian_speech"
csv.field_size_limit(10**9)


def get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def fleurs_rows(cfg):
    """id -> [(file, raw transcription, gender)] from the test split's TSV."""
    rows = {}
    for line in get(f"{HF}/{cfg}/test.tsv").decode("utf-8").splitlines():
        f = line.split("\t")
        if len(f) >= 7:
            # Over 25 s isn't one spoken sentence (one Lao file ran 160 s).
            if f[5].isdigit() and int(f[5]) / 16000 <= 25:
                rows.setdefault(f[0], []).append((f[1], f[2], f[6]))
    return rows


def to_pcm(raw_wav):
    """Any wav -> 16 kHz mono s16 PCM (sox), trimmed of the silence the
    recordings carry at each end. The threshold is relative to the recording's
    own loudness: a fixed one took quiet English recordings for silence."""
    import numpy as np
    with tempfile.TemporaryDirectory() as d:
        a, b = os.path.join(d, "a.wav"), os.path.join(d, "b.wav")
        open(a, "wb").write(raw_wav)
        subprocess.run(["sox", "-V1", a, "-r", str(RATE), "-c", "1", "-b", "16", b], check=True)
        with wave.open(b) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    frame = RATE // 50  # 20 ms
    n = len(x) // frame
    if n < 5:
        return x.tobytes()
    rms = np.sqrt((x[: n * frame].astype(np.float64).reshape(n, frame) ** 2).mean(axis=1))
    # Against typical loudness, not the peak: one click set the bar so high
    # that an 8-second sentence came out 0.4 s.
    loud = np.where(rms > max(np.percentile(rms, 90) * 0.1, 30))[0]
    if not len(loud):
        return x.tobytes()
    pad = 8  # 160 ms either side
    lo, hi = max(0, loud[0] - pad), min(n, loud[-1] + pad + 1)
    if (hi - lo) < 0.4 * n:  # never cut most of a recording away
        return x.tobytes()
    return x[lo * frame : hi * frame].tobytes()


def write_clip(lang, pcms, texts):
    pcm, marks, t = bytearray(b"\0\0" * int(GAP * RATE)), [], GAP
    for i, s in enumerate(pcms):
        dur = len(s) / 2 / RATE
        marks.append({"i": i, "start": round(t, 3), "end": round(t + dur, 3)})
        pcm += s + b"\0\0" * int(GAP * RATE)
        t += dur + GAP
    os.makedirs(os.path.join(HERE, "audio"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "sentences"), exist_ok=True)
    with wave.open(os.path.join(HERE, "audio", f"{lang}.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(bytes(pcm))
    json.dump({"lang": lang, "rate": RATE, "seconds": round(t, 3), "sentences": marks},
              open(os.path.join(HERE, "audio", f"{lang}.json"), "w"), indent=1)
    json.dump(texts, open(os.path.join(HERE, "sentences", f"{lang}.json"), "w"), ensure_ascii=False, indent=1)
    print(f"{lang}: {len(pcms)} sentences, {t:.0f} s", flush=True)


def fleurs():
    rows = {l: fleurs_rows(c) for l, c in FLEURS.items()}
    common = sorted(set.intersection(*(set(r) for r in rows.values())), key=int)
    rnd = random.Random(17)
    # Sentences of speaking length (6-25 English words), drawn at random.
    pool = [i for i in common if 6 <= len(rows["en"][i][0][1].split()) <= 25]
    ids = rnd.sample(pool, N)
    print(f"FLEURS: {len(common)} sentences in all four languages; using {N}", flush=True)
    json.dump(ids, open(os.path.join(HERE, "sentences", "fleurs_ids.json"), "w"))
    for lang, cfg in FLEURS.items():
        # One recording per sentence, alternating speakers' genders where we can.
        want = {}
        for k, i in enumerate(ids):
            recs = rows[lang][i]
            pref = "FEMALE" if k % 2 else "MALE"
            want[i] = next((r for r in recs if r[2].upper() == pref), recs[0])
        names = {r[0]: i for i, r in want.items()}
        got = {}
        with urllib.request.urlopen(f"{HF}/{cfg}/audio/test.tar.gz", timeout=600) as resp:
            with tarfile.open(fileobj=resp, mode="r|gz") as tar:
                for m in tar:
                    base = os.path.basename(m.name)
                    if base in names and m.isfile():
                        got[names[base]] = to_pcm(tar.extractfile(m).read())
                        if len(got) == len(names):
                            break
        missing = [i for i in ids if i not in got]
        if missing:
            sys.exit(f"{lang}: {len(missing)} recordings not found in the archive")
        write_clip(lang, [got[i] for i in ids], [want[i][1] for i in ids])


def haitian():
    lines = get(f"{CMU}/etc/txt.done.data").decode("utf-8").splitlines()
    utts = []
    for ln in lines:
        p = ln.strip().split('"')
        if len(p) >= 3:
            utt = p[0].strip("( ").strip()
            text = p[1].strip()
            if 6 <= len(text.split()) <= 25:
                utts.append((utt, text))
    rnd = random.Random(17)
    # Spread over speakers (the id's first part), both men and women.
    by_spk = {}
    for u in utts:
        by_spk.setdefault(u[0].split("_")[0], []).append(u)
    spks = sorted(by_spk)
    rnd.shuffle(spks)
    chosen = []
    while len(chosen) < N:
        for s in spks:
            if by_spk[s] and len(chosen) < N:
                chosen.append(by_spk[s].pop(rnd.randrange(len(by_spk[s]))))
    pcms = [to_pcm(get(f"{CMU}/wav/{u}.wav")) for u, _ in chosen]
    write_clip("ht", pcms, [t for _, t in chosen])
    print(f"ht: {len({u.split('_')[0] for u, _ in chosen})} speakers", flush=True)


if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "sentences"), exist_ok=True)
    what = sys.argv[1:] or ["fleurs", "ht"]
    if "fleurs" in what:
        fleurs()
    if "ht" in what:
        haitian()
