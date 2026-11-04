# Take N FLEURS test sentences (CC BY 4.0) per language: wav 16 kHz mono + transcript. Streams the tarball, stops early.
import csv, io, json, os, random, sys, tarfile, urllib.request, wave
OUT = sys.argv[1]; N = int(sys.argv[2])
HF = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
for cfg in ["en_us"]:
    rows = {}
    tsv = urllib.request.urlopen(f"{HF}/{cfg}/test.tsv", timeout=120).read().decode()
    for r in csv.reader(io.StringIO(tsv), delimiter="\t"):
        rows[r[1]] = {"id": r[0], "raw": r[2], "norm": r[3]}
    want = set(random.Random(2026).sample(sorted(rows), min(len(rows), N * 3)))
    got = []
    with urllib.request.urlopen(f"{HF}/{cfg}/audio/test.tar.gz", timeout=900) as resp:
        with tarfile.open(fileobj=resp, mode="r|gz") as tf:
            for m in tf:
                name = os.path.basename(m.name)
                if not m.isfile() or name not in want: continue
                data = tf.extractfile(m).read()
                p = os.path.join(OUT, cfg, name); os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "wb").write(data)
                got.append({"file": name, **rows[name]})
                if len(got) >= N: break
    print(cfg, len(got))
    json.dump(got, open(os.path.join(OUT, cfg, "set.json"), "w"), ensure_ascii=False, indent=1)
