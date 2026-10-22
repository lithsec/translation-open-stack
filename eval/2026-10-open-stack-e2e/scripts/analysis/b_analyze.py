# Experiment B on the Mac.
#   python3 -I b_analyze.py pairs   -> podB/qe_pairs.json (every candidate, for MetricX QE on the pod)
#   python3 -I b_analyze.py jobs    -> out/B/jobs.json (blind grading, one job per direction)
#   python3 -I b_analyze.py table   -> out/B/results.json (+ printed tables)
import json, os, statistics, sys

X = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
O = os.path.join(X, "out", "B")
D = json.load(open(os.path.join(X, "podB", "b_inputs.json")))
E2E = os.path.join(os.path.dirname(X), "e2e-stack")
RUNS = {"qwen_direct": "q_direct.json", "qwen_ctx": "q_ctx.json", "qwen_repair": "q_repair.json", "hymt30": "h_direct.json"}
GRADED = ["stack", "qwen_direct", "qwen_ctx", "qwen_repair", "hymt30", "sol"]


def J(p):
    return json.load(open(p))


def candidates():
    C = {}
    runs = {k: J(os.path.join(O, f))["res"] for k, f in RUNS.items() if os.path.exists(os.path.join(O, f))}
    for d in D:
        c = {"stack": d["stack"], "sol": d["sol"]}
        for k, r in runs.items():
            c[k] = r[d["id"]]["out"]
        C[d["id"]] = c
    return C


def pairs():
    C = candidates()
    P = []
    for d in D:
        for sys_, outs in C[d["id"]].items():
            for i, (x, h) in enumerate(zip(d["inputs"], outs)):
                if x.strip() and h.strip():
                    P.append({"key": f"{d['id']}|{sys_}|{i}", "src": x, "hyp": h})
    json.dump(P, open(os.path.join(X, "podB", "qe_pairs.json"), "w"), ensure_ascii=False)
    print(len(P), "pairs")


def reference(d):
    if d["id"].startswith("real:"):
        return d["reference"]
    s = d["src"]
    if s == "fr":
        return J(os.path.expanduser("~/dev/translation-open-stack/eval/2026-10-translator-shootout/refs/meaning_fr.json"))["en"][:20]
    if s == "ht":
        return J(os.path.expanduser("~/dev/translation-open-stack/eval/2026-10-real-voices/sentences/meaning_ht.json"))[:20]
    return J(os.path.join(E2E, "clips", "en.txt.json"))


