# Japanese: are the differing spans real recognition errors or the same words
# written differently? Character errors of each system against what was said are
# grouped into spans (error characters with gaps of at most one matching character),
# a seeded sample of spans per system is shown to a judge blind (systems hidden,
# order shuffled) with a little context, and each is labelled:
#   form      the same words: kanji against kana, a numeral against its reading,
#             punctuation or spacing only
#   error     a different word or meaning, or words missing or added
#
#   GEMINI_API_KEY=... python3 -I ja_spans.py RUNS.json OUT.json [per_system=25]
import json, os, random, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-whisper-vs-azure"))
sys.path.insert(0, HERE)
import score as S       # noqa: E402
from analyze import path  # noqa: E402

MODEL = "gemini-pro-latest"


def spans(ref, hyp):
    p, out, cur = path(ref, hyp), [], None
    for k, (i, j) in enumerate(p):
        bad = not (i is not None and j is not None and ref[i] == hyp[j])
        if bad:
            if cur and k - cur["last"] <= 2:
                cur["last"] = k
            else:
                cur = {"first": k, "last": k}
                out.append(cur)
    res = []
    for c in out:
        seg = p[max(0, c["first"] - 4):c["last"] + 5]
        r = "".join(ref[i] for i, _ in seg if i is not None)
        h = "".join(hyp[j] for _, j in seg if j is not None)
        res.append({"ref": r, "hyp": h})
    return res


def judge(items, key):
    lines = "\n".join(f'{n + 1}. reference: 「{x["ref"]}」 recognised: 「{x["hyp"]}」' for n, x in enumerate(items))
    prompt = ("Each line pairs a short span of what a Japanese speaker said (reference) with a speech "
              "recogniser's output for the same audio. For each, answer 'form' if both say the same words and "
              "differ only in writing (kanji against kana or katakana, a numeral against its reading, "
              "punctuation, spacing, okurigana), or 'error' if a word differs in meaning or words are missing "
              "or added. Reply with JSON only: a list of {\"n\": number, \"label\": \"form\"|\"error\"}.\n\n" + lines)
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    r = json.load(urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(),
                                                                {"Content-Type": "application/json", "x-goog-api-key": key}), timeout=180))
    return json.loads(r["candidates"][0]["content"]["parts"][0]["text"])


if __name__ == "__main__":
    man = json.load(open(sys.argv[1]))
    per = int(sys.argv[3]) if len(sys.argv) > 3 else 25
    r = man["refs"]["ja"]
    said = {w["i"]: w.get("said") for w in json.load(open(r["said"]))}
    text = json.load(open(r["text"]))
    ref = list(S.norm(" ".join(said.get(i) or t for i, t in enumerate(text)), "ja").replace(" ", ""))
    rng, pool, totals = random.Random(7), [], {}
    for run in man["runs"]:
        if run["lang"] != "ja" or run.get("ja_check") is not True:
            continue
        hyp = list(S.norm(S.hyp_text(run), "ja").replace(" ", ""))
        sp = spans(ref, hyp)
        totals[run["system"]] = len(sp)
        for x in rng.sample(sp, min(per, len(sp))):
            pool.append(x | {"system": run["system"]})
    rng.shuffle(pool)
    labels = {d["n"]: d["label"] for d in judge(pool, os.environ["GEMINI_API_KEY"].strip())}
    out = {}
    for n, x in enumerate(pool):
        o = out.setdefault(x["system"], {"spans_total": totals[x["system"]], "sampled": 0, "form": 0, "error": 0})
        o["sampled"] += 1
        o[labels.get(n + 1, "error")] += 1
    json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, indent=1))
