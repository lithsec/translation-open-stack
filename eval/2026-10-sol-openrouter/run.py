# sol via OpenRouter (zero retention) vs our Foundry sol, plus gpt-6-sol and gpt-6.1-sol.
# Each segment is translated with the previous two as context, as the apps do.
#   python3 -I run.py <scratchpad> translate|jobs|table
import concurrent.futures as cf, json, os, sys, time, urllib.error, urllib.request
P, MODE = sys.argv[1], sys.argv[2]
F = os.path.join(P, "full"); OUT = os.path.join(P, "solor"); os.makedirs(OUT, exist_ok=True)
SETS = {"a": os.path.join(P, "heldout"), "b": os.path.join(F, "setb")}
NAMES = {"lo": "Lao", "km": "Khmer", "ht": "Haitian Creole", "en": "English", "es": "Spanish"}
RUNS = {"lo": "L", "km": "A", "ht": "A"}            # full-stack runs whose recognition we reuse (7B for lo/km, base card for ht)
SYS = ["foundry-gpt-5.6-sol@low", "or-gpt-5.6-sol@low", "or-gpt-6.1-sol@low", "or-gpt-6-sol@low"]
OR_MODEL = {"or-gpt-5.6-sol@low": "openai/gpt-5.6-sol", "or-gpt-6.1-sol@low": "openai/gpt-6.1-sol", "or-gpt-6-sol@low": "openai/gpt-6-sol"}
J = lambda p: json.load(open(p))

def utts(events):
    us = []
    for e in events:
        if e["kind"] == "input": us.append({"heard": e["text"]})
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

def streams():
    """[(key, src, tgt, segments, sentence_map or None)]"""
    out = []
    for st in SETS:
        for src, run in RUNS.items():
            e = os.path.join(F, f"e2e_{run}_{st}", "out")
            us = utts(J(os.path.join(e, "runs", f"{src}-en.json"))["events"])
            rows = J(os.path.join(e, "sentences.json"))[f"{src}-en"]["rows"]
            out.append((f"{st}:{src}-en", src, "en", [u["heard"] for u in us], mapping(us, rows)))
    en = J(os.path.join(P, "espt", "out", "stt", "en.sent.json"))       # Azure's per-sentence English, unseen set a
    for t in ("ht", "km", "lo", "es"):
        out.append((f"a:en-{t}", "en", t, en, None))
    out.append(("a:es-en", "es", "en", J(os.path.join(P, "espt", "out", "stt", "es.sent.json")), None))
    return out

def prompt(x, src, tgt, ctx):
    c = f"Previous sentences, for context only (do not translate them): {' '.join(ctx)}\n" if ctx else ""
    return (f"Translate this {NAMES[src]} sentence, transcribed from live speech (it may contain recognition errors), "
            f"into natural {NAMES[tgt]}. Keep numbers, names and negation exact. Output only the {NAMES[tgt]}.\n{c}Sentence: {x}")

def post(url, body, headers, tries=5):
    data = json.dumps(body).encode()
    for a in range(tries):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url, data, {"Content-Type": "application/json", **headers}), timeout=120))
        except urllib.error.HTTPError as e:
            if e.code not in (408, 429, 500, 502, 503, 504) or a == tries - 1: return {"error": f"HTTP {e.code}"}
        except (urllib.error.URLError, TimeoutError) as e:
            if a == tries - 1: return {"error": type(e).__name__}
        time.sleep(2 * (a + 1))

