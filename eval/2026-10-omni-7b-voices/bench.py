#!/usr/bin/env python3
"""Hearing and speaking at once against one omni-stt server (the 7B with the
voices, or the separate services), with the GPU sampled meanwhile.

    python3 bench.py --url ws://127.0.0.1:8080 --clips /workspace/clips \
        --listen 4 --langs ht,en --transcribe ht --speak 2 --seconds 120 --out run.json

Each hearing stream is its own /listen socket that plays clips at real-time
pace (100 ms messages) in a room's order: English, Haitian Creole, French,
Haitian Creole, Spanish, ... (the clip languages among --langs), 0.6 s of
silence between them; streams start on different clips. A message's lag is its
arrival minus the moment the audio at its end_ms was sent. Each voice stream is
its own /speak socket asking for one Haitian Creole sentence after another
(the CMU texts), alternating the voices the hello offers; first audio is the
first binary frame after the request, at the client. nvidia-smi samples the
GPU every 200 ms. --no-gpu skips that (another process samples).
"""
import argparse, asyncio, json, os, statistics, subprocess, threading, time

import numpy as np
import soundfile as sf
import websockets

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="ws://127.0.0.1:8080")
ap.add_argument("--speak-url", default="")
ap.add_argument("--clips", default="/workspace/clips")
ap.add_argument("--listen", type=int, default=4)
ap.add_argument("--langs", default="ht,en")
ap.add_argument("--transcribe", default="")
ap.add_argument("--speak", type=int, default=2)
ap.add_argument("--voices", default="")
ap.add_argument("--seconds", type=float, default=120)
ap.add_argument("--out", required=True)
ap.add_argument("--no-gpu", action="store_true")
a = ap.parse_args()
SR, STEP = 16000, 1600
man = json.load(open(os.path.join(a.clips, "manifest.json"), encoding="utf-8"))["rows"]
langs = a.langs.split(",")
order = []
others = [l for l in langs if l != "ht" and l in man]
k = 0
while len(order) < 400:
    if others:
        order.append(others[k % len(others)])
    if "ht" in langs:
        order.append("ht")
    k += 1
pcm = {l: [(sf.read(r["clip"], dtype="int16")[0]) for r in man[l][:40]] for l in set(order)}
texts = [r["ref"] for r in man["ht"]]


def pct(xs, q):
    return round(float(np.percentile(xs, q)), 3) if xs else None