def jobs():
    C = candidates()
    out = []
    for d in D:
        systems = {k: C[d["id"]][k] for k in GRADED}
        if d["id"] in ("e2e:en-es", "e2e:en-fr", "e2e:en-ja"):  # addition C: other English transcripts, same Hy-MT2
            t = d["tgt"]
            MC = J(os.path.join(X, "out", "C", "mt_c.json"))
            systems["C_hymt_canary_ps"] = MC[f"en-{t}:canary"]["out"]
            systems["C_hymt_whisper_ps"] = MC[f"en-{t}:whisper"]["out"]
            systems["C_stack_gold"] = J(os.path.join(E2E, "out", "mt", "stack-mt:gold", f"en-{t}.json"))["out"]
        out.append({"id": "B:" + d["id"], "src": d["src"], "tgt": d["tgt"], "source": d["source"],
                    "reference": reference(d), "systems": systems})
    json.dump(out, open(os.path.join(O, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(out), "jobs")


def group(d):
    s, t = d["src"], d["tgt"]
    if "lo" in (s, t):
        return "Lao (both ways)"
    if "ht" in (s, t):
        return "Haitian Creole (both ways)"
    return "Into English (ja km fr es)" if t == "en" else "Out of English (ja km fr es)"


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f = int(k); c = min(f + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 3)


def table():
    G = J(os.path.join(O, "grades.json"))
    Q = J(os.path.join(O, "qe_scores.json"))
    C = candidates()
    rows = {}  # direction -> system -> per-sentence (score, critical)
    for d in D:
        g = G["B:" + d["id"]]["grades"]
        n = len(d["source"])
        rows[d["id"]] = {s: [(r.get("score", 0), bool(r.get("critical"))) for r in g[s][:n]] for s in g}

    def qe(did, s, i):  # MetricX error (lower is better); a blank output is the worst
        return Q.get(f"{did}|{s}|{i}", 25.0)

    # simulated systems
    pool = ["stack", "qwen_direct", "qwen_ctx"]
    sims = {}
    for d in D:
        did = d["id"]; n = len(d["source"])
        R = rows[did]
        pick = [min(pool, key=lambda s: (qe(did, s, i), pool.index(s))) for i in range(n)]
        R["qe_pick"] = [R[s][i] for i, s in enumerate(pick)]
        sims.setdefault("qe_pick_choice", {})[did] = pick
        for T in (2, 3, 4, 5, 6, 8):
            for tgt in ("qwen_direct", "qwen_ctx"):
                esc = [qe(did, "stack", i) > T for i in range(n)]
                R[f"esc_{tgt}_T{T}"] = [R[tgt][i] if e else R["stack"][i] for i, e in enumerate(esc)]
                sims.setdefault(f"esc_{tgt}_T{T}", {})[did] = sum(esc)
    allsys = [k for k in next(iter(rows.values())).keys() if not k.startswith("C_")]
    res_c = {did: {s: {"score": round(100 * sum(a for a, _ in v) / (3 * len(v)), 1), "critical": sum(1 for _, c in v if c)}
                   for s, v in rows[did].items() if s in ("stack", "sol", "qwen_direct", "C_hymt_canary_ps", "C_hymt_whisper_ps", "C_stack_gold")}
             for did in ("e2e:en-es", "e2e:en-fr", "e2e:en-ja")}
    json.dump(res_c, open(os.path.join(X, "out", "C", "quality.json"), "w"), indent=1)
    print(json.dumps(res_c, indent=0))

    def agg(dirs, s):
        sc = [x for did in dirs for x in rows[did][s]]
        return {"score": round(100 * sum(a for a, _ in sc) / (3 * len(sc)), 1), "critical": sum(1 for _, c in sc if c), "n": len(sc)}

    groups = {}
    for d in D:
        groups.setdefault(group(d), []).append(d["id"])
    groups["All 22 directions"] = [d["id"] for d in D]
    res = {"per_direction": {did: {s: agg([did], s) for s in allsys} for did in rows},
           "groups": {g: {s: agg(ds, s) for s in allsys} for g, ds in groups.items()},
           "escalation_rate": {k: round(sum(v.values()) / sum(len(d["source"]) for d in D), 3) for k, v in sims.items() if k.startswith("esc_")},
           "qe_pick_share": {s: round(sum(c.count(s) for c in sims["qe_pick_choice"].values()) / sum(len(c) for c in sims["qe_pick_choice"].values()), 3) for s in pool}}
    # QE means per system (sanity: does MetricX rank like the grader?)
    res["metricx_mean"] = {s: round(statistics.mean(qe(d["id"], s, i) for d in D for i in range(len(d["source"])) if d["inputs"][i].strip()), 2)
                           for s in GRADED}
    lat = {}
    for name, f in [("qwen_direct", "qlat_direct.json"), ("qwen_ctx", "qlat_ctx.json"), ("hymt30", "hlat_direct.json")]:
        p = os.path.join(O, f)
        if os.path.exists(p):
            r = J(p)["res"]
            w = [x for v in r.values() for x in v["wall_s"] if x is not None]
            tk = [x for v in r.values() for x in v["completion_tokens"] if x]
            lat[name] = {"p50_s": pct(w, .5), "p90_s": pct(w, .9), "max_s": max(w), "n": len(w), "tokens_p50": pct(tk, .5)}
    res["latency_single_stream"] = lat
    json.dump(res, open(os.path.join(O, "results.json"), "w"), indent=1)
    show = GRADED + ["qe_pick", "esc_qwen_direct_T5", "esc_qwen_ctx_T5"]
    print("group".ljust(30) + "".join(s[:14].rjust(15) for s in show))
    for g, v in res["groups"].items():
        print(g.ljust(30) + "".join(f"{v[s]['score']:6.1f} ({v[s]['critical']:3d})".rjust(15) for s in show))
    print(json.dumps({k: res[k] for k in ("escalation_rate", "qe_pick_share", "metricx_mean", "latency_single_stream")}, indent=1))


{"pairs": pairs, "jobs": jobs, "table": table}[sys.argv[1]]()
