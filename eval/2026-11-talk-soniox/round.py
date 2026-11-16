# One blind round: per direction and set, Soniox speech-to-speech's text (soniox_s2s.py) and the baseline route's
# translation (stt_azure.py + mt.py) side by side in one grading call (grade.py), against the FLEURS text: the
# source-language text as the source, the English text as the reference meaning.
#
#   python3 -I round.py jobs  CLIPS_ROOT OUT     -> OUT/jobs.json
#   GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py OUT/jobs.json OUT/grades.json
#   python3 -I round.py jobs2 CLIPS_ROOT OUT fr-en en-tl   -> OUT/jobs_r2.json (a second read where within ~3)
#   GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py OUT/jobs_r2.json OUT/grades_r2.json
#   python3 -I round.py table CLIPS_ROOT OUT     -> results.json, soniox-talk-rows.json (here)
import json, os, statistics, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mt import BASELINE  # noqa: E402

MODE, CLIPS, OUT = sys.argv[1:4]
SETS = ["a", "b"]
DIRS = list(BASELINE)
ROUND = "talk-soniox-2026-11"
GRADER = os.environ.get("GRADER", "gemini-flash-latest")
J = lambda p: json.load(open(p))
clip = lambda st, l, ext: J(os.path.join(CLIPS, f"clips_{st}", f"{l}.{ext}"))


def systems(st, d):
    return {"soniox": J(os.path.join(OUT, "soniox", st, f"{d}.json"))["sent"],
            "baseline": J(os.path.join(OUT, "mt", st, f"{d}.json"))["out"]}


