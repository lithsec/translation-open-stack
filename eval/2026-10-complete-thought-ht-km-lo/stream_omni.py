# Stream a clip at real time (100 ms PCM16 messages at 16 kHz) to one or more omni-stt /listen sockets at once (the
# same audio to each, as Live Translation's solo Khmer or Lao room sends it to the 7B service and to the streaming
# service), and keep EVERY message with its arrival time and its socket's index, as stream_partials.py does for
# MAI: t = ms since the first audio message was sent (the clip's own clock). Ran on the GPU host itself, against
# the services on 127.0.0.1 (STT_OPEN=1, no port exposed). After the clip: 2.5 s of digital silence, a flush, and
# the wait for each socket's "flushed".
#   python stream_omni.py CLIP.wav OUT.json URL [URL...]
#   e.g. ws://127.0.0.1:8082/listen?langs=km  "ws://127.0.0.1:8083/listen?langs=km&stream=ctc&lookahead=2"
import asyncio, json, sys, time, wave

import websockets

CLIP, OUT, URLS = sys.argv[1], sys.argv[2], sys.argv[3:]


async def main():
    with wave.open(CLIP) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        pcm = w.readframes(w.getnframes()) + b"\0" * 80000
    msgs, t0, hellos = [], [None], []
    socks = [await websockets.connect(u, max_size=None, ping_interval=None) for u in URLS]
    for ws in socks:
        hellos.append(json.loads(await ws.recv()))

    async def reader(k, ws):
        async for m in ws:
            j = json.loads(m)
            j["t"] = round((time.time() - t0[0]) * 1000, 1)
            j["sock"] = k
            msgs.append(j)
            if j.get("type") == "flushed":
                return

    t0[0] = time.time()
    tasks = [asyncio.create_task(reader(k, ws)) for k, ws in enumerate(socks)]
    for off in range(0, len(pcm), 3200):
        for ws in socks:
            await ws.send(pcm[off:off + 3200])
        await asyncio.sleep(max(0, t0[0] + (off + 3200) / 32000 - time.time()))
    for ws in socks:
        await ws.send(json.dumps({"type": "flush"}))
    await asyncio.wait_for(asyncio.gather(*tasks), 180)
    for ws in socks:
        await ws.close()
    json.dump({"urls": [u.split("?", 1)[1] for u in URLS], "hellos": hellos, "messages": msgs},
              open(OUT, "w"), ensure_ascii=False, indent=1)
    kinds = {}
    for m in msgs:
        k = f"{m['sock']}:{m.get('type')}"
        kinds[k] = kinds.get(k, 0) + 1
    print(OUT, kinds, flush=True)


asyncio.run(main())
