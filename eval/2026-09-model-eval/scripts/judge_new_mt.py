# Grade the stack's translations for the 12 new languages (Gemini 2.5 Pro, same rubric as the earlier rounds).
import json, sys, concurrent.futures as cf
from vertex import gemini
D = sys.argv[1]
EN = json.load(open("../sentences/en.json"))
NAMES = {"en": "English", "ar": "Arabic", "hi": "Hindi", "vi": "Vietnamese", "ko": "Korean", "tl": "Tagalog", "fa": "Persian",
         "id": "Indonesian", "tr": "Turkish", "bn": "Bengali", "ur": "Urdu", "it": "Italian", "sw": "Swahili"}
MT = json.load(open(f"{D}/new_mt.json"))["out"]
def judge(direction):
    src, tgt = direction.split("-")
    source = EN if src == "en" else json.load(open(f"../sentences/src_{src}.json"))
    prompt = f"""You are an expert {NAMES[src]}->{NAMES[tgt]} translation evaluator. Grade the translation of each of the 24 source sentences.
The English originals give the authoritative intended meaning.
Score: 3 = meaning fully correct and natural; 2 = correct but awkward; 1 = partly wrong or something important omitted/added; 0 = wrong, wrong language, garbled or missing.
critical=true when a number, time, date, dose, amount, negation or who-did-what is wrong.
Source ({NAMES[src]}): {json.dumps(source, ensure_ascii=False)}
English originals: {json.dumps(EN, ensure_ascii=False)}
Translations ({NAMES[tgt]}): {json.dumps(MT[direction], ensure_ascii=False)}
Return JSON: [{{"i": 0, "score": 3, "critical": false, "note": ""}}, ... 24 items], a short note only when score < 3 or critical."""
    r = gemini(prompt)
    return direction, {"pct": round(100 * sum(x["score"] for x in r) / (3 * len(r))), "critical": sum(bool(x.get("critical")) for x in r),
                       "notes": [f'{x["i"]}: {x.get("note", "")}' for x in r if x.get("critical") or x["score"] < 2]}
with cf.ThreadPoolExecutor(3) as ex: res = dict(ex.map(judge, sorted(MT)))
json.dump(res, open(f"{D}/new_mt_judged.json", "w"), ensure_ascii=False, indent=1)
for d, r in sorted(res.items()): print(f"{d:6} {r['pct']:3}%  critical {r['critical']}")
