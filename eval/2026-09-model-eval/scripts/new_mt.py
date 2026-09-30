# Translation for the 12 new languages through the stack's own routing (server.Pipeline.translate_batch:
# Hy-MT2 NF4 where it supports the language, MADLAD 7B otherwise), both directions.
import json, sys, time
sys.path.insert(0, "/workspace/translation-open-stack/server")
import server
NEW = ["ar", "hi", "vi", "ko", "tl", "fa", "id", "tr", "bn", "ur", "it", "sw"]
pipe = server.Pipeline(["en"] + NEW, mt_ct2="/workspace/mt/madlad7b-ct2", hymt="/workspace/mt/hymt2-7b-nf4", voices_dir="/workspace/voices")
for code in ["tl", "fil", "fa", "ur", "bn", "sw"]:
    print("madlad token", code, pipe.mt_tok.convert_tokens_to_ids(f"<2{code}>") != pipe.mt_tok.unk_token_id, file=sys.stderr)
EN = json.load(open("en.json")); SRC = {L: json.load(open(f"src_{L}.json")) for L in NEW}
out, times = {}, {}
t = time.time(); rows = [pipe.translate_batch(s, NEW, "en") for s in EN]; times["en-*"] = round(time.time() - t, 1)
for i, L in enumerate(NEW):
    out[f"en-{L}"] = [r[i] for r in rows]
for L in NEW:
    t = time.time(); out[f"{L}-en"] = [pipe.translate(s, "en", L) for s in SRC[L]]; times[f"{L}-en"] = round(time.time() - t, 1)
    print(L, out[f"en-{L}"][2][:60], "|", out[f"{L}-en"][2][:60], file=sys.stderr, flush=True)
json.dump({"times": times, "out": out}, open("new_mt.json", "w"), ensure_ascii=False, indent=1)
