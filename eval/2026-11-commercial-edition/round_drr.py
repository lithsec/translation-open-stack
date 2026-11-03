# German, Russian, Romanian: the commercial edition's live output graded side by side with the saved
# nonprofit C1 output of ../2026-10-de-ru-ro (same clips: same ids, checked in build_clips.sh), one blind
# call per direction and set, as ../2026-10-de-ru-ro/round_live.py (against the FLEURS texts; its grade.py).
#   python3 -I round_drr.py jobs RES    -> RES/drr_jobs.json
#   python3 -I round_drr.py table RES   (after ../2026-10-de-ru-ro/grade.py RES/drr_jobs.json RES/drr_grades.json)
#                                       -> RES/drr_results.json
import json, os, sys
from pathlib import Path

mode, R = sys.argv[1], Path(sys.argv[2])
OLD = Path(__file__).parent / ".." / "2026-10-de-ru-ro" / "results"
sys.path.insert(0, str(Path(__file__).parent / ".." / "2026-10-real-voices"))
from judge import cer  # noqa: E402
D6 = ["en-de", "de-en", "en-ru", "ru-en", "en-ro", "ro-en"]
SYS = {"C1": lambda st: OLD / f"e2e_C1_{st}_reg" / "out", "commercial": lambda st: R / f"e2e_C_drr_{st}" / "out"}


def text(st, lang):
    return json.load(open(R / "drr" / f"clips_{st}_reg" / f"{lang}.txt.json"))


def load(sysn, st, f):
    return json.load(open(SYS[sysn](st) / f))


if mode == "jobs":
    jobs = []
    for d in D6:
        s, t = d.split("-")
        for st in "ab":
            jobs.append({"id": f"{d}:{st}", "src": s, "tgt": t, "source": text(st, s), "reference": text(st, t),
                         "systems": {k: load(k, st, "sentences.json")[d]["live_out"] for k in SYS}})
    json.dump(jobs, open(R / "drr_jobs.json", "w"), ensure_ascii=False, indent=1)
    print(len(jobs), "jobs")
else:
    G = json.load(open(R / "drr_grades.json"))
    J = {j["id"]: j for j in json.load(open(R / "drr_jobs.json"))}
    res = {}
    for k, g in G.items():
        d, st = k.split(":")
        n = len(J[k]["source"])
        for sysn, items in g["grades"].items():
            sc = sum(max(0, min(3, int(x.get("score", 0)))) for x in items[:n])
            r = res.setdefault(d, {}).setdefault(st, {}).setdefault(sysn, {})
            r["quality"] = {"q": round(100 * sc / (3 * n), 1), "crit": sum(1 for x in items[:n] if x.get("critical")), "n": n}
    for d in D6:
        s = d.split("-")[0]
        for st in "ab":
            for sysn in SYS:
                L = load(sysn, st, "latency.json")[d]
                S = load(sysn, st, "sentences.json")[d]
                gold = text(st, s)
                r = res.setdefault(d, {}).setdefault(st, {}).setdefault(sysn, {})
                r.update({"cer": round(cer(" ".join(gold), " ".join(S["heard_per_sentence"])), 4), "cer_analyzer": L.get("cer"),
                          "missing_audio": L.get("missing_audio"), "utterances": L.get("utterances"),
                          "stop_to_first_audio_ms": L.get("stop_to_first_audio_ms"),
                          "stop_to_tail_audio_ms": L.get("stop_to_tail_audio_ms"),
                          "dropped_utterances": (L.get("stage") or {}).get("dropped_utterances"),
                          })
            a, b = load("C1", st, "sentences.json")[d]["live_out"], load("commercial", st, "sentences.json")[d]["live_out"]
            res[d][st]["commercial"]["sentences_differing_from_C1"] = sum(1 for x, y in zip(a, b) if x.strip() != y.strip())
        for sysn in SYS:
            q = [res[d][st][sysn]["quality"] for st in "ab"]
            res[d].setdefault("both", {})[sysn] = {"q": round(sum(x["q"] for x in q) / 2, 1), "crit": sum(x["crit"] for x in q)}
    json.dump(res, open(R / "drr_results.json", "w"), ensure_ascii=False, indent=1)
    for d in D6:
        print(d, {k: res[d]["both"][k] for k in SYS},
              {k: [(res[d][st][k]["stop_to_first_audio_ms"] or {}).get("p50") for st in "ab"] for k in SYS})
