# DeepSeek supplemental round (7 shootout real-voice directions) beside round B on the same directions.
import json, os
X = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(X, "out", "B")
GD = json.load(open(os.path.join(B, "grades_ds.json"))); GB = json.load(open(os.path.join(B, "grades.json")))


def sc(rows):
    return round(100 * sum(r.get("score", 0) for r in rows) / (3 * len(rows)), 1), sum(1 for r in rows if r.get("critical"))


res = {"round_D": {}, "round_B": {}}
for k, g in GD.items():
    d = k[2:]
    res["round_D"][d] = {s: sc(r) for s, r in g["grades"].items()}
    res["round_B"][d] = {s: sc(r) for s, r in GB["B:" + d]["grades"].items()}


def pool(G, prefix, dirs, s):
    rows = [r for d in dirs for r in G[prefix + d]["grades"][s]]
    return sc(rows)


dirs = [k[2:] for k in GD]
res["pooled_7"] = {"D:" + s: pool(GD, "D:", dirs, s) for s in ("stack", "sol", "ds_v4flash_direct", "ds_v4flash_ctx")}
res["pooled_7"].update({"B:" + s: pool(GB, "B:", dirs, s) for s in ("stack", "sol", "qwen_direct", "qwen_ctx", "qwen_repair", "hymt30")})
lat = {}
for f in ("ds_v4flash_direct", "ds_v4flash_ctx", "ds_v41flash_direct", "ds_v41flash_ctx", "ds_v4pro_direct"):
    r = json.load(open(os.path.join(B, f + ".json")))["res"]
    w = sorted(x for v in r.values() for x in v["wall_s"] if x)
    u = [x for v in r.values() for x in v["usage"] if x]
    lat[f] = {"api_p50_s": w[len(w) // 2], "api_p90_s": w[int(.9 * (len(w) - 1))], "n": len(w),
              "completion_tokens": sum(x.get("completion_tokens", 0) for x in u),
              "reasoning_tokens": sum((x.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0 for x in u),
              "reasoning_text_returned": sum(v["reasoning_returned"] for v in r.values()),
              "providers": sorted({p for v in r.values() for p in v["providers"]})}
res["deepseek_api"] = lat
json.dump(res, open(os.path.join(B, "results_deepseek.json"), "w"), indent=1)
print(json.dumps(res["pooled_7"], indent=0)); print(json.dumps(lat, indent=0))
for d in dirs:
    print(d, "D", res["round_D"][d], "\n   B", res["round_B"][d])
