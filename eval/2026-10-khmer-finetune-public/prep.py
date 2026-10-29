"""Khmer public-data Parquet for Omnilingual's ASR recipe (mixture of two corpora).

    OMNI_REPO=/workspace/omnilingual-asr python3 prep.py --out /workspace/data/km_public \
        --ddd-train 110 --ddd-dev 3

Corpora (both commercial-use licences, both Khmer):
  ddd     Digital-Divide-Data/khmer-speech-dataset (CC BY-SA 4.0), parquet shards
          sampled evenly across the 653 shards; dev from other shards.
  fleurs  google/fleurs km_kh train (CC BY 4.0), dev from FLEURS dev.
Every FLEURS id or text used by our evaluation clips (assets/*) is excluded.

Layout: <out>/version=0/corpus=<c>/split=<s>/language=khm_Khmr/part-NNNN.parquet
(text, audio_bytes = FLAC, audio_size = frames, corpus, split, language), plus
language_distribution_0.tsv and km_public.yaml (the fairseq2 dataset card).
"""

import argparse
import csv
import io
import json
import os
import sys
import tarfile
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import soundfile as sf

HERE = Path(__file__).resolve().parent
A = HERE / "assets"
CODE, ISO, RATE, ROWS = "khm_Khmr", "khm", 16000, 2000
MAXLEN = 30 * RATE
FL = "https://huggingface.co/datasets/google/fleurs/resolve/main/data/km_kh"
csv.field_size_limit(10 ** 9)


def excluded():
    ids = set(json.load(open(A / "rv" / "fleurs_ids.json")))
    ids |= set(json.load(open(A / "unseen" / "ids.json"))["ids"])
    ids |= set(json.load(open(A / "setb" / "ids.json"))["ids"])
    txt = set()
    for p in (A / "rv" / "km.txt.json", A / "unseen" / "km.txt.json", A / "setb" / "km.txt.json"):
        txt |= {t.strip() for t in json.load(open(p))}
    return {str(i) for i in ids}, txt


def normaliser():
    sys.path.insert(0, os.path.join(os.environ["OMNI_REPO"], "workflows", "dataprep"))
    from text_tools import text_normalize
    return lambda t: " ".join(text_normalize(t, ISO, lower_case=True, remove_numbers=True).split())


def unk_check():
    import omnilingual_asr.models.inference.pipeline  # noqa: F401
    from fairseq2.data.tokenizers.hub import load_tokenizer
    tok = load_tokenizer("omniASR_LLM_300M")
    enc, unk = tok.create_encoder(), tok.vocab_info.unk_idx
    return lambda t: unk in enc(t).tolist()


def flac(x):
    b = io.BytesIO()
    sf.write(b, x, RATE, format="FLAC", subtype="PCM_16")
    return b.getvalue()


def to16k(raw):
    x, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != RATE:
        import soxr
        x = soxr.resample(x, sr, RATE)
    return x


def ddd_shard(path):
    """One DDD parquet shard -> [(text_raw, flac_bytes, frames, speaker)]"""
    t = pq.read_table(path, columns=["transcript", "audio", "speaker_id"]).to_pylist()
    out = []
    for r in t:
        a = r["audio"]
        raw = a.get("bytes") if isinstance(a, dict) else None
        if not raw:
            continue
        try:
            x = to16k(raw)
        except Exception:
            continue
        if not (RATE <= len(x) <= MAXLEN):
            continue
        out.append((r["transcript"] or "", flac(x), len(x), r["speaker_id"]))
    return out


def fleurs(split, ex_ids, ex_txt):
    rows = {}
    with urllib.request.urlopen(f"{FL}/{split}.tsv", timeout=300) as r:
        for line in r.read().decode("utf-8").splitlines():
            f = line.split("\t")
            if len(f) >= 7 and f[0] not in ex_ids and f[2].strip() not in ex_txt:
                rows[f[1]] = f[2]
    out, skipped = [], 0
    with urllib.request.urlopen(f"{FL}/audio/{split}.tar.gz", timeout=1800) as resp:
        with tarfile.open(fileobj=resp, mode="r|gz") as tar:
            for m in tar:
                b = os.path.basename(m.name)
                if m.isfile() and b in rows:
                    x = to16k(tar.extractfile(m).read())
                    if RATE <= len(x) <= MAXLEN:
                        out.append((rows[b], flac(x), len(x), "fleurs"))
                    else:
                        skipped += 1
    print(f"fleurs {split}: {len(out)} kept, {skipped} too short/long, {len(rows)} in tsv after exclusion", flush=True)
    return out


