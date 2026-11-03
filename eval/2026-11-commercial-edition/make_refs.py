# The references round.py needs that aren't in the repository:
#   set a: out/witness/<lang>.json and out/said_en.json, rebuilt from ../2026-10-unseen/results.json
#          (as ../2026-10-open-streaming/make_refs.py, for all eight languages)
#   set b: out/said_en.json from witness.py's out/witness/en.json (what was said, flagged sentences only)
#   both:  out/meaning_ht.json, the English the Haitian Creole sentences are graded against: REGENERATED here
#          with ../2026-10-real-voices/make_refs.py's prompt on gemini-pro-latest (the earlier rounds' files
#          are not in the repository), so ht->en is graded against a model-made reference that differs from
#          the one the full-stack round used.
#   GEMINI_API_KEY=... python3 -I make_refs.py <results dir>
import json, os, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
R = sys.argv[1]
u = json.load(open(os.path.join(HERE, "..", "2026-10-unseen", "results.json")))
A = os.path.join(R, "seta", "out"); os.makedirs(os.path.join(A, "witness"), exist_ok=True)
for lang, w in u["witness"].items():
    rows = [{"i": i, "cut_off": i in w["cut_off"], "meaning_differs": i in w["meaning_differs"]} for i in range(20)]
    json.dump(rows, open(os.path.join(A, "witness", f"{lang}.json"), "w"), indent=1)
json.dump(u["english_said"], open(os.path.join(A, "said_en.json"), "w"), ensure_ascii=False, indent=1)
B = os.path.join(R, "setb", "out")
wb = json.load(open(os.path.join(B, "witness", "en.json")))
assert not any("error" in r for r in wb), "set b English witness has errors"
json.dump({str(r["i"]): r["said"] for r in wb if r.get("cut_off") or r.get("meaning_differs")},
          open(os.path.join(B, "said_en.json"), "w"), ensure_ascii=False, indent=1)


def gemini(prompt):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    for k in range(6):
        try:
            req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-latest:generateContent",
                                         data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
            j = json.load(urllib.request.urlopen(req, timeout=300))
            return json.loads("".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"] if not x.get("thought")))
        except Exception as e:
            err = e; time.sleep(10 * (k + 1))
    raise err


for st in ["seta", "setb"]:
    out = os.path.join(R, st, "out", "meaning_ht.json")
    if os.path.exists(out):
        continue
    src = json.load(open(os.path.join(R, st, "clips_reg", "ht.txt.json")))
    res = gemini("Translate each of these Haitian Creole sentences into accurate, natural English. They are read aloud "
                 "from novels, newspapers, the Bible and literacy primers. Keep every number, name and negation exact; "
                 f"do not explain. Return JSON: a list of exactly {len(src)} strings in the same order.\n\n"
                 + json.dumps(src, ensure_ascii=False))
    assert isinstance(res, list) and len(res) == len(src), (type(res), len(res))
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)
    print("wrote", out)
