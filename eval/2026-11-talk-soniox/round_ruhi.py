# The Russian and Hindi "which hearing" rerun (talk-hearing-ruhi-2026-11): ru→en and hi→en, gpt-6-sol (the baseline
# translator, mt.py) behind three recognisers, on sets a and b (the third round's outputs, results/) and four more
# sets c d e f (build_more.py), n = 120 per direction. Every set is graded again here, fresh and twice, blind side by
# side (grade.py, gemini-flash-latest), so the six sets are one round's grades.
#   soniox-hear  Soniox's own transcript (soniox_s2s.py streams, soniox_hear.py)
#   mai-hear     MAI-Transcribe-2-Streaming pinned to ru-RU / hi-IN (stt_azure.py RECOGNISER=mai)
#   azure-hear   Azure standard streaming (stt_azure.py)
#
#   python3 -I round_ruhi.py restore OUT              -> sets a and b's outputs into OUT from results/
#   python3 -I round_ruhi.py jobs    ROOT_RU ROOT_HI OUT  -> OUT/ruhi/jobs.json, jobs_r2.json (the same jobs, read 2)
#   GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py OUT/ruhi/jobs.json OUT/ruhi/grades.json   (and _r2)
#   python3 -I round_ruhi.py table   ROOT_RU ROOT_HI OUT  -> results.json "hearing_ruhi", results/ruhi/
# ROOT_<lang>/clips_<set>/ holds <lang>.json, <lang>.txt.json and en.txt.json (that language's English reference).
import json, os, random, statistics, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
ROUND = "talk-hearing-ruhi-2026-11"
GRADER = os.environ.get("GRADER", "gemini-flash-latest")
LANGS = ["ru", "hi"]
NEW, OLD = ["c", "d", "e", "f"], ["a", "b"]
SETS = OLD + NEW
ARMS = ["soniox-hear", "mai-hear", "azure-hear"]
J = lambda p: json.load(open(p))


def dump(p, x):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(x, open(p, "w"), ensure_ascii=False, indent=1)


MODE = sys.argv[1]
if MODE == "restore":
    OUT = sys.argv[2]
    mt, mai, sx = J(os.path.join(RES, "mt.json")), J(os.path.join(RES, "hearing", "mt_mai.json")), J(os.path.join(RES, "soniox_hear.json"))
    stt, stt_mai, son = J(os.path.join(RES, "stt_azure.json")), J(os.path.join(RES, "hearing", "stt_mai.json")), J(os.path.join(RES, "soniox.json"))
    for st in OLD:
        for l in LANGS:
            d = f"{l}-en"
            dump(os.path.join(OUT, "mt", st, f"{d}.json"), mt[f"{st}:{d}"])
            dump(os.path.join(OUT, "mt_mai", st, f"{d}.json"), mai[f"{st}:{d}"])
            v = sx[f"{st}:{d}"]
            dump(os.path.join(OUT, "soniox_hear", st, f"{d}.sent.json"), v["transcript"])
            dump(os.path.join(OUT, "mt_soniox_hear", st, f"{d}.json"), {x: v[x] for x in v if x != "transcript"})
            dump(os.path.join(OUT, "stt", st, f"{l}.json"), {"err": stt[f"{st}:{l}"]["err"], "finals": stt[f"{st}:{l}"]["finals"]})
            dump(os.path.join(OUT, "stt_mai", st, f"{l}.json"), {"err": stt_mai[f"{st}:{l}"]["err"], "finals": stt_mai[f"{st}:{l}"]["finals"]})
            dump(os.path.join(OUT, "soniox", st, f"{d}.json"), {"err": son[f"{st}:{d}"]["err"], "heard": son[f"{st}:{d}"]["heard"]})
    print("restored sets a and b")
    sys.exit()

ROOT = {"ru": sys.argv[2], "hi": sys.argv[3]}
OUT = sys.argv[4]
H = os.path.join(OUT, "ruhi")


def clip(st, l, name):   # sets a and b: results/clips_<set>/ (all languages' English reference is en.txt.json)
    if st in OLD:
        return J(os.path.join(RES, f"clips_{st}", name.replace("REF", "en.txt.json").replace("SRC", f"{l}.txt.json")))
    return J(os.path.join(ROOT[l], f"clips_{st}", name.replace("REF", "en.txt.json").replace("SRC", f"{l}.txt.json")))


def systems(st, d):
    return {"soniox-hear": J(os.path.join(OUT, "mt_soniox_hear", st, f"{d}.json"))["out"],
            "mai-hear": J(os.path.join(OUT, "mt_mai", st, f"{d}.json"))["out"],
            "azure-hear": J(os.path.join(OUT, "mt", st, f"{d}.json"))["out"]}


if MODE == "jobs":
    jobs = []
    for st in SETS:
        for l in LANGS:
            d = f"{l}-en"
            sy = systems(st, d)
            assert all(len(v) == 20 for v in sy.values()), (st, d)
            jobs.append({"id": f"ruhi:{st}:{d}", "src": l, "tgt": "en", "source": clip(st, l, "SRC"),
                         "reference": clip(st, l, "REF"), "systems": sy})
    dump(os.path.join(H, "jobs.json"), jobs)
    dump(os.path.join(H, "jobs_r2.json"), [dict(j, id="r2:" + j["id"]) for j in jobs])
    print(len(jobs), "jobs (and the same again for read 2)")
    sys.exit()