async def listen_stream(n, stop, out):
    q = f"langs={a.langs}" + (f"&transcribe={a.transcribe}" if a.transcribe else "")
    async with websockets.connect(f"{a.url}/listen?{q}", max_size=None, open_timeout=120) as ws:
        hello = json.loads(await ws.recv())
        assert hello["type"] == "hello", hello
        t0 = None
        spans = []   # (start_ms, end_ms, lang) sent

        async def reader():
            async for m in ws:
                if isinstance(m, bytes):
                    continue
                m = json.loads(m)
                now = time.monotonic()
                if m["type"] in ("language", "inputTranscript") and t0 is not None:
                    out.append({"stream": n, "type": m["type"], "lang": m["lang"], "conf": m.get("confidence"),
                                "start_ms": m["start_ms"], "end_ms": m["end_ms"],
                                "lag": round(now - (t0 + m["end_ms"] / 1000), 3)})
                if m["type"] == "flushed":
                    return
        rd = asyncio.create_task(reader())
        sent = 0
        idx = n * 3
        sil = np.zeros(int(0.6 * SR), dtype=np.int16)
        while not stop.is_set():
            lang = order[idx % len(order)]
            clip = pcm[lang][(idx // len(order) + n * 7 + idx) % len(pcm[lang])]
            idx += 1
            spans.append((sent / SR * 1000, (sent + len(clip)) / SR * 1000, lang))
            buf = np.concatenate([clip, sil])
            for i in range(0, len(buf), STEP):
                if t0 is None:
                    t0 = time.monotonic()
                await ws.send(buf[i:i + STEP].tobytes())
                sent += len(buf[i:i + STEP])
                # Real-time pace against the stream's own clock.
                wait = t0 + sent / SR - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
        await ws.send(json.dumps({"type": "flush"}))
        try:
            await asyncio.wait_for(rd, 30)
        except asyncio.TimeoutError:
            rd.cancel()
        return spans


async def speak_stream(n, stop, out):
    url = a.speak_url or a.url
    async with websockets.connect(f"{url}/speak", max_size=None, open_timeout=180) as ws:
        hello = json.loads(await ws.recv())
        assert hello["type"] == "hello", hello
        voices = a.voices.split(",") if a.voices else hello["voices"]
        k = n
        while not stop.is_set():
            text = texts[k % len(texts)]
            voice = voices[k % len(voices)]
            k += 1
            t = time.monotonic()
            await ws.send(json.dumps({"type": "speak", "text": text, "voice": voice, "id": str(k)}))
            first, nbytes = None, 0
            while True:
                m = await ws.recv()
                if isinstance(m, bytes):
                    nbytes += len(m)
                    if first is None:
                        first = time.monotonic() - t
                    continue
                m = json.loads(m)
                if m["type"] == "done":
                    out.append({"stream": n, "voice": voice, "chars": len(text), "first": round(first or -1, 3),
                                "server_first": m.get("first_audio_ms"), "ms": m.get("ms"),
                                "audio_ms": m.get("audio_ms"), "total": round(time.monotonic() - t, 3)})
                    break
                if m["type"] == "error":
                    out.append({"stream": n, "voice": voice, "error": m.get("detail")})
                    break
            # A listener hears the sentence before the next one comes: pace at
            # the audio's own length (as Live Translation's player does).
            spoken = nbytes / 2 / 24000
            await asyncio.sleep(max(0.2, spoken - (time.monotonic() - t)))


def gpu_sampler(stop, samples):
    p = subprocess.Popen(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits",
                          "-lms", "200"], stdout=subprocess.PIPE, text=True)
    for line in p.stdout:
        try:
            mem, util = (float(x) for x in line.split(","))
            samples.append((mem, util))
        except ValueError:
            pass
        if stop.is_set():
            break
    p.terminate()


async def main():
    stop = asyncio.Event()
    heard, spoke, gpu = [], [], []
    tstop = threading.Event()
    if not a.no_gpu:
        threading.Thread(target=gpu_sampler, args=(tstop, gpu), daemon=True).start()
    tasks = [asyncio.create_task(listen_stream(i, stop, heard)) for i in range(a.listen)]
    tasks += [asyncio.create_task(speak_stream(i, stop, spoke)) for i in range(a.speak)]
    await asyncio.sleep(a.seconds)
    stop.set()
    res = await asyncio.gather(*tasks, return_exceptions=True)
    tstop.set()
    errors = [repr(r) for r in res if isinstance(r, BaseException)]
    spans = [r for r in res[: a.listen] if isinstance(r, list)]
    # Language ID through the service: each language message against the clip it falls in.
    right = wrong = 0
    for e in heard:
        if e["type"] != "language":
            continue
        sp = spans[e["stream"]] if e["stream"] < len(spans) else []
        mid = (e["start_ms"] + e["end_ms"]) / 2
        truth = next((l for s, t, l in sp if s - 300 <= mid <= t + 300), None)
        if truth:
            right += truth == e["lang"]
            wrong += truth != e["lang"]
    lang_lag = [e["lag"] for e in heard if e["type"] == "language"]
    tr_lag = [e["lag"] for e in heard if e["type"] == "inputTranscript"]
    first = [s["first"] for s in spoke if "first" in s]
    sfirst = [s["server_first"] for s in spoke if s.get("server_first") is not None]
    summary = {
        "args": vars(a), "errors": errors,
        "language_msgs": len(lang_lag), "language_lag_p50": pct(lang_lag, 50), "language_lag_p90": pct(lang_lag, 90),
        "transcripts": len(tr_lag), "transcript_lag_p50": pct(tr_lag, 50), "transcript_lag_p90": pct(tr_lag, 90),
        "lid_through_service": {"right": right, "wrong": wrong},
        "sentences": len(first), "voice_errors": sum(1 for s in spoke if "error" in s),
        "first_audio_p50": pct(first, 50), "first_audio_p90": pct(first, 90),
        "server_first_ms_p50": pct(sfirst, 50), "server_first_ms_p90": pct(sfirst, 90),
        "per_voice": {v: {"n": len(xs), "first_p50": pct(xs, 50), "first_p90": pct(xs, 90)}
                      for v in sorted({s["voice"] for s in spoke if "first" in s})
                      for xs in [[s["first"] for s in spoke if s.get("voice") == v and "first" in s]]},
        "gpu_mem_peak_mib": max((m for m, _ in gpu), default=None),
        "gpu_mem_min_mib": min((m for m, _ in gpu), default=None),
        "gpu_util_mean": round(statistics.mean(u for _, u in gpu), 1) if gpu else None,
    }
    json.dump({"summary": summary, "heard": heard, "spoke": spoke}, open(a.out, "w"), indent=0)
    print(json.dumps(summary, indent=1))


asyncio.run(main())
