import json,subprocess,os,sys
MT={"en":"en","es":"es","pt":"pt-BR","fr":"fr","de":"de","zh":"zh-Hans","vi":"vi","ar":"ar","uk":"uk","ko":"ko","ru":"ru","hi":"hi","it":"it"}
J=json.load(open(os.path.expanduser('~/dev/translation-open-stack/eval/2026-11-apple-on-device/results/jobs.json')))
out=[]
for job in J:
    p=f"in_{job['id'].replace(':','_')}.json"; q=p.replace('in_','out_')
    if not os.path.exists(q):
        json.dump({"src":MT[job['src']],"tgt":MT[job['tgt']],"lines":job['source']},open(p,'w'))
        r=subprocess.run(['./appletext',p,q],capture_output=True,text=True)
        if r.returncode: print(job['id'],r.stderr[-300:]); continue
    t=json.load(open(q))['out']
    out.append({**job,"systems":{"apple-text":t,"apple-whole":job['systems']['apple-whole'],"cloud-auto":job['systems']['cloud-auto']}})
    print(job['id'],'ok',flush=True)
json.dump(out,open('jobs_text.json','w'),ensure_ascii=False)
