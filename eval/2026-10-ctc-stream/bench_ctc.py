# The streaming track's GPU cost: K streams' passes (each a LEFT + LOOKAHEAD + CHUNK window) in one batch.
#   python bench_ctc.py CLIPDIR [--card omniASR_CTC_3B] [--with7b CARD] [--out bench.json]
# CLIPDIR: any 16 kHz mono wavs (the audio only sets realistic content; the cost depends on the window).
# A stream needs one pass per CHUNK of audio, so K streams keep up while a K-pass batch takes < CHUNK.
import argparse, glob, json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "server")); sys.path.insert(0, os.path.join(ROOT, "services", "omni-stt"))
import numpy as np, soundfile as sf, torch
ap = argparse.ArgumentParser(); ap.add_argument("clips"); ap.add_argument("--card", default="omniASR_CTC_3B")
ap.add_argument("--with7b", default=""); ap.add_argument("--window", type=float, default=10.5)
ap.add_argument("--out", default="bench.json")
a = ap.parse_args()
res = {"card": a.card, "gpu": torch.cuda.get_device_name(0)}
if a.with7b:
    import server
    t = time.time(); omni = server.load_omni("cuda", a.with7b); torch.cuda.synchronize()
    res["llm_load_s"] = round(time.time() - t, 1); res["llm_gb"] = round(torch.cuda.memory_allocated() / 1e9, 2)
    # The 7B's own peak on a full batch: six 10 s utterances (omni-stt-7b runs 6 streams).
    clips = sorted(glob.glob(f"{a.clips}/*.wav"))
    long = np.concatenate([sf.read(p, dtype="float32")[0] for p in clips[:4]])[: 10 * 16000]
    torch.cuda.reset_peak_memory_stats(); t = time.time()
    server.decode_batch(omni, [(long, "km")] * 6); torch.cuda.synchronize()
    res["llm_batch6_s"] = round(time.time() - t, 2); res["llm_peak_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
    res["llm_reserved_gb"] = round(torch.cuda.memory_reserved() / 1e9, 2)
    print(res, flush=True)
import ctc_stream
m = ctc_stream.CTCModel("cuda", a.card, load=True)
res["ctc_load_s"], res["ctc_gb"] = m.load_s, m.memory_gb
try:
    t = time.time(); m.warm(); res["ctc_warm_s"] = round(time.time() - t, 1)
except Exception as e:
    res["ctc_warm_error"] = f"{type(e).__name__}: {str(e)[:120]}"; print(res, flush=True)
audio = np.concatenate([sf.read(p, dtype="float32")[0] for p in sorted(glob.glob(f"{a.clips}/*.wav"))[:12]])
n = int(a.window * 16000)
rows = []
for K in (1, 2, 4, 6, 8, 12, 16, 24, 32):
    items = [(audio[(k * 37000) % (len(audio) - n):][:n], "km") for k in range(K)]
    torch.cuda.reset_peak_memory_stats()
    ts = []
    try:
        for rep in range(6):
            t = time.time(); m._call(items); ts.append(time.time() - t)
    except Exception as e:
        rows.append({"K": K, "error": f"{type(e).__name__}: {str(e)[:100]}"}); print(rows[-1], flush=True); break
    ts = sorted(ts[1:])
    rows.append({"K": K, "batch_s_p50": round(ts[len(ts) // 2], 3), "batch_s_max": round(ts[-1], 3),
                 "peak_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
                 "reserved_gb": round(torch.cuda.memory_reserved() / 1e9, 2)})
    print(rows[-1], flush=True)
res["rows"] = rows
free, total = torch.cuda.mem_get_info(); res["free_gb_after"] = round(free / 1e9, 2); res["total_gb"] = round(total / 1e9, 2)
print(json.dumps(res)); json.dump(res, open(a.out, "w"))
