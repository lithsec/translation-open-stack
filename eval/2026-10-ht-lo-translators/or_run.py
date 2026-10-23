# The open LLMs that OpenRouter hosts, over out/inputs.json, with zero data retention
# enforced on every request ("provider": {"zdr": true}) and the precision pinned where the
# hosts offer a choice. The provider that served each sentence is recorded. Timings here are
# OpenRouter round trips from a Mac in the US, NOT our GPU's latency (pod_run.py measures that).
#   OPENROUTER_API_KEY=... python3 or_run.py [name ...]
import concurrent.futures as cf
import json, os, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
NAMES = {"en": "English", "ht": "Haitian Creole", "lo": "Lao"}
MODELS = {  # name -> (OpenRouter id, provider preferences, extra body)
    "qwen3.5-122b-a10b@or": ("qwen/qwen3.5-122b-a10b", {"quantizations": ["bf16"]},
                             {"temperature": 0, "reasoning": {"enabled": False}}),
    "gemma-4-31b-it@or": ("google/gemma-4-31b-it", {"quantizations": ["bf16"]},
                          {"temperature": 0, "reasoning": {"enabled": False}}),
    # gpt-oss ships in MXFP4; round 2's settings: the card's sampling, reasoning effort low.
    "gpt-oss-120b@low@or": ("openai/gpt-oss-120b", {"quantizations": ["fp4"]},
                            {"temperature": 1.0, "top_p": 1.0, "reasoning": {"effort": "low"}}),
}


def prompt(s, src, tgt):  # the same prompt as htlo.py (sol) and pod_run.py
    a, b = NAMES[src], NAMES[tgt]
    return (f"Translate this {a} sentence into natural {b}. Keep numbers, names and negation exact. "
            f"Output only the {b}.\nSentence: {s}")


def call(name, s, src, tgt):
    mid, prov, extra = MODELS[name]
    body = {"model": mid, "messages": [{"role": "user", "content": prompt(s, src, tgt)}], "max_tokens": 4096,
            "provider": {"zdr": True, "allow_fallbacks": True, **prov}, **extra}
    for attempt in range(6):
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                                              "Content-Type": "application/json"})
        t0 = time.time()
        try:
            j = json.load(urllib.request.urlopen(req, timeout=180))
            if "choices" not in j:
                raise ValueError(str(j.get("error"))[:200])
            c = j["choices"][0]["message"]
            return ((c.get("content") or "").strip(), round(time.time() - t0, 3), j.get("provider"),
                    (j.get("usage") or {}).get("completion_tokens"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as e:
            code = getattr(e, "code", None)
            if code in (400, 401, 403) or attempt == 5:
                print(f"{name}: {code} {str(e)[:200]}", flush=True)
                return "", None, None, None
            time.sleep(4 * (attempt + 1))


def run(name):
    D = json.load(open(os.path.join(OUT, "inputs.json")))
    os.makedirs(os.path.join(OUT, "mt", name), exist_ok=True)
    for k, v in D.items():
        p = os.path.join(OUT, "mt", name, k.replace(":", "_") + ".json")
        if os.path.exists(p):
            continue
        with cf.ThreadPoolExecutor(8) as ex:
            r = list(ex.map(lambda s: call(name, s, v["src"], v["tgt"]), v["source"]))
        json.dump({"out": [x[0] for x in r], "or_round_trip_s": [x[1] for x in r], "provider": [x[2] for x in r],
                   "completion_tokens": [x[3] for x in r], "quantization": MODELS[name][1].get("quantizations")},
                  open(p, "w"), ensure_ascii=False, indent=1)
        print(name, k, sum(1 for x in r if not x[0]), "blank", flush=True)


def fill(name):
    """Retry the sentences that came back blank (rate limits), two at a time."""
    D = json.load(open(os.path.join(OUT, "inputs.json")))
    for k, v in D.items():
        p = os.path.join(OUT, "mt", name, k.replace(":", "_") + ".json")
        r = json.load(open(p))
        todo = [i for i, o in enumerate(r["out"]) if not o]
        with cf.ThreadPoolExecutor(2) as ex:
            res = list(ex.map(lambda i: call(name, v["source"][i], v["src"], v["tgt"]), todo))
        for i, x in zip(todo, res):
            r["out"][i], r["or_round_trip_s"][i], r["provider"][i], r["completion_tokens"][i] = x
        json.dump(r, open(p, "w"), ensure_ascii=False, indent=1)
        if todo:
            print(name, k, len(todo), "retried,", sum(1 for x in res if not x[0]), "still blank", flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["fill"]:
        for n in sys.argv[2:] or list(MODELS):
            fill(n)
        sys.exit()
    names = sys.argv[1:] or list(MODELS)
    with cf.ThreadPoolExecutor(len(names)) as ex:
        list(ex.map(run, names))
