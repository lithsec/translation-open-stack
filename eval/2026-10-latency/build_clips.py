# Builds the latency clips: N sentences per language, joined with seeded
# natural pauses (uniform 1.0-2.0 s), 16 kHz mono PCM16.
#
#   en, ja, km : FLEURS (CC BY 4.0) recordings already cut for
#                ../2026-10-real-voices (fetch_audio.py there), first N ids
#   ht         : CMU Haitian Creole speech, same source as ../2026-10-real-voices
#   es         : FLEURS es_419 test, the SAME FLoRes ids (streamed from the
#                tarball; only the chosen recordings are kept)
#
#   python3 build_clips.py <real-voices dir with audio/ and sentences/> <out dir>
#
# Writes <out>/<lang>.wav, <out>/<lang>.json (sentence start/end seconds) and
# <out>/<lang>.txt.json (what was said) plus <out>/refs.json (FLoRes text per
# language for the same ids, for grading).
import json, os, random, subprocess, sys, tarfile, tempfile, urllib.request, wave

N, RATE, LEAD = 20, 16000, 1.0
HF = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
GAPS = [round(g, 2) for g in (lambda r: [r.uniform(1.0, 2.0) for _ in range(N)])(random.Random(7))]


def read_wav(p):
    with wave.open(p) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1
        return w.readframes(w.getnframes())


def write(lang, pcms, texts):
    pcm, marks, t = bytearray(b"\0\0" * int(LEAD * RATE)), [], LEAD
    for i, s in enumerate(pcms):
        dur = len(s) / 2 / RATE
        marks.append({"i": i, "start": round(t, 3), "end": round(t + dur, 3)})
        pcm += s + b"\0\0" * int(GAPS[i] * RATE)
        t += dur + GAPS[i]
    with wave.open(os.path.join(OUT, f"{lang}.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(bytes(pcm))
    json.dump({"lang": lang, "rate": RATE, "seconds": round(t, 3), "gaps": GAPS, "sentences": marks},
              open(os.path.join(OUT, f"{lang}.json"), "w"), indent=1)
    json.dump(texts, open(os.path.join(OUT, f"{lang}.txt.json"), "w"), ensure_ascii=False, indent=1)
    print(f"{lang}: {len(pcms)} sentences, {t:.0f} s", flush=True)


def from_real_voices(lang):
    raw = read_wav(os.path.join(SRC, "audio", f"{lang}.wav"))
    marks = json.load(open(os.path.join(SRC, "audio", f"{lang}.json")))["sentences"][:N]
    texts = json.load(open(os.path.join(SRC, "sentences", f"{lang}.json")))[:N]
    pcms = [raw[int(m["start"] * RATE) * 2: int(m["end"] * RATE) * 2] for m in marks]
    write(lang, pcms, texts)


def spanish(ids):
    sys.path.insert(0, SRC)
    from fetch_audio import to_pcm  # same trimming as the other languages
    rows = {}
    with urllib.request.urlopen(f"{HF}/es_419/test.tsv", timeout=120) as r:
        for line in r.read().decode("utf-8").splitlines():
            f = line.split("\t")
            if len(f) >= 7:
                rows.setdefault(f[0], []).append((f[1], f[2], f[6]))
    want = {}
    for k, i in enumerate(ids):
        pref = "FEMALE" if k % 2 else "MALE"
        want[i] = next((r for r in rows[i] if r[2].upper() == pref), rows[i][0])
    names = {r[0]: i for i, r in want.items()}
    got = {}
    with urllib.request.urlopen(f"{HF}/es_419/audio/test.tar.gz", timeout=600) as resp:
        with tarfile.open(fileobj=resp, mode="r|gz") as tar:
            for m in tar:
                b = os.path.basename(m.name)
                if b in names and m.isfile():
                    got[names[b]] = to_pcm(tar.extractfile(m).read())
                    if len(got) == len(names):
                        break
    write("es", [got[i] for i in ids], [want[i][1] for i in ids])


if __name__ == "__main__":
    ids = json.load(open(os.path.join(SRC, "sentences", "fleurs_ids.json")))[:N]
    what = sys.argv[3:] or ["en", "ja", "km", "ht", "es"]
    for lang in what:
        if lang == "es":
            spanish(ids)
        else:
            from_real_voices(lang)
    # References: FLoRes text of the same ids (the clips' own text), and the
    # English meaning of the Haitian sentences (model-made, see real-voices).
    refs = {l: json.load(open(os.path.join(OUT, f"{l}.txt.json"))) for l in ["en", "ja", "km", "es", "ht"]
            if os.path.exists(os.path.join(OUT, f"{l}.txt.json"))}
    refs["ht_meaning_en"] = json.load(open(os.path.join(SRC, "sentences", "meaning_ht.json")))[:N]
    json.dump(refs, open(os.path.join(OUT, "refs.json"), "w"), ensure_ascii=False, indent=1)
