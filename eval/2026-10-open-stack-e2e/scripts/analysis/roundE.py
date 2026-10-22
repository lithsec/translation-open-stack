# Round E: DeepSeek V4-Pro (ZDR) beside stack, sol, V4-Flash ctx, V4.1-Flash ctx on round D's directions.
#   python3 -I roundE.py build | table
import json, os, sys
B = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out", "B")
HARD = ["en-ja", "en-km", "en-lo", "en-ht", "km-en", "lo-en", "ht-en"]
ADD = {"v4pro_direct": "dsE_v4pro_direct", "v4pro_ctx": "dsE_v4pro_ctx", "v41flash_ctx": "ds_v41flash_ctx"}
if sys.argv[1] == "build":
    J = json.load(open(os.path.join(B, "jobs_ds.json")))
    R = {k: json.load(open(os.path.join(B, f + ".json")))["res"] for k, f in ADD.items()}
    out = []
    for j in J:
        k = j["id"][2:]
        s = {n: j["systems"][n] for n in ("stack", "sol", "ds_v4flash_ctx")}
        s.update({n: R[n][k]["out"] for n in ADD})
        out.append({**j, "id": "E:" + k, "systems": s})
    json.dump(out, open(os.path.join(B, "jobs_E.json"), "w"), ensure_ascii=False, indent=1)
    print(len(out), "jobs", list(out[0]["systems"]))
else:
    G = json.load(open(os.path.join(B, "grades_E.json")))
    sc = lambda rows: (round(100 * sum(r.get("score", 0) for r in rows) / (3 * len(rows)), 1), sum(1 for r in rows if r.get("critical")))
    systems = list(next(iter(G.values()))["grades"])
    res = {"per_direction": {k[7:]: {s: sc(v["grades"][s]) for s in systems} for k, v in G.items()}}
    for name, dirs in (("hard7", HARD), ("all", [k[7:] for k in G])):
        res[name] = {s: sc([r for k, v in G.items() if k[7:] in dirs for r in v["grades"][s]]) for s in systems}
    lat = {}
    for n in ("dsE_v4pro_direct", "dsE_v4pro_ctx"):
        r = json.load(open(os.path.join(B, n + ".json")))["res"]
        w = sorted(x for v in r.values() for x in v["wall_s"] if x)
        u = [x for v in r.values() for x in v["usage"] if x]
        lat[n] = {"p50": w[len(w) // 2], "p90": w[int(.9 * (len(w) - 1))], "reasoning_tokens": sum((x.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0 for x in u),
                  "providers": sorted({p for v in r.values() for p in v["providers"]})}
    res["latency"] = lat
    json.dump(res, open(os.path.join(B, "results_E.json"), "w"), indent=1)
    print(json.dumps({k: res[k] for k in ("hard7", "all", "latency")}, indent=0))
    for d, v in res["per_direction"].items(): print(d, v)
