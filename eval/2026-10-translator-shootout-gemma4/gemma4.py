# Addendum to ../2026-10-translator-shootout: Gemma 4 31B and Gemma 4 26B-A4B
# (OpenRouter) on the SAME Azure transcripts, beside six of that shootout's
# systems (their saved outputs), graded blind side by side in ONE new round.
# Grades move 5-10 points between rounds, so nothing here is compared with the
# original round's numbers.
#
#   python3 gemma4.py translate   # both Gemma 4 models over all 25 directions (cached in out/)
#   python3 gemma4.py grade       # one blind grading call per direction, all eight systems
#   python3 gemma4.py table       # results.json + the README tables
#
# Environment (nothing secret is printed):
#   OPENROUTER_API_KEY   OpenRouter: every request sets "provider": {"zdr": true} (zero data
#                        retention) and pins bf16; the provider that served each sentence is kept
#   GEMINI_API_KEY       the grader (Gemini 3.1 Pro preview, AI Studio), as the original shootout
#   SHOOTOUT_OUT         the original shootout's out/ (inputs.json and mt/<system>/...), which is
#                        not committed: run ../2026-10-translator-shootout first (default: its out/)
import concurrent.futures as cf
import json, os, statistics, sys, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-translator-shootout"))
import shootout as S  # noqa: E402  (its prompt, grader prompt, Gemini client and groups)

SRC_OUT = os.environ.get("SHOOTOUT_OUT", os.path.join(HERE, "..", "2026-10-translator-shootout", "out"))
OUT = os.path.join(HERE, "out")
MODELS = {  # name -> OpenRouter id; bf16, reasoning off, temperature 0 (as ../2026-10-ht-lo-translators)
    "gemma-4-31b-it@or": "google/gemma-4-31b-it",
    "gemma-4-26b-a4b-it@or": "google/gemma-4-26b-a4b-it",
}
REUSED = ["hymt2-7b-nf4", "madlad-7b-int8", "translategemma-12b", "azure-translator",
          "gemini-3.5-flash@medium", "foundry-gpt-5.6-sol@low"]
SYSTEMS = REUSED + list(MODELS)
SHORT = {**S.SHORT, "gemma-4-31b-it@or": "Gemma 4 31B", "gemma-4-26b-a4b-it@or": "Gemma 4 26B"}
GRADES = os.path.join(OUT, f"grades-{S.GRADER}.json")
SENTENCES_PER_HOUR = 392  # ../2026-10-translation-cost: an hour of continuous speech per listener language


def J(p):
    return json.load(open(p))


