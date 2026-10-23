import sys, json, os, fsspec, pyarrow.parquet as pq
lang, meta_p, sel_p, out = sys.argv[1:5]
rows=json.load(open(meta_p)); sel=json.load(open(sel_p))["rows"]
os.makedirs(out, exist_ok=True)
url=f"https://huggingface.co/datasets/facebook/voxpopuli/resolve/main/{lang}/test-00000-of-00001.parquet"
pf=pq.ParquetFile(fsspec.open(url, block_size=2**20).open())
sizes=[pf.metadata.row_group(g).num_rows for g in range(pf.metadata.num_row_groups)]
starts=[sum(sizes[:g]) for g in range(len(sizes))]
need=set(sel); got=0
for g in sorted({rows[i]["_g"] for i in sel}):
    base=starts[g]; mx=max(i for i in sel if rows[i]["_g"]==g)
    pos=base
    for b in pf.iter_batches(row_groups=[g], columns=["audio"], batch_size=32):
        for a in b.column(0).to_pylist():
            if pos in need:
                open(os.path.join(out, f"{sel.index(pos):03d}.bin"),"wb").write(a["bytes"]); got+=1
            pos+=1
        if pos>mx: break
print(lang, "got", got, "of", len(sel))
