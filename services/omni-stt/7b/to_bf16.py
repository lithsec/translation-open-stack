"""Meta's omniASR_LLM_7B checkpoint (fp32, 31 GB) -> the same checkpoint in
bfloat16 (~16 GB): every floating-point tensor cast, everything else as is.

The pipeline decodes in bf16 on a GPU anyway (load_model casts each tensor as
it copies it in), so the transcripts are the same; the file is half the bytes
to pull at a cold start, and fits a 32 GB machine's memory to convert (the fp32
file is mapped, not read whole: torch.load(mmap=True)).

    python to_bf16.py omniASR-LLM-7B.pt omniASR_LLM_7B_bf16.pt
"""
import sys
import time

import torch


def cast(obj):
    if torch.is_tensor(obj):
        return obj.to(torch.bfloat16) if obj.is_floating_point() else obj.clone()
    if isinstance(obj, dict):
        return {k: cast(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(cast(v) for v in obj)
    return obj


def main(src, dst):
    t0 = time.time()
    # Meta's own checkpoint (not user input); its pickle carries non-tensor
    # metadata, so weights_only cannot be used.
    ck = torch.load(src, map_location="cpu", mmap=True, weights_only=False)
    print("top-level keys:", list(ck)[:10] if isinstance(ck, dict) else type(ck), flush=True)
    out = cast(ck)
    del ck
    torch.save(out, dst)
    n = sum(t.numel() for t in _tensors(out))
    print(f"wrote {dst}: {n / 1e9:.2f} B elements in {time.time() - t0:.0f}s", flush=True)


def _tensors(obj):
    if torch.is_tensor(obj):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _tensors(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _tensors(v)


if __name__ == "__main__":
    main(*sys.argv[1:3])
