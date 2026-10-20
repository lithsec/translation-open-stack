# Scores transcribe_live.mjs (gemini-3.5-transcribe-live) and azure_stt.py on
# the same clips: CER against the verified text each speaker read (judge.cer:
# NFKC, lowercased letters and digits, as text-mt/stt_compare.py), and how
# long after each sentence's audio ends its final arrives.
#
# Latency, two ways (audio is fed at real-time pace, so clip time = wall time):
#  segment: each final's arrival minus the end of the speech it covers (Gemini:
#    the paired voiceActivity ACTIVITY_END audioOffset, one per final; Azure:
#    offset+duration, as azure_stt.py prints).
#  sentence: what a listener waits for each sentence's final. A sentence's real
#    speech end is found from the audio (last 20 ms frame within its marks
#    above -20 dB of its peak; checked against Azure's and Gemini's own speech
#    ends: the marks carry trailing silence/noise, up to
#    3 s on some FLEURS clips), and its final is the first one whose segment
#    end reaches it. When the model keeps several sentences in one turn, the
#    earlier ones wait for the turn to close; that shows up here.
# "turns" = finals; fewer than 30 means sentences were merged into one turn.
#
#   python3 score_transcribe_live.py      -> stt_transcribe_live.json + table
import array, glob, json, math, os, statistics, sys, wave
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-09-model-eval", "scripts"))
sys.path.insert(0, HERE)
from judge import cer  # noqa: E402


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]) if xs else None


def speech_ends(lang):
    with wave.open(os.path.join(HERE, "audio", f"{lang}.wav")) as w:
        rate, pcm = w.getframerate(), array.array("h", w.readframes(w.getnframes()))
    hop = rate // 50
    out = []
    for m in json.load(open(os.path.join(HERE, "audio", f"{lang}.json")))["sentences"]:
        a, b = int(m["start"] * rate), int(m["end"] * rate)
        rms = [math.sqrt(sum(x * x for x in pcm[i:i + hop]) / hop) for i in range(a, b - hop, hop)]
        thr = max(rms) * 10 ** (-20 / 20)
        last = max(i for i, r in enumerate(rms) if r >= thr)
        out.append((a + (last + 1) * hop) / rate * 1000)
    return out


def score(lang, finals):
    """finals: [(arrival ms since clip start, text, end of the speech it covers in ms)]"""
    src = json.load(open(os.path.join(HERE, "sentences", f"{lang}.json")))
    hyp = " ".join(t for _, t, _ in finals)
    seg = [a - e for a, _, e in finals]
    sent, missing = [], 0
    for e in speech_ends(lang):
        cov = [a for a, _, se in finals if se >= e - 300]
        if cov:
            sent.append(cov[0] - e)
        else:
            missing += 1
    return {"cer": cer(" ".join(src), hyp), "turns": len(finals), "sentences": len(src),
            "segment_latency_ms_median": pct(seg, 0.5), "segment_latency_ms_p90": pct(seg, 0.9),
            "sentence_latency_ms_median": pct(sent, 0.5), "sentence_latency_ms_p90": pct(sent, 0.9),
            "transcript": hyp}


def gemini_finals(r):
    ends = [(o["at"], float(o["voiceActivity"]["audioOffset"].rstrip("s")) * 1000) for o in r["other"]
            if o.get("voiceActivity", {}).get("type") == "ACTIVITY_END"]
    out = []
    for f in r["finals"]:
        near = [e for a, e in ends if a <= f["at"] + 1500]
        out.append((f["at"], f.get("text", ""), max(near) if near else f["at"]))
    return out


rows = []
for p in sorted(glob.glob(os.path.join(HERE, "out", "stt-transcribe-live", "*.json"))):
    r = json.load(open(p))
    row = {"system": "gemini-3.5-transcribe-live", "lang": r["lang"], "mode": r["code"], "err": r["err"], "close": r["close"]}
    if not r["err"] and r["finals"]:
        row.update(score(r["lang"], gemini_finals(r)))
    rows.append(row)
for lang in ("en", "fr", "ja", "km", "lo"):
    p = os.path.join(HERE, "out", "stt", f"{lang}.json")
    if not os.path.exists(p):
        continue
    r = json.load(open(p))
    row = {"system": "azure-speech", "lang": lang, "mode": r["locale"], "err": r["err"]}
    if not r["err"] and r["finals"]:
        row.update(score(lang, [(f["arrivedMs"], f["text"], f["offsetMs"] + f["durationMs"]) for f in r["finals"]]))
    rows.append(row)

# ElevenLabs Scribe v2 Realtime (elevenlabs_stt.mjs), told the language and not.
for sub, mode in (("stt-elevenlabs", "given"), ("stt-elevenlabs-auto", "auto")):
    for p in sorted(glob.glob(os.path.join(HERE, "out", sub, "*.json"))):
        r = json.load(open(p))
        row = {"system": "elevenlabs-scribe-v2-rt", "lang": r["lang"], "mode": mode, "err": r["err"]}
        fs = [(f["arrivedMs"], f["text"], f["offsetMs"] + f["durationMs"]) for f in r["finals"] if f.get("offsetMs") is not None]
        if not r["err"] and fs:
            row.update(score(r["lang"], fs))
        rows.append(row)

ref = json.load(open(os.path.join(HERE, "text-mt", "out", "stt_cer.json")))
summary = {"note": "CER = judge.cer vs the verified text; latency in ms, see score_transcribe_live.py header",
           "runs": rows, "haitian_reference_cer": ref}
json.dump(summary, open(os.path.join(HERE, "stt_transcribe_live.json"), "w"), ensure_ascii=False, indent=1)
print(f"{'system':28} {'lang':4} {'mode':6} {'CER':>7} {'turns':>5} {'seg med':>7} {'seg p90':>7} {'sent med':>8} {'sent p90':>8}")
for r in rows:
    if r.get("err") or "cer" not in r:
        print(f"{r['system']:28} {r['lang']:4} {r['mode']:6} ERROR {r.get('err') or 'no finals'}")
    else:
        print(f"{r['system']:28} {r['lang']:4} {r['mode']:6} {r['cer']:7.1%} {r['turns']:5} {r['segment_latency_ms_median']:7} {r['segment_latency_ms_p90']:7} {r['sentence_latency_ms_median']:8} {r['sentence_latency_ms_p90']:8}")
