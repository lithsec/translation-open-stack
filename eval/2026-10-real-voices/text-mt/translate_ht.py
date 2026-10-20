# Haitian Creole -> English with TEXT translators, on two inputs:
#   gladia: Gladia's live transcript of the real speakers, regrouped into the
#           30 read sentences by where each piece fell in the clip (so the
#           translator sees whole sentences, not Gladia's 97 fragments);
#   gold:   the text the speakers actually read (the translator's ceiling).
# Graded blind with the same grader and prompt as judge.py.
#
#   GOOGLE_CLOUD_PROJECT=... python3 text-mt/translate_ht.py
#   GEMINI_API_KEY=... EVAL_BACKEND=aistudio python3 text-mt/translate_ht.py
#     (no gcloud: Gemini through AI Studio. Gemini 2.5 Pro is closed to new
#     AI Studio keys, so the grader is GRADER, default gemini-3.1-pro-preview,
#     and its grades go to grades-<grader>.json: compare within one run only.
#     Translators needing Google Cloud must already be in out/.)
#   INPUTS=omnilingual,gold limits which transcripts are translated and graded.
#   KEEP_GRADES=1 adds new systems' rows to the grades file and leaves the rest.
#   kreyol-mt runs locally: use the eval's .venv (torch, transformers,
#   sentencepiece, protobuf).
#   OPEN_MT_POD=<pod id> OPEN_MT_KEY=... [HF_TOKEN=...] adds the open-weight
#   translators served by text-mt/open_mt_pod.py on a GPU pod (see there).
# NOTE: the English references were written by Gemini 2.5 Pro, so Gemini
# translators may be flattered; the grade says so.
import json, os, random, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "..", "2026-09-model-eval", "scripts"))
import vertex  # noqa: E402
import urllib.error


AISTUDIO = os.environ.get("EVAL_BACKEND") == "aistudio"
GRADER = os.environ.get("GRADER") or ("gemini-3.1-pro-preview" if AISTUDIO else "gemini-2.5-pro")


def aistudio(prompt, model="gemini-2.5-pro", json_out=True, thinking=None):
    import time
    import urllib.request
    gen = {"temperature": 0, "maxOutputTokens": 32000, **({"responseMimeType": "application/json"} if json_out else {}),
           **({"thinkingConfig": {"thinkingLevel": thinking}} if thinking else {})}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen}).encode(),
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"], "Content-Type": "application/json"})
    for attempt in range(8):
        try:
            j = json.load(urllib.request.urlopen(req, timeout=600)); break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 503) or attempt == 7: raise
            time.sleep(10 * (attempt + 1))
        except TimeoutError:
            # The grader once sat past 300 s on a long side-by-side: ask again.
            if attempt == 7: raise
            time.sleep(5)
    t = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought"))
    return json.loads(t) if json_out else t


def gemini(*a, thinking=None, **k):
    # gcloud tokens last an hour and vertex.py keeps the first one: refresh on 401.
    # An answer with no content (Gemini declined, e.g. Chirp's 7,000-character
    # looped "sentence") counts as a blank translation.
    if AISTUDIO:
        try:
            return aistudio(*a, thinking=thinking, **k)
        except KeyError:
            return ""
    if thinking:
        raise SystemExit("thinking levels need EVAL_BACKEND=aistudio")
    try:
        return vertex.gemini(*a, **k)
    except KeyError:
        return ""
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        vertex._tok = None
        return vertex.gemini(*a, **k)
OUT = os.path.join(HERE, "text-mt", "out")
os.makedirs(OUT, exist_ok=True)

src = json.load(open(os.path.join(HERE, "sentences", "ht.json")))
ref = json.load(open(os.path.join(HERE, "sentences", "meaning_ht.json")))
marks = json.load(open(os.path.join(HERE, "audio", "ht.json")))["sentences"]
finals = json.load(open(os.path.join(HERE, "out", "stt-gladia", "ht.json")))["finals"]
groups = [[] for _ in marks]
for f in finals:
    mid = (f["offsetMs"] + f["durationMs"] / 2) / 1000
    k = min(range(len(marks)), key=lambda i: 0 if marks[i]["start"] <= mid <= marks[i]["end"] else min(abs(mid - marks[i]["start"]), abs(mid - marks[i]["end"])))
    groups[k].append(f["text"])
gladia = [" ".join(g) for g in groups]


