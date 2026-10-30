# How many rooms one stack serves at once: N rooms, each one English speaker (the same 20-sentence clip, streamed in
# real time from a staggered start) and the listener languages given, all connected to the same stack. Run on the pod
# itself (ws://127.0.0.1:8790), so the network is not part of it.
#   python3 load.py --rooms 8 --langs es,fr,de,ja --clip DIR --out runs/r8.json
# DIR holds en.wav (16 kHz mono PCM16) and en.json (sentence start/end in seconds). The token is STACK_TOKEN or
# /workspace/.stack-token. Records, per connection, when each translation's text and audio arrive; analyze.py turns
# that into speech end -> first audio per sentence, and the backlog at the end.
import argparse, asyncio, json, os, random, time, wave

import numpy as np
import websockets

ap = argparse.ArgumentParser()
ap.add_argument("--rooms", type=int, required=True)
ap.add_argument("--langs", required=True)
ap.add_argument("--clip", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--url", default="ws://127.0.0.1:8790")
ap.add_argument("--stagger", type=float, default=7.0, help="room starts spread over this many seconds")
args = ap.parse_args()
TOKEN = os.environ.get("STACK_TOKEN") or open("/workspace/.stack-token").read().strip()
LANGS = args.langs.split(",")
with wave.open(os.path.join(args.clip, "en.wav")) as w:
    PCM16K = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
CLIP_S = len(PCM16K) / 16000


async def room(r, start_at, out):
    rid = f"cap{args.rooms}_{r}_{random.randrange(10**6)}"
    conns, rec = [], {lg: {"text": [], "audio": []} for lg in LANGS}
    for lg in LANGS:   # the first one is the primary: its audio is the room's
        url, hdr = f"{args.url}/translate?lang={lg}&src=en&room={rid}&context=1", {"Authorization": f"Bearer {TOKEN}"}
        try:
            ws = await websockets.connect(url, additional_headers=hdr, max_size=None)
        except TypeError:   # websockets before 14
            ws = await websockets.connect(url, extra_headers=hdr, max_size=None)
        hello = json.loads(await ws.recv())
        conns.append((lg, ws, hello))
    rate = conns[0][2].get("rate", 24000)
    pcm = np.interp(np.arange(0, len(PCM16K), 16000 / rate), np.arange(len(PCM16K)), PCM16K).astype("<i2").tobytes()
    frame = int(rate * 0.1) * 2
    last_out = [time.monotonic()]

    async def reader(lg, ws):
        try:
            async for m in ws:
                t = time.monotonic()
                last_out[0] = t
                if isinstance(m, bytes):
                    rec[lg]["audio"].append(t)
                else:
                    j = json.loads(m)
                    if j.get("type") == "transcript":
                        rec[lg]["text"].append(t)
        except websockets.ConnectionClosed:
            pass

    readers = [asyncio.create_task(reader(lg, ws)) for lg, ws, _ in conns]
    await asyncio.sleep(max(0.0, start_at - time.monotonic()))
    ws0, sil = conns[0][1], b"\0" * frame
    p0 = time.monotonic()
    for k in range(15):                       # 1.5 s of silence first
        await asyncio.sleep(max(0.0, p0 + (k + 1) * 0.1 - time.monotonic()))
        await ws0.send(sil)
    t0 = time.monotonic()
    n = (len(pcm) + frame - 1) // frame
    for k in range(n):
        await asyncio.sleep(max(0.0, t0 + (k + 1) * 0.1 - time.monotonic()))
        c = pcm[k * frame:(k + 1) * frame]
        await ws0.send(c + b"\0" * (frame - len(c)))
    last_out[0] = max(last_out[0], time.monotonic())
    k = n
    while time.monotonic() - last_out[0] < 12 and k - n < 900:   # silence until 12 s pass with no output
        k += 1
        await asyncio.sleep(max(0.0, t0 + k * 0.1 - time.monotonic()))
        await ws0.send(sil)
    for _, ws, _ in conns:
        await ws.close()
    await asyncio.gather(*readers)
    out[r] = {"room": rid, "t0": t0, "rate": rate,
              "langs": {lg: {k2: [round(x - t0, 3) for x in v] for k2, v in d.items()} for lg, d in rec.items()}}


async def main():
    out = {}
    base = time.monotonic() + 3
    await asyncio.gather(*[room(r, base + args.stagger * r / max(1, args.rooms), out) for r in range(args.rooms)])
    json.dump({"rooms": args.rooms, "langs": LANGS, "clip_s": CLIP_S, "runs": [out[r] for r in sorted(out)]},
              open(args.out, "w"), indent=0)
    print(f"{args.rooms} rooms x {len(LANGS)} languages done")


asyncio.run(main())
