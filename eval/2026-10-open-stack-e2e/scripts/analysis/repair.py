# LLM repair of the open stack's transcripts (e2e run 2026-10-21), DeepSeek V4-Pro via OpenRouter with ZDR enforced.
#   OPENROUTER_API_KEY=... python3 -I repair.py run     # repair (none / prev-sentence context) + translate (V4-Pro) → out/
#   python3 -I repair.py cer | jobs | table
import concurrent.futures as cf, json, os, re, sys, time, unicodedata, urllib.error, urllib.request
H = os.path.dirname(os.path.abspath(__file__)); E = os.environ.get("E2E_DIR", os.path.join(H, "..", "e2e-stack"))  # the e2e run: clips/, out/sentences.json, out/mt/, scripts/mt_grade.py; O = os.path.join(H, "out"); os.makedirs(O, exist_ok=True)
S = json.load(open(os.path.join(E, "out", "sentences.json")))
NAMES = {"en": "English", "fr": "French", "es": "Spanish", "ja": "Japanese", "km": "Khmer", "lo": "Lao", "ht": "Haitian Creole"}
SRC_DIR = {"en": "en-es", "es": "es-en", "ja": "ja-en", "fr": "fr-en", "km": "km-en", "ht": "ht-en", "lo": "lo-en"}
MODEL = "deepseek/deepseek-v4-pro"


def call(messages, n):
    body = {"model": MODEL, "messages": messages, "temperature": 0, "max_tokens": min(1024, 64 + 4 * n),
            "reasoning": {"enabled": False}, "usage": {"include": True}, "provider": {"zdr": True}}
    for attempt in range(6):
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]})
        try:
            j = json.load(urllib.request.urlopen(req, timeout=120))
            return (j["choices"][0]["message"].get("content") or "").strip(), j.get("provider")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError) as e:
            if attempt == 5 or (isinstance(e, urllib.error.HTTPError) and e.code not in (429, 500, 502, 503, 504)):
                raise
        time.sleep(4 * (attempt + 1))


def repair_msgs(text, lang, prev):
    sys_p = (f"You correct speech-recognition output in {NAMES[lang]}. The text is one sentence of a live talk, transcribed "
             "automatically, and may contain misheard words, wrong word boundaries, missing punctuation or a fragment of a "
             f"neighbouring sentence. Fix only clear recognition errors so it reads as what the speaker most likely said, in {NAMES[lang]}. "
             "Do not translate, summarise, add information or complete a cut-off sentence. If it already looks right, return it "
             "unchanged. Reply with the corrected sentence only.")
    u = (f"Previous sentence (context only, do not output it):\n{prev}\n\n" if prev else "") + f"Transcript to correct:\n{text}"
    return [{"role": "system", "content": sys_p}, {"role": "user", "content": u}]


def translate_msgs(text, s, t):
    return [{"role": "system", "content": f"Translate the user's {NAMES[s]} text into {NAMES[t]}. Reply with the translation only."},
            {"role": "user", "content": text}]


def norm(s, lang):
    s = unicodedata.normalize("NFKC", s).lower()
    s = "".join(c for c in s if not unicodedata.category(c).startswith(("P", "S")))
    return re.sub(r"\s+", "" if lang in ("ja", "km", "lo") else " ", s).strip()


def lev(a, b):
    p = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        c = [i]
        for j, cb in enumerate(b, 1):
            c.append(min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (ca != cb)))
        p = c
    return p[-1]


def cer(hyps, refs, lang):
    e = sum(lev(norm(h, lang), norm(r, lang)) for h, r in zip(hyps, refs)); n = sum(len(norm(r, lang)) for r in refs)
    return round(e / n, 4)


