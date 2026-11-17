# Soniox speech-to-speech's translation text on the clips (build_clips.py): one Soniox real-time stream per
# direction and set (stt-rt-v6, one-way translation into the listener's language), the start message the Talk app
# sends (LithosSpike/SonioxStreamHub.swift: language identification and speaker labels on, endpoint detection with
# max_endpoint_delay_ms 1500, no language hints), the clip streamed at real time in 100 ms chunks of 16 kHz PCM.
# Only the text is kept: Soniox's voice is not called or graded.
#
#   SONIOX_API_KEY=... python3 -I soniox_s2s.py CLIPS_ROOT OUT [src-tgt ...]
#
# CLIPS_ROOT holds clips_a/ and clips_b/. Writes OUT/soniox/<set>/<src>-<tgt>.json: every final token (text,
# translation_status, language, start_ms, end_ms, arrival ms since the first audio), the error if any, and
# `sent`: the translation per read sentence. A translation block (final translation tokens in a row) belongs to
# the sentences of the original tokens since the block before it (by their audio offsets); a block over several
# sentences is cut where they end (../2026-10-translator-shootout/shootout.py split_like, against the FLEURS text
# in the target language); a block with no new original words joins the previous block's last sentence.
# Three streams at a time at most (the key's streams are shared with live users). Nothing secret is printed.
import asyncio, json, os, sys, time, wave
import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-translator-shootout"))
from shootout import split_like  # noqa: E402

URL = "wss://stt-rt.soniox.com/transcribe-websocket"
KEY = os.environ["SONIOX_API_KEY"].strip()
CLIPS, OUT = sys.argv[1], sys.argv[2]
LANGS = ["es", "pt", "fr", "de", "zh", "vi", "ar", "fa", "tl", "uk", "ko", "ru", "hi", "it"]
DIRS = sys.argv[3:] or [f"en-{l}" for l in LANGS] + [f"{l}-en" for l in LANGS]
SETS = os.environ.get("SETS", "a,b").split(",")   # SETS=c,d,e,f: build_more.py's sets
CONCURRENCY = 3
J = lambda p: json.load(open(p))


def start_msg(tgt):
    return {"model": "stt-rt-v6", "audio_format": "pcm_s16le", "sample_rate": 16000, "num_channels": 1,
            "enable_language_identification": True, "enable_speaker_diarization": True,
            "enable_endpoint_detection": True, "max_endpoint_delay_ms": 1500,
            "translation": {"type": "one_way", "target_language": tgt}}


def sentence_of(ms, marks):
    t = ms / 1000
    for i, m in enumerate(marks):
        hi = marks[i + 1]["start"] - 0.3 if i + 1 < len(marks) else 1e9
        if t < hi:
            return i
    return len(marks) - 1


def assign(finals, marks, gold_tgt):
    """Translation text per read sentence (see the header)."""
    out = [[] for _ in marks]
    seen, block, prev_last = [], [], None

    def close():
        nonlocal block, seen, prev_last
        if not block:
            return
        text = "".join(t["text"] for t in block).strip()
        sents = sorted(set(seen))
        if not sents:
            sents = [prev_last] if prev_last is not None else [0]
        if len(sents) == 1:
            out[sents[0]].append(text)
        else:
            for i, piece in zip(sents, split_like(text, [gold_tgt[i] for i in sents])):
                out[i].append(piece)
        prev_last, block, seen = sents[-1], [], []

    for t in finals:
        if t["text"] in ("<end>", "<fin>") or not t["text"]:
            continue
        if t.get("translation_status") == "translation":
            block.append(t)
        else:
            close()
            if t.get("start_ms") is not None:
                mid = (t["start_ms"] + t.get("end_ms", t["start_ms"])) / 2
                seen.append(sentence_of(mid, marks))
    close()
    return [" ".join(x for x in o if x).strip() for o in out]


async def stream(src, tgt, st):
    clips = os.path.join(CLIPS, f"clips_{st}")
    with wave.open(os.path.join(clips, f"{src}.wav")) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        pcm = w.readframes(w.getnframes())
    finals, err, t0 = [], "", [None]
    async with websockets.connect(URL, additional_headers={"Authorization": f"Bearer {KEY}"}, max_size=1 << 22,
                                  open_timeout=30) as ws:
        await ws.send(json.dumps(start_msg(tgt)))

        async def send():
            t0[0] = time.time()
            for off in range(0, len(pcm), 3200):
                await ws.send(pcm[off:off + 3200])
                await asyncio.sleep(max(0, t0[0] + (off + 3200) / 32000 - time.time()))
            await ws.send(b"\0" * 32000)   # one second of silence, then the end of the audio
            await ws.send("")

        sender = asyncio.create_task(send())
        try:
            async for raw in ws:
                m = json.loads(raw)
                if m.get("error_code") or m.get("error_message"):
                    err = f"{m.get('error_code')}: {m.get('error_message')}"[:300]
                    break
                now = (time.time() - (t0[0] or time.time())) * 1000
                for k in m.get("tokens") or []:
                    if k.get("is_final"):
                        finals.append({"text": k.get("text", ""), "translation_status": k.get("translation_status"),
                                       "language": k.get("language"), "source_language": k.get("source_language"),
                                       "start_ms": k.get("start_ms"), "end_ms": k.get("end_ms"),
                                       "arrived_ms": round(now)})
                if m.get("finished"):
                    break
        finally:
            sender.cancel()
    return finals, err


async def job(sem, src, tgt, st):
    p = os.path.join(OUT, "soniox", st, f"{src}-{tgt}.json")
    if os.path.exists(p) and not J(p).get("err"):
        return
    meta = J(os.path.join(CLIPS, f"clips_{st}", f"{src}.json"))
    gold_tgt = J(os.path.join(CLIPS, f"clips_{st}", f"{tgt}.txt.json"))
    async with sem:
        for attempt in range(5):
            try:
                finals, err = await stream(src, tgt, st)
            except Exception as e:  # noqa: BLE001
                finals, err = [], f"{type(e).__name__}: {e}"[:300]
            if not err:
                break
            print(f"{st} {src}-{tgt}: {err} (attempt {attempt + 1})", flush=True)
            await asyncio.sleep(10 * (attempt + 1))
    marks = meta["sentences"]
    sent = assign(finals, marks, gold_tgt) if not err else []
    orig = "".join(t["text"] for t in finals if t.get("translation_status") != "translation" and not t["text"].startswith("<"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump({"src": src, "tgt": tgt, "set": st, "start": start_msg(tgt), "err": err, "heard": orig.strip(),
               "sent": sent, "finals": finals}, open(p, "w"), ensure_ascii=False, indent=1)
    n_tr = sum(1 for t in finals if t.get("translation_status") == "translation")
    print(f"{st} {src}-{tgt}: {'ERROR ' + err if err else f'{len(finals)} finals, {n_tr} translated, {sum(1 for s in sent if not s)} empty sentences'}", flush=True)


async def main():
    sem = asyncio.Semaphore(CONCURRENCY)
    await asyncio.gather(*(job(sem, *d.split("-"), st) for st in SETS for d in DIRS))


if __name__ == "__main__":
    asyncio.run(main())
