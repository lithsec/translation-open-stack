# The 25 Khmer FLEURS test sentences of ../../2026-11-chirp3-lao-khmer (its runs/tr_km.json), with the same sentences'
# English (FLEURS shares sentence ids across languages) and, for the language-ID check, English recordings of them.
# FLEURS (CC BY 4.0). Streams the tarballs and stops when every file wanted is found.
#   python3 -I fetch.py DATA      (DATA holds tr_km.json; writes set.json, km/*.raw, en/*.raw: 16 kHz mono PCM16)
import csv, io, json, os, subprocess, sys, tarfile, urllib.request
D = sys.argv[1]
HF = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
def tsv(cfg):
    rows = []
    for r in csv.reader(io.StringIO(urllib.request.urlopen(f"{HF}/{cfg}/test.tsv", timeout=120).read().decode()), delimiter="\t", quoting=csv.QUOTE_NONE):
        if len(r) >= 7: rows.append({"id": r[0], "file": r[1], "raw": r[2], "samples": int(r[5]) if r[5].isdigit() else 0})
    return rows
tr = json.load(open(os.path.join(D, "tr_km.json")))
km, en = tsv("km_kh"), tsv("en_us")
by_file = {r["file"]: r for r in km}
en_by_id = {}
for r in en: en_by_id.setdefault(r["id"], []).append(r)
items = []
for t in tr:
    k = by_file[t["file"]]
    e = sorted(en_by_id.get(k["id"], []), key=lambda r: r["samples"])
    items.append({"id": k["id"], "km_file": t["file"], "km": k["raw"], "en": e[0]["raw"] if e else None, "en_file": e[0]["file"] if e else None})
print("items", len(items), "with English", sum(1 for i in items if i["en"]))
json.dump(items, open(os.path.join(D, "set.json"), "w"), ensure_ascii=False, indent=1)
def audio(cfg, want, sub):
    os.makedirs(os.path.join(D, sub), exist_ok=True)
    want = {w for w in want if w and not os.path.exists(os.path.join(D, sub, w.replace(".wav", ".raw")))}
    if not want: return
    with urllib.request.urlopen(f"{HF}/{cfg}/audio/test.tar.gz", timeout=900) as resp, tarfile.open(fileobj=resp, mode="r|gz") as tf:
        for m in tf:
            n = os.path.basename(m.name)
            if not m.isfile() or n not in want: continue
            raw = subprocess.run(["sox", "-t", "wav", "-", "-t", "raw", "-r", "16000", "-c", "1", "-b", "16", "-e", "signed-integer", "-"],
                                 input=tf.extractfile(m).read(), capture_output=True, check=True).stdout
            open(os.path.join(D, sub, n.replace(".wav", ".raw")), "wb").write(raw)
            want.discard(n)
            if not want: break
    print(cfg, "missing", len(want))
audio("km_kh", [i["km_file"] for i in items], "km")
audio("en_us", [i["en_file"] for i in items], "en")
