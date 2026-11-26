import json, os, re, sys, statistics
RUN = os.path.expanduser('~/dev/translation-open-stack/eval/2026-11-apple-on-device/run.py')
CL = os.path.expanduser('~/dev/apple-eval-work/clips')
def load(work):
    g = {"__file__": RUN}
    sys.argv = ['run.py', 'x', CL, work]
    src = open(RUN).read()
    exec(src.split('if MODE == "hear":')[0], g)
    exec(src[src.index('def hits'):src.index('if MODE == "show"')], g)
    exec(src[src.index('# ---- recognition scores'):src.index('if MODE == "peek"')], g)
    return g
P = load('/tmp/phone-work'); M = load(os.path.expanduser('~/dev/apple-eval-work'))
J = P['J']; clip = P['clip']
if sys.argv[0] and os.environ.get('STAGE') == 'cer':
    for l in ['en', 'es', 'fr', 'zh']:
        row = {}
        for st in 'ab':
            gold = " ".join(J(clip(st, l, "txt.json")))
            for who, w in [('phone', '/tmp/phone-work'), ('mac', os.path.expanduser('~/dev/apple-eval-work'))]:
                h = J(os.path.join(w, 'hear', st, f'{l}.json'))
                row.setdefault(who, []).append(P['cer'](gold, " ".join(e["text"] for e in h["events"] if e["kind"] == "final")))
            for k, v in P['cloud_heard'](st, l).items():
                vs = v if isinstance(v, list) else [v]
                row.setdefault(k, []).append(statistics.mean(P['cer'](gold, x) for x in vs))
        print(l, "  ".join(f"{k} {100*statistics.mean(v):.1f}%" for k, v in row.items()))
    sys.exit()
MT = {"en":"en","es":"es","pt":"pt-BR","fr":"fr","de":"de","zh":"zh-Hans"}
jobs = []
for st in 'ab':
    for d in ['en-es','es-en','en-fr','fr-en','en-zh','zh-en','en-de','de-en','en-pt','pt-en']:
        s, t = d.split('-')
        tid = f"apple_{st}_{d}.json"
        pt, mt = f"/tmp/phone-out/text/out_{tid}", f"/tmp/appletext/out_{tid}"
        if not os.path.exists(pt): continue
        sysm = {"phone-text": J(pt)["out"], "mac-text": J(mt)["out"], "cloud-auto": P['cloud_out'](st, d),
                "mac-heard": M['arms'](st, d)["whole"]["out"]}
        if os.path.exists(f"/tmp/phone-work/cut/{st}/{d}.json"):
            sysm["phone-heard"] = P['arms'](st, d)["whole"]["out"]
        jobs.append({"id": f"phone:{st}:{d}", "src": s, "tgt": t, "source": J(clip(st, s, "txt.json")),
                     "reference": J(clip(st, "en", "txt.json")), "systems": sysm})
json.dump(jobs, open('/tmp/phone-work/jobs.json', 'w'), ensure_ascii=False)
print(len(jobs), 'jobs;', sum('phone-heard' in j['systems'] for j in jobs), 'with phone hearing')
