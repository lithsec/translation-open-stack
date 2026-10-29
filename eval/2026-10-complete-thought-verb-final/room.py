# The room decider against per-language CT (b), per room of three listeners' languages (ja, ko, ur): calls and tokens
# per hour of speech, by model and kind, from the replays (sim/). Per-language: en->ja CT (b) Gemma decides, sol
# translates (production's translator into Japanese), en->ko and en->ur CT (b) on Gemma alone. Room: one Gemma decision
# stream, then a translation per target per thought (sol into ja, Gemma into ko and ur). Also each kind of call's
# time (p50 / p90, ms).
#   python3 -I room.py WORK > raw/room.json
import json, os, statistics, sys

WORK = sys.argv[1]
J = lambda p: json.load(open(p))
PER = {"ja": "ctb-gs-az", "ko": "ctb-az", "ur": "ctb-az"}


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))] if v else None


out = {}
for pattern in ("reg", "irr"):
    secs = J(os.path.join(os.path.dirname(WORK.rstrip("/")), "clips", f"clips_{pattern}", "en.json"))["seconds"]
    arms = {"per-language": [(t, PER[t]) for t in PER], "room": [(t, "room-az") for t in PER]}
    res = {}
    for arm, files in arms.items():
        tot, seen_dec = {}, False
        for t, name in files:
            sim = J(os.path.join(WORK, "sim", name, f"{pattern}_en-{t}.json"))
            for c in sim["calls"]:
                if c.get("kind") == "decide":
                    if seen_dec:
                        continue
                if not (c.get("wall_ms", 0) > 0 or c.get("prompt_tokens")):
                    continue
                k = f"{'sol' if c.get('mt') == 'sol' else 'gemma'}:{c.get('kind')}"
                x = tot.setdefault(k, {"calls": 0, "in": 0, "out": 0, "wall": []})
                x["calls"] += 1
                x["in"] += c.get("prompt_tokens") or 0
                x["out"] += c.get("completion_tokens") or 0
                x["wall"].append(c["wall_ms"])
            seen_dec = seen_dec or any(c.get("kind") == "decide" for c in sim["calls"])
        res[arm] = {k: {"calls_per_hour": round(v["calls"] * 3600 / secs), "in_tokens_per_hour": round(v["in"] * 3600 / secs),
                        "out_tokens_per_hour": round(v["out"] * 3600 / secs), "wall_p50": pct(v["wall"], .5),
                        "wall_p90": pct(v["wall"], .9)} for k, v in sorted(tot.items())}
        res[arm]["_total"] = {f: sum(v[f] for k, v in res[arm].items() if not k.startswith("_"))
                              for f in ("calls_per_hour", "in_tokens_per_hour", "out_tokens_per_hour")}
    out[pattern] = res
json.dump(out, sys.stdout, indent=1)