def split_like(text, sents):
    """A transcript with no sentence breaks (the stack's), cut where the read
    sentences end: align it to the read text character by character and map
    each sentence's end across. Fair while the transcript is close (6% CER)."""
    import difflib
    gold = " ".join(sents)
    sm = difflib.SequenceMatcher(None, gold, text, autojunk=False)
    ends, pos = [], 0
    for s_ in sents:
        pos += len(s_)
        ends.append(pos)
        pos += 1
    def across(i):
        for a, b, n in sm.get_matching_blocks():
            if a <= i <= a + n:
                return b + (i - a)
            if a > i:
                return b
        return len(text)
    cuts = [0] + [across(e) for e in ends]
    cuts[-1] = len(text)
    return [text[cuts[k]:cuts[k + 1]].strip() for k in range(len(sents))]


omni = split_like(json.load(open(os.path.join(HERE, "out", "stack", "ht-en.json")))["heard"], src)
# Only transcripts good enough to be worth translating (the user's call,
# 2026-10-17): Gladia (19% CER, words wrong) and Gemini Live (49%, heard as
# French) are left out.
inputs = {"gold": src, "omnilingual": omni}
_pro = os.path.join(OUT, "stt__gemini-2.5-pro.json")
if os.path.exists(_pro):
    inputs["gemini-2.5-pro-stt"] = json.load(open(_pro))
_chirp = os.path.join(OUT, "stt__chirp_3.json")
if os.path.exists(_chirp):
    inputs["chirp3"] = json.load(open(_chirp))


def gem(model, sents, context, thinking=None):
    """One call per sentence, as a live pipeline would; with context, the two
    sentences before it are shown (already spoken) to resolve pronouns etc."""
    import concurrent.futures as cf

    def one(i):
        s = sents[i]
        prev = " ".join(sents[max(0, i - 2):i]) if context else ""
        p = ("Translate this Haitian Creole sentence, transcribed from live speech (it may contain recognition errors), "
             "into natural English. Keep numbers, names and negation exact. Output only the English.\n"
             + (f"Earlier sentences, for context only (do not translate): {prev}\n" if prev else "")
             + f"Sentence: {s}")
        return gemini(p, model=model, json_out=False, thinking=thinking).strip() if s.strip() else ""
    with cf.ThreadPoolExecutor(6) as ex:
        return list(ex.map(one, range(len(sents))))


def google_nmt(sents):
    """Cloud Translation v3, the standard model (its LLM model refuses ht->en)."""
    import urllib.request
    url = f"https://translation.googleapis.com/v3/projects/{vertex.project()}/locations/us-central1:translateText"
    body = {"contents": [s or "-" for s in sents], "sourceLanguageCode": "ht", "targetLanguageCode": "en",
            "model": f"projects/{vertex.project()}/locations/us-central1/models/general/nmt"}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {vertex.token()}", "Content-Type": "application/json", "x-goog-user-project": vertex.project()})
    out = [t["translatedText"] for t in json.load(urllib.request.urlopen(req, timeout=120))["translations"]]
    return [o if s.strip() else "" for o, s in zip(out, sents)]


def azure_translator(sents):
    """Azure Translator (text; Microsoft documents it as 'No Trace', not confirmed
    for our resource), key and region
    from AZURE_TRANSLATOR_KEY1 / AZURE_TRANSLATOR_REGION (default eastus)."""
    import urllib.request
    key = os.environ["AZURE_TRANSLATOR_KEY1"]
    region = os.environ.get("AZURE_TRANSLATOR_REGION", "eastus")
    req = urllib.request.Request(
        "https://api.cognitive.microsofttranslator.com/translate?api-version=3.0&from=ht&to=en",
        data=json.dumps([{"Text": s or "-"} for s in sents]).encode(),
        headers={"Ocp-Apim-Subscription-Key": key, "Ocp-Apim-Subscription-Region": region, "Content-Type": "application/json"})
    out = [r["translations"][0]["text"] for r in json.load(urllib.request.urlopen(req, timeout=120))]
    return [o if s.strip() else "" for o, s in zip(out, sents)]


