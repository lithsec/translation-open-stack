# Gemini Live Translate answers in one continuous stream, so its translation is
# cut into the read sentences before grading. A Gemini call names where each
# sentence's translation STARTS (its first words, copied from the stream); the
# cut is made here at those anchors, in order, so the cut can only divide the
# stream, never change a word. A sentence with no anchor gets an empty piece.
# Also: per-sentence latency from the arrival times of the stream's text.
#
#   GEMINI_API_KEY=... python3 -I segment.py CLIPS OUT
#
# Writes OUT/live/en-<tgt>.sent.json: {"live_out": [...], "first_ms": [...], "last_ms": [...]}
# (times are from the end of the sentence's speech).
import json, os, sys, urllib.request, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CLIPS, OUT = sys.argv[1], sys.argv[2]
NAMES = {"es": "Spanish", "pt": "Portuguese", "fr": "French", "ja": "Japanese", "km": "Khmer", "lo": "Lao", "ht": "Haitian Creole"}
MODEL = os.environ.get("SEGMENTER", "gemini-pro-latest")


def speech_ends():
    """End of each sentence's speech, ms (../2026-10-held-out/analyze_e2e.py speech_bounds)."""
    meta = json.load(open(os.path.join(CLIPS, "en.json")))
    with wave.open(os.path.join(CLIPS, "en.wav")) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)
    ends = []
    for s in meta["sentences"]:
        a = int(s["start"] * 16000)
        seg = x[a:int(s["end"] * 16000)]
        n = len(seg) // 320
        rms = np.sqrt((seg[: n * 320].reshape(n, 320) ** 2).mean(axis=1))
        loud = np.where(rms >= 0.2 * np.percentile(rms, 90))[0]
        ends.append(round((s["start"] + (loud[-1] + 1) * 0.02) * 1000))
    return ends


def gemini(text):
    body = {"contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": 32768}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                                 json.dumps(body).encode(), {"Content-Type": "application/json",
                                                             "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    j = json.load(urllib.request.urlopen(req, timeout=600))
    return json.loads("".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought")))


def cut(stream, anchors):
    starts, pos = [], 0
    for a in anchors:
        a = (a or "").strip()
        k = stream.find(a, pos) if a else -1
        starts.append(k)
        if k >= 0:
            pos = k + len(a)
    pieces = []
    for i, k in enumerate(starts):
        if k < 0:
            pieces.append((None, None))
            continue
        nxt = next((s for s in starts[i + 1:] if s >= 0), len(stream))
        pieces.append((k, nxt))
    return pieces


def main():
    en = json.load(open(os.path.join(CLIPS, "en.txt.json")))
    ends = speech_ends()
    for tgt in NAMES:
        p = os.path.join(OUT, "live", f"en-{tgt}.json")
        d = json.load(open(p))
        stream = "".join(x["text"] for x in d["said"])
        # character offset -> arrival time of the fragment that carried it
        at, t = [], []
        for x in d["said"]:
            at.extend([x["t"]] * len(x["text"]))
        prompt = f"""Below are {len(en)} English sentences that a speaker read aloud, in order, and the continuous {NAMES[tgt]} output of a live interpreter who translated them as they were spoken. The interpreter may have skipped, merged or garbled some sentences.

For each English sentence, give the exact first words (about 4-8 words, or the first 6-12 characters for languages written without spaces) of where ITS translation begins in the interpreter's output, copied character for character from the output. Use "" if that sentence was not translated at all, or if its content only appears merged inside the previous sentence's translation. The starts must appear in the output in order.

English sentences:
{json.dumps(en, ensure_ascii=False, indent=0)}

Interpreter output:
{stream}

Return JSON: {{"starts": ["...", ... exactly {len(en)} strings]}}"""
        for _ in range(3):
            r = gemini(prompt)
            anchors = r.get("starts", []) if isinstance(r, dict) else []
            if len(anchors) == len(en):
                break
        spans = cut(stream, anchors)
        out, first, last = [], [], []
        for i, (a, b) in enumerate(spans):
            if a is None:
                out.append(""); first.append(None); last.append(None)
                continue
            out.append(stream[a:b].strip())
            first.append(at[a] - ends[i] if a < len(at) else None)
            last.append(at[max(a, b - 1)] - ends[i] if b else None)
        found = sum(1 for a, _ in spans if a is not None)
        lost = sum(1 for a in anchors if a and a.strip()) - found   # anchors not found verbatim
        json.dump({"live_out": out, "first_ms": first, "last_ms": last, "anchors": anchors, "anchors_not_found": lost,
                   "stream_chars": len(stream)}, open(os.path.join(OUT, "live", f"en-{tgt}.sent.json"), "w"),
                  ensure_ascii=False, indent=1)
        print(f"en-{tgt}: {found}/{len(en)} sentences located, {lost} anchors not found verbatim", flush=True)


if __name__ == "__main__":
    main()
