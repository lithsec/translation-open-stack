# Streams a whole unseen clip at real time (100 ms PCM16 messages, one connection)
# through omni-stt /listen with the CTC 3B streaming track (?stream=ctc), keeps every
# message with its arrival time, and writes the stream_partials.py shape:
#   {"partials": [{"t", "text", "offsetMs", "stable"}], "finals": [{"t", "text", "offsetMs", "durationMs"}]}
# t = ms since the clip's first sample was sent (the clip's own clock; no lead-in).
#
# The track's committed text is append-only, so it is final-like; the "partial" is the
# revisable tail after it. A partial here is the turn's committed text so far plus the
# tail, and "stable" counts its leading words that are committed (simulate_open.py
# commits them at once; the last committed word is held back, since a commit can end
# inside a word). A final is the turn's committed text when the segmenter ends the turn
# (the commit with "end": true); its audio span is the utterance's (the "language"
# message the server sends for the same turn). The 3B's own per-utterance text
# ("inputTranscript", masked like the track) is kept as "pieces".
#
#   python stream_ctc.py ws://127.0.0.1:8310/listen CLIPS_DIR OUT TAG lang...   (one connection per lang, at once)
import asyncio, json, os, sys, time, wave
import websockets

URL, CLIPS, OUT, TAG = sys.argv[1:5]
LANGS = sys.argv[5:]
LOOKAHEAD = os.environ.get("LOOKAHEAD", "2")
STEP = 1600   # 100 ms


async def run(lang):
    with wave.open(os.path.join(CLIPS, f"{lang}.wav")) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        pcm = w.readframes(w.getnframes())
    msgs = []
    async with websockets.connect(f"{URL}?langs={lang}&stream=ctc&lookahead={LOOKAHEAD}", max_size=None) as ws:
        hello = json.loads(await ws.recv())
        t0 = time.monotonic()

        async def reader():
            async for m in ws:
                d = json.loads(m)
                d["t"] = round((time.monotonic() - t0) * 1000, 1)
                msgs.append(d)
                if d.get("type") == "flushed":
                    return
        rt = asyncio.create_task(reader())
        for k, i in enumerate(range(0, len(pcm), STEP * 2)):
            await ws.send(pcm[i:i + STEP * 2])
            await asyncio.sleep(max(0, t0 + (k + 1) * STEP / 16000 - time.monotonic()))
        await ws.send(b"\0\0" * 16000 * 2)          # 2 s of silence: the last turn ends on a pause
        await asyncio.sleep(2.0)
        await ws.send(json.dumps({"type": "flush"}))
        await asyncio.wait_for(rt, 120)
    partials, finals, pieces = [], [], []
    langs_msgs = [m for m in msgs if m.get("type") == "language"]
    committed, tail = "", ""
    for m in msgs:
        if m.get("type") == "committed" and m.get("track") == "ctc":
            committed += m["text"]
            if m.get("end"):
                text = " ".join(committed.split())
                if text:
                    # the utterance whose end is nearest this turn's closing commit
                    u = min(langs_msgs, key=lambda x: abs(x["end_ms"] - m["end_ms"])) if langs_msgs else None
                    off = u["start_ms"] if u else m["start_ms"]
                    end = u["end_ms"] if u else m["end_ms"]
                    finals.append({"t": m["t"], "text": text, "offsetMs": off, "durationMs": max(1, end - off)})
                committed, tail = "", ""
                continue
        elif m.get("type") == "partial" and m.get("track") == "ctc":
            tail = m["text"]
        elif m.get("type") == "inputTranscript":
            pieces.append({"t": m["t"], "text": m["text"], "offsetMs": m["start_ms"], "durationMs": m["end_ms"] - m["start_ms"]})
            continue
        else:
            continue
        words = committed.split()
        full = " ".join(words + tail.split())
        if full:
            partials.append({"t": m["t"], "text": full, "offsetMs": m.get("start_ms", 0), "stable": max(0, len(words) - 1)})
    json.dump({"lang": lang, "model": "omniASR_CTC_3B streaming track", "lookahead_s": LOOKAHEAD, "hello": hello, "err": "",
               "partials": partials, "finals": finals, "pieces": pieces, "raw": msgs},
              open(os.path.join(OUT, f"{TAG}_{lang}.json"), "w"), ensure_ascii=False, indent=1)
    print(TAG, lang, len(partials), "partials", len(finals), "finals", len(pieces), "pieces", flush=True)


async def main():
    await asyncio.gather(*(run(l) for l in LANGS))

asyncio.run(main())
