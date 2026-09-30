#!/usr/bin/env python3
"""
Read several paragraphs through the stack and prove nothing was dropped.

    python3 tools/coverage-test.py --host 127.0.0.1:8790 --lang es

Latency has instruments; COVERAGE did not. Phrases went missing while reading
scripture aloud and the only way to notice was a person hearing a gap. This
speaks a known passage, feeds it in at real time, and diffs what the stack
heard against what was said — so a dropped clause is a number, not a feeling.

Ground truth comes from synthesising the passage locally, which means the
words are known EXACTLY rather than approximately as with a corpus clip.
"""
import argparse, asyncio, json, re, sys, time, wave, io
import numpy as np

PASSAGE = [
    "Good morning, and welcome to our service today.",
    "We are glad you have joined us, whether you are here in the building or listening from home.",
    "Please turn with me to the reading for this morning.",
    "The Lord is my shepherd; I shall not want.",
    "He maketh me to lie down in green pastures; he leadeth me beside the still waters.",
    "He restoreth my soul; he leadeth me in the paths of righteousness for his name's sake.",
    "Yea, though I walk through the valley of the shadow of death, I will fear no evil.",
    "For thou art with me; thy rod and thy staff they comfort me.",
    "Let us pray together before we begin.",
]

def norm(t):
    return re.sub(r"[^a-z0-9 ]", " ", t.lower()).split()

def synthesise(sentences, rate=24000, gap=0.6):
    """Known text -> speech, with a controllable pause between sentences.

    The gap is the whole experiment. At 0.6s the stack endpoints after every
    sentence and each turn is ~3s. A reader working through a passage does not
    pause like that, and the live log shows 9-10s turns instead -- a different
    regime, where commits come from LocalAgreement rather than from endpoints.
    """
    import torch
    from kokoro import KPipeline
    pipe = KPipeline(lang_code="a", device="cuda" if torch.cuda.is_available() else "cpu")
    out = []
    for s in sentences:
        chunks = [a for _, _, a in pipe(s, voice="am_michael")]
        a = np.concatenate([c.detach().cpu().numpy() if hasattr(c, "detach") else np.asarray(c)
                            for c in chunks]).astype("float32")
        out.append(a)
        out.append(np.zeros(int(rate * gap), dtype="float32"))
    return np.concatenate(out)

async def run(host, lang, pcm, rate, stream=False, room="coverage"):
    import websockets
    heard, translated, arrivals = [], [], []
    url = (f"ws://{host}/translate?lang={lang}&src=auto&room={room}"
           + ("&stream=1" if stream else ""))
    t0 = time.monotonic()
    async with websockets.connect(url, max_size=2**24, open_timeout=20) as ws:
        async def rx():
            async for m in ws:
                if isinstance(m, bytes):
                    arrivals.append((time.monotonic() - t0, len(m)))
                    continue
                d = json.loads(m)
                if d.get("type") == "inputTranscript": heard.append(d["text"])
                if d.get("type") == "transcript": translated.append(d.get("delta", ""))
        task = asyncio.create_task(rx())
        raw = (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()
        frame = int(rate / 10) * 2
        for i in range(0, len(raw), frame):
            await ws.send(raw[i:i + frame]); await asyncio.sleep(0.1)
        for _ in range(30):                       # let the last utterance end
            await ws.send(np.zeros(frame // 2, dtype="<i2").tobytes()); await asyncio.sleep(0.1)
        await asyncio.sleep(12)
        task.cancel()
    return " ".join(heard), " ".join(translated), arrivals

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1:8790")
    ap.add_argument("--stream", action="store_true",
                    help="simultaneous mode (?stream=1) -- the path a live "
                         "reader actually uses")
    ap.add_argument("--room", default="coverage")
    ap.add_argument("--gap", type=float, default=0.6,
                    help="silence between sentences; 0.1 mimics a reader who "
                         "does not pause, which is where the live report came "
                         "from")
    ap.add_argument("--lang", default="es")
    args = ap.parse_args()

    said = " ".join(PASSAGE)
    print(f"speaking {len(PASSAGE)} sentences, {len(norm(said))} words…")
    pcm = synthesise(PASSAGE, gap=args.gap)
    print(f"  {len(pcm)/24000:.1f}s of audio")
    heard, translated, arrivals = asyncio.run(
        run(args.host, args.lang, pcm, 24000, stream=args.stream, room=args.room))

    want, got = norm(said), set(norm(heard))
    missing = [w for w in want if w not in got]
    covered = 100 * (len(want) - len(missing)) / max(1, len(want))
    print(f"\n  heard back : {heard[:150]}")
    print(f"  translated : {translated[:150]}")
    print(f"\n  WORD COVERAGE: {covered:.1f}%  ({len(want) - len(missing)}/{len(want)})")
    if missing:
        print(f"  missing: {' '.join(missing[:25])}")
    # Sentence level: a dropped CLAUSE is what a listener notices.
    dropped = [s for s in PASSAGE
               if sum(1 for w in norm(s) if w in got) < 0.6 * len(norm(s))]
    print(f"  SENTENCES DROPPED: {len(dropped)}/{len(PASSAGE)}")
    for s in dropped:
        print(f"    - {s}")

    # Coverage uses a SET, so it cannot see text being ADDED. A reader who
    # says a line once and sees it twice is looking at duplication, not loss.
    hw, sw = norm(heard), want
    print(f"\n  WORDS SAID: {len(sw)}   WORDS HEARD: {len(hw)}   "
          f"inflation: {len(hw) / max(1, len(sw)):.2f}x")
    dupes = []
    n = 5
    seen = {}
    for i in range(len(hw) - n + 1):
        g = " ".join(hw[i:i + n])
        if g in seen:
            dupes.append(g)
        seen[g] = i
    if dupes:
        print(f"  REPEATED {n}-GRAMS: {len(dupes)}")
        for g in dupes[:8]:
            print(f"    - {g}")
    else:
        print(f"  no repeated {n}-grams")
    # "Pauses when I read": the listener hears silence between bursts of audio
    # while the speaker never stopped. Measure the gaps in audio ARRIVAL over
    # the window where speech was still being sent.
    speech_end = len(pcm) / 24000
    if arrivals:
        gaps, prev = [], arrivals[0][0]
        for t, _ in arrivals:
            if t - prev > 0.35 and t < speech_end:
                gaps.append((prev, t - prev))
            prev = t
        total = sum(n for _, n in arrivals) / 2 / 24000
        print(f"\n  AUDIO: {total:.1f}s in {len(arrivals)} frames, "
              f"first at {arrivals[0][0]:.2f}s, speech ran {speech_end:.1f}s")
        if gaps:
            worst = max(g for _, g in gaps)
            print(f"  GAPS >0.35s while still speaking: {len(gaps)}  "
                  f"worst {worst:.2f}s")
            for at, g in sorted(gaps, key=lambda x: -x[1])[:6]:
                print(f"    - {g:.2f}s of silence starting at {at:.1f}s")
        else:
            print("  no gaps >0.35s while speaking")
    return 1 if (dropped or len(hw) > 1.15 * len(sw)) else 0
    sys.exit(1 if dropped or covered < 90 else 0)

main()