def kreyol_mt(sents, batch=4):
    """JHU's Kreyol-MT (jhu-clsp/kreyol-mt: mBART-50 fine-tuned on Creole data,
    MIT, open weights), run locally on CPU in float32. Input "sentence </s> SRC",
    output starts with the target token; the model card maps Haitian (hat) to
    mBART's ko_KR and English to en_XX. Beam 4 as on the card, but max_length
    256 rather than its 60 so long sentences are not cut. Needs torch,
    transformers and sentencepiece (the eval's .venv has them)."""
    import time
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    global _kmt
    if "_kmt" not in globals():  # load once for all inputs
        _kmt = (AutoTokenizer.from_pretrained("jhu-clsp/kreyol-mt", do_lower_case=False, use_fast=False, keep_accents=True),
                AutoModelForSeq2SeqLM.from_pretrained("jhu-clsp/kreyol-mt", dtype=torch.float32).eval())
    tok, model = _kmt
    tgt = tok.convert_tokens_to_ids("en_XX")
    out, t0 = [], time.time()
    for i in range(0, len(sents), batch):
        chunk = sents[i:i + batch]
        enc = tok([f"{s.strip() or '-'} </s> ko_KR" for s in chunk], add_special_tokens=False, return_tensors="pt", padding=True)
        with torch.inference_mode():
            gen = model.generate(**enc, num_beams=4, max_length=256, min_length=1, early_stopping=True,
                                 pad_token_id=tok.pad_token_id, bos_token_id=tok.bos_token_id,
                                 eos_token_id=tok.eos_token_id, decoder_start_token_id=tgt)
        out += [tok.decode(g, skip_special_tokens=True, clean_up_tokenization_spaces=False).strip() for g in gen]
    print(f"kreyol-mt: {len(sents)} sentences in {time.time() - t0:.0f} s on CPU", flush=True)
    return [o if s.strip() else "" for o, s in zip(out, sents)]


def openai_chat(model, sents, effort=None, foundry=False):
    """OpenAI, one call per sentence with gem()'s prompt (OPENAI_API_KEY).
    foundry: the same call to an Azure AI Foundry deployment of that name
    (FOUNDRY_ENDPOINT, FOUNDRY_KEY), Microsoft-hosted under Azure's terms.
    Per-sentence timing goes beside the output as <name>.timing.json."""
    import concurrent.futures as cf
    import time
    import urllib.request
    times = [0.0] * len(sents)

    def one(i):
        s = sents[i]
        if not s.strip():
            return ""
        p = ("Translate this Haitian Creole sentence, transcribed from live speech (it may contain recognition errors), "
             "into natural English. Keep numbers, names and negation exact. Output only the English.\n"
             f"Sentence: {s}")
        body = {"model": model, "messages": [{"role": "user", "content": p}],
                **({"reasoning_effort": effort} if effort else {"temperature": 0})}
        if foundry:
            req = urllib.request.Request(os.environ["FOUNDRY_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions",
                data=json.dumps(body).encode(), headers={"api-key": os.environ["FOUNDRY_KEY"], "Content-Type": "application/json"})
        else:
            req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"})
        for attempt in range(6):
            try:
                t0 = time.time()
                j = json.load(urllib.request.urlopen(req, timeout=120))
                times[i] = round(time.time() - t0, 2)
                return j["choices"][0]["message"]["content"].strip()
            except urllib.error.HTTPError as e:
                if e.code == 400 and foundry:
                    # Azure refused the sentence (e.g. its content filter on a
                    # Bible verse): a blank translation, said in the log.
                    print(f"{model} #{i} refused: {e.read().decode(errors='replace')[:200]}", flush=True)
                    return ""
                if e.code not in (429, 500, 503) or attempt == 5:
                    raise
                time.sleep(5 * (attempt + 1))
    with cf.ThreadPoolExecutor(3 if foundry else 6) as ex:
        out = list(ex.map(one, range(len(sents))))
    LAST["times"] = times
    return out


LAST = {}  # per-sentence seconds of the last timed translator, saved as <name>.timing.json


def open_mt(kind, sents, model=None):
    """Open-weight translators on our own GPU: a RunPod pod running
    text-mt/open_mt_pod.py (image vllm/vllm-openai, env API_KEY), reached at
    https://<OPEN_MT_POD>-8000/-8001.proxy.runpod.net with OPEN_MT_KEY.
    kind "nllb" is NLLB-200 on :8000; the rest go to vLLM on :8001, which the
    pod switches to `model` first (HF_TOKEN, if set, is posted to the pod for
    gated weights and never written to its env). One sentence at a time, so
    the timing is single-stream latency as a live pipeline would see it (it
    includes the proxy round trip from here)."""
    import time
    import urllib.request
    pod, key = os.environ["OPEN_MT_POD"], os.environ["OPEN_MT_KEY"]
    ctl, llm = f"https://{pod}-8000.proxy.runpod.net", f"https://{pod}-8001.proxy.runpod.net"

    def call(url, body=None):
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                              "User-Agent": "ht-mt-eval"})  # the proxy 403s urllib's default
        return json.load(urllib.request.urlopen(req, timeout=300))
    if kind == "nllb" and call(ctl)["vllm_alive"]:
        call(ctl + "/stop", {})  # one GPU: NLLB needs the memory vLLM holds
    if kind != "nllb" and call(ctl).get("model") != model:
        if os.environ.get("HF_TOKEN"):
            call(ctl + "/token", {"hf_token": os.environ["HF_TOKEN"]})
        call(ctl + "/serve", {"model": model, "args": ["--max-model-len", "4096", "--gpu-memory-utilization", "0.9"]})
        t0 = time.time()
        while True:  # download + load: minutes for a 27-31B model
            time.sleep(20)
            st = call(ctl)
            if not st["vllm_alive"]:
                raise SystemExit(f"vLLM died loading {model}:\n{st['log'][-3000:]}")
            try:
                call(llm + "/v1/models"); break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                print(f"waiting for {model} ({time.time() - t0:.0f} s)", flush=True)
    out, times = [], []
    for s in sents:
        if not s.strip():
            out.append(""); times.append(0.0); continue
        p = ("Translate this Haitian Creole sentence, transcribed from live speech (it may contain recognition errors), "
             "into natural English. Keep numbers, names and negation exact. Output only the English.\n"
             f"Sentence: {s}")
        t0 = time.time()
        if kind == "nllb":
            t = call(ctl + "/nllb", {"text": s})["text"]
        elif kind == "translategemma":
            # Its own chat template (the model card's), rendered by hand: vLLM's
            # chat endpoint drops the source/target codes the template needs.
            # No <bos>: the completions endpoint adds it.
            tp = ("<start_of_turn>user\nYou are a professional Haitian (ht) to English (en) translator. Your goal is to "
                  "accurately convey the meaning and nuances of the original Haitian text while adhering to English grammar, "
                  "vocabulary, and cultural sensitivities.\nProduce only the English translation, without any additional "
                  "explanations or commentary. Please translate the following Haitian text into English:\n\n\n"
                  f"{s.strip()}<end_of_turn>\n<start_of_turn>model\n")
            t = call(llm + "/v1/completions", {"model": model, "prompt": tp, "temperature": 0, "max_tokens": 400})["choices"][0]["text"]
        else:
            # Thinking off where the template has it (Qwen): a live pipeline can't wait.
            t = call(llm + "/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content": p}],
                     "temperature": 0, "max_tokens": 400, "chat_template_kwargs": {"enable_thinking": False}})["choices"][0]["message"]["content"]
        times.append(round(time.time() - t0, 2))
        out.append(t.strip())
    LAST["times"] = times
    return out


