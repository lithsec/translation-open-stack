import sys, json, fsspec, pyarrow.parquet as pq
lang=sys.argv[1]
url=f"https://huggingface.co/datasets/facebook/voxpopuli/resolve/main/{lang}/test-00000-of-00001.parquet"
f=fsspec.open(url, block_size=2**20).open()
pf=pq.ParquetFile(f)
md=pf.metadata; print(lang, "row groups", md.num_row_groups, "rows", md.num_rows, pf.schema_arrow.names)
cols=[c for c in pf.schema_arrow.names if c!="audio"]
rows=[]
for g in range(md.num_row_groups):
    t=pf.read_row_group(g, columns=cols).to_pylist()
    for r in t: r["_g"]=g
    rows+=t
json.dump(rows, open(sys.argv[2],"w"))
print(rows[0])
