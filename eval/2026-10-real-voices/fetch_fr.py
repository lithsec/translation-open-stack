# Real French speech (FLEURS fr_fr, CC BY 4.0) for the Haitian Creole vs
# French language-ID test: the two sound alike, and Gemini Live and Chirp 3
# both took the Haitian Creole speakers for French. Same shape as
# fetch_audio.py's clips; the FLEURS ids already used where French has them,
# topped up at random. Doesn't touch the other languages' clips.
#
#   .venv/bin/python fetch_fr.py
import json, os, random, tarfile, urllib.request
import fetch_audio as fa

ids = json.load(open(os.path.join(fa.HERE, "sentences", "fleurs_ids.json")))
rows = fa.fleurs_rows("fr_fr")
chosen = [i for i in ids if i in rows]
pool = [i for i in rows if i not in chosen and 6 <= len(rows[i][0][1].split()) <= 25]
chosen += random.Random(17).sample(pool, fa.N - len(chosen)) if len(chosen) < fa.N else []
chosen = chosen[: fa.N]
want = {}
for k, i in enumerate(chosen):
    pref = "FEMALE" if k % 2 else "MALE"
    want[i] = next((r for r in rows[i] if r[2].upper() == pref), rows[i][0])
names = {r[0]: i for i, r in want.items()}
got = {}
with urllib.request.urlopen(f"{fa.HF}/fr_fr/audio/test.tar.gz", timeout=600) as resp:
    with tarfile.open(fileobj=resp, mode="r|gz") as tar:
        for m in tar:
            base = os.path.basename(m.name)
            if base in names and m.isfile():
                got[names[base]] = fa.to_pcm(tar.extractfile(m).read())
                if len(got) == len(names):
                    break
order = [i for i in chosen if i in got]
fa.write_clip("fr", [got[i] for i in order], [want[i][1] for i in order])
print(f"fr: {sum(1 for i in order if i in ids)} of the shared FLEURS ids", flush=True)