TRANSLATORS = {
    "google-translate": google_nmt,
    # Graded wherever its output is already in out/; only translating needs the key.
    "azure-translator": azure_translator,
    "kreyol-mt": kreyol_mt,
    "gemini-2.5-flash": lambda s: gem("gemini-2.5-flash", s, False),
    "gemini-2.5-flash+ctx": lambda s: gem("gemini-2.5-flash", s, True),
    "gemini-3.5-flash": lambda s: gem("gemini-3.5-flash", s, False),
    "gemini-3.5-flash-lite": lambda s: gem("gemini-3.5-flash-lite", s, False),
    # Thinking "low", as the app runs them (AI Studio only).
    **({f"{m}@low": (lambda m: lambda s: gem(m, s, False, "low"))(m)
        for m in ("gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash")} if AISTUDIO else {}),
    **({"gemini-3.5-flash@medium": lambda s: gem("gemini-3.5-flash", s, False, "medium")} if AISTUDIO else {}),
    # OpenAI (2026-10-19): the flagship at low reasoning, a fast mini, and a
    # non-reasoning model.
    "gpt-5.5@low": lambda s: openai_chat("gpt-5.5", s, "low"),
    "gpt-5.4-mini@low": lambda s: openai_chat("gpt-5.4-mini", s, "low"),
    "gpt-4.1": lambda s: openai_chat("gpt-4.1", s),
    # Azure AI Foundry deployments (FOUNDRY_KEY set; 2026-10-19): a more
    # private host for the same kind of model. DeepSeek and Mistral are held
    # to 20 requests or 20k tokens a minute by quota; the retries absorb it.
    **({"foundry-gpt-5.6-sol@low": lambda s: openai_chat("gpt-5.6-sol", s, "low", foundry=True),
        "foundry-gpt-5.6-luna@low": lambda s: openai_chat("gpt-5.6-luna", s, "low", foundry=True),
        "foundry-deepseek-v4.1-flash": lambda s: openai_chat("DeepSeek-V4.1-Flash", s, foundry=True),
        "foundry-mistral-large-3": lambda s: openai_chat("Mistral-Large-3", s, foundry=True)} if os.environ.get("FOUNDRY_KEY") else {}),
    # Open weights on our own GPU (OPEN_MT_POD set): could the Haitian route
    # stay self-hosted end to end? NLLB-200 is CC-BY-NC-4.0 (fine for the
    # non-profit use), TranslateGemma is under the Gemma terms (gated on HF),
    # Gemma 4 31B is Apache-2.0.
    **({"nllb-200-3.3b": lambda s: open_mt("nllb", s),
        "translategemma-27b": lambda s: open_mt("translategemma", s, "google/translategemma-27b-it"),
        "gemma-4-31b": lambda s: open_mt("chat", s, "google/gemma-4-31B-it")} if os.environ.get("OPEN_MT_POD") else {}),
}
if os.environ.get("INPUTS"):
    inputs = {k: v for k, v in inputs.items() if k in os.environ["INPUTS"].split(",")}

