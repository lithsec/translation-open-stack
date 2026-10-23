"""CER of endpoint_sweep.py runs (omni-stt's own AudioIn + Silero + Segmenter path) on the Khmer clips.

    python3 ep_score.py OUT.json <set>:<sweep.json> [...]
set is rv or unseen; references from assets (written; and what was said for unseen).
Also reported without segments over 30 characters per second of audio (the repetition guard).
"""
import json
import sys
from pathlib import Path

from eval_km import A, norm_full, norm_judge, edits


def score(refs, hyps, f):
    a, b = f(" ".join(refs)), f(" ".join(hyps))
    return round(100 * edits(a, b) / max(len(a), 1), 2)


res = {}
for spec in sys.argv[2:]:
    name, path = spec.split(":", 1)
    d = json.load(open(path))
    written = json.load(open(A / name / "km.txt.json"))
    said = [r["said"] for r in json.load(open(A / name / "km.said.json"))] if (A / name / "km.said.json").exists() else None
    for run in d["runs"]:
        segs = run["segments"]
        hyps = [s["text"] for s in segs]
        guard = [s["text"] for s in segs if len(s["text"]) <= 30 * max((s["end_ms"] - s["start_ms"]) / 1000, 0.1)]
        r = {"segments": len(segs), "forced": sum(s.get("forced", False) for s in segs),
             "written_judge": score(written, hyps, norm_judge), "written_full": score(written, hyps, norm_full),
             "written_full_guard": score(written, guard, norm_full)}
        if said:
            r["said_judge"] = score(said, hyps, norm_judge)
            r["said_full"] = score(said, hyps, norm_full)
            r["said_full_guard"] = score(said, guard, norm_full)
        key = f"{d['card']}|{name}|{run['endpoint_ms']}:{run['max_s']}"
        res[key] = r
        print(key, r, flush=True)
Path(sys.argv[1]).write_text(json.dumps(res, ensure_ascii=False, indent=1))
