# The English reference for the Haitian Creole clip: the CMU texts have no translations, so gemini-flash-latest
# writes one per sentence (temperature 0), as ../2026-10-real-voices/make_refs.py did with a Pro model. The
# references are model-made, so ht->en scores rank the arms against each other, not against a human translation.
# Kept beside the clips (not in this folder: the CMU texts are not published here).
#   GEMINI_API_KEY=... python3 -I make_refs.py CLIPS_DIR
import json, os, sys, time, urllib.request

CL = sys.argv[1]
texts = json.load(open(os.path.join(CL, "ht.txt.json")))
p = ("Translate each of these Haitian Creole sentences into natural, accurate English, one by one. Keep numbers, "
     "names and negation exact. Answer JSON: a list of " + str(len(texts)) + " strings, in order.\n"
     + json.dumps(texts, ensure_ascii=False))
body = {"contents": [{"role": "user", "parts": [{"text": p}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
for k in range(5):
    try:
        req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent",
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
        j = json.load(urllib.request.urlopen(req, timeout=300))
        out = json.loads("".join(x.get("text", "") for x in j["candidates"][0]["content"]["parts"] if not x.get("thought")))
        assert len(out) == len(texts)
        break
    except Exception as e:
        print("retry", e)
        time.sleep(5 * (k + 1))
for pat in ("clips_reg", "clips_irr"):
    json.dump(out, open(os.path.join(os.path.dirname(CL.rstrip("/")), pat, "ht.ref_en.json"), "w"), ensure_ascii=False, indent=1)
print(len(out), "references")