for inp, sents in inputs.items():
    for name, fn in TRANSLATORS.items():
        p = os.path.join(OUT, f"{inp}__{name}.json")
        if not os.path.exists(p):
            json.dump(fn(sents), open(p, "w"), ensure_ascii=False, indent=1)
            if "times" in LAST:
                json.dump(LAST.pop("times"), open(p.replace(".json", ".timing.json"), "w"))
            print("translated", inp, name, flush=True)

# Blind grade, one call per input so systems on the same input are compared side by side.
results = {}
for inp in inputs:
    systems = {n: json.load(open(os.path.join(OUT, f"{inp}__{n}.json"))) for n in TRANSLATORS}
    labels = list(systems); random.Random(inp).shuffle(labels)
    names = {chr(65 + i): m for i, m in enumerate(labels)}
    blocks = [f"### System {L}\n" + json.dumps(systems[m], ensure_ascii=False) for L, m in names.items()]
    prompt = f"""You are an expert Haitian Creole->English translation evaluator. Grade each system's translation of each of the {len(src)} source sentences (each system gives a list aligned to the sources).
The intended meaning of every sentence is given by its English reference, which is authoritative.

Score each sentence per system:
3 = meaning fully correct and natural; 2 = meaning correct but awkward or unidiomatic; 1 = partly wrong, or something important omitted or added; 0 = wrong meaning, wrong language, garbled, or missing.
Also set critical=true when a number, time, date, dose, amount, negation, or who-did-what is wrong (even if the rest is fine).

Source sentences (Haitian Creole):
{json.dumps(src, ensure_ascii=False)}

Reference meaning (English):
{json.dumps(ref, ensure_ascii=False)}

Translations into English:
{chr(10).join(blocks)}

Return JSON: {{"A": [{{"i": 0, "score": 3, "critical": false, "note": "..."}}, ... {len(src)} items], "B": [...], ...}} with a note of at most 8 words only when score < 3 or critical."""
    for _ in range(3):  # the grader once answered with a bare list, once ran out of room: ask again
        try:
            res = gemini(prompt, model=GRADER)
        except json.JSONDecodeError:
            continue
        if isinstance(res, dict) and all(isinstance(res.get(L), list) for L in names):
            break
    for L, m in names.items():
        g = {x["i"]: x for x in res.get(L, [])}
        full = sum(1 for i in range(len(src)) if g.get(i, {}).get("score") == 3)
        mean = sum(g.get(i, {}).get("score", 0) for i in range(len(src))) / (3 * len(src))
        crit = sum(1 for x in g.values() if x.get("critical"))
        results[f"{inp}__{m}"] = {"fully_correct": round(full / len(src), 3), "mean_score": round(mean, 3), "critical": crit}
fresh = results
gp = os.path.join(OUT, "grades.json" if GRADER == "gemini-2.5-pro" else f"grades-{GRADER}.json")
if os.environ.get("KEEP_GRADES") and os.path.exists(gp):
    # Add only systems not graded yet; earlier rows stay as published (the
    # re-grade of the others is printed below, to show the grader's drift).
    kept = json.load(open(gp))
    results = {**kept, **{k: v for k, v in results.items() if k not in kept}}
json.dump(results, open(gp, "w"), indent=1)
print("grader:", GRADER, "(this run's grades)")
for k, v in sorted(fresh.items()):
    print(f"{k:40s} fully correct {v['fully_correct']:.0%}  mean {v['mean_score']:.0%}  critical {v['critical']}")
