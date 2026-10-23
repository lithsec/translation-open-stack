# System (e): the branch's live English pieces (system b, exactly as it cut them) re-translated by
# Hy-MT2-30B-A3B on OpenRouter, with the stack's Hy-MT2 prompt, sentence by sentence as the stack
# does (split_sentences / join_sentences), no context (the e2e client never asks for it), temperature 0.
# Zero data retention requested per request. OpenRouter-hosted: its latency is not a stack figure.
#   OPENROUTER_API_KEY=... python3 -I e_mt.py <pieces.json> <out.json>
import concurrent.futures as cf, json, os, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "server"))   # the branch under test
from engines.common import split_sentences, join_sentences  # the branch's (abbreviations kept whole)
NAMES = {"es": "Spanish", "fr": "French", "ja": "Japanese", "km": "Khmer", "pt": "Portuguese"}
INSTRUCTION = ("Translate the following text into {lang}. Note that you should only output "
               "the translated result without any additional explanation:\n\n{text}")
P = json.load(open(sys.argv[1]))


def call(text, lang):
    body = {"model": "tencent/hy-mt2-30b-a3b", "temperature": 0, "max_tokens": 1024,
            "messages": [{"role": "user", "content": INSTRUCTION.format(lang=NAMES[lang], text=text)}],
            "provider": {"zdr": True}}
    for k in range(6):
        t0 = time.time()
        try:
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]})
            j = json.load(urllib.request.urlopen(req, timeout=120))
            c = (j["choices"][0]["message"].get("content") or "").strip()
            if not c and k < 3:      # an empty answer now and then: ask again (an empty one stays empty)
                raise KeyError("empty")
            return c, j.get("provider"), round(time.time() - t0, 3), j.get("usage", {})
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError) as e:
            err = e
            time.sleep(3 * (k + 1))
    raise SystemExit(f"failed: {err}")


def one(p):
    sents = [s for s in split_sentences(p["src"]) if s.strip()] if p["src"].strip() else []
    outs, provs, lat = [], set(), []
    for s in sents:
        t, prov, sec, _ = call(s, p["tgt"])
        outs.append(t); provs.add(prov); lat.append(sec)
    return {**p, "hy7b": p["hy"], "hy": join_sentences(outs, p["tgt"]) if outs else "", "providers": sorted(x for x in provs if x), "lat_s": lat}


with cf.ThreadPoolExecutor(6) as ex:
    res = list(ex.map(one, P))
json.dump(res, open(sys.argv[2], "w"), ensure_ascii=False, indent=0)
lats = sorted(x for r in res for x in r["lat_s"])
print(len(res), "pieces", len(lats), "requests; providers", sorted({x for r in res for x in r["providers"]}),
      "latency p50", lats[len(lats) // 2] if lats else None, "p90", lats[int(len(lats) * 0.9)] if lats else None)
