# Azure's per-sentence transcripts (stt_azure.py) translated by three systems,
# one call per sentence as a live pipeline would make them. Gemma 4 and sol get
# the translator shootout's prompt (it warns about recognition errors); Hy-MT2,
# a translation model, gets its own instruction, as the stack and the shootout
# gave it (server/engines/hymt.py).
#
#   OPENROUTER_API_KEY=... FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=... \
#     python3 -I mt.py OUT
#
# Writes OUT/mt/<system>/<src>-<tgt>.json: out, wall_s, provider, tokens.
import concurrent.futures as cf
import json, os, sys, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-translator-shootout"))
import shootout as S  # noqa: E402  (prompt())

OUT = sys.argv[1]
DIRS = ["en-es", "en-pt", "en-fr", "en-ja", "en-km", "en-lo", "en-ht", "es-en", "pt-en"]
OR = {"hymt2-7b@or": "tencent/hy-mt2-7b", "gemma-4-31b-it@or": "google/gemma-4-31b-it"}
NO = {"hymt2-7b@or": {"lo", "ht"}}   # Hy-MT2 has no Lao or Haitian Creole
S.NAMES.setdefault("pt", "Portuguese")


def post(url, body, headers, tries=8):
    data = json.dumps(body).encode()
    for attempt in range(tries):
        t0 = time.time()
        try:
            j = json.load(urllib.request.urlopen(urllib.request.Request(url, data, {"Content-Type": "application/json", **headers}), timeout=120))
            return j, round(time.time() - t0, 3)
        except urllib.error.HTTPError as e:
            if e.code not in (408, 429, 500, 502, 503, 504) or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(4 * (attempt + 1))


HYMT = ("Translate the following text into {lang}. Note that you should only output "
        "the translated result without any additional explanation:\n\n{text}")


def openrouter(mid, s, src, tgt):
    content = HYMT.format(lang=S.NAMES[tgt], text=s) if "hy-mt" in mid else S.prompt(s, src, tgt)
    body = {"model": mid, "messages": [{"role": "user", "content": content}], "max_tokens": 2048,
            "temperature": 0, "usage": {"include": True},
            "provider": {"zdr": True, "quantizations": ["bf16", "fp8"], "allow_fallbacks": True}}
    if "gemma" in mid:
        body["reasoning"] = {"enabled": False}
    for _ in range(4):
        j, wall = post("https://openrouter.ai/api/v1/chat/completions", body,
                       {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
        text = ((j.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if text:
            break
        time.sleep(2)   # a blank is re-sent
    u = j.get("usage") or {}
    return {"out": text, "wall_s": wall, "provider": j.get("provider"),
            "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens")}


def sol(s, src, tgt):
    url = os.environ["FOUNDRY_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions"
    body = {"model": os.environ["FOUNDRY_DEPLOYMENT"], "messages": [{"role": "user", "content": S.prompt(s, src, tgt)}],
            "reasoning_effort": "low"}
    j, wall = post(url, body, {"api-key": os.environ["FOUNDRY_KEY"]})
    u = j.get("usage") or {}
    return {"out": (j["choices"][0]["message"].get("content") or "").strip(), "wall_s": wall, "provider": "foundry",
            "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
            "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens")}


SYSTEMS = {**{k: (lambda mid: lambda s, a, b: openrouter(mid, s, a, b))(v) for k, v in OR.items()}, "sol@low": sol}

for name, fn in SYSTEMS.items():
    for d in DIRS:
        src, tgt = d.split("-")
        if tgt in NO.get(name, ()):
            continue
        p = os.path.join(OUT, "mt", name, f"{d}.json")
        if os.path.exists(p):
            continue
        inputs = json.load(open(os.path.join(OUT, "stt", f"{src}.sent.json")))
        empty = {"out": "", "wall_s": None, "provider": None, "prompt_tokens": None, "completion_tokens": None}
        with cf.ThreadPoolExecutor(6) as ex:
            res = list(ex.map(lambda x: fn(x, src, tgt) if x.strip() else empty, inputs))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump({k: [r.get(k) for r in res] for k in res[0]}, open(p, "w"), ensure_ascii=False, indent=1)
        print(f"{name:20s} {d}: blanks={sum(1 for x, r in zip(inputs, res) if x.strip() and not r['out'])}", flush=True)
