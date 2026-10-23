# Pod: fetch the audio for the small-speaker-model test.
#   LibriSpeech test-clean (CC BY 4.0, openslr 12): bleed owners (en) + English speaker trials
#   CMU Haitian Creole speech (free use with acknowledgement): bleed owners (ht) + ht speaker trials
#   FLEURS test (CC BY 4.0): interferers (en/es/fr/pt/ja) and per-language trials (es/fr/pt/ja/lo/km/en),
#                            streamed; only the first files kept
import csv, io, json, os, subprocess, sys, tarfile, urllib.request, wave
import numpy as np
OUT = sys.argv[1]
R = 16000
HF = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
CMU = "http://speech.cs.cmu.edu/haitian/speech/data/cmu_haitian_speech"
FL = {k: v for k, v in {"en": "en_us", "es": "es_419", "fr": "fr_fr", "pt": "pt_br", "ja": "ja_jp", "lo": "lo_la", "km": "km_kh"}.items() if k in os.environ.get("FL_LANGS", "en,es,fr,pt,ja,lo,km").split(",")}
KEEP = 60
csv.field_size_limit(10**9)


def get(url):
    with urllib.request.urlopen(url, timeout=300) as r:
        return r.read()


def to16k(raw):
    p = subprocess.run(["sox", "-V1", "-t", "wav", "-", "-r", "16000", "-c", "1", "-b", "16", "-t", "wav", "-"],
                       input=raw, capture_output=True, check=True).stdout
    with wave.open(io.BytesIO(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2")


os.makedirs(OUT, exist_ok=True)
# LibriSpeech
lib = os.path.join(OUT, "libri")
if not os.path.isdir(os.path.join(lib, "LibriSpeech")):
    os.makedirs(lib, exist_ok=True)
    subprocess.run(f"curl -sL https://www.openslr.org/resources/12/test-clean.tar.gz | tar xz -C {lib}", shell=True, check=True)
print("libri ok", flush=True)
# CMU Haitian: 12 speakers with the most utterances, up to 30 each
cmu = os.path.join(OUT, "cmu")
os.makedirs(os.path.join(cmu, "wav"), exist_ok=True)
txt = get(f"{CMU}/etc/txt.done.data").decode("utf-8")
open(os.path.join(cmu, "txt.done.data"), "w", encoding="utf-8").write(txt)
by = {}
for ln in txt.splitlines():
    p = ln.strip().split('"')
    if len(p) >= 3:
        u = p[0].strip("( ").strip()
        by.setdefault(u.split("_")[0], []).append(u)
spk = sorted(by, key=lambda k: -len(by[k]))[:12]
n = 0
for s in spk:
    for u in by[s][:30]:
        f = os.path.join(cmu, "wav", u + ".wav")
        if not os.path.exists(f):
            try:
                open(f, "wb").write(get(f"{CMU}/wav/{u}.wav")); n += 1
            except Exception as e:
                print("cmu miss", u, e)
print("cmu ok", len(spk), "speakers", n, "files", flush=True)
# FLEURS: stream the test tar, keep the first KEEP files (16 kHz PCM) with text and gender
for lang, cfg in FL.items():
    d = os.path.join(OUT, "fleurs", lang)
    if os.path.exists(os.path.join(d, "meta.json")):
        continue
    os.makedirs(d, exist_ok=True)
    rows = {}
    for line in get(f"{HF}/{cfg}/test.tsv").decode("utf-8").splitlines():
        f = line.split("\t")
        if len(f) >= 7 and f[5].isdigit() and 3 * R <= int(f[5]) <= 25 * R:
            rows[f[1]] = {"id": f[0], "text": f[2], "gender": f[6]}
    meta, seen_ids = [], set()
    with urllib.request.urlopen(f"{HF}/{cfg}/audio/test.tar.gz", timeout=600) as r:
        with tarfile.open(fileobj=r, mode="r|gz") as t:
            for m in t:
                b = os.path.basename(m.name)
                if not m.isfile() or b not in rows:
                    continue
                x = to16k(t.extractfile(m).read())
                name = f"{len(meta):03d}.wav"
                with wave.open(os.path.join(d, name), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(R); w.writeframes(x.tobytes())
                meta.append({"file": name, "src": b, **rows[b]})
                if len(meta) >= KEEP:
                    break
    json.dump(meta, open(os.path.join(d, "meta.json"), "w"), ensure_ascii=False)
    print("fleurs", lang, len(meta), flush=True)
print("DONE")