cmd = sys.argv[1]
if cmd == "run":
    prov = set()

    def rep(lang):
        heard = S[SRC_DIR[lang]]["heard_per_sentence"]
        out = {"none": [], "ctx": []}
        for i, h in enumerate(heard):
            for mode in ("none", "ctx"):
                if not h.strip():
                    out[mode].append(""); continue
                prev = heard[i - 1] if mode == "ctx" and i > 0 else ""
                r, p = call(repair_msgs(h, lang, prev), len(h)); prov.add(p)
                out[mode].append(r)
        return lang, out

    with cf.ThreadPoolExecutor(7) as ex:
        R = dict(ex.map(rep, SRC_DIR))
    json.dump(R, open(os.path.join(O, "repaired.json"), "w"), ensure_ascii=False, indent=1)
    print("repaired", flush=True)

    def tr(d):
        s, t = d.split("-")
        variants = {"raw": S[d]["heard_per_sentence"], "rep_none": R[s]["none"], "rep_ctx": R[s]["ctx"]}
        res = {}
        for name, texts in variants.items():
            outs = []
            for x in texts:
                if not x.strip():
                    outs.append(""); continue
                y, p = call(translate_msgs(x, s, t), len(x)); prov.add(p); outs.append(y)
            res[name] = outs
        return d, res

    with cf.ThreadPoolExecutor(6) as ex:
        T = dict(ex.map(tr, S))
    json.dump(T, open(os.path.join(O, "translated.json"), "w"), ensure_ascii=False, indent=1)
    json.dump({"providers": sorted(map(str, prov))}, open(os.path.join(O, "meta.json"), "w"), indent=1)
    print("done; providers", sorted(map(str, prov)))
elif cmd == "cer":
    R = json.load(open(os.path.join(O, "repaired.json"))); res = {}
    for lang, d in SRC_DIR.items():
        src = S[d]["source"]; raw = S[d]["heard_per_sentence"]
        res[lang] = {"raw": cer(raw, src, lang), "rep_none": cer(R[lang]["none"], src, lang), "rep_ctx": cer(R[lang]["ctx"], src, lang),
                     "changed_none": sum(norm(a, lang) != norm(b, lang) for a, b in zip(raw, R[lang]["none"])),
                     "changed_ctx": sum(norm(a, lang) != norm(b, lang) for a, b in zip(raw, R[lang]["ctx"]))}
    json.dump(res, open(os.path.join(O, "cer.json"), "w"), indent=1)
    for k, v in res.items(): print(k, v)
elif cmd == "jobs":
    sys.argv = ["x", E, "table"]  # mt_grade's reference() needs its globals only
    ns = {}
    src = open(os.path.join(E, "scripts", "mt_grade.py")).read().split("def http(")[0]
    exec(compile(src, "mt_grade_refs", "exec"), ns)
    T = json.load(open(os.path.join(O, "translated.json"))); jobs = []
    for d in S:
        s, t = d.split("-")
        mt = lambda k: json.load(open(os.path.join(E, "out", "mt", k, d + ".json")))
        def outs(x): return x["out"] if isinstance(x, dict) and "out" in x else x
        systems = {"stack_raw": outs(mt("stack-mt:transcript")), "stack_gold": outs(mt("stack-mt:gold")),
                   "v4pro_raw": T[d]["raw"], "v4pro_rep_none": T[d]["rep_none"], "v4pro_rep_ctx": T[d]["rep_ctx"]}
        jobs.append({"id": "R:" + d, "src": s, "tgt": t, "source": S[d]["source"], "reference": ns["reference"](d), "systems": systems})
    json.dump(jobs, open(os.path.join(O, "jobs.json"), "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs", {k: len(v) for k, v in jobs[0]["systems"].items()}, len(jobs[0]["reference"]))
else:
    G = json.load(open(os.path.join(O, "grades.json")))
    sc = lambda rows: (round(100 * sum(r.get("score", 0) for r in rows) / (3 * len(rows)), 1), sum(1 for r in rows if r.get("critical")))
    res = {k[2:]: {s: sc(v["grades"][s]) for s in v["grades"]} for k, v in G.items()}
    sysn = list(next(iter(res.values())))
    res["ALL"] = {s: sc([r for v in G.values() for r in v["grades"][s]]) for s in sysn}
    json.dump(res, open(os.path.join(O, "results.json"), "w"), indent=1)
    for k, v in res.items(): print(k, v)
