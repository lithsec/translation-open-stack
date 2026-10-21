"""Metrics-only results.json from the Azure continuous-speech runs.

    python3 collect.py <runs dir> <clip dir> results.json

<runs dir> holds the harness's per-run files: <run>.json (event log),
<run>.stats.json (azstats: chunks and lags), <run>.judge_summary.json (judge),
<lang>-gemini-lt.lat.txt (Gemini Live Translate timings) and <run>.log.
<clip dir> holds the five-minute clips as <lang>.wav (16 kHz mono).
Only numbers are written: no transcript, translation or judge text.
"""
import json
import os
import re
import sys
import wave

import numpy as np

RUNS, CLIPS, OUT = sys.argv[1:4]
LANGS = ["es", "fr", "ja"]
# gpt-5.6-sol, Data Zone Standard, short context (Azure Retail Prices API, eastus2, 2026-10-21), $ per million tokens
P_IN, P_CACHED, P_OUT = 4.40, 0.44, 22.0
CLIP_H = 300 / 3600


def jl(name):
    p = os.path.join(RUNS, name)
    return json.load(open(p)) if os.path.exists(p) else None


def pauses(lang):
    """Pauses in the clip: runs of 10 ms frames more than 25 dB below the clip's 90th-percentile level."""
    with wave.open(os.path.join(CLIPS, f"{lang}.wav")) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float)
    f = 160
    n = len(x) // f
    db = 20 * np.log10(np.sqrt((x[: n * f].reshape(n, f) ** 2).mean(axis=1)) / 32768 + 1e-9)
    q = db < np.percentile(db, 90) - 25
    runs, i = [], 0
    while i < n:
        if q[i]:
            j = i
            while j < n and q[j]:
                j += 1
            runs.append((j - i) * 10)
            i = j
        else:
            i += 1
    return {str(lo): sum(1 for d in runs if d >= lo) for lo in (150, 300, 600, 1000)}


def tokens(run):
    ev = run["events"]
    f = [e for e in ev if e["kind"] == "foundry"]
    u = [e for e in f if e.get("prompt") is not None]
    if not u:
        return None
    mean = lambda k: round(sum(e.get(k) or 0 for e in u) / len(u))  # noqa: E731
    cost = sum(((e["prompt"] - (e.get("cached") or 0)) * P_IN + (e.get("cached") or 0) * P_CACHED + e["completion"] * P_OUT) / 1e6 for e in u)
    return {"calls": len(f), "calls_per_hour": round(len(f) / CLIP_H), "non200": sum(1 for e in f if e["status"] != 200),
            "mean_prompt_tokens": mean("prompt"), "mean_cached_tokens": mean("cached"), "mean_completion_tokens": mean("completion"),
            "mean_reasoning_tokens": mean("reasoning"), "usd_per_hour": round(cost / CLIP_H, 2)}


def pipeline(name):
    s = jl(f"{name}.stats.json")
    j = jl(f"{name}.judge_summary.json")
    if s is None:
        # a repeat that was only judged: its quality, no timing breakdown
        return {"quality": {"pct_of_max": j["quality_pct"], "critical": j["critical"], "sentences": j["n"], "source_cer": j["cer"]}} if j else None
    out = {"segmentation": "semantic" if s["seg"] == "semantic" else "pause (LT default)", "chunks": s["chunks"],
           "chunk_s": dict(zip(("p50", "p90", "max"), s["chunk_s_p50_p90_max"])), "chunks_over_10s": s["chunks_over_10s"],
           "start_to_first_audio_s": s["start_to_first_voice_s"],
           "chunk_start_to_its_audio_s": dict(zip(("p50", "p90"), s["chunkstart_to_first_voice_played_p50_p90"])),
           "chunk_end_to_its_audio_s": dict(zip(("p50", "p90"), s["chunkend_to_first_voice_played_p50_p90"])),
           "last_word_to_end_of_translation_s": s["lastword_to_last_voice_end_played_s"]}
    if j:
        out["quality"] = {"pct_of_max": j["quality_pct"], "critical": j["critical"], "sentences": j["n"], "source_cer": j["cer"]}
    return out


def behind(log):
    """Largest "voice N s behind" the app logged."""
    p = os.path.join(RUNS, log)
    if not os.path.exists(p):
        return None
    v = [float(m) for m in re.findall(r"voice ([0-9.]+) s behind", open(p).read())]
    return max(v) if v else None


def speculation(log):
    p = os.path.join(RUNS, log)
    if not os.path.exists(p):
        return None
    m = re.search(r"speculation \(\w+\): (\d+)/(\d+) finals hit, (\d+) started", open(p).read())
    return {"finals_hit": int(m.group(1)), "finals": int(m.group(2)), "started": int(m.group(3))} if m else None


res = {"date": "2026-10-21", "lt_commit": "66ae717", "judge": "gemini-3.1-pro-preview",
       "reference": "gemini-3.1-pro-preview transcript and English translation of each clip; not checked by a person",
       "prices_usd_per_million_tokens": {"input": P_IN, "cached_input": P_CACHED, "output": P_OUT, "model": "gpt-5.6-sol (Data Zone Standard), reasoning low"},
       "langs": {}}
for l in LANGS:
    lat = open(os.path.join(RUNS, f"{l}-gemini-lt.lat.txt")).read()
    lat = json.loads(lat[: lat.rindex("}") + 1])
    g = jl(f"{l}-gemini-lt.judge_summary.json")
    tok = jl(f"{l}-tok.json")
    spec = jl(f"{l}-spec.json")
    res["langs"][l] = {
        "pauses_at_least_ms": pauses(l),
        "default": pipeline(f"{l}-default"),
        "default_repeat": pipeline(f"{l}-default.r1"),
        "semantic": pipeline(f"{l}-semantic"),
        "semantic_repeat": pipeline(f"{l}-semantic.r1"),
        "gemini_lt": {"start_to_first_audio_s": lat["start_to_first_voiced_s"], "last_word_to_end_of_translation_s": lat["lastword_to_last_voiced_end_played_s"],
                      "quality": {"pct_of_max": g["quality_pct"], "critical": g["critical"], "sentences": g["n"]}},
        "translation_tokens": tokens(tok) if tok else None,
        "speculation": ({**speculation(f"{l}-spec.log"),
                         "translation_calls_answered": sum(1 for e in spec["events"] if e["kind"] == "foundry" and e["status"] == 200),
                         "translation_calls_refused": sum(1 for e in spec["events"] if e["kind"] == "foundry" and e["status"] != 200),
                         "usd_per_hour": tokens(spec)["usd_per_hour"]} if spec else None),
        "streaming_max_voice_behind_s": behind(f"{l}-stream.log"),
    }
json.dump(res, open(OUT, "w"), indent=1, ensure_ascii=False)
print("wrote", OUT)