def write(root, corpus, split, items, norm, has_unk, out):
    d = root / f"corpus={corpus}" / f"split={split}" / f"language={CODE}"
    d.mkdir(parents=True, exist_ok=True)
    kept, unk, empty = [], 0, 0
    for raw, b, n, spk in items:
        t = norm(raw)
        if not t:
            empty += 1
            continue
        if has_unk(t):
            unk += 1
            continue
        kept.append((t, b, n, spk, raw))
    import random
    random.Random(0).shuffle(kept)
    schema = pa.schema([("text", pa.string()), ("audio_bytes", pa.list_(pa.int8())), ("audio_size", pa.int64()),
                        ("corpus", pa.dictionary(pa.int32(), pa.string())),
                        ("split", pa.dictionary(pa.int32(), pa.string())),
                        ("language", pa.dictionary(pa.int32(), pa.string()))])
    for p, i in enumerate(range(0, len(kept), ROWS)):
        ch = kept[i:i + ROWS]
        flat = b"".join(c[1] for c in ch)
        offs = [0]
        for c in ch:
            offs.append(offs[-1] + len(c[1]))
        vals = pa.Array.from_buffers(pa.int8(), offs[-1], [None, pa.py_buffer(flat)])
        n = len(ch)
        tab = pa.table({"text": pa.array([c[0] for c in ch]),
                        "audio_bytes": pa.ListArray.from_arrays(pa.array(offs, type=pa.int32()), vals),
                        "audio_size": pa.array([c[2] for c in ch], pa.int64()),
                        "corpus": pa.array([corpus] * n).dictionary_encode(),
                        "split": pa.array([split] * n).dictionary_encode(),
                        "language": pa.array([CODE] * n).dictionary_encode()}, schema=schema)
        pq.write_table(tab, d / f"part-{p:04d}.parquet", row_group_size=100)
    hours = sum(c[2] for c in kept) / RATE / 3600
    spk = sorted({c[3] for c in kept})
    (out / f"manifest_{corpus}_{split}.jsonl").write_text("".join(
        json.dumps({"text": c[0], "raw": c[4], "speaker": c[3]}, ensure_ascii=False) + "\n" for c in kept))
    print(corpus, split, {"clips": len(kept), "hours": round(hours, 2), "dropped_unk": unk,
                          "dropped_empty": empty, "speakers": len(spk)}, flush=True)
    return hours, len(kept), spk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--ddd-train", type=int, default=110)
    ap.add_argument("--ddd-dev", type=int, default=3)
    ap.add_argument("--procs", type=int, default=14)
    args = ap.parse_args()
    out = Path(args.out)
    root = out / "version=0"
    root.mkdir(parents=True, exist_ok=True)
    ex_ids, ex_txt = excluded()
    norm, has_unk = normaliser(), unk_check()
    from huggingface_hub import hf_hub_download

    total = 653
    stride = total / (args.ddd_train + args.ddd_dev)
    picks = [int(i * stride) for i in range(args.ddd_train + args.ddd_dev)]
    dev_shards = {picks[int(k)] for k in np.linspace(5, len(picks) - 5, args.ddd_dev)}
    train_shards = [p for p in picks if p not in dev_shards]

    def get(i):
        return hf_hub_download("Digital-Divide-Data/khmer-speech-dataset", f"data/train-{i:05d}-of-00653.parquet",
                               repo_type="dataset", cache_dir="/workspace/cache/ddd")

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(16) as tp:
        paths = dict(zip(train_shards + sorted(dev_shards), tp.map(get, train_shards + sorted(dev_shards))))
    print(f"ddd: {len(paths)} shards downloaded", flush=True)
    with ProcessPoolExecutor(args.procs) as pp:
        res = dict(zip(paths, pp.map(ddd_shard, list(paths.values()))))
    ddd_train = [x for i in train_shards for x in res[i]]
    ddd_dev = [x for i in sorted(dev_shards) for x in res[i]][:400]

    stats = {}
    stats["ddd/train"] = write(root, "ddd", "train", ddd_train, norm, has_unk, out)
    stats["ddd/dev"] = write(root, "ddd", "dev", ddd_dev, norm, has_unk, out)
    stats["fleurs/train"] = write(root, "fleurs", "train", fleurs("train", ex_ids, ex_txt), norm, has_unk, out)
    stats["fleurs/dev"] = write(root, "fleurs", "dev", fleurs("dev", ex_ids, ex_txt), norm, has_unk, out)
    (out / "language_distribution_0.tsv").write_text(
        "corpus\tlanguage\thours\n" + "".join(f"{c}\t{CODE}\t{stats[c + '/train'][0]:.3f}\n" for c in ("ddd", "fleurs")))
    (out / "km_public.yaml").write_text(
        f"name: km_public\ndataset_family: mixture_parquet_asr_dataset\n"
        f"dataset_config:\n  data: {root.resolve()}\ntokenizer_ref: omniASR_tokenizer_v1\n")
    (out / "stats.json").write_text(json.dumps({k: {"hours": round(v[0], 3), "clips": v[1], "speakers": v[2]}
                                                for k, v in stats.items()}, ensure_ascii=False, indent=1))
    (out / "shards.json").write_text(json.dumps({"train": train_shards, "dev": sorted(dev_shards)}))
    print("wrote", out, flush=True)


if __name__ == "__main__":
    main()
