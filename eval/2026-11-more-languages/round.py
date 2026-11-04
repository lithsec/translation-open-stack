# Grading jobs and the table. A system's output per sentence is live_out of analyze_e2e.py's sentences.json;
# graded against the FLEURS texts (../2026-10-de-ru-ro's method: the English FLEURS text is the reference
# meaning), one blind call per direction and set, with A and B side by side where B ran (the seven Hy-MT2-only
# languages: A = Hy-MT2, B = Gemma 4).
#   python3 -I round.py jobs WORK     -> WORK/grade_jobs.json
#   python3 -I round.py table WORK    -> ./results.json (+ printed)
import json, statistics, sys
from pathlib import Path

mode, W = sys.argv[1], Path(sys.argv[2])
GEMMA7 = ["zh", "uk", "vi", "ar", "fa", "tl", "sw"]
HYMT7 = ["it", "ko", "id", "tr", "bn", "ur", "hi"]
DIRS = [d for l in GEMMA7 + HYMT7 for d in (f"en-{l}", f"{l}-en")]


def text(st, lang):
    return json.load(open(W / f"clips_{st}" / f"{lang}.txt.json"))


def sent(tag, st, d):
    p = W / f"e2e_{tag}_{st}" / "out" / "sentences.json"
    return json.load(open(p)).get(d) if p.exists() else None


def lat(tag, st, d):
    p = W / f"e2e_{tag}_{st}" / "out" / "latency.json"
    return json.load(open(p)).get(d) if p.exists() else None


def systems(d, st):
    out = {}
    for tag in ("A", "B"):
        s = sent(tag, st, d)
        if s:
            out[tag] = s["live_out"]
    return out


if mode == "jobs":
    jobs = []
    for d in DIRS:
        s, t = d.split("-")
        for st in "ab":
            sy = systems(d, st)
            if sy:
                jobs.append({"id": f"{d}:{st}", "src": s, "tgt": t, "source": text(st, s), "reference": text(st, "en"),
                             "systems": sy})
    json.dump(jobs, open(W / "grade_jobs.json", "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs")
else:
    J = {j["id"]: j for j in json.load(open(W / "grade_jobs.json"))}
    G = json.load(open(W / "grades.json"))
    res = {}
    for d in DIRS:
        for tag in ("A", "B"):
            per, crit, pts, tot = {}, 0, 0, 0
            for st in "ab":
                k = f"{d}:{st}"
                if k not in G or tag not in G[k]["grades"]:
                    continue
                n = len(J[k]["source"])
                items = G[k]["grades"][tag][:n]
                p = sum(max(0, min(3, int(x.get("score", 0)))) for x in items)
                per[st] = round(100 * p / (3 * n), 1)
                crit += sum(1 for x in items if x.get("critical"))
                pts, tot = pts + p, tot + 3 * n
            if not per:
                continue
            L = {st: lat(tag, st, d) for st in "ab"}
            L = {st: v for st, v in L.items() if v}
            r = {"score": round(100 * pts / tot, 1), "per_set": per, "critical": crit, "sentences": tot // 3}
            if L:
                r["cer"] = round(statistics.mean(v["cer"] for v in L.values() if v["cer"] is not None), 3)
                r["first_audio_p50_ms"] = {st: v["stop_to_first_audio_ms"]["p50"] for st, v in L.items()}
                r["last_audio_p50_ms"] = {st: v["stop_to_tail_audio_ms"]["p50"] for st, v in L.items()}
                r["last_audio_p90_ms"] = {st: v["stop_to_tail_audio_ms"]["p90"] for st, v in L.items()}
                r["missing_audio"] = sum(v["missing_audio"] for v in L.values())
                r["dropped"] = sum(v.get("dropped_utterances", 0) for v in L.values())
            res.setdefault(d, {})[tag] = r
    json.dump({"grader": "gemini-pro-latest, blind, A and B side by side, one call per direction and set",
               "systems": {"A": "the stack as configured (languages.toml)", "B": "it ko id tr bn ur hi on Gemma 4 (configs/B.toml)"},
               "results": res}, open(Path(__file__).parent / "results.json", "w"), ensure_ascii=False, indent=1)
    for d, v in res.items():
        print(d, {k: (x["score"], x["critical"], x.get("cer"), x.get("last_audio_p50_ms")) for k, x in v.items()})
