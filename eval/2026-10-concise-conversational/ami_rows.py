import json, sys, urllib.request, concurrent.futures as cf
def page(off):
    u=f"https://datasets-server.huggingface.co/rows?dataset=edinburghcstr/ami&config=ihm&split=test&offset={off}&length=100"
    for k in range(4):
        try: return json.load(urllib.request.urlopen(u, timeout=60))["rows"]
        except Exception as e: err=e
    return []
rows=[]
with cf.ThreadPoolExecutor(8) as ex:
    for rs in ex.map(page, range(0, 2400, 100)):
        for r in rs:
            x=r["row"]; rows.append({k:x[k] for k in ("meeting_id","audio_id","text","begin_time","end_time","speaker_id")} | {"src":x["audio"][0]["src"]})
json.dump(rows, open(sys.argv[1],"w"))
from collections import Counter; print(len(rows), Counter(r["meeting_id"] for r in rows))
