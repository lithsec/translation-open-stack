# Addition C: CER/WER of Canary-Qwen / Parakeet / Whisper (per sentence) on the e2e-stack clips, and the MT variants.
import json, os, re, sys, unicodedata
X = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
O = os.path.join(X, "out", "C")
E2E = os.path.join(os.path.dirname(X), "e2e-stack")
S = json.load(open(os.path.join(E2E, "out", "sentences.json")))
sys.argv.append("cer")


def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c for c in s if c.isalnum())


def words(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return [w for w in re.sub(r"[^\w\s']", " ", s).split() if w]


def ed(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


refs = {"en": S["en-es"]["source"], "es": S["es-en"]["source"], "fr": S["fr-en"]["source"]}
res, variants = {}, {}
for m in ("canary", "parakeet", "whisper"):
    d = json.load(open(os.path.join(O, f"c_{m}.json")))
    for lang, rows in d["langs"].items():
        hyp = " ".join(r["text"] for r in rows); ref = " ".join(refs[lang])
        dec = sorted(r["decode_s"] for r in rows)
        res[f"{m}:{lang}"] = {"cer": round(ed(norm(ref), norm(hyp)) / len(norm(ref)), 4),
                              "wer": round(ed(words(ref), words(hyp)) / len(words(ref)), 4),
                              "empty": sum(1 for r in rows if not r["text"]), "rtf": d["rtf"], "mem_peak_gb_torch": d["mem_peak_gb"],
                              "decode_p50_s": dec[len(dec) // 2], "decode_p90_s": dec[int(.9 * (len(dec) - 1))]}
        if lang == "en" and m in ("canary", "whisper"):
            for t in ("es", "fr", "ja"):
                variants[f"en-{t}:{m}"] = {"lang": "en", "tgt": t, "texts": [r["text"] for r in rows]}
# the e2e live (stack, Whisper large-v3 segmented) for reference
for lang, d in (("en", "en-es"), ("es", "es-en"), ("fr", "fr-en")):
    ref = " ".join(refs[lang]); hyp = S[d]["heard_all"]
    res[f"e2e-live-whisper:{lang}"] = {"cer": round(ed(norm(ref), norm(hyp)) / len(norm(ref)), 4),
                                       "wer": round(ed(words(ref), words(hyp)) / len(words(ref)), 4)}
json.dump(res, open(os.path.join(O, "cer.json"), "w"), indent=1)
json.dump(variants, open(os.path.join(X, "podB", "variants_c.json"), "w"), ensure_ascii=False, indent=1)
for k, v in res.items():
    print(k, v)
