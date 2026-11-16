# The baseline: Azure's per-sentence transcripts (stt_azure.py) translated by the translator Talk's automatic engine
# runs today for the direction (BASELINE, from the server's planner), one call per sentence. Gemma 4 31B on Amazon
# Bedrock (bedrock-mantle, us-east-2, google.gemma-4-31b, temperature 0: production's host and model) and gpt-6-sol
# on Azure AI Foundry (the gpt-6-sol-us deployment, reasoning_effort "low": production's deployment and effort).
# Both get the translator shootout's prompt (../2026-10-translator-shootout/shootout.py prompt(), as
# ../2026-10-es-pt-live-compare/mt.py), not production's prompt with conversation context.
#
#   AWS_PROFILE=lithos-evals FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=gpt-6-sol-us \
#     python3 -I mt.py OUT
#
# Writes OUT/mt/<set>/<src>-<tgt>.json: out, wall_s, tokens. HEAR=soniox (the soniox-hear arm): the same
# translator and prompt on Soniox's own transcripts (soniox_hear.py, OUT/soniox_hear/<set>/<src>-<tgt>.sent.json),
# written to OUT/mt_soniox_hear/<set>/<src>-<tgt>.json. At most 3 calls at a time to each host (both are
# shared with live users); 429s and 5xx are retried with a growing wait. Nothing secret is printed.
import concurrent.futures as cf
import json, os, sys, threading, time
import urllib.error, urllib.request
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-translator-shootout"))
import shootout as S  # noqa: E402  (prompt())

OUT = sys.argv[1]
HEAR = os.environ.get("HEAR", "azure")
# direction -> (route, recogniser, translator): what auto runs today (the brief, from the server's planner).
BASELINE = {
    "en-es": ("hybrid-gemma", "azure", "gemma"), "es-en": ("mai-gemma", "mai", "gemma"),
    "en-pt": ("hybrid-gemma", "azure", "gemma"), "pt-en": ("hybrid-gemma", "azure", "sol"),
    "en-fr": ("hybrid-gemma", "azure", "gemma"), "fr-en": ("mai-gemma", "mai", "gemma"),
    "en-de": ("hybrid-gemma", "azure", "gemma"), "de-en": ("mai-gemma", "mai", "sol"),
    "en-zh": ("hybrid-gemma", "azure", "gemma"), "zh-en": ("mai-gemma", "mai", "gemma"),
    "en-vi": ("hybrid-gemma", "azure", "gemma"), "vi-en": ("mai-gemma", "mai", "gemma"),
    "en-ar": ("hybrid-gemma", "azure", "sol"), "ar-en": ("mai-gemma", "mai", "gemma"),
    "en-fa": ("hybrid-gemma", "azure", "sol"), "fa-en": ("mai-gemma", "mai", "gemma"),
    "en-tl": ("hybrid-gemma", "azure", "gemma"), "tl-en": ("mai-gemma", "mai", "gemma"),
    "en-uk": ("hybrid-gemma", "azure", "sol"), "uk-en": ("mai-gemma", "mai", "sol"),
    "en-ko": ("hybrid-gemma", "azure", "gemma"), "ko-en": ("hybrid-gemma", "azure", "sol"),
    "en-ru": ("hybrid-gemma", "azure", "gemma"), "ru-en": ("hybrid-gemma", "azure", "sol"),
    "en-hi": ("hybrid-gemma", "azure", "gemma"), "hi-en": ("hybrid-gemma", "azure", "sol"),
    "en-it": ("hybrid-gemma", "azure", "gemma"), "it-en": ("hybrid-gemma", "azure", "sol"),
}
S.NAMES.update({"pt": "Portuguese", "vi": "Vietnamese", "ar": "Arabic", "fa": "Persian", "tl": "Filipino",
                "ko": "Korean", "hi": "Hindi", "it": "Italian", "zh": "Chinese (Simplified)"})
BEDROCK_URL = "https://bedrock-mantle.us-east-2.api.aws/openai/v1/chat/completions"
_sess = boto3.Session(region_name="us-east-2")
_lock = threading.Lock()
RETRY = (408, 429, 500, 502, 503, 504)


def post(url, body, headers_fn, tries=10):
    data = json.dumps(body).encode()
    for attempt in range(tries):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, data, headers_fn(data))
            j = json.load(urllib.request.urlopen(req, timeout=120))
            return j, round(time.time() - t0, 3)
        except urllib.error.HTTPError as e:
            if e.code not in RETRY or attempt == tries - 1:
                raise
            if e.code == 429:
                print(f"429 from {url.split('/')[2]}, waiting", flush=True)
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(5 * (attempt + 1))


def bedrock_headers(data):
    with _lock:
        creds = _sess.get_credentials().get_frozen_credentials()
    r = AWSRequest(method="POST", url=BEDROCK_URL, data=data, headers={"Content-Type": "application/json"})
    SigV4Auth(creds, "bedrock-mantle", "us-east-2").add_auth(r)
    return dict(r.headers.items())


def gemma(s, src, tgt):
    body = {"model": "google.gemma-4-31b", "temperature": 0, "messages": [{"role": "user", "content": S.prompt(s, src, tgt)}]}
    for _ in range(3):
        j, wall = post(BEDROCK_URL, body, bedrock_headers)
        text = ((j.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if text:
            break
        time.sleep(2)   # a blank is re-sent
    u = j.get("usage") or {}
    return {"out": text, "wall_s": wall, "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens")}


def sol(s, src, tgt):
    url = os.environ["FOUNDRY_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions"
    body = {"model": os.environ["FOUNDRY_DEPLOYMENT"], "messages": [{"role": "user", "content": S.prompt(s, src, tgt)}],
            "reasoning_effort": "low"}
    key = os.environ["FOUNDRY_KEY"].strip()
    j, wall = post(url, body, lambda _d: {"Content-Type": "application/json", "api-key": key})
    u = j.get("usage") or {}
    return {"out": (j["choices"][0]["message"].get("content") or "").strip(), "wall_s": wall,
            "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
            "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens")}


FN = {"gemma": gemma, "sol": sol}
POOLS = {k: cf.ThreadPoolExecutor(3) for k in FN}   # at most 3 at a time per host


def direction(st, d):
    src, tgt = d.split("-")
    tr = BASELINE[d][2]
    p = os.path.join(OUT, "mt" if HEAR == "azure" else "mt_soniox_hear", st, f"{d}.json")
    if os.path.exists(p):
        return
    inputs = json.load(open(os.path.join(OUT, "stt", st, f"{src}.sent.json") if HEAR == "azure"
                            else os.path.join(OUT, "soniox_hear", st, f"{d}.sent.json")))
    empty = {"out": "", "wall_s": None, "prompt_tokens": None, "completion_tokens": None}
    futs = [POOLS[tr].submit(FN[tr], x, src, tgt) if x.strip() else None for x in inputs]
    res = [f.result() if f else empty for f in futs]
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump({"translator": tr, **{k: [r.get(k) for r in res] for k in ["out", "wall_s", "prompt_tokens", "completion_tokens"]}},
              open(p, "w"), ensure_ascii=False, indent=1)
    print(f"{st} {d} ({tr}): blanks={sum(1 for x, r in zip(inputs, res) if x.strip() and not r['out'])}", flush=True)


if __name__ == "__main__":
    dirs = sys.argv[2:] or list(BASELINE)
    # One thread per (set, direction) feeding the two host pools; each pool caps its host at 3 calls.
    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda a: direction(*a), [(st, d) for st in ["a", "b"] for d in dirs]))
