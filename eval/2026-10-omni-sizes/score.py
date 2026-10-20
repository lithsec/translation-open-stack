"""Scores sizes_eval.py's runs (out/<card>.json) on the real-voice clips.

    python3 score.py out            # -> results.json (real voices only) + a table

CER per language = judge.cer(" ".join(refs), " ".join(hyps)) over the 30
per-sentence clips, judge.py from ../2026-10-real-voices (as
out/stt-bakeoff/score.py there), with ../2026-09-model-eval/scripts on sys.path.
"cer_pooled": character edits summed per clip over reference characters
(pooled CER, as a fine-tuning eval reports it), same normalisation.

Leak check: the English and French clips decoded with hat_Latn and with no
language. cer_vs_own_ref is against the clip's own English/French text; a
model that "hears" Haitian Creole in them scores far worse with hat_Latn.
latin_share / ht_words: share of the hypothesis words that are common
Haitian Creole function words (a rough signal of Creole output).
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RV = HERE.parent / "2026-10-real-voices"
sys.path.insert(0, str(HERE.parent / "2026-09-model-eval" / "scripts"))
sys.path.insert(0, str(RV))
import types  # noqa: E402
sys.modules.setdefault("vertex", types.SimpleNamespace(gemini=None))  # judge.py imports it; cer() doesn't use it
from judge import cer, norm  # noqa: E402

HT_WORDS = {"nan", "yo", "li", "pou", "ki", "mwen", "ou", "nou", "se", "pa", "te", "ak", "yon", "sa", "gen", "lè",
            "kote", "konsa", "paske", "tou", "fè", "di", "kounye", "anpil", "sou", "ap", "la"}


def edits(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def pooled(refs, hyps):
    return round(sum(edits(norm(r), norm(h)) for r, h in zip(refs, hyps)) / sum(len(norm(r)) for r in refs), 4)


def refs(lang):
    return json.load(open(RV / "sentences" / f"{lang}.json"))


def marks(lang):
    return [m["i"] for m in json.load(open(RV / "audio" / f"{lang}.json"))["sentences"]]


def ht_share(text):
    w = [x.strip(".,!?;:'\"").lower() for x in text.split()]
    return round(sum(x in HT_WORDS for x in w) / max(len(w), 1), 3)


L4 = {
    "method": "estimate, not measured on an L4. H200 batch-1 RTF is ~0.08-0.09 for every LLM size (per-step overhead, not weight reads). "
              "On an L4 (24 GB, ~300 GB/s, ~120 TFLOPS bf16) the decoder step is bandwidth-bound: ~2.6 GB of bf16 decoder weights "
              "per token is ~9 ms; at 8.5-13 tokens per audio second (ht/lo/km, counted with the cards' tokenizers) that is "
              "~0.08-0.12 s per audio second, plus the encoder (one pass, ~0.01-0.07 s/s from 300M to 7B). Expected L4 RTF ~0.15-0.25 for "
              "300M and ~0.2-0.35 for 7B per stream: real time either way, with less headroom for 4 streams at 7B.",
    "memory": "peak bf16 at batch 1: 3.6 GB (LLM 300M) to 15.1 GB (LLM 7B); batch 16: 5.5 to 17.4 GB. All fit 24 GB with VoxLingua LID and Silero VAD beside them.",
}
NOT_RUN = {
    "omniASR_LLM_Unlimited_{300M,1B,3B,7B}_v2": "long-form variants; queued last, but results were lost when the pod was deleted before they were copied back",
    "omniASR_LLM_7B_ZS": "zero-shot card for unseen languages; needs in-context example audio/text pairs (transcribe_with_context), so not comparable",
    "omniASR_W2V_*": "pretrained encoders without an ASR head",
}


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "out")
    rows = []
    for p in sorted(out.glob("*.json")):
        r = json.load(open(p))
        row = {k: r[k] for k in ("card", "gpu", "dtype", "params_m", "load_s", "mem_load_gb", "mem_peak_batch1_gb", "rtf_batch1") if k in r}
        row["cer"], row["cer_pooled"], row["leak"] = {}, {}, {}
        for key, v in r["real_voices"].items():
            lang = v["lang"]
            rs = [refs(lang)[i] for i in marks(lang)]
            c = cer(" ".join(rs), " ".join(v["hyps"]))
            if lang in ("ht", "km", "lo"):
                row["cer"][lang] = c
                row["cer_pooled"][lang] = pooled(rs, v["hyps"])
                row.setdefault("rtf_by_lang", {})[lang] = round(v["decode_s"] / v["audio_s"], 4)
            if lang in ("en", "fr"):
                row["leak"][key] = {"cer_vs_own_ref": c, "ht_function_word_share": ht_share(" ".join(v["hyps"])),
                                    "sample": v["hyps"][:2]}
        row["hyps"] = {k: v["hyps"] for k, v in r["real_voices"].items()}
        rows.append(row)
    for lang in ("en", "fr"):
        row_ref = " ".join(refs(lang)[i] for i in marks(lang))
        print(f"reference ht function-word share, {lang} text: {ht_share(row_ref)}")
    res = {"date": "2026-10-19",
           "what": "Zero-shot Meta Omnilingual ASR model cards on the real-voice clips (30 sentences per language, cut per sentence)",
           "package": "omnilingual-asr 0.2.0, fairseq2 0.6, torch 2.8.0 cu128, bf16 (pipeline default)",
           "cer_method": "judge.cer(' '.join(refs), ' '.join(hyps)); cer_pooled = per-clip edits summed / reference chars",
           "gpu_note": "Measured on one NVIDIA H200 (RunPod, EUR-IS-4); A100/H100 had no stock",
           "decoder_note": "Every LLM card has the same ~1.3 B-parameter decoder (LLM params minus the CTC card of the same size); only the encoder grows",
           "l4_estimate": L4,
           "not_run": NOT_RUN,
           "endpointing_sweep": {"status": "not run", "why": "the extra pod work was blocked by the session's permission check before it started; the pod was then deleted. endpoint_sweep.py is ready to run on a fresh pod"},
           "runs": rows}
    (HERE / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"{'card':32} {'ht':>6} {'km':>6} {'lo':>6} {'load GB':>8} {'peak b1':>8} {'RTF b1':>7}   leak en hat/none  fr hat/none")
    for r in rows:
        lk = r["leak"]
        def g(k):
            return lk.get(k, {}).get("cer_vs_own_ref")
        leak = f"{g('en:hat_Latn')}/{g('en:none')}  {g('fr:hat_Latn')}/{g('fr:none')}"
        print(f"{r['card']:32} " + " ".join(f"{r['cer'].get(l, 0):6.1%}" for l in ("ht", "km", "lo"))
              + f" {r.get('mem_load_gb', 0):8.2f} {r.get('mem_peak_batch1_gb', 0):8.2f} {r.get('rtf_batch1', 0):7.3f}   {leak}")


if __name__ == "__main__":
    main()
