# Per level: how much later each turn's first audio arrives than with one room (every listener in every room), and the backlog when the
# clip ends; plus the server's dropped utterances and the GPU's peak memory, from run_levels.sh's side files.
#   python3 -I analyze.py RUNS_DIR CLIP_DIR      -> RUNS_DIR/summary.json (+ printed)
import glob, json, os, re, statistics, sys

RUNS, CLIP = sys.argv[1], sys.argv[2]
ends = [s["end"] for s in json.load(open(os.path.join(CLIP, "en.json")))["sentences"]]


def pct(v, q):
    v = sorted(v)
    return round(v[min(len(v) - 1, int(q * len(v)))], 2) if v else None


def turns(rec):
    """(text time, first audio after it) per turn, seconds from the clip's start."""
    return [(t, next((a for a in rec["audio"] if a >= t), None)) for t in rec["text"]]


def base_lat(tt):
    """Speech end -> first audio per turn with no load: from the last sentence end before the turn's text."""
    out = []
    for t, a in tt:
        e = max((x for x in ends if x < t), default=None)
        out.append(a - e if a is not None and e is not None else None)
    return out


# The 1-room runs are the baselines: the same audio cuts into the same turns at every load, so a turn's speech end
# -> first audio under load is its baseline value plus how much later its first audio arrived.
BASE = {}
for tag in ("r1", "w1"):
    p = os.path.join(RUNS, f"{tag}.json")
    if os.path.exists(p):
        BASE[tag[0]] = {lg: (turns(rec), base_lat(turns(rec))) for lg, rec in json.load(open(p))["runs"][0]["langs"].items()}

rows = []
for f in sorted(glob.glob(os.path.join(RUNS, "[rw]*.json")), key=lambda p: (os.path.basename(p)[0], len(p), p)):
    d = json.load(open(f))
    base = BASE.get(os.path.basename(f)[0], {})
    lat, drain, unmatched, conns = [], [], 0, 0
    for run in d["runs"]:
        for lg, rec in run["langs"].items():
            conns += 1
            if rec["audio"]:
                drain.append(rec["audio"][-1] - d["clip_s"])
            tt = turns(rec)
            if lg not in base or len(tt) != len(base[lg][0]):   # cut into different turns: backlog only
                unmatched += 1
                continue
            for (t, a), (t0, a0), l0 in zip(tt, base[lg][0], base[lg][1]):
                if a is not None and a0 is not None:
                    lat.append(a - a0)
    tag = os.path.basename(f)[:-5]
    side = {}
    for name in ("drops", "gpu"):
        p = os.path.join(RUNS, f"{tag}.{name}")
        side[name] = open(p).read() if os.path.exists(p) else ""
    gpu = [int(x) for x in re.findall(r"^(\d+)", side["gpu"], flags=re.M)]
    rows.append({"level": tag, "rooms": d["rooms"], "langs": d["langs"], "listeners": conns,
                 "added_delay_vs_one_room_s": {"p50": pct(lat, .5), "p90": pct(lat, .9), "max": pct(lat, 1)},
                 "sentences_timed": len(lat), "listeners_without_one_turn_per_sentence": unmatched,
                 "backlog_after_clip_end_s": {"p50": pct(drain, .5), "max": pct(drain, 1)},
                 "dropped_utterances": len(side["drops"].strip().splitlines()) if side["drops"].strip() else 0,
                 "gpu_mem_peak_mb": max(gpu) if gpu else None})
    r = rows[-1]
    print(f"{tag:>12}: {d['rooms']:>2} rooms x {len(d['langs'])} langs | added delay p50 "
          f"{r['added_delay_vs_one_room_s']['p50']} p90 {r['added_delay_vs_one_room_s']['p90']} max "
          f"{r['added_delay_vs_one_room_s']['max']} | backlog max {r['backlog_after_clip_end_s']['max']} s | "
          f"dropped {r['dropped_utterances']} | unmatched {unmatched}/{conns} | GPU peak {r['gpu_mem_peak_mb']} MB")
json.dump(rows, open(os.path.join(RUNS, "summary.json"), "w"), indent=1)
