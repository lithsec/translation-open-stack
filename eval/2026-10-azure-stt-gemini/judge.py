# Blind-grades the two contenders per direction with the September grader
# (Gemini 2.5 Pro on Vertex, same prompt as judge_e2e.py), measures delay and
# how well each one HEARD the speaker, and writes results.json plus a table.
#
#   GOOGLE_CLOUD_PROJECT=... python3 judge.py en-ja ja-en ...
import json, os, random, re, sys, unicodedata
import concurrent.futures as cf

HERE = os.path.dirname(os.path.abspath(__file__))
SEPT = os.path.join(HERE, "..", "2026-09-model-eval")
sys.path.insert(0, os.path.join(SEPT, "scripts"))
from vertex import gemini  # noqa: E402

NAMES = {"en": "English", "ja": "Japanese", "zh": "Chinese", "km": "Khmer", "lo": "Lao", "ht": "Haitian Creole"}
EN = json.load(open(os.path.join(SEPT, "sentences", "en.json")))
SYSTEMS = {"pipe": "azure_stt_gemini", "live": "gemini_live"}


def source(lang):
    return EN if lang == "en" else json.load(open(os.path.join(SEPT, "sentences", f"src_{lang}.json")))


def load(mode, d):
    try:
        return json.load(open(os.path.join(HERE, "out", mode, f"{d}.json")))
    except FileNotFoundError:
        return None


def said(r):
    return " ".join(t["said"].strip() for t in r["turns"] if t["said"].strip())


def judge(d):
    src, tgt = d.split("-")
    systems = {}
    for mode, name in SYSTEMS.items():
        r = load(mode, d)
        if r and not r.get("err") and said(r):
            systems[name] = said(r)
    if not systems:
        return d, {}
    cache = os.path.join(HERE, "out", "judge", f"{d}.json")
    if os.path.exists(cache):
        return d, json.load(open(cache))
    labels = list(systems)
    random.Random(d).shuffle(labels)
    names = {chr(65 + i): m for i, m in enumerate(labels)}
    blocks = [f"### System {L}\n(one continuous transcript of a spoken interpretation; align it to the 24 sentences yourself; "
              f"a sentence it does not render scores 0)\n{systems[m]}" for L, m in names.items()]
    prompt = f"""You are an expert {NAMES[src]}->{NAMES[tgt]} translation evaluator. Grade each system's translation of each of the 24 source sentences.
The intended meaning of every sentence is given by its English original (reference meaning), which is authoritative.

Score each sentence per system:
3 = meaning fully correct and natural; 2 = meaning correct but awkward or unidiomatic; 1 = partly wrong, or something important omitted or added; 0 = wrong meaning, wrong language, garbled, or missing.
Also set critical=true when a number, time, date, dose, amount, negation, or who-did-what is wrong (even if the rest is fine).

Source sentences ({NAMES[src]}):
{json.dumps(source(src), ensure_ascii=False)}

Reference meaning (English originals):
{json.dumps(EN, ensure_ascii=False)}

Translations into {NAMES[tgt]}:
{chr(10).join(blocks)}

Return JSON: {{"A": [{{"i": 0, "score": 3, "critical": false, "note": "..."}}, ... 24 items], "B": [...], ...}} with a short note only when score < 3 or critical."""
    res = gemini(prompt)
    out = {names[L]: v for L, v in res.items() if L in names}
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump(out, open(cache, "w"), ensure_ascii=False, indent=1)
    return d, out


def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c for c in s if c.isalnum())


def cer(ref, hyp):
    a, b = norm(ref), norm(hyp)
    if not a:
        return None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return round(prev[-1] / len(a), 3)


def delays(d, mode):
    """For each sentence end, ms until the next translated audio starts."""
    r = load(mode, d)
    if not r or r.get("err"):
        return None
    marks = json.load(open(os.path.join(HERE, "audio", f"{d.split('-')[0]}.json")))["sentences"]
    starts = sorted(t["audioAt"] for t in r["turns"] if t["audioAt"] is not None)
    out = []
    for m in marks:
        end = m["end"] * 1000
        nxt = next((s for s in starts if s >= end), None)
        if nxt is not None:
            out.append(nxt - end)
    if not out:
        return None
    out.sort()
    return {"median_ms": round(out[len(out) // 2]), "p90_ms": round(out[int(len(out) * 0.9) - 1])}


def main(dirs):
    with cf.ThreadPoolExecutor(5) as ex:
        grades = dict(ex.map(judge, dirs))
    results = {}
    for d in dirs:
        src = d.split("-")[0]
        row = {}
        for mode, name in SYSTEMS.items():
            g = grades.get(d, {}).get(name)
            r = load(mode, d)
            entry = {"error": r.get("err")} if r and r.get("err") else {}
            if g:
                entry["score_pct"] = round(100 * sum(x["score"] for x in g) / (3 * 24))
                entry["critical"] = sum(1 for x in g if x.get("critical"))
                entry["grades"] = g
            dl = delays(d, mode)
            if dl:
                entry["delay"] = dl
            row[name] = entry
        stt = os.path.join(HERE, "out", "stt", f"{src}.json")
        if os.path.exists(stt):
            s = json.load(open(stt))
            row["azure_stt_cer"] = cer(" ".join(source(src)), " ".join(f["text"] for f in s["finals"])) if not s["err"] else None
        lv = load("live", d)
        if lv and lv.get("heard"):
            row["gemini_heard_cer"] = cer(" ".join(source(src)), lv["heard"])
        results[d] = row
    json.dump(results, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)

    def cell(e):
        if e.get("error"):
            return "error"
        if "score_pct" not in e:
            return "—"
        dl = e.get("delay", {}).get("median_ms")
        return f"{e['score_pct']}% ({e['critical']} crit){f', {dl/1000:.1f} s' if dl is not None else ''}"
    print("| Direction | Azure STT → Gemini | Gemini Live | Azure heard (CER) | Gemini heard (CER) |")
    print("|---|---|---|---|---|")
    for d, row in results.items():
        a, g = row.get("azure_stt_gemini", {}), row.get("gemini_live", {})
        ac, gc = row.get("azure_stt_cer"), row.get("gemini_heard_cer")
        print(f"| {d} | {cell(a)} | {cell(g)} | {'—' if ac is None else f'{ac:.0%}'} | {'—' if gc is None else f'{gc:.0%}'} |")


if __name__ == "__main__":
    main(sys.argv[1:])
