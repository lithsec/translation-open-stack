# Apple on-device (SpeechTranscriber + Translation) against Talk's automatic cloud route, on the clips of
# ../2026-11-talk-soniox (rebuilt with its build_clips.py from its results/ids.json).
#
#   python3 -I run.py hear  CLIPS WORK [lang ...]   stage 1, real time, 3 clips at a time (harness/applehear hear)
#   python3 -I run.py cut   CLIPS WORK              stage 2 per direction (harness/applehear cut): both arms translated
#   python3 -I run.py jobs  CLIPS WORK              WORK/jobs.json: Apple whole, Apple pieces, the automatic cloud route
#   GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I ../2026-11-talk-soniox/grade.py WORK/jobs.json WORK/grades.json
#   python3 -I run.py jobs2 CLIPS WORK <dir ...>    WORK/jobs_r2.json (a second read where the top two are close)
#   python3 -I run.py table CLIPS WORK              results.json, the README's tables (printed)
#
# APPLEHEAR: the harness binary (default WORK/applehear; build with harness/build.sh).
import concurrent.futures as cf, json, os, statistics, subprocess, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
TALK = os.path.join(HERE, "..", "2026-11-talk-soniox")
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-translator-shootout"))
from shootout import split_like  # noqa: E402

MODE, CLIPS, WORK = sys.argv[1:4]
EXTRA = sys.argv[4:]
BIN = os.environ.get("APPLEHEAR", os.path.join(WORK, "applehear"))
SETS = ["a", "b"]
# Clip language -> the code given to SpeechTranscriber.supportedLocale(equivalentTo:) (pinned to the region the
# clips were read in and Azure was pinned to: see the README on the app's bare codes) and to Translation.
HEAR_LOCALE = {"en": "en-US", "es": "es-MX", "pt": "pt-BR", "fr": "fr-FR", "de": "de-DE", "zh": "zh-CN", "ko": "ko-KR",
               "hi": "hi-IN", "it": "it-IT"}
MT_CODE = {"en": "en", "es": "es", "pt": "pt-BR", "fr": "fr", "de": "de", "zh": "zh-Hans", "vi": "vi", "ar": "ar",
           "uk": "uk", "ko": "ko", "ru": "ru", "hi": "hi", "it": "it"}
# Apple on this Mac (macOS 27.0.1): SpeechTranscriber hears en es pt fr de zh ko hi it (not vi ar fa tl uk ru);
# Translation has en<->every language here but fa and tl.
INTO_EN = ["es", "pt", "fr", "de", "zh", "ko", "hi", "it"]
OUT_OF_EN = ["es", "pt", "fr", "de", "zh", "vi", "ar", "uk", "ko", "ru", "hi", "it"]
DIRS = [f"en-{x}" for x in OUT_OF_EN] + [f"{x}-en" for x in INTO_EN]
NOT_RUN = {"fa-en": "no Apple speech recognition or translation for Persian", "en-fa": "no Apple translation for Persian",
           "tl-en": "no Apple speech recognition or translation for Filipino", "en-tl": "no Apple translation for Filipino",
           "vi-en": "no Apple speech recognition for Vietnamese", "ar-en": "no Apple speech recognition for Arabic",
           "uk-en": "no Apple speech recognition for Ukrainian", "ru-en": "no Apple speech recognition for Russian"}
