# Each run's finals, cut into the read sentences by text (align.py sentences: not by audio offset, which misplaces
# MAI's text), translated en→es and en→fr by Gemma 4 31B on Bedrock with the shootout prompt: ../2026-11-talk-soniox/mt.py
# gemma() (production's host and model, temperature 0; Talk's auto engine translates English into Spanish and French
# with Gemma). At most 3 calls at a time.
#   AWS_PROFILE=lithos-evals python3 -I mt_styles.py <out root> mt <styles root>-> <out root>/mt/<recogniser>/<clip>-<tgt>.json
#   python3 -I mt_styles.py <out root> jobs <styles root>             -> <out root>/jobs.json for ../2026-11-talk-soniox/grade.py
import concurrent.futures as cf, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1]
sys.argv = sys.argv[:1] + [OUT] + sys.argv[2:]
sys.path.insert(0, os.path.join(HERE, "..", "2026-11-talk-soniox"))
import mt  # noqa: E402  (gemma)
sys.path.insert(0, HERE)
import align  # noqa: E402

TGTS = ["es", "fr"]
# The arms: azure and mai (Talk's settings), azure-default (the SDK's segmentation, the control), where run.
RECS = [r for r in ["azure", "mai", "azure-default"] if os.path.isdir(os.path.join(OUT, r))]
J = lambda p: json.load(open(p))

if len(sys.argv) > 2 and sys.argv[2] == "jobs":
    STY = sys.argv[3]
    jobs = []
    for f in sorted(os.listdir(os.path.join(OUT, "azure"))):
        clip = f.removesuffix(".json")
        for t in TGTS:
            ref = J(os.path.join(STY, f"clips_{clip}", "en.txt.json"))
            jobs.append({"id": f"encont:{clip}:en-{t}", "src": "en", "tgt": t, "source": ref, "reference": ref,
                         "systems": {f"{r}-hear": J(os.path.join(OUT, "mt", r, f"{clip}-{t}.json"))["out"] for r in RECS}})
    json.dump(jobs, open(os.path.join(OUT, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs")
    sys.exit()

STY = sys.argv[3]
pool = cf.ThreadPoolExecutor(3)


def one(rec, f, t):
    p = os.path.join(OUT, "mt", rec, f"{f.removesuffix('.json')}-{t}.json")
    if os.path.exists(p):
        return
    x = J(os.path.join(OUT, rec, f))
    sents = align.sentences(x["finals"], J(os.path.join(STY, f"clips_{f.removesuffix('.json')}", "en.txt.json")))
    futs = [pool.submit(mt.gemma, s, "en", t) if s.strip() else None for s in sents]
    res = [x.result() if x else {"out": ""} for x in futs]
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump({"translator": "gemma", "out": [r["out"] for r in res]}, open(p, "w"), ensure_ascii=False, indent=1)
    print(rec, f, t, "blanks", sum(1 for s, r in zip(sents, res) if s.strip() and not r["out"]), flush=True)


with cf.ThreadPoolExecutor(6) as ex:
    list(ex.map(lambda a: one(*a), [(r, f, t) for r in RECS for f in sorted(os.listdir(os.path.join(OUT, r))) for t in TGTS]))
