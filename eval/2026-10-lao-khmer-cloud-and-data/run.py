# Lao and Khmer into English on the cloud route, from the stack's own 7B recognition (full-stack run).
# Each utterance the stack heard is translated as heard, with the previous two utterances as context,
# then mapped to the read sentences exactly as the stack's live output was (sentences.json rows).
#   SET_A=<unseen clip set> SET_B=<set b> FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=... OPENROUTER_API_KEY=... \
#     python3 -I run.py <work dir holding full/ (the full-stack run)> map|translate|jobs|table
# Grading: ../2026-10-unseen/grade.py (the full-stack round's grader, gemini-pro-latest): python3 -I grade.py jobs.json grades.json
import concurrent.futures as cf, json, os, sys, time, urllib.error, urllib.request
P, MODE = sys.argv[1], sys.argv[2]
F = os.path.join(P, "full"); OUT = os.path.join(P, "lkcloud"); os.makedirs(OUT, exist_ok=True)
SETS = {"a": os.environ.get("SET_A", os.path.join(P, "unseen")), "b": os.environ.get("SET_B", os.path.join(F, "setb"))}  # the clip sets of ../2026-10-full-stack
RUNS = {"lo": ("L", "milmmt"), "km": ("A", "hymt")}
NAMES = {"lo": "Lao", "km": "Khmer", "en": "English"}

def utts(events):
    us = []
    for e in events:
        if e["kind"] == "input": us.append({"t": e["t"], "heard": e["text"], "out": ""})
        elif e["kind"] == "text" and us: us[-1]["out"] += e["text"]
    return us

def mapping(us, rows):
    res, j = [], 0
    for r in rows:
        n, want = r["n_utt"], r["heard"]
        if n == 0: res.append([]); continue
        found = None
        for start in range(max(0, j - 2), len(us) - n + 1):
            if " ".join(u["heard"] for u in us[start:start + n]) == want: found = start; break
        if found is None: raise SystemExit(f"no map for row {r['i']}")
        res.append(list(range(found, found + n))); j = found + n - 1
    return res

def load(st, src):
    run, sysn = RUNS[src]
    e = os.path.join(F, f"e2e_{run}_{st}", "out")
    ev = json.load(open(os.path.join(e, "runs", f"{src}-en.json")))["events"]
    s = json.load(open(os.path.join(e, "sentences.json")))[f"{src}-en"]
    us = utts(ev)
    return us, s, mapping(us, s["rows"]), sysn

def prompt(x, src, ctx):
    c = f"Previous sentences, for context only (do not translate them): {' '.join(ctx)}\n" if ctx else ""
    return (f"Translate this {NAMES[src]} sentence, transcribed from live speech (it may contain recognition errors), "
            f"into natural English. Keep numbers, names and negation exact. Output only the English.\n{c}Sentence: {x}")

def post(url, body, headers, tries=6):
    data = json.dumps(body).encode()
    for a in range(tries):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url, data, {"Content-Type": "application/json", **headers}), timeout=90))
        except urllib.error.HTTPError as e:
            if e.code not in (408, 429, 500, 502, 503, 504) or a == tries - 1: raise
        except (urllib.error.URLError, TimeoutError):
            if a == tries - 1: raise
        time.sleep(2 * (a + 1))