def tr(name, x, src, tgt, ctx):
    p = prompt(x, src, tgt, ctx); t0 = time.time()
    if name.startswith("foundry"):
        j = post(os.environ["FOUNDRY_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions",
                 {"model": os.environ["FOUNDRY_DEPLOYMENT"], "messages": [{"role": "user", "content": p}], "reasoning_effort": "low"},
                 {"api-key": os.environ["FOUNDRY_KEY"]})
        prov = "foundry"
    else:
        j = post("https://openrouter.ai/api/v1/chat/completions",
                 {"model": OR_MODEL[name], "messages": [{"role": "user", "content": p}], "reasoning": {"effort": "low"},
                  "provider": {"zdr": True, "data_collection": "deny"}, "usage": {"include": True}},
                 {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
        prov = j.get("provider")
    o = ((j.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip() if "error" not in j else ""
    u = j.get("usage") or {}
    return {"out": o, "provider": prov, "ms": round(1000 * (time.time() - t0)), "error": j.get("error"),
            "in": u.get("prompt_tokens", 0), "outtok": u.get("completion_tokens", 0), "cost_or": u.get("cost")}

if MODE == "translate":
    path = os.path.join(OUT, "translations.json")
    T = J(path) if os.path.exists(path) else {}
    jobs = []
    for k, s, t, segs, _ in streams():
        for name in SYS:
            kk = f"{k}:{name}"; have = T.get(kk, [None] * len(segs))
            for i, x in enumerate(segs):
                if not have[i] or (not have[i]["out"] and have[i].get("error")):
                    jobs.append((kk, i, name, x, s, t, segs[max(0, i - 2):i]))
            T[kk] = have
    with cf.ThreadPoolExecutor(10) as ex:
        futs = {ex.submit(tr, n, x, s, t, c): (k, i) for k, i, n, x, s, t, c in jobs}
        for f in cf.as_completed(futs):
            k, i = futs[f]; T[k][i] = f.result()
    json.dump(T, open(path, "w"), ensure_ascii=False, indent=1)
    print("translated", len(jobs), "blank", sum(1 for v in T.values() for x in v if not x or not x["out"]))
elif MODE == "jobs":
    T = J(os.path.join(OUT, "translations.json")); jobs = []
    for k, s, t, segs, mp in streams():
        st = k.split(":")[0]; CL = os.path.join(SETS[st], "clips_reg")
        sy = {}
        mp = mp or [[i] for i in range(len(segs))]
        # Only sentences every system finished: the OpenRouter account ran out of credit mid-run (HTTP 402).
        keep = [i for i, m in enumerate(mp) if m and all(T[f"{k}:{n}"][j] and T[f"{k}:{n}"][j]["out"] for n in SYS for j in m)]
        for name in SYS:
            tv = T[f"{k}:{name}"]
            sy[name] = [" ".join(tv[j]["out"] for j in mp[i]).strip() for i in keep]
        en = J(os.path.join(CL, "en.txt.json"))
        sub = lambda xs: [xs[i] for i in keep]
        if t == "en":
            ref = J(os.path.join(SETS[st], "out", "meaning_ht.json")) if s == "ht" else en
            jobs.append({"id": f"WRITTEN:{k}", "src": s, "tgt": t, "source": sub(J(os.path.join(CL, f"{s}.txt.json"))), "reference": sub(ref), "systems": sy, "idx": keep})
        else:
            jobs.append({"id": f"WRITTEN:{k}", "src": s, "tgt": t, "source": sub(en), "reference": sub(en), "systems": sy, "idx": keep})
    json.dump(jobs, open(os.path.join(OUT, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs", [ (j["id"], len(j["source"]), {n: len(v) for n, v in j["systems"].items()}) for j in jobs][:2])
elif MODE == "table":
    G = J(os.path.join(OUT, "grades.json")); T = J(os.path.join(OUT, "translations.json"))
    def flagged(st, l):
        p = os.path.join(SETS[st], "out", "witness", f"{l}.json")
        return {r["i"] for r in (J(p) if os.path.exists(p) else []) if r.get("cut_off") or r.get("meaning_differs")}
    q = lambda g: {"q": round(100 * sum(x.get("score", 0) for x in g) / (3 * max(1, len(g))), 1), "crit": sum(1 for x in g if x.get("critical")), "n": len(g)}
    res = {}
    IDX = {j["id"]: j["idx"] for j in J(os.path.join(OUT, "jobs.json"))}
    for gid, v in G.items():
        _, st, d = gid.split(":"); s = d.split("-")[0]
        bad = flagged(st, "en" if s == "en" else s); idx = IDX[gid]
        for name, g in v["grades"].items():
            r = res.setdefault(d, {}).setdefault(name, {"written": [], "said": []})
            r["written"] += g; r["said"] += [x for x in g if idx[x["i"]] not in bad]
    for d, ss in res.items():
        for name, r in ss.items():
            r["written"], r["said"] = q(r["written"]), q(r["said"])
            tv = [x for kk, v in T.items() if kk.endswith(f"{d}:{name}") for x in v if x]
            ms = sorted(x["ms"] for x in tv)
            r.update({"p50_ms": ms[len(ms) // 2], "p90_ms": ms[int(0.9 * (len(ms) - 1))], "n_req": len(tv),
                      "empty_or_error": sum(1 for x in tv if not x["out"]), "providers": sorted({str(x["provider"]) for x in tv}),
                      "tok_in_mean": round(sum(x["in"] for x in tv) / len(tv)), "tok_out_mean": round(sum(x["outtok"] for x in tv) / len(tv))})
    json.dump(res, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    for d, ss in sorted(res.items()):
        for name, r in sorted(ss.items()):
            print(d, name, "W", r["written"]["q"], "S", r["said"]["q"], "crit", r["said"]["crit"], "p50/p90", r["p50_ms"], r["p90_ms"], "err", r["empty_or_error"], r["providers"], "tok", r["tok_in_mean"], r["tok_out_mean"])
