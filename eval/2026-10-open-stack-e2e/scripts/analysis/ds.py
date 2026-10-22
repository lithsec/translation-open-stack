# DeepSeek V4 via OpenRouter on experiment B's inputs, with b_client.py's exact prompts (direct, ctx).
#   OPENROUTER_API_KEY=... python3 -I ds.py <model> <mode> <inputs.json> <out.json>
# reasoning {"enabled": false}, temperature 0. Latency = API round trip from the Mac (not GPU time).
import concurrent.futures as cf, json, os, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "..", "gpu", "b_client.py")).read()
src = src.replace('KEY = open("/root/apikey").read().strip()', 'KEY = None').split("def call(")[0]
ns = {}
exec(compile(src, "b_client_prompts", "exec"), ns)
URL = "https://openrouter.ai/api/v1/chat/completions"


def call(model, messages, n):
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": min(1024, 64 + 4 * n),
            "reasoning": {"enabled": False}, "usage": {"include": True}}
    data = json.dumps(body).encode()
    for attempt in range(6):
        req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json",
                                                               "Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]})
        t = time.time()
        try:
            j = json.load(urllib.request.urlopen(req, timeout=120))
            m = j["choices"][0]["message"]
            return (m.get("content") or "").strip(), round(time.time() - t, 3), j.get("usage", {}), bool(m.get("reasoning")), j.get("provider")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 5:
                raise
        except (urllib.error.URLError, TimeoutError, KeyError):
            if attempt == 5:
                raise
        time.sleep(4 * (attempt + 1))


def run_direction(model, mode, d):
    outs, secs, usage, reasoned, prov = [], [], [], 0, set()
    before, said = [], ""
    for i, x in enumerate(d["inputs"]):
        if not x.strip():
            outs.append(""); secs.append(None); usage.append({}); continue
        m = ns["direct_prompt"](x, d["src"], d["tgt"]) if mode == "direct" else ns["lt_messages"](x, d["src"], d["tgt"], before[-2:], said)
        out, s, u, r, p = call(model, m, len(x))
        outs.append(out); secs.append(s); usage.append(u); reasoned += r; prov.add(p)
        before.append(x); said = out
    return d["id"], {"out": outs, "wall_s": secs, "usage": usage, "reasoning_returned": reasoned, "providers": sorted(map(str, prov))}


model, mode, inp, out = sys.argv[1:5]
D = json.load(open(inp))
t = time.time()
with cf.ThreadPoolExecutor(8) as ex:
    res = dict(ex.map(lambda d: run_direction(model, mode, d), D))
json.dump({"model": model, "mode": mode, "total_s": round(time.time() - t, 1), "res": res}, open(out, "w"), ensure_ascii=False, indent=1)
u = [x for v in res.values() for x in v["usage"] if x]
print(model, mode, "done", round(time.time() - t), "s; completion tokens", sum(x.get("completion_tokens", 0) for x in u),
      "reasoning tokens", sum((x.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0 for x in u), flush=True)
