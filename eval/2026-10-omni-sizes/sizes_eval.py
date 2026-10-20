"""Zero-shot Omnilingual ASR, one model card per run: transcripts, GPU memory and speed.

    python3 sizes_eval.py --card omniASR_LLM_1B_v2 --clips clips --out out [--test manifest.jsonl --data DIR]

clips/<lang>/NN.wav are the real-voice sentences (cut.sh: one wav per
audio/<lang>.json "sentences" mark, 16 kHz mono). Writes out/<card>.json with
the hypotheses only; score.py (run where judge.py is) computes CER.

Decoding: ASRInferencePipeline(model_card, device="cuda"), the pipeline's
default GPU dtype (bf16), as omni-stt. LLM cards get the language code
(hat_Latn / khm_Khmr / lao_Laoo); CTC cards ignore it.

Real-voice sentences are decoded one at a time (batch 1), as the omni-stt
service does, and timed: rtf = decode seconds / audio seconds. The en/fr
leak check decodes the English and French clips with hat_Latn and with no
language. --test decodes a held-out set from a manifest (batch 16) with hat_Latn.

Memory: torch.cuda.memory_allocated right after load (weights), and
max_memory_allocated over the batch-1 decodes and over the batch-16 decodes
(the peak a one-utterance-at-a-time service would see, and a batched one).
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

CODES = {"ht": "hat_Latn", "km": "khm_Khmr", "lo": "lao_Laoo", "en": "eng_Latn", "fr": "fra_Latn"}
GB = 1024 ** 3


def read(p):
    w, sr = sf.read(str(p), dtype="float32")
    assert sr == 16000, (p, sr)
    return w.mean(axis=1) if w.ndim > 1 else w


def one(pipe, wave, lang):
    try:
        return (pipe.transcribe([{"waveform": wave, "sample_rate": 16000}], lang=[lang], batch_size=1)[0] or "").strip()
    except ValueError as e:  # an empty beam ("seq_lens ... is 0"): the service logs it and sends nothing
        print(f"  decode failed: {e}", flush=True)
        return ""


def batched(pipe, waves, lang, batch):
    order = sorted(range(len(waves)), key=lambda k: len(waves[k]))
    out = [""] * len(waves)
    for i in range(0, len(order), batch):
        idx = order[i:i + batch]
        items = [{"waveform": waves[k], "sample_rate": 16000} for k in idx]
        try:
            texts = pipe.transcribe(items, lang=[lang] * len(idx), batch_size=len(idx))
        except ValueError:
            texts = [one(pipe, waves[k], lang) for k in idx]
        for k, t in zip(idx, texts):
            out[k] = (t or "").strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True)
    ap.add_argument("--clips", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--test", help="a held-out manifest.jsonl (audio path and text per line); keep results on data you may not share out of the repo")
    ap.add_argument("--data", help="root the manifest's clip paths are relative to")
    ap.add_argument("--batch", type=int, default=16)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline

    llm = "_LLM_" in args.card
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    pipe = ASRInferencePipeline(model_card=args.card, device="cuda")
    torch.cuda.synchronize()
    res = {"card": args.card, "dtype": str(getattr(pipe, "dtype", "")), "gpu": torch.cuda.get_device_name(0),
           "load_s": round(time.time() - t0, 1),
           "params_m": round(sum(p.numel() for p in pipe.model.parameters()) / 1e6, 1),
           "mem_load_gb": round(torch.cuda.memory_allocated() / GB, 2),
           "mem_load_peak_gb": round(torch.cuda.max_memory_allocated() / GB, 2)}
    print(json.dumps(res), flush=True)

    clips = Path(args.clips)
    # Warm-up (CUDA kernels, allocator), not timed.
    one(pipe, read(sorted((clips / "en").glob("*.wav"))[0]), "eng_Latn" if llm else None)

    torch.cuda.reset_peak_memory_stats()
    runs = [(l, CODES[l]) for l in ("ht", "km", "lo")]
    runs += [("en", "hat_Latn"), ("en", None), ("fr", "hat_Latn"), ("fr", None)]
    if not llm:  # CTC has no conditioning: one pass each
        runs = [(l, None) for l in ("ht", "km", "lo", "en", "fr")]
    res["real_voices"] = {}
    dec_s = aud_s = 0.0
    for lang, code in runs:
        files = sorted((clips / lang).glob("*.wav"))
        hyps, secs = [], []
        for f in files:
            w = read(f)
            torch.cuda.synchronize()
            a = time.time()
            hyps.append(one(pipe, w, code))
            torch.cuda.synchronize()
            secs.append(time.time() - a)
            if lang in ("ht", "km", "lo"):
                dec_s += secs[-1]
                aud_s += len(w) / 16000
        key = f"{lang}:{code or 'none'}"
        res["real_voices"][key] = {"lang": lang, "cond": code, "hyps": hyps,
                                  "decode_s": round(sum(secs), 2),
                                  "audio_s": round(sum(len(read(f)) for f in files) / 16000, 2)}
        print(key, round(sum(secs), 2), "s", hyps[0][:80], flush=True)
    res["rtf_batch1"] = round(dec_s / aud_s, 4)
    res["mem_peak_batch1_gb"] = round(torch.cuda.max_memory_allocated() / GB, 2)

    if args.test:
        man = Path(args.test)
        data = Path(args.data) if args.data else man.parent.parent.parent
        rows = sorted((json.loads(l) for l in man.read_text().splitlines() if l.strip()), key=lambda r: r["clip"])
        waves = [read(data / r["clip"]) for r in rows]
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        a = time.time()
        hyps = batched(pipe, waves, "hat_Latn", args.batch)
        torch.cuda.synchronize()
        res["test"] = {"n": len(rows), "decode_s": round(time.time() - a, 1),
                       "audio_s": round(sum(len(w) for w in waves) / 16000, 1),
                       "mem_peak_batch_gb": round(torch.cuda.max_memory_allocated() / GB, 2),
                       "rows": [{"clip": r["clip"], "ref": r["text"], "hyp": h} for r, h in zip(rows, hyps)]}
        res["test"]["rtf_batch"] = round(res["test"]["decode_s"] / res["test"]["audio_s"], 4)
        print("test", res["test"]["n"], res["test"]["decode_s"], "s", flush=True)

    (out / f"{args.card}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("done", args.card, flush=True)


if __name__ == "__main__":
    main()
