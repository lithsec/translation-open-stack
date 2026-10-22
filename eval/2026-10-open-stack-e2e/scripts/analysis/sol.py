# GPT-5.6-sol @low on Azure AI Foundry, the shootout/e2e prompt, one call per sentence.
#   FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... python3 -I sol.py variants.json out.json [only_keys_regex]
import concurrent.futures as cf, json, os, re, sys, time, urllib.error, urllib.request

NAMES = {"en": "English", "fr": "French", "es": "Spanish", "ja": "Japanese", "km": "Khmer", "lo": "Lao", "ht": "Haitian Creole"}
URL = os.environ["FOUNDRY_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions"


def one(x, s, t):
    if not x.strip():
        return "", {}
    p = (f"Translate this {NAMES[s]} sentence, transcribed from live speech (it may contain recognition errors), "
         f"into natural {NAMES[t]}. Keep numbers, names and negation exact. Output only the {NAMES[t]}.\nSentence: {x}")
    body = json.dumps({"model": os.environ.get("FOUNDRY_DEPLOYMENT", "gpt-5.6-sol"), "messages": [{"role": "user", "content": p}],
                       "reasoning_effort": "low"}).encode()
    for attempt in range(6):
        req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json", "api-key": os.environ["FOUNDRY_KEY"]})
        try:
            j = json.load(urllib.request.urlopen(req, timeout=120))
            return (j["choices"][0]["message"]["content"] or "").strip(), j.get("usage", {})
        except urllib.error.HTTPError as e:
            if e.code == 400:
                return "", {"refused": True}
            if e.code not in (429, 500, 502, 503, 504) or attempt == 5:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 5:
                raise
        time.sleep(5 * (attempt + 1))


V = json.load(open(sys.argv[1]))
out = sys.argv[2]
R = json.load(open(out)) if os.path.exists(out) else {}
pat = re.compile(sys.argv[3]) if len(sys.argv) > 3 else None
for k, v in V.items():
    if k in R or (pat and not pat.search(k)):
        continue
    with cf.ThreadPoolExecutor(4) as ex:
        rs = list(ex.map(lambda x: one(x, v["lang"], v.get("tgt", "en")), v["texts"]))
    R[k] = {"out": [r[0] for r in rs], "usage": [r[1] for r in rs]}
    json.dump(R, open(out, "w"), ensure_ascii=False, indent=1)
    print("sol", k, flush=True)
