# Native renderings of the 24 English test sentences in each new language (Gemini 2.5 Pro), with a script check:
# a Ukrainian set once came back in broken English and silently skewed a round, so every sentence is verified.
import json, re, sys, unicodedata
sys.path.insert(0, "scripts")
from vertex import gemini
EN = json.load(open("sentences/en.json"))
NAMES = {"ar": "Arabic (Modern Standard, as said in church or at a clinic)", "hi": "Hindi", "vi": "Vietnamese", "ko": "Korean",
         "tl": "Tagalog (Filipino)", "fa": "Persian (Farsi, Iran)", "id": "Indonesian", "tr": "Turkish", "bn": "Bengali",
         "ur": "Urdu, written in Urdu script (Perso-Arabic Nastaliq letters), never romanised", "it": "Italian", "sw": "Swahili"}
SCRIPT = {"ar": "ARABIC", "fa": "ARABIC", "ur": "ARABIC", "hi": "DEVANAGARI", "bn": "BENGALI", "ko": "HANGUL"}
def script_ok(L, s):
    letters = [c for c in s if c.isalpha()]
    if not letters: return False
    if L in SCRIPT:
        return sum(SCRIPT[L] in unicodedata.name(c, "") for c in letters) / len(letters) > 0.8
    return sum("LATIN" in unicodedata.name(c, "") for c in letters) / len(letters) > 0.9
import os
for L, name in NAMES.items():
    if os.path.exists(f"sentences/src_{L}.json") and L not in ("it",): continue
    prompt = (f"Translate each of these 24 English sentences into natural, everyday spoken {name}, the way a native "
              f"speaker would say it aloud. Keep every number, time, dose and name exact. Write numbers as words where a "
              f"speaker would say them. Return JSON: a list of exactly 24 strings in the same order.\n\n{json.dumps(EN, ensure_ascii=False)}")
    out = gemini(prompt)
    assert isinstance(out, list) and len(out) == 24, (L, type(out), len(out))
    bad = [i for i, s in enumerate(out) if not script_ok(L, s)]
    same = [i for i, s in enumerate(out) if len(set(s.lower().split()) & set(EN[i].lower().split())) > 0.5 * len(s.split())]
    print(L, "script-bad:", bad, "english-like:", same, "|", out[2][:70], flush=True)
    json.dump(out, open(f"sentences/src_{L}.json", "w"), ensure_ascii=False, indent=1)
