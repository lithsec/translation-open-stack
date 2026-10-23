"""Khmer CER of an Omnilingual LLM card (optionally with fine-tuned weights).

    python3 eval_km.py --card omniASR_LLM_300M --name base [--weights sdp_00.pt] --out /workspace/eval \
        [--sets rv,unseen,setb] [--dev /workspace/data/km_public]

Sets (all FLEURS km test recordings, decoded one sentence at a time, batch 1, as omni-stt does):
  rv      real-voices clip (30 sentences), cut at audio marks; reference: written text
  unseen  the unseen clip (20), cut at marks; references: written text and what was said (witness)
  setb    full-stack set b (20): the same FLEURS files, trimmed as the clip builder did; both references
CER = edits / reference characters on the joined text, two normalisations:
  judge   judge.py's (NFKC, lower case, letters and digits only): comparable with earlier rounds,
          but it drops Khmer vowel signs (Unicode marks), so it under-counts vowel errors
  full    NFKC, keeps letters, marks and digits: counts vowel-sign errors too
--dev: also pooled CER on the dev Parquet (ddd, fleurs) for checkpoint picking.
"""

import argparse
import io
import json
import os
import sys
import tarfile
import time
import unicodedata
import urllib.request
import wave
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import soundfile as sf
import torch

HERE = Path(__file__).resolve().parent
A = HERE / "assets"
CODE, RATE = "khm_Khmr", 16000
sys.path.insert(0, str(HERE))


def norm_judge(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c for c in s if c.isalnum())


def norm_full(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c for c in s if unicodedata.category(c)[0] in "LMN")


def edits(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def cer(refs, hyps, f):
    a, b = f(" ".join(refs)), f(" ".join(hyps))
    return round(100 * edits(a, b) / max(len(a), 1), 2)


def cut(wav_path, marks_path):
    with wave.open(str(wav_path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    marks = json.load(open(marks_path))["sentences"]
    return [x[int(m["start"] * RATE):int(m["end"] * RATE)] for m in marks]


def setb_waves():
    cache = A / "setb" / "waves.npz"
    if cache.exists():
        z = np.load(cache)
        return [z[f"w{i}"] for i in range(len(z.files))]
    import fetch_audio as fa
    files = json.load(open(A / "setb" / "km.json"))["files"]
    got = {}
    with urllib.request.urlopen(f"{fa.HF}/km_kh/audio/test.tar.gz", timeout=1800) as resp:
        with tarfile.open(fileobj=resp, mode="r|gz") as tar:
            for m in tar:
                b = os.path.basename(m.name)
                if b in files and m.isfile():
                    got[b] = np.frombuffer(fa.to_pcm(tar.extractfile(m).read()), dtype="<i2").astype(np.float32) / 32768
                    if len(got) == len(files):
                        break
    waves = [got[f] for f in files]
    np.savez(cache, **{f"w{i}": w for i, w in enumerate(waves)})
    return waves


def sets(names):
    out = {}
    if "rv" in names:
        out["rv"] = (cut(A / "rv" / "km.wav", A / "rv" / "km.json"), json.load(open(A / "rv" / "km.txt.json")), None)
    if "unseen" in names:
        out["unseen"] = (cut(A / "unseen" / "km.wav", A / "unseen" / "km.json"),
                         json.load(open(A / "unseen" / "km.txt.json")),
                         [r["said"] for r in json.load(open(A / "unseen" / "km.said.json"))])
    if "setb" in names:
        out["setb"] = (setb_waves(), json.load(open(A / "setb" / "km.txt.json")),
                       [r["said"] for r in json.load(open(A / "setb" / "km.said.json"))])
    return out


def load(card, weights):
    from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline
    pipe = ASRInferencePipeline(model_card=card, device="cuda")
    if weights:
        sd = torch.load(weights, map_location="cpu", weights_only=True)
        missing, unexpected = pipe.model.load_state_dict(sd, strict=False)
        assert not missing and not unexpected, (missing[:5], unexpected[:5])
        pipe.model.eval()
    return pipe


def one(pipe, w):
    try:
        return (pipe.transcribe([{"waveform": w, "sample_rate": RATE}], lang=[CODE], batch_size=1)[0] or "").strip()
    except ValueError:
        return ""


def batched(pipe, waves, batch=16):
    order = sorted(range(len(waves)), key=lambda k: len(waves[k]))
    out = [""] * len(waves)
    for i in range(0, len(order), batch):
        idx = order[i:i + batch]
        try:
            t = pipe.transcribe([{"waveform": waves[k], "sample_rate": RATE} for k in idx], lang=[CODE] * len(idx),
                                batch_size=len(idx))
        except ValueError:
            t = [one(pipe, waves[k]) for k in idx]
        for k, h in zip(idx, t):
            out[k] = (h or "").strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", default="omniASR_LLM_300M")
    ap.add_argument("--weights")
    ap.add_argument("--name", required=True)
    ap.add_argument("--sets", default="rv,unseen,setb")
    ap.add_argument("--dev")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pipe = load(args.card, args.weights)
    res = {"name": args.name, "card": args.card, "weights": args.weights, "sets": {}, "dev": {}}
    hyps_all = {}
    for name, (waves, written, said) in sets([s for s in args.sets.split(",") if s]).items():
        t0 = time.time()
        hyps = [one(pipe, w) for w in waves]
        r = {"n": len(waves), "seconds": round(time.time() - t0, 1),
             "written_judge": cer(written, hyps, norm_judge), "written_full": cer(written, hyps, norm_full)}
        if said:
            r["said_judge"] = cer(said, hyps, norm_judge)
            r["said_full"] = cer(said, hyps, norm_full)
        # Runaway loops (the 7B failure mode): characters per second of audio.
        r["max_chars_per_s"] = round(max(len(h) / max(len(w) / RATE, 0.1) for h, w in zip(hyps, waves)), 1)
        res["sets"][name] = r
        hyps_all[name] = hyps
        print(args.name, name, r, flush=True)
    if args.dev:
        root = Path(args.dev) / "version=0"
        for corpus in ("ddd", "fleurs"):
            files = sorted((root / f"corpus={corpus}" / "split=dev" / f"language={CODE}").glob("*.parquet"))
            tab = pq.read_table(files, columns=["text", "audio_bytes"]).to_pylist()[:400]
            waves = [sf.read(io.BytesIO(np.asarray(r["audio_bytes"], dtype=np.int8).tobytes()), dtype="float32")[0]
                     for r in tab]
            refs = [r["text"] for r in tab]
            hyps = batched(pipe, waves)
            e = sum(edits(norm_judge(a), norm_judge(b)) for a, b in zip(refs, hyps))
            ef = sum(edits(norm_full(a), norm_full(b)) for a, b in zip(refs, hyps))
            res["dev"][corpus] = {"n": len(refs), "judge": round(100 * e / sum(len(norm_judge(a)) for a in refs), 2),
                                  "full": round(100 * ef / sum(len(norm_full(a)) for a in refs), 2)}
            print(args.name, "dev", corpus, res["dev"][corpus], flush=True)
    (out / f"{args.name}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    (out / f"{args.name}_hyps.json").write_text(json.dumps(hyps_all, ensure_ascii=False))


if __name__ == "__main__":
    main()
