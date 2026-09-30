import json, random, concurrent.futures as cf
from vertex import gemini
LANGS = ["es","fr","de","pt","ru","uk","zh","ja","km","ht"]
NAMES = {"en":"English","es":"Spanish","fr":"French","de":"German","pt":"Portuguese","ru":"Russian","uk":"Ukrainian","zh":"Chinese","ja":"Japanese","km":"Khmer","ht":"Haitian Creole"}
EN = json.load(open("en.json"))
SYS = {m: json.load(open(f"pod/{m}.json"))["out"] for m in ["madlad3b","madlad7b","hymt7b","nllb3b"]}
def gem(d):
    try: return json.load(open(f"gem/{d}.json"))["said"]
    except Exception: return None
def judge(direction):
    src, tgt = direction.split("-")
    source = EN if src == "en" else json.load(open(f"src_{src}.json"))
    systems = {m: SYS[m][direction] for m in SYS}
    labels = list(systems); random.Random(direction).shuffle(labels)
    names = {chr(65 + i): m for i, m in enumerate(labels)}
    blocks = []
    for L, m in names.items():
        o = systems[m]
        blocks.append(f"### System {L}\n" + (json.dumps(o, ensure_ascii=False) if isinstance(o, list)
                      else "(one continuous transcript of a spoken interpretation; align it to the 24 sentences yourself; a sentence it does not render scores 0)\n" + o))
    prompt = f"""You are an expert {NAMES[src]}->{NAMES[tgt]} translation evaluator. Grade each system's translation of each of the 24 source sentences.
The intended meaning of every sentence is given by its English original (reference meaning), which is authoritative.

Score each sentence per system:
3 = meaning fully correct and natural; 2 = meaning correct but awkward or unidiomatic; 1 = partly wrong, or something important omitted or added; 0 = wrong meaning, wrong language, garbled, or missing.
Also set critical=true when a number, time, date, dose, amount, negation, or who-did-what is wrong (even if the rest is fine).

Source sentences ({NAMES[src]}):
{json.dumps(source, ensure_ascii=False)}

Reference meaning (English originals):
{json.dumps(EN, ensure_ascii=False)}

Translations into {NAMES[tgt]}:
{chr(10).join(blocks)}

Return JSON: {{"A": [{{"i": 0, "score": 3, "critical": false, "note": "..."}}, ... 24 items], "B": [...], ...}} with a short note only when score < 3 or critical."""
    import os
    cache = f"jcache_nllb/{direction}.json"
    if os.path.exists(cache): return direction, json.load(open(cache))
    for attempt in range(3):
        try: res = gemini(prompt); break
        except Exception:
            if attempt == 2: raise
    r = {names[L]: v for L, v in res.items() if L in names}
    json.dump(r, open(cache, "w"), ensure_ascii=False)
    return direction, r
dirs = [f"en-{l}" for l in LANGS] + [f"{l}-en" for l in LANGS if l != "uk"]
out = {}
with cf.ThreadPoolExecutor(6) as ex:
    for d, r in ex.map(judge, dirs):
        out[d] = r; print(d, {m: sum(x["score"] for x in v) for m, v in r.items()}, flush=True)
json.dump(out, open("judged_nllb.json", "w"), ensure_ascii=False, indent=1)
