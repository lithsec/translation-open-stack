#!/usr/bin/env python3
"""
Drive the stack with a WAV and hear what comes back.

    python3 tools/client.py --host <ip> --lang es --wav sermon.wav
    STACK_TOKEN=... python3 tools/client.py --url wss://<pod-id>-8790.proxy.runpod.net --lang es --wav sermon.wav

Streams the file at real-time pace (100 ms frames, like the app), prints every
transcript, saves translated audio to out-<lang>.wav, and reports the number
that decides everything: seconds from END OF UTTERANCE to FIRST AUDIO BACK.
"""
import argparse, asyncio, json, os, time, wave
from urllib.parse import urlencode

RATE = 24000


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="",
                    help="the stack's base URL, e.g. wss://<pod-id>-8790.proxy.runpod.net (overrides --host/--port)")
    ap.add_argument("--token", default=None,
                    help="access token (default: $STACK_TOKEN); sent as an Authorization header, never printed")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--lang", default="es")
    ap.add_argument("--wav", required=True, help="24 kHz mono PCM16 WAV")
    ap.add_argument("--src", default="en",
                    help="source language of the WAV; 'auto' lets the server identify and "
                         "route it per utterance (needs a --xeng server when not en)")
    args = ap.parse_args()

    import websockets
    with wave.open(args.wav) as w:
        if w.getframerate() != RATE or w.getnchannels() != 1:
            raise SystemExit(f"need {RATE} Hz mono — ffmpeg -i in.wav -ar {RATE} -ac 1 out.wav")
        audio = w.readframes(w.getnframes())

    out = wave.open(f"out-{args.lang}.wav", "wb")
    out.setnchannels(1); out.setsampwidth(2); out.setframerate(RATE)

    base = (args.url or f"ws://{args.host}:{args.port}").rstrip("/")
    url = f"{base}/translate?" + urlencode({"lang": args.lang, "src": args.src})
    token = args.token if args.token is not None else os.environ.get("STACK_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:  # websockets >= 14
        conn = websockets.connect(url, additional_headers=headers)
    except TypeError:
        conn = websockets.connect(url, extra_headers=headers)
    async with conn as ws:
        print(await ws.recv())  # hello
        frame = RATE // 10 * 2  # 100 ms
        sent_done_at = None
        first_audio_at = None

        async def receiver():
            nonlocal first_audio_at
            async for msg in ws:
                if isinstance(msg, bytes):
                    if first_audio_at is None:
                        first_audio_at = time.perf_counter()
                        if sent_done_at:
                            print(f"\n*** end-of-speech -> first audio: {first_audio_at - sent_done_at:.2f}s ***\n")
                    out.writeframes(msg)
                else:
                    m = json.loads(msg)
                    print(f"  [{m.get('type')}] {m.get('text') or m.get('delta')}")

        recv = asyncio.create_task(receiver())
        for i in range(0, len(audio), frame):
            await ws.send(audio[i:i + frame])
            await asyncio.sleep(0.1)  # real-time pace — the whole point
        sent_done_at = time.perf_counter()
        # a second of trailing silence so the VAD closes the utterance
        await ws.send(b"\x00" * frame * 15)
        await asyncio.sleep(10)
        recv.cancel()
    out.close()
    print(f"wrote out-{args.lang}.wav")


if __name__ == "__main__":
    asyncio.run(main())
