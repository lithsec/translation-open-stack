# A FLEURS test subset for eval_client.py (its manifest format): the first N clips of km_kh and lo_la.
#   python3 prep_fleurs.py SETDIR N
import csv, io, json, os, sys, tarfile, urllib.request
out, n = sys.argv[1], int(sys.argv[2])
rows = {}
for lang, code in (("km", "km_kh"), ("lo", "lo_la")):
    base = f"https://huggingface.co/datasets/google/fleurs/resolve/main/data/{code}"
    tsv = urllib.request.urlopen(f"{base}/test.tsv").read().decode("utf-8")
    recs = [r for r in csv.reader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)][:n]
    want = {r[1]: r[2] for r in recs}
    os.makedirs(f"{out}/clips/{lang}", exist_ok=True)
    tf = tarfile.open(fileobj=urllib.request.urlopen(f"{base}/audio/test.tar.gz"), mode="r|gz")
    got = []
    for m in tf:
        name = os.path.basename(m.name)
        if name in want:
            with open(f"{out}/clips/{lang}/{name}", "wb") as f: f.write(tf.extractfile(m).read())
            got.append({"i": len(got), "clip": f"clips/{lang}/{name}", "ref": want[name]})
            if len(got) == len(want): break
    rows[lang] = got; print(lang, len(got))
json.dump({"rows": rows}, open(f"{out}/manifest.json", "w"), ensure_ascii=False)
