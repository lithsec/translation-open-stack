# Rebuild October's Lao clips (complete-thought-ht-km-lo) from their stored layout: FLEURS files, pauses, 1 s lead.
import csv, io, json, os, sys, tarfile, urllib.request
RV = "/Users/sstone/dev/translation-open-stack/eval/2026-10-real-voices"
sys.path.insert(0, RV)
import fetch_audio as fa  # noqa: E402
CL = "/Users/sstone/dev/tos-untracked-evals-2026-10-29/eval/2026-10-complete-thought-ht-km-lo/raw/clips"
OUT = "/tmp/rs/chirp/data/oct_lo"
RATE = 16000
lay = {p: json.load(open(f"{CL}/clips_{p}/lo.json")) for p in ("reg", "irr")}
files = lay["reg"]["files"]
assert files == lay["irr"]["files"]
rows = fa.fleurs_rows("lo_la")
text = {r[0]: r[1] for recs in rows.values() for r in recs}
pcm = {}
with urllib.request.urlopen(f"{fa.HF}/lo_la/audio/test.tar.gz", timeout=900) as resp:
    with tarfile.open(fileobj=resp, mode="r|gz") as tar:
        for m in tar:
            b = os.path.basename(m.name)
            if b in files and m.isfile():
                pcm[b] = fa.to_pcm(tar.extractfile(m).read())
                if len(pcm) == len(files): break
assert len(pcm) == len(files), len(pcm)
for p, L in lay.items():
    buf, t, worst = bytearray(b"\0\0" * RATE), 1.0, 0.0
    for i, f in enumerate(files):
        dur = len(pcm[f]) / 2 / RATE
        s = L["sentences"][i]
        worst = max(worst, abs(s["start"] - t), abs(s["end"] - (t + dur)))
        buf += pcm[f] + b"\0\0" * int(L["gaps"][i] * RATE)
        t += dur + L["gaps"][i]
    os.makedirs(f"{OUT}/{p}", exist_ok=True)
    open(f"{OUT}/{p}/lo.raw", "wb").write(bytes(buf))
    json.dump([text[f] for f in files], open(f"{OUT}/{p}/lo.txt.json", "w"), ensure_ascii=False)
    json.dump(L, open(f"{OUT}/{p}/lo.json", "w"))
    print(p, f"{t:.2f}s vs stored {L['seconds']}s; worst sentence-edge mismatch {worst * 1000:.0f} ms")
