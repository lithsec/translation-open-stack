# Stream clips through omni-stt /listen at real-time pacing, timestamp every message.
#   python eval_client.py URL SETDIR LANG OUT.json [--lookahead 2] [--streams 1] [--loops 1] [--limit 0]
# SETDIR has manifest.json {"rows": {lang: [{"i", "clip", "ref"}...]}}. Each clip: a fresh connection,
# 0.5 s silence, the clip, 1.5 s silence, flush, wait for "flushed". With --streams N, N workers run at once,
# each over the clip list (offset so they do not play the same clip together), --loops times.
# Times are seconds from the clip's first sample being sent (the 0.5 s lead-in sent before it).
import argparse, asyncio, json, time
import numpy as np, soundfile as sf, websockets

ap = argparse.ArgumentParser()
ap.add_argument("url"); ap.add_argument("set"); ap.add_argument("lang"); ap.add_argument("out")
ap.add_argument("--lookahead", default="2"); ap.add_argument("--streams", type=int, default=1)
ap.add_argument("--loops", type=int, default=1); ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--nostream", action="store_true")
a = ap.parse_args()
SR = 16000; STEP = 1600
rows = json.load(open(f"{a.set}/manifest.json"))["rows"][a.lang][: a.limit or None]

def load(p):
    w, sr = sf.read(p, dtype="float32")
    if w.ndim > 1: w = w.mean(1)
    assert sr == SR, (p, sr)
    return w

def onset(w):
    f = w[: len(w) // 320 * 320].reshape(-1, 320)
    rms = np.sqrt((f ** 2).mean(1) + 1e-12)
    thr = max(rms.max() * 10 ** (-30 / 20), 1e-3)
    k = int(np.argmax(rms > thr)); kend = len(rms) - int(np.argmax(rms[::-1] > thr))
    return k * 0.02, kend * 0.02

async def one(row, wav):
    q = f"?langs={a.lang}" + ("" if a.nostream else f"&stream=ctc&lookahead={a.lookahead}")
    pcm = np.concatenate([np.zeros(SR // 2, np.float32), wav, np.zeros(int(1.5 * SR), np.float32)])
    b = (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()
    msgs = []
    async with websockets.connect(a.url + q, max_size=None) as ws:
        hello = json.loads(await ws.recv())
        t0 = time.monotonic() + 0.5          # the clip's first sample goes out 0.5 s after the start
        start = time.monotonic()

        async def reader():
            async for m in ws:
                d = json.loads(m); d["t"] = round(time.monotonic() - t0, 3); msgs.append(d)
                if d["type"] == "flushed":
                    return
        rt = asyncio.create_task(reader())
        for k, i in enumerate(range(0, len(b), STEP * 2)):
            await ws.send(b[i:i + STEP * 2])
            due = start + (k + 1) * STEP / SR
            await asyncio.sleep(max(0, due - time.monotonic()))
        await ws.send(json.dumps({"type": "flush"}))
        await asyncio.wait_for(rt, 60)
    on, off = onset(wav)
    return {"i": row["i"], "dur": round(len(wav) / SR, 3), "onset_s": on, "speech_end_s": off, "hello": hello, "msgs": msgs}

async def worker(k, out):
    order = rows[k % len(rows):] + rows[: k % len(rows)]
    for loop in range(a.loops):
        for r in order:
            try:
                res = await one(r, load(f"{a.set}/{r['clip']}"))
                res["stream"] = k; res["loop"] = loop; out.append(res)
            except Exception as e:
                out.append({"i": r["i"], "stream": k, "err": f"{type(e).__name__}: {e}"})

async def main():
    out = []; t = time.time()
    await asyncio.gather(*(worker(k, out) for k in range(a.streams)))
    json.dump({"lang": a.lang, "lookahead": a.lookahead, "streams": a.streams, "wall_s": round(time.time() - t, 1),
               "rows": out}, open(a.out, "w"), ensure_ascii=False)
    print("done", a.out, len(out), "clips", round(time.time() - t), "s", flush=True)

asyncio.run(main())
