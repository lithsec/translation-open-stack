# Translation, one sentence per call, through the stack's own engines (server/engines) on the pod:
#   hymt    Hy-MT2 7B 4-bit NF4 (/workspace/mt/hymt2-7b-nf4), the stack's prompt and decoding
#   madlad  MADLAD-400 7B, CTranslate2 int8 (/workspace/mt/madlad7b-ct2), beam as the stack
#   gemma   Gemma 4 31B 4-bit (google/gemma-4-31B-it-qat-w4a16-ct) under vLLM, through engines/llmmt.py
# No context (each sentence alone), as the short check. Jobs, per language L in de, ru, ro and set a + b:
#   L-en      the FLEURS text of L into English
#   en-L      the English FLEURS text of the same id into L
#   L-en-asr  Whisper's per-sentence output (asr/whisper.json) into English (the route a live room takes)
#   STACK=/workspace/tos python3 -I mt.py WORK hymt|madlad|gemma
# Writes WORK/mt/<system>.json: {job: [{"id", "out", "s"}]}.
import json, os, sys, time
from pathlib import Path

WORK, SYS = sys.argv[1], sys.argv[2]
STACK = os.environ["STACK"]
sys.path.insert(0, os.path.join(STACK, "server"))
import stack_config  # noqa: E402
from engines.base import Context  # noqa: E402

GEMMA = "chat http://127.0.0.1:8101/v1 google/gemma-4-31B-it-qat-w4a16-ct"
LANGS = ("de", "ru", "ro")


def texts(lang):
    out = {}
    for st in ("a", "b"):
        for i, t in enumerate(json.load(open(Path(WORK) / f"clips_{st}_reg" / f"{lang}.txt.json"))):
            out[f"{st}{i:02d}"] = t
    return out


def engine():
    table, _ = stack_config.load()
    for lang in LANGS:
        table[lang]["llmmt"] = GEMMA   # Romanian has none in languages.toml; de/ru already this one
    opts = {"hymt": "/workspace/mt/hymt2-7b-nf4", "mt_ct2": "/workspace/mt/madlad7b-ct2", "mt_model": "google/madlad400-7b-mt"}
    ctx = Context(device="cuda", models=stack_config.load_models()[0], table=table, tables=stack_config.tables(table),
                  langs=["en", *LANGS], srcs=["en", *LANGS], options=opts)
    if SYS == "hymt":
        from engines.hymt import HyMT as E
    elif SYS == "madlad":
        from engines.madlad import Madlad as E
    else:
        from engines.llmmt import LlmMT as E
    e = E(ctx)
    e.load()
    return e


def main():
    e = engine()
    en = texts("en")
    asr = json.load(open(Path(WORK) / "asr" / "whisper.json"))
    jobs = {}
    for lang in LANGS:
        src = texts(lang)
        hyp = {r["id"]: r["text"] for r in asr[lang]}
        jobs[f"{lang}-en"] = (lang, "en", src)
        jobs[f"en-{lang}"] = ("en", lang, en)
        jobs[f"{lang}-en-asr"] = (lang, "en", hyp)
    out = {}
    for job, (s, t, items) in jobs.items():
        if SYS == "hymt" and not (e.supports(t) and e.supports_source(s)):
            continue
        rows = []
        for sid, x in sorted(items.items()):
            a = time.time()
            got = e.translate([x], s, [t]).get(t, "") if x.strip() else ""
            rows.append({"id": sid, "out": got, "s": round(time.time() - a, 3)})
        out[job] = rows
        print(SYS, job, len(rows), flush=True)
    os.makedirs(Path(WORK) / "mt", exist_ok=True)
    json.dump(out, open(Path(WORK) / "mt" / f"{SYS}.json", "w"), ensure_ascii=False, indent=1)


main()