# What Talk's automatic engine runs today (lithos-server src/routes/plan.ts autoPlan, mode talk, Standard, Plus, the
# Soniox switch on; run 2026-11-25): its hearing, and the translator (the same as the Talk eval's mt.py BASELINE).
AUTO = {
    "en-es": ("soniox", "gemma"), "es-en": ("soniox", "gemma"), "en-pt": ("azure", "gemma"), "pt-en": ("mai", "sol"),
    "en-fr": ("soniox", "gemma"), "fr-en": ("soniox", "gemma"), "en-de": ("azure", "gemma"), "de-en": ("azure", "sol"),
    "en-zh": ("azure", "gemma"), "zh-en": ("mai", "gemma"), "en-vi": ("soniox", "gemma"), "vi-en": ("soniox", "gemma"),
    "en-ar": ("soniox", "sol"), "ar-en": ("soniox", "gemma"), "en-fa": ("soniox", "sol"), "fa-en": ("soniox", "gemma"),
    "en-tl": ("azure", "gemma"), "tl-en": ("mai", "gemma"), "en-uk": ("soniox", "sol"), "uk-en": ("soniox", "sol"),
    "en-ko": ("azure", "gemma"), "ko-en": ("mai", "sol"), "en-ru": ("azure", "gemma"), "ru-en": ("mai", "sol"),
    "en-hi": ("soniox", "gemma"), "hi-en": ("soniox", "sol"), "en-it": ("azure", "gemma"), "it-en": ("azure", "sol"),
}
ARM_OF = {"soniox": "soniox-hear", "mai": "mai-hear", "azure": "azure-hear"}
ROUND = "apple-on-device-2026-11"
GRADER = os.environ.get("GRADER", "gemini-flash-latest")
J = lambda p: json.load(open(p))
clip = lambda st, l, ext: os.path.join(CLIPS, f"clips_{st}", f"{l}.{ext}")
TR = os.path.join(TALK, "results")


def dump(p, x):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(x, open(p, "w"), ensure_ascii=False, indent=1)


