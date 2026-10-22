# Experiment A on the Mac: CER from the pod's ASR outputs, the transcript variants for the translators,
# then (after MT + sol) the grading jobs and the final table.
#   python3 -I a_analyze.py cer        -> out/A/cer.json, podA/variants.json
#   python3 -I a_analyze.py jobs       -> out/A/jobs.json (needs out/A/mt_a.json, out/A/sol_a.json)
#   python3 -I a_analyze.py table      -> out/A/results.json (needs out/A/grades.json)
import difflib, json, os, sys, unicodedata

X = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
O = os.path.join(X, "out", "A")
RV = os.path.expanduser("~/dev/translation-open-stack/eval/2026-10-real-voices")
E2E = os.path.join(os.path.dirname(X), "e2e-stack")
CARDS = {"300M": "omniASR_LLM_300M", "7B": "omniASR_LLM_7B"}
SETTINGS = ["200:10", "700:15"]


def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c for c in s if c.isalnum())


def edits(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref, hyp):  # judge.cer on the joined text (as omni-sizes score.py / e2e)
    a, b = norm(ref), norm(hyp)
    return round(edits(a, b) / len(a), 4)


def split_like(text, sents):  # shootout.split_like
    gold = " ".join(sents)
    sm = difflib.SequenceMatcher(None, gold, text, autojunk=False)
    ends, pos = [], 0
    for s_ in sents:
        pos += len(s_); ends.append(pos); pos += 1
    blocks = sm.get_matching_blocks()

    def across(i):
        for a, b, n in blocks:
            if a <= i <= a + n:
                return b + (i - a)
            if a > i:
                return b
        return len(text)
    cuts = [0] + [across(e) for e in ends]
    cuts[-1] = len(text)
    return [text[cuts[k]:cuts[k + 1]].strip() for k in range(len(sents))]


def J(p):
    return json.load(open(p))


def do_cer():
    os.makedirs(O, exist_ok=True)
    S = J(os.path.join(E2E, "out", "sentences.json"))
    res, variants = {}, {}
    for lang in ("km", "lo"):
        refs30 = J(os.path.join(RV, "sentences", f"{lang}.json"))
        refs20 = refs30[:20]
        r = res[lang] = {}
        # the e2e-stack live run (stack server, LLM 300M): as analyze_e2e (heard_all vs the 20 sources)
        r["e2e_live_300M"] = {"cer": cer(" ".join(refs20), S[f"{lang}-en"]["heard_all"])}
        for size, card in CARDS.items():
            d = J(os.path.join(O, f"{card}.json"))
            rows = d["per_sentence"][lang]
            r[f"per_sentence_{size}"] = {
                "cer": cer(" ".join(refs30), " ".join(x["text"] for x in rows)),
                "cer_unguarded": cer(" ".join(refs30), " ".join(x["raw"] for x in rows)),
                "cer_first20": cer(" ".join(refs20), " ".join(x["text"] for x in rows[:20])),
                "guarded": sum(1 for x in rows if x["guard"]), "empty": sum(1 for x in rows if not x["text"]),
                "rtf_all": d["rtf_batch1"], "mem_peak_gb": d["mem_peak_gb"], "gpu": d["gpu"]}
            variants[f"{lang}:ps:{size}"] = {"lang": lang, "texts": [x["text"] for x in rows]}
            for st in SETTINGS:
                segs = d["segmented"][f"{lang}:{st}"]
                joined = " ".join(x["text"] for x in segs if x["text"])
                r[f"seg_{st}_{size}"] = {"cer": cer(" ".join(refs20), joined),
                                         "cer_unguarded": cer(" ".join(refs20), " ".join(x["raw"] for x in segs if x["raw"])),
                                         "segments": len(segs), "guarded": sum(1 for x in segs if x["guard"])}
                variants[f"{lang}:seg{st}:{size}"] = {"lang": lang, "texts": split_like(joined, refs20)}
    json.dump(res, open(os.path.join(O, "cer.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(variants, open(os.path.join(X, "podA", "variants.json"), "w"), ensure_ascii=False, indent=1)
    for lang, r in res.items():
        for k, v in r.items():
            print(lang, k, v)


def systems_for(lang, n):
    """Grading jobs: e2e-20 (with the existing e2e stack-mt/sol on the live 300M transcript) and rv-30."""
    MT = J(os.path.join(O, "mt_a.json")); SOL = J(os.path.join(O, "sol_a.json"))
    sysd = {}
    for k in MT:
        parts = k.split(":"); l, size, kind = parts[0], parts[-1], ":".join(parts[1:-1])
        if l != lang or (kind == "ps") != (n == 30):
            continue
        sysd[f"stack|{kind}|{size}"] = MT[k]["out"]
        if k in SOL:
            sysd[f"sol|{kind}|{size}"] = SOL[k]["out"]
    return sysd


def jobs():
    S = J(os.path.join(E2E, "out", "sentences.json"))
    en20 = J(os.path.join(E2E, "clips", "en.txt.json"))
    out = []
    for lang in ("km", "lo"):
        d = f"{lang}-en"
        sysd = systems_for(lang, 20)
        sysd["stack|e2e-live|300M"] = J(os.path.join(E2E, "out", "mt", "stack-mt:transcript", f"{d}.json"))["out"]
        sysd["sol|e2e-live|300M"] = J(os.path.join(E2E, "out", "mt", "sol:transcript", f"{d}.json"))["out"]
        sysd["stack|gold|-"] = J(os.path.join(E2E, "out", "mt", "stack-mt:gold", f"{d}.json"))["out"]
        out.append({"id": f"A:e2e20:{d}", "src": lang, "tgt": "en", "source": S[d]["source"], "reference": en20, "systems": sysd})
        sysd = systems_for(lang, 30)
        out.append({"id": f"A:rv30:{d}", "src": lang, "tgt": "en", "source": J(os.path.join(RV, "sentences", f"{lang}.json")),
                    "reference": J(os.path.join(RV, "sentences", f"meaning_{lang}.json")), "systems": sysd})
    for j in out:
        for k, v in j["systems"].items():
            assert len(v) == len(j["source"]) == len(j["reference"]), (j["id"], k)
    json.dump(out, open(os.path.join(O, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(out), "jobs", [len(j["systems"]) for j in out])


def table():
    G = J(os.path.join(O, "grades.json"))
    res = {}
    for d, g in G.items():
        res[d] = {}
        for s, rows in g["grades"].items():
            n = len(rows)
            res[d][s] = {"score": round(100 * sum(r.get("score", 0) for r in rows) / (3 * n)),
                         "critical": sum(1 for r in rows if r.get("critical")), "full": sum(1 for r in rows if r.get("score") == 3)}
    json.dump(res, open(os.path.join(O, "quality.json"), "w"), indent=1)
    for d, r in res.items():
        print(d)
        for s, v in sorted(r.items()):
            print(f"   {s:28s} {v['score']:3d}  crit {v['critical']:2d}  full {v['full']}")


{"cer": do_cer, "jobs": jobs, "table": table}[sys.argv[1]]()
