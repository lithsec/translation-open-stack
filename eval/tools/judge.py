#!/usr/bin/env python3
"""Grade a live translation 0-3 per reference sentence with a Gemini model, and
the character error rate of the recogniser's transcript.

    python3 judge.py --pair "Spanish -> English" --refs ref_en.json --output out.txt [--out judge.json]
                     [--model gemini-2.5-pro] [--prompt prompts/judge.txt]
                     [--src-ref ref_src.txt --src-hyp src.txt]

The judge reads the whole live output (lag.py --text writes it) and the
numbered reference sentences and grades each one 0-3 (3 correct and natural,
2 minor errors, 1 major meaning errors or mostly missing, 0 wrong or missing),
flagging a critical error (a wrong number, name, date or negation, or reversed
meaning). Temperature 0. The prompt is prompts/judge.txt with {PAIR},
{REFERENCE} and {OUTPUT} filled in; edit it or pass your own.

References: a JSON {"sentences": [{"id": int, "text": ...}]} (or "en"), a JSON
list of strings, or a text file with one sentence per line. Make them from the
clip with prompts/reference.txt and prompts/translate.txt, or from captions;
model-made references are approximate, so the scores rank runs against each
other rather than measuring them absolutely.

The model runs on Vertex AI: GOOGLE_CLOUD_PROJECT (or VERTEX_PROJECT) names the
project and the token comes from `gcloud auth print-access-token`, as in
eval/README.md. With GEMINI_API_KEY set instead, the Gemini API is used. Both
only from the environment; nothing is written but the grades.

--src-ref/--src-hyp: CER of the recogniser's transcript (lag.py --source-text)
against a reference transcript, after NFKC, lowercasing and dropping
punctuation. Standard library only.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROMPT = os.path.join(HERE, "prompts", "judge.txt")


def load_refs(path):
    text = open(path, encoding="utf-8").read()
    if path.endswith(".json"):
        d = json.loads(text)
        if isinstance(d, dict):
            d = d["sentences"]
        out = []
        for i, s in enumerate(d):
            if isinstance(s, dict):
                out.append((s.get("id", i), s.get("text") or s.get("en") or s.get("ref") or ""))
            else:
                out.append((i, str(s)))
        return out
    return [(i, line.strip()) for i, line in enumerate(text.splitlines()) if line.strip()]


def build_prompt(template, pair, refs, output):
    ref_block = "\n".join(f"{i}: {t}" for i, t in refs)
    return template.replace("{PAIR}", pair).replace("{REFERENCE}", ref_block).replace("{OUTPUT}", output)


def call_gemini(prompt, model, max_tokens=32000):
    """Vertex AI when a project is set, else the Gemini API; JSON output, temperature 0."""
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens,
                                 "responseMimeType": "application/json"}}
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("VERTEX_PROJECT")
    if project:
        url = (f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global"
               f"/publishers/google/models/{model}:generateContent")
        tok = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
        headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    elif os.environ.get("GEMINI_API_KEY"):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"], "Content-Type": "application/json"}
    else:
        raise SystemExit("set GOOGLE_CLOUD_PROJECT (Vertex AI, token from gcloud) or GEMINI_API_KEY")
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    for attempt in range(8):           # 429/503 under load: back off rather than fail the run
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                j = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == 7:
                raise
            time.sleep(15 * (attempt + 1))
    parts = j["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return json.loads(text), j.get("usageMetadata", {})


def summarise(grades, n_refs):
    scores = grades.get("scores", [])
    total = sum(int(s.get("score", 0)) for s in scores)
    return {
        "sentences": n_refs,
        "graded": len(scores),
        "mean_0_3": round(total / max(1, len(scores)), 2),
        "quality_pct": round(100 * total / (3 * max(1, len(scores)))),
        "critical": sum(1 for s in scores if s.get("critical")),
        "zero": sum(1 for s in scores if int(s.get("score", 0)) == 0),
        "hallucination": str(grades.get("hallucination", ""))[:200],
        "overall": str(grades.get("overall", ""))[:200],
    }


def norm_text(s):
    s = unicodedata.normalize("NFKC", s).lower()
    s = "".join(c for c in s if not unicodedata.category(c).startswith("P"))
    return " ".join(s.split())


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for k, cb in enumerate(b, 1):
            cur.append(min(prev[k] + 1, cur[k - 1] + 1, prev[k - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref, hyp):
    r, h = "".join(norm_text(ref).split()), "".join(norm_text(hyp).split())
    return round(edit_distance(r, h) / max(1, len(r)), 3)


def main(argv=None):
    ap = argparse.ArgumentParser(description="grade a live translation against reference sentences")
    ap.add_argument("--pair", required=True, help='e.g. "Haitian Creole -> English"')
    ap.add_argument("--refs", required=True, help="reference sentences (JSON or one per line)")
    ap.add_argument("--output", required=True, help="the live translation as one text (lag.py --text)")
    ap.add_argument("--model", default="gemini-2.5-pro")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT, help="prompt template")
    ap.add_argument("--out", help="write the grades and summary here")
    ap.add_argument("--src-ref", help="reference transcript of the source speech (text)")
    ap.add_argument("--src-hyp", help="the recogniser's transcript (lag.py --source-text)")
    args = ap.parse_args(argv)

    refs = load_refs(args.refs)
    output = open(args.output, encoding="utf-8").read().strip()
    prompt = build_prompt(open(args.prompt, encoding="utf-8").read(), args.pair, refs, output)
    grades, usage = call_gemini(prompt, args.model)
    res = {"model": args.model, "summary": summarise(grades, len(refs)), "usage": usage, "grades": grades}
    if args.src_ref and args.src_hyp:
        res["cer"] = cer(open(args.src_ref, encoding="utf-8").read(), open(args.src_hyp, encoding="utf-8").read())
    print(json.dumps({k: v for k, v in res.items() if k != "grades"}, indent=1, ensure_ascii=False))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1, ensure_ascii=False)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