if MODE == "hear":
    langs = EXTRA or list(HEAR_LOCALE)
    todo = [(st, l) for l in langs for st in SETS if not os.path.exists(os.path.join(WORK, "hear", st, f"{l}.json"))]

    def one(x):
        st, l = x
        p = os.path.join(WORK, "hear", st, f"{l}.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        r = subprocess.run([BIN, "hear", clip(st, l, "wav"), HEAR_LOCALE[l], p], capture_output=True, text=True)
        return (r.stdout + r.stderr).strip()
    with cf.ThreadPoolExecutor(3) as ex:
        for line in ex.map(one, todo):
            print(line, flush=True)
    sys.exit()

if MODE == "cut":
    def one(x):
        st, d = x
        s, t = d.split("-")
        p = os.path.join(WORK, "cut", st, f"{d}.json")
        if os.path.exists(p):
            return f"{st} {d} done"
        os.makedirs(os.path.dirname(p), exist_ok=True)
        r = subprocess.run([BIN, "cut", os.path.join(WORK, "hear", st, f"{s}.json"), clip(st, s, "wav"), MT_CODE[s],
                            MT_CODE[t], p], capture_output=True, text=True)
        return f"{st} " + (r.stdout + r.stderr).strip()
    for x in [(st, d) for st in SETS for d in DIRS if not EXTRA or d in EXTRA]:   # one at a time: timings
        print(one(x), flush=True)
    sys.exit()


# ---- grouping into the read sentences (as ../2026-10-translator-shootout/shootout.py group does for Azure's finals)
def hits(a, b, marks):
    h = [i for i, m in enumerate(marks)
         if min(b, m["end"]) - max(a, m["start"]) >= 0.5 * min(b - a, m["end"] - m["start"])
         or (min(b, m["end"]) - max(a, m["start"])) >= 0.5 * (m["end"] - m["start"])]
    if not h:
        mid = (a + b) / 2
        h = [min(range(len(marks)), key=lambda i: 0 if marks[i]["start"] <= mid <= marks[i]["end"]
                 else min(abs(mid - marks[i]["start"]), abs(mid - marks[i]["end"])))]
    return h


def arms(st, d):
    """Per read sentence, for each Apple arm: its transcript, its translation, and when the translation of the
    sentence's last words was available (ms, clip time) and its first words."""
    s, t = d.split("-")
    c = J(os.path.join(WORK, "cut", st, f"{d}.json"))
    marks = J(clip(st, s, "json"))["sentences"]
    gold_s, gold_t = J(clip(st, s, "txt.json")), J(clip(st, t, "txt.json"))
    seg_hits = [hits(g["start"], g["end"], marks) for g in c["segments"]]
    out = {}
    for arm in ["whole", "pieces"]:
        n = len(marks)
        heard, tr, last, first = [[] for _ in range(n)], [[] for _ in range(n)], [None] * n, [None] * n
        ps = [p for p in c["pieces"] if p["arm"] == arm]
        for k, g in enumerate(c["segments"]):
            mine = [p for p in ps if p["seg"] == k]
            h = seg_hits[k]
            if not mine:
                continue
            if len(h) == 1:
                who = [h[0]] * len(mine)
                trs = [[p["translation"]] for p in mine]
            elif arm == "whole":   # one final over several sentences: its translation cut where they end
                who = [h]
                trs = [split_like(mine[0]["translation"], [gold_t[i] for i in h])]
            else:   # pieces over several sentences: each piece to the sentence most of its words were heard in
                src_cut = split_like(" ".join(p["text"] for p in mine), [gold_s[i] for i in h])
                bounds, pos = [], 0
                for piece in src_cut:
                    pos += len(piece) + 1
                    bounds.append(pos)
                who, pos = [], 0
                for p in mine:
                    mid = pos + len(p["text"]) / 2
                    pos += len(p["text"]) + 1
                    who.append(h[next((j for j, b in enumerate(bounds) if mid < b), len(h) - 1)])
                trs = [[p["translation"]] for p in mine]
            if arm == "pieces":   # spoken pieces joined: a piece Apple capitalised mid-sentence starts lower-case
                for j in range(1, len(trs)):
                    prev, cur = mine[j - 1]["translation"].rstrip(), trs[j][0]
                    if cur[:1].isupper() and prev and prev[-1] not in ".?!。？！" and not cur[:2].isupper():
                        trs[j] = [cur[:1].lower() + cur[1:]]
            for p, w, x in zip(mine, who, trs):
                ws = w if isinstance(w, list) else [w]
                for i, piece in zip(ws, x if isinstance(w, list) else x * len(ws)):
                    tr[i].append(piece)
                    last[i] = max(last[i] or 0, p["done"])
                    first[i] = p["done"] if first[i] is None else min(first[i], p["done"])
            for i, piece in zip(h, split_like(g["text"], [gold_s[i] for i in h]) if len(h) > 1 else [g["text"]]):
                if arm == "whole":
                    heard[i].append(piece)
        out[arm] = {"heard": [" ".join(x).strip() for x in heard], "out": [" ".join(x).strip() for x in tr],
                    "last_ms": last, "first_ms": first,
                    "pieces": len(ps), "cut_pieces": sum(1 for p in ps if not p["whole"]),
                    "translate_ms": [p["translate_ms"] for p in ps]}
    out["cut_mode"], out["locale"], out["warmup_ms"] = c["cut_mode"], c["locale"], c["warmup_ms"]
    return out


def cloud_out(st, d):
    """The automatic route's translations from the Talk eval's which-hearing round (same clips, same references)."""
    hear, _ = AUTO[d]
    if hear == "azure":
        return J(os.path.join(TR, "mt.json"))[f"{st}:{d}"]["out"]
    if hear == "soniox":
        return J(os.path.join(TR, "soniox_hear.json"))[f"{st}:{d}"]["out"]
    m = J(os.path.join(TR, "hearing", "mt_mai.json"))
    return m[f"{st}:{d}"]["out"]


if MODE == "show":   # run.py show CLIPS WORK <set> <dir>: one direction's sentences, both arms
    a = arms(EXTRA[0], EXTRA[1])
    for arm in ["whole", "pieces"]:
        x = a[arm]
        print(arm, x["pieces"], "pieces,", x["cut_pieces"], "cut,", sum(1 for o in x["out"] if not o), "sentences empty")
        for i, o in enumerate(x["out"]):
            print(f"  {i:2} {x['first_ms'][i]} {x['last_ms'][i]} | {o}")
    sys.exit()

if MODE in ("jobs", "jobs2"):
    jobs = []
    for st in SETS:
        for d in DIRS:
            s, t = d.split("-")
            a = arms(st, d)
            systems = {"apple-whole": a["whole"]["out"], "cloud-auto": cloud_out(st, d)}
            if a["cut_mode"] != "whole":
                systems["apple-pieces"] = a["pieces"]["out"]
            jobs.append({"id": f"apple:{st}:{d}", "src": s, "tgt": t, "source": J(clip(st, s, "txt.json")),
                         "reference": J(clip(st, "en", "txt.json")), "systems": systems})
    if MODE == "jobs2":
        jobs = [dict(j, id="r2:" + j["id"]) for j in jobs if j["id"].split(":")[2] in set(EXTRA)]
    dump(os.path.join(WORK, "jobs.json" if MODE == "jobs" else "jobs_r2.json"), jobs)
    print(len(jobs), "jobs")
    sys.exit()


# ---- recognition scores
def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c if c.isalnum() else " " for c in s)


