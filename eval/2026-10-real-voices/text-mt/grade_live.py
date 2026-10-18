# Grades the Gemini Live voice outputs (live_voice_ht.mjs) with translate_ht.py's
# own blind grader: its prompt and its system list are taken from that file at
# run time, so the live systems are graded side by side with every other
# translator of the same input, exactly as a KEEP_GRADES=1 run would. Only the
# new rows (<input>__live:<model>) are added to the grades file, re-read just
# before writing; the whole run (every system's re-grade, per-sentence notes)
# goes to out/live-grade-run-<grader>.json to show the grader's drift.
#
#   GEMINI_API_KEY=... EVAL_BACKEND=aistudio python3 text-mt/grade_live.py <model> [<model> ...]
#   GOOGLE_CLOUD_PROJECT=... python3 text-mt/grade_live.py <model> ...   (Gemini 2.5 Pro grader, grades.json)
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "translate_ht.py")).read()
MODELS = sys.argv[1:]
g = {"__file__": os.path.join(HERE, "translate_ht.py"), "__name__": "translate_ht"}
exec(SRC[:SRC.index('if os.environ.get("INPUTS")')], g)
OUT = g["OUT"]
g["inputs"] = {k: v for k, v in g["inputs"].items() if k in (os.environ.get("INPUTS") or "omnilingual,gold").split(",")
               and all(os.path.exists(os.path.join(OUT, f"{k}__live_{m}.json")) for m in MODELS)}
for m in MODELS:
    g["TRANSLATORS"][f"live:{m}"] = None
block = SRC[SRC.index("# Blind grade"):SRC.index("gp = os.path.join")]
old = 'os.path.join(OUT, f"{inp}__{n}.json")'
assert old in block, "translate_ht.py's grading block changed: update grade_live.py"
block = block.replace(old, 'os.path.join(OUT, f"{inp}__{n.replace(\'live:\', \'live_\')}.json")')
block = block.replace("    for L, m in names.items():\n        g = ", "    RAW[inp] = {m: res.get(L) for L, m in names.items()}\n    for L, m in names.items():\n        g = ")
assert "RAW[inp]" in block
g["RAW"] = {}
exec(block, g)
GRADER, results = g["GRADER"], g["results"]
gp = os.path.join(OUT, "grades.json" if GRADER == "gemini-2.5-pro" else f"grades-{GRADER}.json")
json.dump({"grader": GRADER, "results": results, "per_sentence": g["RAW"]},
          open(os.path.join(OUT, f"live-grade-run-{GRADER}.json"), "w"), indent=1, ensure_ascii=False)
mine = {k: v for k, v in results.items() if "__live:" in k}
kept = json.load(open(gp)) if os.path.exists(gp) else {}  # re-read right before writing
kept.update(mine)
json.dump(kept, open(gp, "w"), indent=1)
print("grader:", GRADER, "->", os.path.basename(gp))
for k, v in sorted(results.items()):
    print(f"{k:60s} fully correct {v['fully_correct']:.0%}  mean {v['mean_score']:.1%}  critical {v['critical']}{'   (added)' if k in mine else ''}")
