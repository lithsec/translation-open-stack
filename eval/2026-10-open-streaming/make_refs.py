# The references analyze_open.py needs, rebuilt from ../2026-10-unseen/results.json (its
# witness flags and the English "what was said" of the flagged sentences), since the
# unseen run's working folder is not in the repository:
#   UO/witness/<lang>.json  [{"i", "cut_off", "meaning_differs"}]   (en, es, fr)
#   UO/said_en.json         {"i": what was said}  (flagged English sentences only; the
#                           others are taken as read, the written text)
#   python3 -I make_refs.py UO
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
UO = sys.argv[1]
r = json.load(open(os.path.join(HERE, "..", "2026-10-unseen", "results.json")))
os.makedirs(os.path.join(UO, "witness"), exist_ok=True)
for lang in ["en", "es", "fr"]:
    w = r["witness"][lang]
    rows = [{"i": i, "cut_off": i in w["cut_off"], "meaning_differs": i in w["meaning_differs"]} for i in range(20)]
    json.dump(rows, open(os.path.join(UO, "witness", f"{lang}.json"), "w"), indent=1)
json.dump(r["english_said"], open(os.path.join(UO, "said_en.json"), "w"), ensure_ascii=False, indent=1)
print("wrote", UO)
