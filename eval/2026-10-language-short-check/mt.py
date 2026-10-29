# Translation, one sentence per call, by three systems:
#   sol@low            gpt-5.6-sol on our Foundry deployment, reasoning low
#   gemma-4-31b@or     Gemma 4 31B on OpenRouter, only the named zero-retention hosts the apps use
#   hymt2-7b@or        Hy-MT2 7B on OpenRouter, where it has the language
# The translator shootout's prompt (eval/2026-10-translator-shootout/shootout.py prompt(): it warns
# about recognition errors) for the LLMs; Hy-MT2 its own instruction (server/engines/hymt.py).
#
# Directions per language: X->en from the FLEURS text, en->X from the English text of the same
# FLEURS id, and X->en from the best recogniser's output ("asr": the realistic route). Twi is
# text only (FLORES-200 devtest, first 20 lines; no openly licensed Twi speech was found).
#
#   OPENROUTER_API_KEY=... FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=... python3 -I mt.py WORK
#
# Writes WORK/mt/<system>/<job>.json: {"out": [...], "wall_s": [...], "provider": [...]}.
import concurrent.futures as cf
import json, os, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-translator-shootout"))
import shootout as S  # noqa: E402  (prompt(), NAMES)

WORK = sys.argv[1]
S.NAMES.update({"vi": "Vietnamese", "fa": "Persian", "kea": "Cape Verdean Creole", "zh": "Mandarin Chinese",
                "yue": "Cantonese", "ar": "Arabic", "sw": "Swahili", "fil": "Filipino (Tagalog)",
                "uk": "Ukrainian", "tw": "Twi (Akan)"})
HYMT = {"vi", "fa", "zh", "yue", "ar", "uk", "fil"}
HOSTS = ["deepinfra", "crusoe", "parasail", "coreweave", "sambanova"]   # the apps' OPENROUTER_HOSTS
BEST_ASR = {"vi": "mai", "fa": "mai", "zh": "mai", "yue": "azure", "ar": "mai", "sw": "mai", "fil": "mai", "uk": "mai"}


def post(url, body, headers, tries=6):
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


HYMT_PROMPT = ("Translate the following text into {lang}. Note that you should only output "
               "the translated result without any additional explanation:\n\n{text}")


def openrouter(mid, s, src, tgt):
    content = HYMT_PROMPT.format(lang=S.NAMES[tgt], text=s) if "hy-mt" in mid else S.prompt(s, src, tgt)
    body = {"model": mid, "messages": [{"role": "user", "content": content}], "max_tokens": 2048, "temperature": 0,
            "provider": {"zdr": True, "data_collection": "deny", **({"only": HOSTS} if "gemma" in mid else {}),
                         "allow_fallbacks": True}}
    if "gemma" in mid:
        body["reasoning"] = {"enabled": False}
    j, wall = {}, None
    for _ in range(3):
        j, wall = post("https://openrouter.ai/api/v1/chat/completions", body,
                       {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
        text = ((j.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if text:
            break
        time.sleep(2)
    return {"out": text, "wall_s": wall, "provider": j.get("provider")}


def sol(s, src, tgt):
    url = os.environ["FOUNDRY_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions"
    body = {"model": os.environ["FOUNDRY_DEPLOYMENT"], "messages": [{"role": "user", "content": S.prompt(s, src, tgt)}],
            "reasoning_effort": "low"}
    try:
        j, wall = post(url, body, {"api-key": os.environ["FOUNDRY_KEY"]})
    except urllib.error.HTTPError as e:   # a 400 is usually the content filter: scored as a blank
        return {"out": "", "wall_s": None, "provider": f"foundry HTTP {e.code}: {e.read()[:160].decode(errors='replace')}"}
    return {"out": (j["choices"][0]["message"].get("content") or "").strip(), "wall_s": wall, "provider": "foundry"}


SYSTEMS = {"sol@low": sol,
           "gemma-4-31b@or": lambda s, a, b: openrouter("google/gemma-4-31b-it", s, a, b),
           "hymt2-7b@or": lambda s, a, b: openrouter("tencent/hy-mt2-7b", s, a, b)}


def jobs():
    sentences = json.load(open(os.path.join(WORK, "sentences.json")))
    J = {}
    for lang, rows in sentences.items():
        J[f"{lang}-en"] = (lang, "en", [r["text"] for r in rows], [r["en"] for r in rows])
        J[f"en-{lang}"] = ("en", lang, [r["en"] for r in rows], [r["en"] for r in rows])
        if lang in BEST_ASR:
            hyp = json.load(open(os.path.join(WORK, "asr", f"{BEST_ASR[lang]}_{lang}.json")))
            J[f"{lang}-en-asr"] = (lang, "en", [h["text"] for h in hyp], [r["en"] for r in rows])
    fl = os.path.join(WORK, "flores", "flores200_dataset", "devtest")
    tw = open(os.path.join(fl, "twi_Latn.devtest"), encoding="utf-8").read().splitlines()[:20]
    en = open(os.path.join(fl, "eng_Latn.devtest"), encoding="utf-8").read().splitlines()[:20]
    J["tw-en"] = ("tw", "en", tw, en)
    J["en-tw"] = ("en", "tw", en, en)
    return J


def main():
    J = jobs()
    json.dump({k: {"src": v[0], "tgt": v[1], "source": v[2], "reference": v[3]} for k, v in J.items()},
              open(os.path.join(WORK, "mt_jobs.json"), "w"), ensure_ascii=False, indent=1)
    for name, fn in SYSTEMS.items():
        for k, (src, tgt, source, _) in J.items():
            if name.startswith("hymt") and not ({src, tgt} - {"en"}) <= HYMT:
                continue
            p = os.path.join(WORK, "mt", name, f"{k}.json")
            if os.path.exists(p):
                continue
            empty = {"out": "", "wall_s": None, "provider": None}
            with cf.ThreadPoolExecutor(6) as ex:
                res = list(ex.map(lambda x: fn(x, src, tgt) if x.strip() else empty, source))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            json.dump({key: [r.get(key) for r in res] for key in res[0]}, open(p, "w"), ensure_ascii=False, indent=1)
            print(f"{name:16s} {k}: blanks={sum(1 for x, r in zip(source, res) if x.strip() and not r['out'])}", flush=True)


if __name__ == "__main__":
    main()
