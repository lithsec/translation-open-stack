# Blind-grades the three contenders per direction with the September grader
# (Gemini 2.5 Pro on Vertex, same prompt as judge_e2e.py), measures delay and
# how well each one HEARD the speaker, and writes results.json plus a table.
# Real voices: each clip's own sentences (sentences/<lang>.json) and their
# English meaning (sentences/meaning_<lang>.json: FLEURS's English, or for
# Haitian Creole the reference make_refs.py wrote).
#
#   GOOGLE_CLOUD_PROJECT=... python3 judge.py en-ja ja-en ...
import json, os, random, re, sys, unicodedata
import concurrent.futures as cf

HERE = os.path.dirname(os.path.abspath(__file__))
SEPT = os.path.join(HERE, "..", "2026-09-model-eval")
sys.path.insert(0, os.path.join(SEPT, "scripts"))
from vertex import gemini  # noqa: E402

NAMES = {"en": "English", "ja": "Japanese", "zh": "Chinese", "km": "Khmer", "lo": "Lao", "ht": "Haitian Creole"}
SENT = os.path.join(HERE, "sentences")
SYSTEMS = {"azure": "azure_only", "pipe": "azure_stt_gemini", "gladia": "gladia_stt_gemini", "live": "gemini_live", "told": "gemini_live_told_lang", "stack": "open_stack"}


def source(lang):
    return json.load(open(os.path.join(SENT, f"{lang}.json")))


def meaning(lang):
    return json.load(open(os.path.join(SENT, f"meaning_{lang}.json")))


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
    n = len(source(src))
    blocks = [f"### System {L}\n(one continuous transcript of a spoken interpretation; align it to the {n} sentences yourself; "
              f"a sentence it does not render scores 0)\n{systems[m]}" for L, m in names.items()]
    prompt = f"""You are an expert {NAMES[src]}->{NAMES[tgt]} translation evaluator. Grade each system's translation of each of the {n} source sentences.
The intended meaning of every sentence is given by its English reference, which is authoritative.

Score each sentence per system:
3 = meaning fully correct and natural; 2 = meaning correct but awkward or unidiomatic; 1 = partly wrong, or something important omitted or added; 0 = wrong meaning, wrong language, garbled, or missing.
Also set critical=true when a number, time, date, dose, amount, negation, or who-did-what is wrong (even if the rest is fine).

Source sentences ({NAMES[src]}):
{json.dumps(source(src), ensure_ascii=False)}

Reference meaning (English):
{json.dumps(meaning(src), ensure_ascii=False)}

Translations into {NAMES[tgt]}:
{chr(10).join(blocks)}

Return JSON: {{"A": [{{"i": 0, "score": 3, "critical": false, "note": "..."}}, ... {n} items], "B": [...], ...}} with a short note only when score < 3 or critical."""
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
    """How far behind the speaker it runs. per_sentence (the pipeline, one turn
    per sentence): from each sentence's end to the next answer's first audio.
    tail (both): from the last sentence's end to the last translated audio,
    i.e. how long the room waits after the speaker stops."""
    r = load(mode, d)
    if not r or r.get("err"):
        return None
    marks = json.load(open(os.path.join(HERE, "audio", f"{d.split('-')[0]}.json")))["sentences"]
    out = {}
    chunks = sorted(r.get("chunks") or [])
    # Live Translate streams audio (silence included) until the session
    # closes, so its last chunk says nothing about when it finished speaking.
    if chunks and mode in ("pipe", "gladia", "stack"):
        out["tail_ms"] = round(chunks[-1] - marks[-1]["end"] * 1000)
    if mode in ("pipe", "gladia", "azure", "stack"):
        # Azure only: when the translated text arrived, plus how long Azure's
        # voice takes to start speaking (measured separately on five sentences).
        extra = (r.get("voice_first_audio_ms") or 0) if mode == "azure" else 0
        starts = sorted(t["audioAt"] + extra for t in r["turns"] if t["audioAt"] is not None)
        lags = sorted(n - m["end"] * 1000 for m in marks for n in [next((s for s in starts if s >= m["end"] * 1000), None)] if n is not None)
        if lags:
            out["per_sentence_median_ms"] = round(lags[len(lags) // 2])
    return out or None


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
                # One grade per sentence: the grader once returned 25 items.
                n = len(source(src))
                g = list({x["i"]: x for x in g if isinstance(x.get("i"), int) and 0 <= x["i"] < n}.values())
                entry["score_pct"] = round(100 * sum(x["score"] for x in g) / (3 * n))
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
        gl = os.path.join(HERE, "out", "stt-gladia", f"{src}.json")
        if os.path.exists(gl):
            s = json.load(open(gl))
            row["gladia_stt_cer"] = cer(" ".join(source(src)), " ".join(f["text"] for f in s["finals"])) if not s["err"] else None
        sk = load("stack", d)
        if sk and sk.get("heard"):
            row["stack_heard_cer"] = cer(" ".join(source(src)), sk["heard"])
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
        dl = e.get("delay", {})
        lag = []
        if "per_sentence_median_ms" in dl:
            lag.append(f"{dl['per_sentence_median_ms']/1000:.1f} s/sentence")
        if "tail_ms" in dl:
            lag.append(f"ends +{dl['tail_ms']/1000:.1f} s")
        return f"{e['score_pct']}% ({e['critical']} crit)" + (f", {', '.join(lag)}" if lag else "")
    pct = lambda v: "—" if v is None else f"{v:.0%}"
    print("| Direction | Open stack | Azure only | Azure STT → Gemini | Gladia STT → Gemini | Gemini Live | Stack heard | Azure heard | Gladia heard | Gemini heard |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for d, row in results.items():
        st, z, a, gl, g = (row.get(k, {}) for k in ("open_stack", "azure_only", "azure_stt_gemini", "gladia_stt_gemini", "gemini_live"))
        print(f"| {d} | {cell(st)} | {cell(z)} | {cell(a)} | {cell(gl)} | {cell(g)} | {pct(row.get('stack_heard_cer'))} | "
              f"{pct(row.get('azure_stt_cer'))} | {pct(row.get('gladia_stt_cer'))} | {pct(row.get('gemini_heard_cer'))} |")


if __name__ == "__main__":
    main(sys.argv[1:])
