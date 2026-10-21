#!/usr/bin/env python3
"""Extract the numbers the research site needs from result files that also
carry free text (grader notes, transcripts), into site/data/derived.json.

    python3 site/extract_derived.py      # rewrite site/data/derived.json

Why a separate step: site/check_private.sh scans every file site/build.py
reads, because text from them can end up on a page. These result files hold
long grader notes and transcripts the site never shows; build.py reads only
the scores and delays copied here (numbers and direction names, no text).
Rerun this after any of SOURCES changes, then rebuild the site.

Standard library only (Python 3.11+).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "data", "derived.json")

SOURCES = {
    "sept_e2e": "eval/2026-09-model-eval/results/round3_real_server_vs_gemini.json",
    "sept_text": "eval/2026-09-model-eval/results/round4_translators_incl_nllb.json",
    "oct_cloud": "eval/2026-10-azure-stt-gemini/results.json",
}


def J(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def graded(items):
    """[points, maximum, critical sentences] from a list of per-sentence grades."""
    return [sum(int(x["score"]) for x in items), 3 * len(items), sum(1 for x in items if x.get("critical"))]


def main():
    out = {
        "generated_by": "site/extract_derived.py",
        "sources": SOURCES,
        "note": "Per direction and system: [points, maximum points, sentences flagged critical], "
                "summed from the per-sentence grades (0-3) in the source file; delays copied as given. "
                "Grader notes and transcripts are left out.",
    }
    e2e = J(SOURCES["sept_e2e"])
    out["sept_e2e"] = {d: {s: graded(v) for s, v in systems.items()} for d, systems in e2e.items()}
    txt = J(SOURCES["sept_text"])
    out["sept_text"] = {d: {s: graded(v) for s, v in systems.items()} for d, systems in txt.items()}
    cloud = J(SOURCES["oct_cloud"])
    keep = ("azure_only", "azure_stt_gemini", "gladia_stt_gemini", "gemini_live")
    out["oct_cloud"] = {}
    for d, systems in cloud.items():
        row = {}
        for s in keep:
            x = systems.get(s)
            if not isinstance(x, dict) or x.get("score_pct") is None:
                continue
            row[s] = {"score_pct": x["score_pct"], "critical": x.get("critical"),
                      "delay_ms_median": (x.get("delay") or {}).get("per_sentence_median_ms")}
        out["oct_cloud"][d] = row
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
