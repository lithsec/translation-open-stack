# Four continuous English speeches from VoxPopuli (en test, CC0 1.0): the longest runs of consecutive segments of one
# session with 1,200-2,600 characters of raw text, no audio downloaded.
import collections, json, sys, fsspec, pyarrow.parquet as pq
url = "https://huggingface.co/datasets/facebook/voxpopuli/resolve/main/en/test-00000-of-00001.parquet"
pf = pq.ParquetFile(fsspec.open(url, block_size=2**20).open())
cols = [c for c in pf.schema_arrow.names if c != "audio"]
rows = []
for g in range(pf.metadata.num_row_groups):
    rows += pf.read_row_group(g, columns=cols).to_pylist()
grp = collections.defaultdict(list)
for i, r in enumerate(rows):
    pre, idx = r["audio_id"].rsplit("_", 1); grp[pre].append((int(idx), i))
cands = []
for pre, v in grp.items():
    v.sort(); run = [v[0]]; best = [v[0]]
    for a, b in zip(v, v[1:]):
        run = run + [b] if b[0] == a[0] + 1 else [b]
        if len(run) > len(best): best = run
    text = " ".join(rows[i]["raw_text"].strip() for _, i in best)
    if len(text) >= 800: cands.append((len(text), pre, text[:2600].rsplit(". ", 1)[0] + "." if len(text) > 2600 else text))
cands.sort(key=lambda c: -c[0])
pick = cands[:10]
json.dump([{"id": p, "text": t} for _, p, t in pick], open(sys.argv[1], "w"), indent=1)
print(len(cands), "candidates;", [(c[1], c[0]) for c in pick])
print(pick[0][2][:300])
