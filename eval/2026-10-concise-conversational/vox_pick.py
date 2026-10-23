import json, sys, re, collections
rows=json.load(open(sys.argv[1]))
grp=collections.defaultdict(list)
for i,r in enumerate(rows):
    pre,idx=r["audio_id"].rsplit("_",1); grp[pre].append((int(idx),i))
cands=[]
for pre,v in grp.items():
    v.sort(); idxs=[x[0] for x in v]
    # longest consecutive run
    run=[v[0]]; best=[v[0]]
    for a,b in zip(v,v[1:]):
        run = run+[b] if b[0]==a[0]+1 else [b]
        if len(run)>len(best): best=run
    chars=sum(len(rows[i]["raw_text"]) for _,i in best)
    if 1700<=chars<=2600: cands.append((chars,pre,[i for _,i in best]))
cands.sort(key=lambda c:-c[0])
print(len(cands), [(c[0],c[1]) for c in cands[:5]])
chars,pre,ids=cands[0]
json.dump({"prefix":pre,"rows":ids}, open(sys.argv[2],"w"))
print(pre, len(ids), chars, rows[ids[0]]["raw_text"][:150])
