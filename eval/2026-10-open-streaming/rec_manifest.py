# The manifest for ../2026-10-whisper-vs-azure/score.py over the open recognisers' finals,
# and WORK/tts.json (the phrase eval's measured Azure voice, from its results.json).
# "said": English uses the unseen run's witness text for the flagged sentences (the
# written text for the others); Spanish and French "said" falls back to the written
# text (their witness transcripts are not in the repository), so only "text" compares
# with the cloud rows there.
#   python3 -I rec_manifest.py CLIPS_ROOT UO WORK
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT, UO, WORK = sys.argv[1:4]
said_en = json.load(open(os.path.join(UO, "said_en.json")))
json.dump([{"i": int(k), "said": v} for k, v in said_en.items()], open(os.path.join(UO, "witness_said_en.json"), "w"), ensure_ascii=False)
json.dump([], open(os.path.join(UO, "witness_said_none.json"), "w"))
refs = {l: {"said": os.path.join(UO, "witness_said_en.json" if l == "en" else "witness_said_none.json"),
            "text": os.path.join(ROOT, "clips_reg", f"{l}.txt.json")} for l in ["en", "es", "fr"]}
runs = []
for rec in os.environ.get("RECS", "simul,ctc,nemo").split(","):
    for p in ["reg", "irr"]:
        for l in ["en", "es", "fr"]:
            path = os.path.join(WORK, "rec", f"{rec}_{p}_{l}.json")
            if os.path.exists(path):
                runs.append({"lang": l, "pattern": p, "system": rec, "kind": "finals", "path": path})
json.dump({"refs": refs, "runs": runs}, open(os.path.join(WORK, "rec_manifest.json"), "w"), indent=1)
ph = json.load(open(os.path.join(HERE, "..", "2026-10-simultaneous-phrases", "results.json")))
json.dump(ph["tts"], open(os.path.join(WORK, "tts.json"), "w"), indent=1)
print(len(runs), "runs")
