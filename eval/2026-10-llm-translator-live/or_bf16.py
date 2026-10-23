# The live run's exact translator inputs, sent again to Gemma 4 31B in bf16 on OpenRouter.
# Inputs: each utterance the stack heard (its "input" event) and the 4-bit translation it spoke ("text").
# The stack didn't log llmmt's requests, so they are rebuilt with llmmt.py itself: split_sentences(heard),
# then llmmt.request("chat", ...) per sentence, joined with join_sentences (no context: llmmt takes none).
#   OPENROUTER_API_KEY=... python3 or_bf16.py <run.json> <out run.json> <out log.json>
import concurrent.futures as cf, copy, json, os, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.environ.get("SERVER_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "server")))
from engines.common import split_sentences, join_sentences  # noqa: E402
from engines import llmmt  # noqa: E402

MODEL = "google/gemma-4-31b-it"
run = json.load(open(sys.argv[1]))
src, tgt = run["src"], run["tgt"]


def call(sentence):
    path, body = llmmt.request("chat", MODEL, sentence, src, tgt)
    body = dict(body)
    body.pop("chat_template_kwargs", None)
    body.update(provider={"zdr": True, "data_collection": "deny", "quantizations": ["bf16"], "allow_fallbacks": True},
                reasoning={"enabled": False})
    for attempt in range(6):
        try:
            req = urllib.request.Request("https://openrouter.ai/api/v1" + path, data=json.dumps(body).encode(),
                                         headers={"content-type": "application/json",
                                                  "authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]})
            r = json.load(urllib.request.urlopen(req, timeout=120))
            out = llmmt.answer("chat", r)
            if out:
                return {"sentence": sentence, "prompt": body["messages"][0]["content"], "out": out,
                        "provider": r.get("provider"), "model": r.get("model")}
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
            err = str(e)
        time.sleep(3 * (attempt + 1))
    return {"sentence": sentence, "out": "", "provider": None, "error": err if 'err' in dir() else "empty"}


ev = run["events"]
jobs = []
for k, e in enumerate(ev):
    if e.get("kind") == "input":
        nxt = next((x for x in ev[k + 1:] if x.get("kind") in ("text", "input")), None)
        out4 = nxt["text"] if nxt and nxt.get("kind") == "text" else ""
        jobs.append((k, e["text"], out4))
log = []
new = copy.deepcopy(run)
with cf.ThreadPoolExecutor(8) as ex:
    for k, heard, out4 in jobs:
        sents = split_sentences(heard)
        got = list(ex.map(call, sents))
        bf = join_sentences([g["out"] for g in got], tgt)
        log.append({"heard": heard, "out_4bit": out4, "out_bf16": bf, "requests": got})
        nxt = next((i for i in range(k + 1, len(ev)) if ev[i].get("kind") in ("text", "input")), None)
        if nxt is not None and ev[nxt].get("kind") == "text":
            new["events"][nxt]["text"] = bf
json.dump(new, open(sys.argv[2], "w"), ensure_ascii=False)
json.dump(log, open(sys.argv[3], "w"), ensure_ascii=False, indent=1)
prov = {}
for u in log:
    for g in u["requests"]:
        prov[g.get("provider")] = prov.get(g.get("provider"), 0) + 1
print(sys.argv[1].split("/")[-1], len(log), "utterances, providers", prov,
      "identical", sum(1 for u in log if u["out_4bit"].strip() == u["out_bf16"].strip()))
