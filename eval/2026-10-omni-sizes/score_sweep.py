"""Scores endpoint_sweep.py's runs (out_sweep/<card>.json).

    python3 score_sweep.py out_sweep/omniASR_LLM_300M.json [more.json ...] [--json summary.json]

Per (card, lang, ENDPOINT_MS, MAX_UTTERANCE_S):
  cer        judge.cer(" ".join(the 30 reference sentences), " ".join(segment texts))
  segments   utterances the Segmenter handed out (30 sentences per clip)
  forced     of those, cut by MAX_UTTERANCE_S
  mid_cuts   segment boundaries inside a sentence (more than 300 ms after the
             sentence's mark starts and 300 ms before its speech ends): a sentence
             chopped in two, whether by a pause or a forced cut
  seg_wait   for turns ended by a pause: emit - the end of the last speech block
             (the endpoint wait, audio time), median / p90
  sent_wait  what a listener waits for each sentence: emit of the first segment
             whose end reaches the sentence's speech end (found from the audio as
             in ../2026-10-real-voices/score_transcribe_live.py) minus that end;
             median / p90. A sentence held in a long turn waits for the turn.
  dropped    sentences less than 10% inside any segment (the VAD heard nothing:
             the quiet FLEURS recordings); left out of sent_wait
  longest_s  the longest segment (the forced cut caps it at MAX_UTTERANCE_S)
  decode_p90 p90 decode time per segment on the GPU (wall seconds), to add to
             the waits for the time to text
"""
import array
import json
import math
import os
import statistics
import sys
import types
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
RV = HERE.parent / "2026-10-real-voices"
sys.path.insert(0, str(HERE.parent / "2026-09-model-eval" / "scripts"))
sys.path.insert(0, str(RV))
sys.modules.setdefault("vertex", types.SimpleNamespace(gemini=None))  # judge.py imports it; cer() doesn't use it
from judge import cer  # noqa: E402


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]) if xs else None


_ends = {}


def speech_ends(lang):
    """(mark start ms, speech end ms) per sentence, as score_transcribe_live.py."""
    if lang in _ends:
        return _ends[lang]
    with wave.open(str(RV / "audio" / f"{lang}.wav")) as w:
        rate, pcm = w.getframerate(), array.array("h", w.readframes(w.getnframes()))
    hop = rate // 50
    out = []
    for m in json.load(open(RV / "audio" / f"{lang}.json"))["sentences"]:
        a, b = int(m["start"] * rate), int(m["end"] * rate)
        rms = [math.sqrt(sum(x * x for x in pcm[i:i + hop]) / hop) for i in range(a, b - hop, hop)]
        thr = max(rms) * 10 ** (-20 / 20)
        last = max(i for i, r in enumerate(rms) if r >= thr)
        out.append((m["start"] * 1000, (a + (last + 1) * hop) / rate * 1000))
    _ends[lang] = out
    return out


def score_run(run):
    lang, segs = run["lang"], run["segments"]
    refs = json.load(open(RV / "sentences" / f"{lang}.json"))
    sents = speech_ends(lang)
    hyp = " ".join(s["text"] for s in segs if s["text"])
    paused = [s["emit_ms"] - s["speech_end_ms"] for s in segs if not s["forced"] and not s.get("flush")]
    sent_wait, missing = [], 0
    for a, e in sents:
        heard = sum(max(0, min(e, s["end_ms"]) - max(a, s["start_ms"])) for s in segs) / (e - a)
        cov = [s["emit_ms"] for s in segs if s["end_ms"] >= e - 300]
        if heard < 0.1 or not cov:
            missing += 1  # the VAD heard (almost) none of it: no wait to speak of
        else:
            sent_wait.append(cov[0] - e)
    mid = sum(1 for s in segs[:-1] for a, e in sents if a + 300 < s["end_ms"] < e - 300)
    return {"lang": lang, "endpoint_ms": run["endpoint_ms"], "max_s": run["max_s"],
            "cer": cer(" ".join(refs), hyp), "segments": len(segs),
            "forced": sum(bool(s["forced"]) for s in segs), "mid_cuts": mid,
            "seg_wait_ms_median": pct(paused, 0.5), "seg_wait_ms_p90": pct(paused, 0.9),
            "sent_wait_ms_median": pct(sent_wait, 0.5), "sent_wait_ms_p90": pct(sent_wait, 0.9),
            "dropped": missing,
            "longest_s": round(max((s["end_ms"] - s["start_ms"]) / 1000 for s in segs), 2),
            "decode_s_p90": round(sorted(s["decode_s"] for s in segs)[int(0.9 * (len(segs) - 1))], 3)}


def main():
    args = sys.argv[1:]
    out = None
    if "--json" in args:
        i = args.index("--json")
        out = args[i + 1]
        del args[i:i + 2]
    summary = []
    for p in args:
        d = json.load(open(p))
        rows = [score_run(r) for r in d["runs"]]
        summary.append({k: d[k] for k in ("card", "gpu", "load_s", "rtf_batch1", "decoded_audio_s", "mem_peak_gb", "segmenter") if k in d}
                       | {"rows": rows})
        print(f"\n{d['card']}  ({d.get('gpu')}, rtf b1 {d.get('rtf_batch1')}, peak {d.get('mem_peak_gb')} GB)")
        print(f"{'lang':4} {'ep':>4} {'max':>4} {'CER':>6} {'segs':>4} {'forc':>4} {'mid':>4} {'segw50':>6} {'segw90':>6} "
              f"{'sntw50':>6} {'sntw90':>6} {'long':>5} {'dec90':>5} {'drop':>4}")
        for r in rows:
            print(f"{r['lang']:4} {r['endpoint_ms']:>4} {r['max_s']:>4.0f} {r['cer'] * 100:>5.1f}% {r['segments']:>4} {r['forced']:>4} "
                  f"{r['mid_cuts']:>4} {r['seg_wait_ms_median']!s:>6} {r['seg_wait_ms_p90']!s:>6} {r['sent_wait_ms_median']!s:>6} "
                  f"{r['sent_wait_ms_p90']!s:>6} {r['longest_s']:>5} {r['decode_s_p90']:>5} {r['dropped']:>4}")
    if out:
        Path(out).write_text(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