def openrouter(mid, s, src, tgt):
    body = {"model": mid, "messages": [{"role": "user", "content": S.prompt(s, src, tgt)}], "max_tokens": 2048,
            "temperature": 0, "reasoning": {"enabled": False}, "usage": {"include": True},
            "provider": {"zdr": True, "quantizations": ["bf16"], "allow_fallbacks": True}}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json",
                                  "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
    for attempt in range(8):
        t0 = time.time()
        try:
            j = json.load(urllib.request.urlopen(req, timeout=120))
        except urllib.error.HTTPError as e:
            if e.code not in (408, 429, 500, 502, 503, 504) or attempt == 7:
                raise
            time.sleep(4 * (attempt + 1))
            continue
        except (urllib.error.URLError, TimeoutError):
            time.sleep(4 * (attempt + 1))
            continue
        wall = round(time.time() - t0, 3)
        text = ((j.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        u = j.get("usage") or {}
        if text or attempt == 7:  # a blank is re-sent (rate limits blank some answers)
            return {"out": text, "wall_s": wall, "provider": j.get("provider"),
                    "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                    "cost": u.get("cost")}
        time.sleep(2)
    return {"out": "", "wall_s": None, "provider": None, "prompt_tokens": None, "completion_tokens": None, "cost": None}


def translate():
    D = J(os.path.join(SRC_OUT, "inputs.json"))
    for name, mid in MODELS.items():
        for d, v in D.items():
            src, tgt = d.split(":")[1].split("-")
            p = os.path.join(OUT, "mt", name, f"{d.replace(':', '_')}.json")
            if os.path.exists(p):
                continue
            os.makedirs(os.path.dirname(p), exist_ok=True)

            def run(x):
                if not x.strip():
                    return {"out": "", "wall_s": None, "provider": None, "prompt_tokens": None,
                            "completion_tokens": None, "cost": None}
                return openrouter(mid, x, src, tgt)
            with cf.ThreadPoolExecutor(6) as ex:
                res = list(ex.map(run, v["input"]))
            rec = {k: [r[k] for r in res] for k in res[0]}
            rec["quantization"] = "bf16"
            json.dump(rec, open(p, "w"), ensure_ascii=False, indent=1)
            blanks = sum(1 for x, o in zip(v["input"], rec["out"]) if x.strip() and not o)
            print(f"{name:24s} {d:12s} blanks={blanks}", flush=True)


def outputs(d):
    sys_ = {}
    for name in SYSTEMS:
        base = os.path.join(OUT, "mt") if name in MODELS else os.path.join(SRC_OUT, "mt")
        p = os.path.join(base, name, f"{d.replace(':', '_')}.json")
        if os.path.exists(p):
            sys_[name] = J(p)
    return sys_


def grade():
    D = J(os.path.join(SRC_OUT, "inputs.json"))
    if os.path.exists(GRADES):
        sys.exit(f"{GRADES} exists: one round only")
    S.outputs = outputs  # the original grader prompt and shuffle, over this round's eight systems
    with cf.ThreadPoolExecutor(5) as ex:
        G = dict(ex.map(lambda kv: S.grade_one(*kv), D.items()))
    json.dump(G, open(GRADES, "w"), ensure_ascii=False, indent=1)
    print("graded", len(G), "directions with", S.GRADER)


def pct(x):
    return f"{round(100 * x)}%"


def table():
    D = J(os.path.join(SRC_OUT, "inputs.json"))
    G = J(GRADES)
    R = {"grader": S.GRADER, "systems": SYSTEMS, "directions": {}, "groups": {}, "openrouter": {}}
    for d, v in D.items():
        n = len(v["source"])
        row = {}
        for name in outputs(d):
            g = {x["i"]: x for x in G[d][name]}
            row[name] = {"score": round(sum(g.get(i, {}).get("score", 0) for i in range(n)) / (3 * n), 3),
                         "critical": sum(1 for x in g.values() if x.get("critical"))}
        R["directions"][d] = {"sentences": n, "systems": row}
    for c in SYSTEMS:
        R["groups"][c] = {}
        for gname, ds in list(S.GROUPS.items()) + [("All 25 directions", list(D))]:
            xs = [R["directions"][d]["systems"].get(c) for d in ds]
            if all(xs):
                R["groups"][c][gname] = {"score": round(statistics.mean(x["score"] for x in xs), 3),
                                         "critical": sum(x["critical"] for x in xs)}
    for name, mid in MODELS.items():
        recs = [J(os.path.join(OUT, "mt", name, f"{d.replace(':', '_')}.json")) for d in D]
        flat = lambda k: [x for r in recs for x in r[k] if x is not None]
        wall = sorted(flat("wall_s"))
        provs = {}
        for p in flat("provider"):
            provs[p] = provs.get(p, 0) + 1
        sent = len(wall)
        cost = sum(flat("cost"))
        R["openrouter"][name] = {
            "model": mid, "quantization": "bf16", "zdr": True, "providers": provs, "sentences": sent,
            "blank_outputs": sum(1 for r, d in zip(recs, D) for x, o in zip(D[d]["input"], r["out"]) if x.strip() and not o),
            "round_trip_p50_s": round(statistics.median(wall), 2), "round_trip_p90_s": round(wall[int(0.9 * (sent - 1))], 2),
            "mean_prompt_tokens": round(statistics.mean(flat("prompt_tokens")), 1),
            "mean_completion_tokens": round(statistics.mean(flat("completion_tokens")), 1),
            "list_price_per_hour_usd": round(cost / sent * SENTENCES_PER_HOUR, 4) if sent else None,
        }
    json.dump(R, open(os.path.join(HERE, "results.json"), "w"), indent=1)

    cols = SYSTEMS
    print("| Direction | " + " | ".join(SHORT[c] for c in cols) + " |")
    print("|---|" + "---|" * len(cols))
    for d, x in R["directions"].items():
        best = max(s["score"] for s in x["systems"].values())
        cells = []
        for c in cols:
            s = x["systems"].get(c)
            cells.append("n/a" if not s else (f"**{pct(s['score'])} ({s['critical']})**" if s["score"] == best
                                              else f"{pct(s['score'])} ({s['critical']})"))
        print(f"| {d} | " + " | ".join(cells) + " |")
    print()
    print("| Group | " + " | ".join(SHORT[c] for c in cols) + " |")
    print("|---|" + "---|" * len(cols))
    for gname in list(S.GROUPS) + ["All 25 directions"]:
        cells = [(f"{pct(R['groups'][c][gname]['score'])} ({R['groups'][c][gname]['critical']})"
                  if gname in R["groups"][c] else "n/a") for c in cols]
        print(f"| {gname} | " + " | ".join(cells) + " |")
    print()
    for name, o in R["openrouter"].items():
        print(name, json.dumps(o))


if __name__ == "__main__":
    {"translate": translate, "grade": grade, "table": table}[sys.argv[1]]()
