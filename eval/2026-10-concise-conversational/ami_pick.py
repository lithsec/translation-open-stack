import json, sys, re
rows=[r for r in json.load(open(sys.argv[1])) if r["meeting_id"]=="EN2002a"]
rows.sort(key=lambda r:r["begin_time"])
def ok(r): return len(r["text"].split())>=4 and r["end_time"]-r["begin_time"]>=1.2
best=None
for i in range(len(rows)):
    t0=rows[i]["begin_time"]; sel=[]; last_end=-1; dur=0
    for r in rows[i:]:
        if r["begin_time"]>t0+600: break
        if not ok(r) or r["begin_time"]<last_end: continue
        sel.append(r); last_end=r["end_time"]; dur+=r["end_time"]-r["begin_time"]+0.7
        if dur>=150: break
    if dur<140: continue
    fill=sum(len(re.findall(r"\b(UM|UH|HMM|YOU KNOW|LIKE|I MEAN)\b", r["text"])) for r in sel)
    words=sum(len(r["text"].split()) for r in sel)
    span=sel[-1]["end_time"]-sel[0]["begin_time"]
    score=fill*3+words-span*0.5
    if best is None or score>best[0]: best=(score,i,sel,fill,words,span)
_,i,sel,fill,words,span=best
print(len(sel),"utts, fillers",fill,"words",words,"span",round(span),"s from",round(sel[0]["begin_time"]))
json.dump(sel, open(sys.argv[2],"w"), indent=1)
for r in sel[:6]: print(r["speaker_id"], round(r["begin_time"],1), r["text"][:90])