def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c for c in s if c.isalnum())


def cer(ref, hyp):   # round_hearing.py cer
    a, b = norm(ref), norm(hyp)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return round(prev[-1] / len(a), 4)


G1, G2 = J(os.path.join(H, "grades.json")), J(os.path.join(H, "grades_r2.json"))
q = lambda xs: round(100 * sum(xs) / (3 * len(xs)), 1)
out = {"round": ROUND, "grader": GRADER, "sets": SETS, "n_per_set": 20, "reads": 2, "directions": {}, "recognition_cer": {}}
rng = random.Random(7)
B = 10000
for l in LANGS:
    d = f"{l}-en"
    per = {a: [] for a in ARMS}          # per-sentence score, mean of both reads
    crit = {a: 0 for a in ARMS}          # critical flags, read 1
    reads = {a: {"read1": [], "read2": []} for a in ARMS}
    sets = {a: {} for a in ARMS}
    for st in SETS:
        g1, g2 = G1[f"ruhi:{st}:{d}"]["grades"], G2[f"r2:ruhi:{st}:{d}"]["grades"]
        for a in ARMS:
            s1 = {x["i"]: x.get("score", 0) for x in g1[a]}
            s2 = {x["i"]: x.get("score", 0) for x in g2[a]}
            r1, r2 = [s1.get(i, 0) for i in range(20)], [s2.get(i, 0) for i in range(20)]
            reads[a]["read1"] += r1
            reads[a]["read2"] += r2
            per[a] += [(x + y) / 2 for x, y in zip(r1, r2)]
            crit[a] += sum(1 for x in g1[a] if x.get("critical"))
            sets[a][st] = q([(x + y) / 2 for x, y in zip(r1, r2)])
    n = len(per["mai-hear"])
    row = {"translator": "sol", "n": n}
    for a in ARMS:
        row[a] = {"q": q(per[a]), "read1_q": q(reads[a]["read1"]), "read2_q": q(reads[a]["read2"]), "crit": crit[a],
                  "sets": sets[a], "q_ab": q([x for k, x in enumerate(per[a]) if k < 40]), "q_cdef": q([x for k, x in enumerate(per[a]) if k >= 40])}

    def boot(x, y):
        diffs = [xi - yi for xi, yi in zip(x, y)]
        bs = sorted(100 * statistics.mean(rng.choices(diffs, k=len(diffs))) / 3 for _ in range(B))
        return {"diff": round(100 * statistics.mean(diffs) / 3, 1), "lo": round(bs[int(0.025 * B)], 1), "hi": round(bs[int(0.975 * B)], 1)}

    row["mai_minus_azure"] = boot(per["mai-hear"], per["azure-hear"])
    row["soniox_minus_mai"] = boot(per["soniox-hear"], per["mai-hear"])
    row["soniox_minus_azure"] = boot(per["soniox-hear"], per["azure-hear"])
    out["directions"][d] = row
    # Recognition: characters wrong against the FLEURS text of each whole clip, pooled over the six sets (mean of sets).
    c = {}
    for st in SETS:
        gold = " ".join(clip(st, l, "SRC"))
        c.setdefault("azure", {})[st] = cer(gold, " ".join(f["text"] for f in J(os.path.join(OUT, "stt", st, f"{l}.json"))["finals"]))
        c.setdefault("mai", {})[st] = cer(gold, " ".join(f["text"] for f in J(os.path.join(OUT, "stt_mai", st, f"{l}.json"))["finals"]))
        c.setdefault("soniox", {})[st] = cer(gold, J(os.path.join(OUT, "soniox", st, f"{d}.json"))["heard"])
    for k in c:
        c[k]["mean"] = round(statistics.mean(c[k][st] for st in SETS), 4)
    out["recognition_cer"][l] = c

res = J(os.path.join(HERE, "results.json"))
res["hearing_ruhi"] = out
json.dump(res, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
R = os.path.join(RES, "ruhi")
for name in ["jobs.json", "jobs_r2.json", "grades.json", "grades_r2.json"]:
    dump(os.path.join(R, name), J(os.path.join(H, name)))
new = {}
for st in NEW:
    for l in LANGS:
        d = f"{l}-en"
        new[f"{st}:{l}"] = {"azure": J(os.path.join(OUT, "stt", st, f"{l}.json")), "mai": J(os.path.join(OUT, "stt_mai", st, f"{l}.json")),
                            "soniox": J(os.path.join(OUT, "soniox", st, f"{d}.json")),
                            "mt": {a: J(os.path.join(OUT, p, st, f"{d}.json")) for a, p in [("azure-hear", "mt"), ("mai-hear", "mt_mai"), ("soniox-hear", "mt_soniox_hear")]},
                            "soniox_transcript": J(os.path.join(OUT, "soniox_hear", st, f"{d}.sent.json"))}
dump(os.path.join(R, "outputs_cdef.json"), new)
for d, r in out["directions"].items():
    print(d, " | ".join(f"{a} {r[a]['q']} [{r[a]['read1_q']},{r[a]['read2_q']}] c{r[a]['crit']} ab {r[a]['q_ab']} cdef {r[a]['q_cdef']}" for a in ARMS))
    for k in ["mai_minus_azure", "soniox_minus_mai", "soniox_minus_azure"]:
        print("  ", k, r[k])
print(json.dumps({l: {k: v["mean"] for k, v in c.items()} for l, c in out["recognition_cer"].items()}))
