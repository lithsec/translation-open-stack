#!/usr/bin/env python3
"""
Drive the stack hard and report numbers, not impressions.

    python3 tools/bench.py --host <ip> --port <port> --mode fanout --wav en.wav \
        --langs es,fr,pt,sw,ht,km,lo

Two modes, matching the two claims worth testing:

  fanout   ONE English clip -> N target languages, all at once, on separate
           connections. This is the economic claim in the design doc: one ASR
           and one MT serve every language, so the GPU cost is flat while the
           provider bill scales with language count. If latency collapses at
           seven, that claim is wrong.

  xeng     N source languages -> English, one at a time. The direction the
           design doc recommends KEEPING on a provider. Measured so the
           recommendation rests on evidence rather than assertion.

Every connection streams at real-time pace (100 ms frames), exactly as the app
does, so the latency numbers mean what they say.
"""
import argparse, asyncio, json, statistics, time, wave
from pathlib import Path

RATE = 24000


def load(path):
    with wave.open(str(path)) as w:
        if w.getframerate() != RATE or w.getnchannels() != 1:
            raise SystemExit(f"{path}: need {RATE} Hz mono")
        return w.readframes(w.getnframes())


class Result:
    def __init__(self, tag):
        self.tag = tag
        self.first_audio = None     # seconds after end of speech
        self.inputs, self.outputs = [], []
        self.audio_bytes = 0
        self.error = None


async def one(host, port, src, lang, audio, out_dir, tag, room=None):
    import websockets
    r = Result(tag)
    url = f"ws://{host}:{port}/translate?lang={lang}&src={src}"
    if room:
        url += f"&room={room}"
    frame = RATE // 10 * 2
    try:
        async with websockets.connect(url, max_size=2**24, open_timeout=60) as ws:
            done_at = None
            out = wave.open(str(Path(out_dir) / f"{tag}.wav"), "wb")
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(RATE)

            async def rx():
                async for m in ws:
                    if isinstance(m, bytes):
                        if r.first_audio is None and done_at:
                            r.first_audio = time.perf_counter() - done_at
                        r.audio_bytes += len(m)
                        out.writeframes(m)
                    else:
                        d = json.loads(m)
                        if d.get("type") == "inputTranscript":
                            r.inputs.append(d.get("text", ""))
                        elif d.get("type") == "transcript":
                            r.outputs.append(d.get("delta", ""))
                        elif d.get("type") == "error":
                            r.error = d.get("detail")

            task = asyncio.create_task(rx())
            for i in range(0, len(audio), frame):
                await ws.send(audio[i:i + frame])
                await asyncio.sleep(0.1)          # real-time pace
            done_at = time.perf_counter()
            await ws.send(b"\x00" * frame * 15)   # trailing silence closes the utterance
            await asyncio.sleep(25)
            task.cancel()
            out.close()
    except Exception as e:
        r.error = f"{type(e).__name__}: {e}"
    return r


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--mode", choices=["fanout", "xeng"], default="fanout")
    ap.add_argument("--wav", help="fanout: the English source clip")
    ap.add_argument("--langs", default="es,fr,pt,sw,ht,km,lo")
    ap.add_argument("--srcdir", help="xeng: dir of <lang>.wav source clips")
    ap.add_argument("--srcs", default="es,fr,pt,sw,km,lo")
    ap.add_argument("--out", default="bench-out")
    ap.add_argument("--no-room", action="store_true",
                    help="fanout WITHOUT the shared pipeline (the old per-connection path)")
    args = ap.parse_args()
    Path(args.out).mkdir(exist_ok=True)

    t0 = time.perf_counter()
    if args.mode == "fanout":
        audio = load(args.wav)
        langs = [x.strip() for x in args.langs.split(",") if x.strip()]
        secs = len(audio) / 2 / RATE
        print(f"FANOUT — one {secs:.1f}s English clip -> {len(langs)} languages, concurrently\n")
        # room=bench puts every connection on the SHARED pipeline — the app's
        # real shape (one mic, N sessions). --no-room measures the old
        # duplicate-work path for comparison.
        room = None if args.no_room else "bench"
        results = await asyncio.gather(*[
            one(args.host, args.port, "en", lg, audio, args.out, f"en-{lg}", room=room) for lg in langs
        ])
    else:
        srcs = [x.strip() for x in args.srcs.split(",") if x.strip()]
        print(f"X->ENG — {len(srcs)} source languages -> English, sequentially\n")
        results = []
        for s in srcs:
            p = Path(args.srcdir) / f"{s}.wav"
            if not p.exists():
                print(f"  skip {s}: no {p}"); continue
            results.append(await one(args.host, args.port, s, "en", load(p), args.out, f"{s}-en"))
    wall = time.perf_counter() - t0

    print(f"{'run':10} {'1st audio':>10} {'audio':>8}  transcript")
    print("-" * 100)
    lats = []
    for r in sorted(results, key=lambda x: x.tag):
        if r.error:
            print(f"{r.tag:10} {'ERROR':>10}          {r.error[:70]}")
            continue
        lat = f"{r.first_audio:.2f}s" if r.first_audio is not None else "none"
        if r.first_audio is not None:
            lats.append(r.first_audio)
        secs = r.audio_bytes / 2 / RATE
        text = " ".join(r.outputs).strip().replace("\n", " ")[:70]
        print(f"{r.tag:10} {lat:>10} {secs:>7.1f}s  {text}")

    print("-" * 100)
    ok = sum(1 for r in results if not r.error and r.audio_bytes > 0)
    print(f"{ok}/{len(results)} produced audio   ·   wall clock {wall:.1f}s")
    if lats:
        print(f"first-audio after end of speech: median {statistics.median(lats):.2f}s  "
              f"min {min(lats):.2f}s  max {max(lats):.2f}s")
    if results and results[0].inputs:
        print(f"\nheard: {' '.join(results[0].inputs)[:160]}")

    # The exit code IS the verdict. A bench that prints a sad table and exits 0
    # lets a wrapper announce success over 1/13 audio — which happened.
    if ok < len(results) or not results:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