if MODE == "jobs":
    jobs = []
    for st in SETS:
        for d in DIRS:
            s, t = d.split("-")
            jobs.append({"id": f"{st}:{d}", "src": s, "tgt": t, "source": clip(st, s, "txt.json"),
                         "reference": clip(st, "en", "txt.json"), "systems": systems(st, d)})
    json.dump(jobs, open(os.path.join(OUT, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs")
    sys.exit()

if MODE == "jobs2":   # the second read: the named directions' jobs again, ids "r2:<set>:<dir>"
    keep = set(sys.argv[4:])
    jobs = [dict(j, id="r2:" + j["id"]) for j in J(os.path.join(OUT, "jobs.json")) if j["id"].split(":")[1] in keep]
    json.dump(jobs, open(os.path.join(OUT, "jobs_r2.json"), "w"), ensure_ascii=False)
    print(len(jobs), "jobs")
    sys.exit()


def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c for c in s if c.isalnum())


def cer(ref, hyp):   # ../2026-10-real-voices/judge.py cer
    a, b = norm(ref), norm(hyp)
    if not a:
        return None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return round(prev[-1] / len(a), 4)


def pct(v, p):
    v = sorted(x for x in v if x is not None)
    return round(v[min(len(v) - 1, int(p * len(v)))]) if v else None


G = J(os.path.join(OUT, "grades.json"))
# The second read (grade.py on OUT/jobs_r2.json, ids "r2:<set>:<dir>"): only directions within ~3 points on the
# first; where it exists, a direction's quality is the mean of both reads.
R2P = os.path.join(OUT, "grades_r2.json")
R2 = J(R2P) if os.path.exists(R2P) else {}
q = lambda g: round(100 * sum(x.get("score", 0) for x in g) / (3 * max(1, len(g))), 1)
res = {"round": ROUND, "grader": GRADER, "n_per_set": 20, "directions": {}, "recognition_cer": {}, "latency_ms": {}}

# Recognition: characters wrong against the FLEURS text (whole clip). Azure: one run per language and set.
# Soniox: the original-language transcript of each stream (every direction from that language), mean.
for l in ["en"] + [d.split("-")[0] for d in DIRS if not d.startswith("en-")]:
    r = {}
    for st in SETS:
        gold = " ".join(clip(st, l, "txt.json"))
        az = J(os.path.join(OUT, "stt", st, f"{l}.json"))
        r.setdefault("azure", {})[st] = cer(gold, " ".join(f["text"] for f in az["finals"]))
        so = [J(os.path.join(OUT, "soniox", st, f"{d}.json"))["heard"] for d in DIRS if d.startswith(l + "-")]
        r.setdefault("soniox", {})[st] = round(statistics.mean(cer(gold, h) for h in so), 4)
    for k in ("azure", "soniox"):
        r[k]["mean"] = round(statistics.mean(r[k][st] for st in SETS), 4)
    res["recognition_cer"][l] = r

for d in DIRS:
    route, hear, tr = BASELINE[d]
    row = {"baseline_route": route, "baseline_recogniser": "azure" if hear == "azure" else "azure (stand-in for mai)",
           "baseline_translator": {"gemma": "gemma-4-31b (Bedrock)", "sol": "gpt-6-sol (Foundry, low)"}[tr]}
    for name in ["soniox", "baseline"]:
        per = {}
        for st in SETS:
            g = G[f"{st}:{d}"]["grades"][name]
            per[st] = {"q": q(g), "crit": sum(1 for x in g if x.get("critical")), "n": len(g),
                       "zeros": sum(1 for x in g if x.get("score", 0) == 0)}
        row[name] = {"q": round(statistics.mean(per[st]["q"] for st in SETS), 1),
                     "crit": sum(per[st]["crit"] for st in SETS), "n": sum(per[st]["n"] for st in SETS), "sets": per}
        if f"r2:a:{d}" in R2:
            per2 = {st: {"q": q(R2[f"r2:{st}:{d}"]["grades"][name]),
                         "crit": sum(1 for x in R2[f"r2:{st}:{d}"]["grades"][name] if x.get("critical"))} for st in SETS}
            q1 = statistics.mean(per[st]["q"] for st in SETS)
            q2 = statistics.mean(per2[st]["q"] for st in SETS)
            row[name]["read1_q"], row[name]["read2_q"] = round(q1, 1), round(q2, 1)
            row[name]["read2"] = per2
            row[name]["q"] = round((q1 + q2) / 2, 1)
    row["diff"] = round(row["soniox"]["q"] - row["baseline"]["q"], 1)
    row["server_picks_soniox"] = row["soniox"]["q"] >= 70 and row["soniox"]["q"] >= row["baseline"]["q"] - 3
    row["empty_sentences"] = {"soniox": sum(sum(1 for x in systems(st, d)["soniox"] if not x.strip()) for st in SETS),
                              "baseline": sum(sum(1 for x in systems(st, d)["baseline"] if not x.strip()) for st in SETS)}
    res["directions"][d] = row

    # Latency, ms after the sentence's speech ends (no voice in either):
    # Soniox: the arrival of the last translation token assigned to the sentence's block.
    # Baseline: the sentence's last Azure final arrives + the translation call's wall time.
    s, _ = d.split("-")
    lat_so, lat_bl = [], []
    for st in SETS:
        marks = clip(st, s, "json")["sentences"]
        so = J(os.path.join(OUT, "soniox", st, f"{d}.json"))["finals"]
        # the last translation token before the next sentence's first original token was final
        orig_sent = []
        for t in so:
            if t.get("translation_status") != "translation" and t.get("start_ms") is not None:
                mid = (t["start_ms"] + (t.get("end_ms") or t["start_ms"])) / 2000
                k = next((i for i, m in enumerate(marks) if i + 1 == len(marks) or mid < marks[i + 1]["start"] - 0.3), 0)
                orig_sent.append(k)
            else:
                orig_sent.append(None)
        last_tr, cur = {}, None
        for t, k in zip(so, orig_sent):
            if k is not None:
                cur = k
            elif t.get("translation_status") == "translation" and cur is not None:
                last_tr[cur] = t["arrived_ms"]
        lat_so += [last_tr[i] - marks[i]["end"] * 1000 for i in last_tr]
        fin = J(os.path.join(OUT, "stt", st, f"{s}.json"))["finals"]
        wall = J(os.path.join(OUT, "mt", st, f"{d}.json"))["wall_s"]
        for i, sm in enumerate(marks):
            hi = marks[i + 1]["start"] if i + 1 < len(marks) else 1e9
            fs = [f for f in fin if sm["start"] - 0.3 <= (f["offsetMs"] + f["durationMs"] / 2) / 1000 < hi]
            if fs and wall[i] is not None:
                lat_bl.append(max(f["arrivedMs"] for f in fs) - sm["end"] * 1000 + 1000 * wall[i])
    res["latency_ms"][d] = {"soniox_last_text_p50": pct(lat_so, .5), "soniox_last_text_p90": pct(lat_so, .9),
                            "baseline_last_text_p50": pct(lat_bl, .5), "baseline_last_text_p90": pct(lat_bl, .9)}

json.dump(res, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
rows = {"rounds": {ROUND: {"kind": "real", "grader": GRADER, "source": "translation-open-stack eval/2026-11-talk-soniox"}},
        "rows": [{"src": d.split("-")[0], "tgt": d.split("-")[1], "round": ROUND, "soniox": r["soniox"]["q"],
                  "baseline": {"route": r["baseline_route"], "quality": r["baseline"]["q"]}}
                 for d, r in res["directions"].items()]}
open(os.path.join(HERE, "soniox-talk-rows.json"), "w").write(
    '{"rounds": ' + json.dumps(rows["rounds"]) + ',\n "rows": [\n' + ",\n".join("  " + json.dumps(r) for r in rows["rows"]) + "\n]}\n")

for d, r in res["directions"].items():
    s = d.split("-")[0]
    print(f"{d}  soniox {r['soniox']['q']:5.1f} ({r['soniox']['sets']['a']['q']}/{r['soniox']['sets']['b']['q']}, crit {r['soniox']['crit']})"
          f"  baseline {r['baseline_route']}/{r['baseline_translator'][:5]} {r['baseline']['q']:5.1f} ({r['baseline']['sets']['a']['q']}/{r['baseline']['sets']['b']['q']}, crit {r['baseline']['crit']})"
          f"  diff {r['diff']:+5.1f}  pick={r['server_picks_soniox']}  empty {r['empty_sentences']}  {res['latency_ms'][d]}")
print(json.dumps(res["recognition_cer"]))
