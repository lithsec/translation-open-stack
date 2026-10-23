# Translations that failed during a live run (an HTTP 429 from every zero-retention
# provider, or a blank after re-sends) are made again afterwards, six at a time with
# back-off, so the grading compares the translators rather than their rate limits.
# A filled translation keeps "filled_offline": true and is left out of the latency
# figures; the live failure counts are reported as they happened.
#
#   (same environment as pipeline.py) python -I fill.py RUNS
import concurrent.futures as cf
import glob, json, os, sys, time

sys.argv = [sys.argv[0], "mai", "-", "-", "-", sys.argv[1]]
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "pipeline.py")).read().split("\ndef run(lang)")[0]
exec(src)   # prompt(), translate(): exactly what the live run used
RUNS = sys.argv[5]

for p in sorted(glob.glob(os.path.join(RUNS, "*_*_*.json"))):
    d = json.load(open(p))
    if "translations" not in d:
        continue
    fin = d["finals"]

    def redo(t):
        i = t["final"]
        ctx = [f["text"] for f in fin[max(0, i - 2):i]]
        r = {}
        for attempt in range(8):
            try:
                r = translate(t["translator"], fin[i]["text"], d["lang"], t["tgt"], ctx)
                if r["out"]:
                    break
            except Exception:
                pass
            time.sleep(5 * (attempt + 1))
        t.update({"out": r.get("out", ""), "filled_offline": True, "live_error": t.get("error", "blank"),
                  "provider": r.get("provider"), "prompt_tokens": r.get("prompt_tokens"),
                  "completion_tokens": r.get("completion_tokens"), "cost": r.get("cost")})

    todo = [t for t in d["translations"] if not t["out"]]
    with cf.ThreadPoolExecutor(6) as ex:
        list(ex.map(redo, todo))
    n = len(todo)
    json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
    print(os.path.basename(p), "filled", n, "still blank", sum(1 for t in d["translations"] if not t["out"]), flush=True)