def ed(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref, hyp):   # ../2026-11-talk-soniox/round_hearing.py cer: letters and digits only
    a, b = norm(ref).replace(" ", ""), norm(hyp).replace(" ", "")
    return ed(a, b) / len(a)


def wer(ref, hyp):   # words after the same normalisation (not for zh: no spaces)
    a, b = norm(ref).split(), norm(hyp).split()
    return ed(a, b) / len(a)


def cloud_heard(st, l):
    """The whole clip's transcript from each cloud recogniser (the Talk eval's results)."""
    r = {"azure": " ".join(f["text"] for f in J(os.path.join(TR, "stt_azure.json"))[f"{st}:{l}"]["finals"])}
    m = J(os.path.join(TR, "hearing", "stt_mai.json")).get(f"{st}:{l}")
    if m:
        r["mai"] = " ".join(f["text"] for f in m["finals"])
    so = J(os.path.join(TR, "soniox.json"))
    streams = [v for k, v in so.items() if k.startswith(f"{st}:{l}-")]
    if streams:
        r["soniox"] = [v["heard"] for v in streams]
    return r


if MODE == "peek":
    for k in ["stt_azure.json", "soniox.json", "mt.json", "soniox_hear.json", "hearing/stt_mai.json", "hearing/mt_mai.json"]:
        x = J(os.path.join(TR, k))
        k0 = next(iter(x))
        v = x[k0]
        print(k, len(x), k0, list(v)[:8] if isinstance(v, dict) else type(v))
    sys.exit()

if MODE != "table":
    sys.exit(f"unknown mode {MODE}")

pct = lambda xs, q: statistics.quantiles(xs, n=100, method="inclusive")[q - 1] if len(xs) > 1 else (xs[0] if xs else None)
G = J(os.path.join(WORK, "grades.json"))
R2P = os.path.join(WORK, "grades_r2.json")
R2 = J(R2P) if os.path.exists(R2P) else {}
q = lambda g: round(100 * sum(x.get("score", 0) for x in g) / (3 * max(1, len(g))), 1)
res = {"round": ROUND, "grader": GRADER, "n_per_set": 20, "mac": os.uname().release, "recognition": {}, "directions": {},
       "not_run": NOT_RUN, "auto": {d: {"hear": h, "translator": t} for d, (h, t) in AUTO.items()}}
talk_hearing = J(os.path.join(TALK, "results.json"))["hearing"]["directions"]

# recognition: Apple's finals over the whole clip, against the FLEURS text (as the Talk eval), and WER
for l in HEAR_LOCALE:
    r = {}
    for st in SETS:
        gold = " ".join(J(clip(st, l, "txt.json")))
        h = J(os.path.join(WORK, "hear", st, f"{l}.json"))
        apple = " ".join(e["text"] for e in h["events"] if e["kind"] == "final")
        hyps = {"apple": apple, **cloud_heard(st, l)}
        for k, v in hyps.items():
            vs = v if isinstance(v, list) else [v]
            r.setdefault(k, {})[st] = {"cer": statistics.mean(cer(gold, x) for x in vs),
                                       "wer": None if l == "zh" else statistics.mean(wer(gold, x) for x in vs)}
        r["apple"][st]["locale"] = h["locale"]
    for k in r:
        r[k]["cer"] = round(100 * statistics.mean(r[k][st]["cer"] for st in SETS), 1)
        r[k]["wer"] = None if l == "zh" else round(100 * statistics.mean(r[k][st]["wer"] for st in SETS), 1)
    res["recognition"][l] = r