HOSTS = ["deepinfra", "crusoe", "parasail", "coreweave", "sambanova"]
def tr(name, x, src, ctx):
    p = prompt(x, src, ctx); t0 = time.time()
    if name == "sol@low":
        j = post(os.environ["FOUNDRY_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions",
                 {"model": os.environ["FOUNDRY_DEPLOYMENT"], "messages": [{"role": "user", "content": p}], "reasoning_effort": "low"},
                 {"api-key": os.environ["FOUNDRY_KEY"]})
        return {"out": (j["choices"][0]["message"].get("content") or "").strip(), "provider": "foundry", "ms": round(1000 * (time.time() - t0))}
    body = {"model": "google/gemma-4-31b-it", "messages": [{"role": "user", "content": p}], "max_tokens": 1024, "temperature": 0,
            "reasoning": {"enabled": False}, "provider": {"zdr": True, "data_collection": "deny", "only": HOSTS, "allow_fallbacks": False}}
    for _ in range(3):
        j = post("https://openrouter.ai/api/v1/chat/completions", body, {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
        o = ((j.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if o: break
    return {"out": o, "provider": j.get("provider"), "ms": round(1000 * (time.time() - t0))}

TRS = ["sol@low", "gemma-4-31b@or"]
if MODE == "translate":
    path = os.path.join(OUT, "translations.json")
    T = json.load(open(path)) if os.path.exists(path) else {}
    jobs = []
    for st in SETS:
        for src in RUNS:
            us, _, _, _ = load(st, src)
            for name in TRS:
                k = f"{st}:{src}:{name}"
                have = T.get(k, [None] * len(us))
                for i, u in enumerate(us):
                    if not have[i]:
                        jobs.append((k, i, name, u["heard"], src, [v["heard"] for v in us[max(0, i - 2):i]]))
                T[k] = have
    with cf.ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(tr, n, x, s, c): (k, i) for k, i, n, x, s, c in jobs}
        for f in cf.as_completed(futs):
            k, i = futs[f]; T[k][i] = f.result()
    json.dump(T, open(path, "w"), ensure_ascii=False, indent=1)
    print("translated", len(jobs), "blank", sum(1 for v in T.values() for x in v if not x or not x["out"]))
elif MODE == "jobs":
    T = json.load(open(os.path.join(OUT, "translations.json")))
    jobs = []
    for st, d in SETS.items():
        CL = os.path.join(d, "clips_reg")
        en = json.load(open(os.path.join(CL, "en.txt.json")))
        for src in RUNS:
            us, s, mp, sysn = load(st, src)
            sy = {sysn + " (stack)": s["live_out"]}
            for name in TRS:
                tv = T[f"{st}:{src}:{name}"]
                sy[name] = [" ".join(tv[j]["out"] for j in m).strip() for m in mp]
            jobs.append({"id": f"WRITTEN:{st}:{src}-en", "src": src, "tgt": "en", "source": json.load(open(os.path.join(CL, f"{src}.txt.json"))),
                         "reference": en, "systems": sy})
    json.dump(jobs, open(os.path.join(OUT, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs")
elif MODE == "table":
    G = json.load(open(os.path.join(OUT, "grades.json")))
    T = json.load(open(os.path.join(OUT, "translations.json")))
    def flagged(st, l):
        p = os.path.join(SETS[st], "out", "witness", f"{l}.json")
        return {r["i"] for r in (json.load(open(p)) if os.path.exists(p) else []) if r.get("cut_off") or r.get("meaning_differs")}
    q = lambda g: {"q": round(100 * sum(x.get("score", 0) for x in g) / (3 * max(1, len(g))), 1), "crit": sum(1 for x in g if x.get("critical")), "n": len(g)}
    res = {}
    for k, v in G.items():
        _, st, d = k.split(":"); src = d.split("-")[0]; bad = flagged(st, src)
        for sysn, g in v["grades"].items():
            res.setdefault(d, {}).setdefault(sysn, {})[st] = {"written": q(g), "said": q([x for x in g if x["i"] not in bad])}
    lat = {}
    for k, v in T.items():
        st, src, name = k.split(":")
        ms = sorted(x["ms"] for x in v if x); lat.setdefault(f"{src}-en", {})[name] = {"p50_ms": ms[len(ms) // 2], "p90_ms": ms[int(0.9 * (len(ms) - 1))],
                                                                                    "providers": sorted({str(x["provider"]) for x in v if x})}
    for d, ss in res.items():
        for sysn, r in ss.items():
            r["mean"] = {m: round(sum(r[st][m]["q"] for st in SETS) / 2, 1) for m in ("written", "said")}
            r["crit"] = sum(r[st]["said"]["crit"] for st in SETS)
            if sysn in lat.get(d, {}): r["latency"] = lat[d][sysn]
    json.dump(res, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    for d, ss in sorted(res.items()):
        for sysn, r in sorted(ss.items()):
            print(d, sysn, r["mean"], "crit", r["crit"], {st: (r[st]["written"]["q"], r[st]["said"]["q"]) for st in SETS}, r.get("latency", {}))
else:
    for st in SETS:
        for src in RUNS:
            us, s, mp, _ = load(st, src); print(st, src, len(us), "utts mapped", sum(len(m) for m in mp))