for d in DIRS:
    s, t = d.split("-")
    row = {"auto": {"hear": AUTO[d][0], "translator": AUTO[d][1]}, "systems": {}}
    names = list(G[f"apple:a:{d}"]["grades"])
    for name in names:
        gs = {st: G[f"apple:{st}:{d}"]["grades"][name] for st in SETS}
        per = {st: {"q": q(gs[st]), "crit": sum(1 for x in gs[st] if x.get("critical")), "n": len(gs[st])} for st in SETS}
        r = {"q": round(statistics.mean(per[st]["q"] for st in SETS), 1), "crit": sum(per[st]["crit"] for st in SETS),
             "n": sum(per[st]["n"] for st in SETS), "sets": per}
        if f"r2:apple:a:{d}" in R2:
            g2 = {st: R2[f"r2:apple:{st}:{d}"]["grades"][name] for st in SETS}
            q1 = statistics.mean(per[st]["q"] for st in SETS)
            q2 = statistics.mean(q(g2[st]) for st in SETS)
            r.update({"read1_q": round(q1, 1), "read2_q": round(q2, 1), "q": round((q1 + q2) / 2, 1)})
        row["systems"][name] = r
    if "apple-pieces" not in row["systems"]:
        row["systems"]["apple-pieces"] = dict(row["systems"]["apple-whole"], same_as="apple-whole")
    # delays: speech end (the sentence's marked end in the clip) -> its last words' translation; and speech start ->
    # its first words' translation. Seconds, over both sets' sentences that got a translation.
    lat = {"whole": {"end": [], "first": []}, "pieces": {"end": [], "first": []}}
    info = {}
    for st in SETS:
        a = arms(st, d)
        marks = J(clip(st, s, "json"))["sentences"]
        for arm in ["whole", "pieces"]:
            for i, m in enumerate(marks):
                if a[arm]["last_ms"][i] is not None:
                    lat[arm]["end"].append(a[arm]["last_ms"][i] / 1000 - m["end"])
                    lat[arm]["first"].append(a[arm]["first_ms"][i] / 1000 - m["start"])
            info.setdefault(arm, {"pieces": 0, "cut_pieces": 0, "translate_ms": []})
            info[arm]["pieces"] += a[arm]["pieces"]
            info[arm]["cut_pieces"] += a[arm]["cut_pieces"]
            info[arm]["translate_ms"] += a[arm]["translate_ms"]
        row["cut_mode"], row["locale"] = a["cut_mode"], a["locale"]
    row["delay_s"] = {arm: {k: {"p50": round(pct(v, 50), 2), "p90": round(pct(v, 90), 2), "n": len(v)}
                            for k, v in lat[arm].items()} for arm in lat}
    row["pieces"] = {arm: {"pieces": info[arm]["pieces"], "cut_pieces": info[arm]["cut_pieces"],
                           "translate_ms_p50": round(pct(info[arm]["translate_ms"], 50)),
                           "translate_ms_p90": round(pct(info[arm]["translate_ms"], 90))} for arm in info}
    th = talk_hearing.get(d, {})
    row["talk_hearing_round"] = {k: (th.get(k) or {}).get("q") for k in ["soniox-hear", "mai-hear", "azure-hear"]}
    res["directions"][d] = row

json.dump(res, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
for d, r in res["directions"].items():
    S = r["systems"]
    f = lambda n: f"{S[n]['q']:5.1f} c{S[n]['crit']:2d}" + (f" [{S[n]['read1_q']},{S[n]['read2_q']}]" if "read1_q" in S[n] else "")
    dl = r["delay_s"]
    print(f"{d:6} {r['cut_mode']:12} whole {f('apple-whole')} | pieces {f('apple-pieces')} | cloud {f('cloud-auto')} "
          f"({r['auto']['hear']}+{r['auto']['translator']}) | end p50/p90 whole {dl['whole']['end']['p50']}/{dl['whole']['end']['p90']}"
          f" pieces {dl['pieces']['end']['p50']}/{dl['pieces']['end']['p90']} first {dl['whole']['first']['p50']}/{dl['pieces']['first']['p50']}"
          f" n={dl['whole']['end']['n']} cut={r['pieces']['pieces']['cut_pieces']}")
for l, r in res["recognition"].items():
    print(l, {k: (v["cer"], v["wer"]) for k, v in r.items()})
