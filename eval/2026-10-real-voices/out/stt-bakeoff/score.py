# STT bake-off (2026-10-19): scores every run under out/stt-bakeoff/raw/
# (raw/el-realtime* = ../../elevenlabs_stt.mjs output, copied/written there) exactly as
# score_transcribe_live.py does: CER = judge.cer(" ".join(reference), hyp),
# hyp = the run's texts joined with spaces. Live systems also get
#   segment latency: final arrival minus the end of the speech it covers
#     (vendor timestamps / VAD), median and p90
#   sentence latency: per sentence, from its speech end (found from the audio,
#     as score_transcribe_live.speech_ends) to the first final covering it
# Batch per-sentence systems get the median request round trip ("if sent the
# moment the sentence ended"). Also counts Thai letters in Lao/Khmer output.
#
#   python3 out/stt-bakeoff/score.py   (from eval/2026-10-real-voices)
#   -> out/stt-bakeoff/summary.json + table
import array, glob, json, math, os, statistics, sys, wave
HERE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "2026-09-model-eval", "scripts"))
sys.path.insert(0, HERE)
from judge import cer  # noqa: E402

LANGS = ("en", "ja", "km", "lo")
RAW = os.path.join(HERE, "out", "stt-bakeoff", "raw")


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]) if xs else None


_ends = {}


def speech_ends(lang):
    if lang in _ends:
        return _ends[lang]
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
    _ends[lang] = out
    return out


def ref(lang):
    return " ".join(json.load(open(os.path.join(HERE, "sentences", f"{lang}.json"))))


def script_share(text):
    letters = [c for c in text if c.isalpha()]
    n = len(letters) or 1
    return {"thai": round(sum("฀" <= c <= "๿" for c in letters) / n, 3),
            "lao": round(sum("຀" <= c <= "໿" for c in letters) / n, 3),
            "khmer": round(sum("ក" <= c <= "៿" for c in letters) / n, 3),
            "latin": round(sum(c.isascii() for c in letters) / n, 3),
            "replacement_chars": text.count("\ufffd")}


def live_row(lang, finals):
    """finals: [(arrival ms, text, end ms of the speech it covers or None)]"""
    hyp = " ".join(t for _, t, _ in finals if t)
    seg = [a - e for a, _, e in finals if e is not None]
    sent = []
    for e in speech_ends(lang):
        cov = [a for a, _, se in finals if se is not None and se >= e - 300]
        if cov:
            sent.append(cov[0] - e)
    return {"cer": cer(ref(lang), hyp), "turns": len(finals),
            "segment_latency_ms_median": pct(seg, 0.5), "segment_latency_ms_p90": pct(seg, 0.9),
            "sentence_latency_ms_median": pct(sent, 0.5), "sentence_latency_ms_p90": pct(sent, 0.9),
            "script": script_share(hyp), "transcript": hyp}


LABEL = {
    "el-scribe-v2": ("ElevenLabs Scribe v2 (batch, whole clip)", "batch"),
    "aai-batch": ("AssemblyAI batch (U-3.5 Pro, U-2 fallback; whole clip)", "batch"),
    "oai__gpt-transcribe": ("OpenAI gpt-transcribe (per sentence)", "batch"),
    "oai__gpt-4o-transcribe": ("OpenAI gpt-4o-transcribe (per sentence)", "batch"),
    "oai__gpt-4o-mini-transcribe": ("OpenAI gpt-4o-mini-transcribe (per sentence)", "batch"),
    "gem__gemini-3.1-pro-preview": ("Gemini 3.1 Pro preview (per sentence)", "batch"),
    "gem__gemini-3.8-flash": ("Gemini 3.8 Flash (per sentence)", "batch"),
    "oai-live": ("OpenAI gpt-live-transcribe (Realtime; commit 0.5 s after speech end)", "live"),
    "aai-stream": ("AssemblyAI Universal-3.6 Pro Streaming", "live"),
    "el-realtime": ("ElevenLabs Scribe v2 Realtime (VAD 1.5 s default)", "live"),
    "el-realtime-vad05": ("ElevenLabs Scribe v2 Realtime (VAD 0.5 s)", "live"),
}

rows = []
for sysdir in sorted(os.listdir(RAW)):
    for lang in LANGS:
        p = os.path.join(RAW, sysdir, f"{lang}.json")
        if not os.path.exists(p):
            continue
        r = json.load(open(p))
        label, kind = LABEL.get(sysdir, (sysdir, "?"))
        row = {"system": sysdir, "label": label, "kind": kind, "lang": lang, "err": r.get("err", "")}
        for k in ("model", "requested", "language", "languageGiven", "transcription", "codeRefused"):
            if r.get(k) is not None:
                row[k] = r[k]
        if sysdir.startswith("el-realtime"):
            row["language"] = (r.get("config") or {}).get("language_code")
            fs = [(f["arrivedMs"], f["text"], f["offsetMs"] + f["durationMs"]) for f in r["finals"] if f.get("offsetMs") is not None]
            if fs:
                row.update(live_row(lang, fs))
        elif kind == "live":
            fs = [(f["arrivedMs"], f["text"], f.get("endMs")) for f in r.get("finals", [])]
            if fs:
                row.update(live_row(lang, fs))
        elif r.get("text"):
            row.update({"cer": cer(ref(lang), r["text"]), "script": script_share(r["text"]), "transcript": r["text"]})
            if r.get("rows"):
                ok = [x for x in r["rows"] if not x.get("err")]
                row["sentences_ok"] = len(ok)
                row["request_ms_median"] = pct([x["ms"] for x in ok], 0.5)
                row["request_ms_p90"] = pct([x["ms"] for x in ok], 0.9)
            elif r.get("ms"):
                row["request_ms_whole_clip"] = r["ms"]
        rows.append(row)

BASE = {"Azure Speech (live)": {"en": 0.064, "ja": 0.102, "km": 0.133, "lo": 0.179},
        "Google gemini-3.5-transcribe-live (live)": {"en": 0.142, "ja": 0.073, "km": 0.108, "lo": 0.302},
        "Omnilingual ASR (open stack, live)": {"en": 0.274, "ja": 0.351, "km": 0.300, "lo": 0.240}}

# What each vendor officially lists (checked 2026-10-19; docs, or the API's own refusal).
LISTED = {
    "Azure Speech": "en-US, ja-JP, km-KH, lo-LA all listed (live)",
    "ElevenLabs Scribe v2 / v2 Realtime": "all four; docs tier: Japanese 'excellent' (<=5% WER), Khmer and Lao 'moderate' (>25-50% WER)",
    "OpenAI gpt-transcribe / gpt-4o(-mini)-transcribe": "en, ja accepted as codes; km and lo refused as codes ('not recognized', 'invalid_value'), so the prompt names the language",
    "OpenAI gpt-live-transcribe (Realtime)": "en, ja in its supported-values list; km, lo refused (prompt names the language); refuses server turn detection",
    "AssemblyAI batch": "Universal-3.5 Pro: 18 languages incl. ja, not km/lo; Universal-2 (fallback): 99 incl. km, lo. 'universal-3-6-pro' refused for batch",
    "AssemblyAI streaming": "universal-3-6-pro language_codes: en, ja (+30 others), not km or lo (refused)",
    "Gemini (generateContent)": "no ASR-specific list; Gemini's language list includes all four",
}
# Gemini sentences that never came back (blocked 'OTHER' / repeated 180 s timeouts) count as
# deletions in the CER above; CER on the sentences that did come back:
GAPS = {"gem__gemini-3.1-pro-preview/km": {"missing": [3], "cer_answered": 0.097, "why": "4 x 180 s timeouts"},
        "gem__gemini-3.8-flash/km": {"missing": [0], "cer_answered": 0.082, "why": "promptFeedback.blockReason OTHER, 3 tries"},
        "gem__gemini-3.8-flash/lo": {"missing": [6, 28], "cer_answered": 0.104, "why": "promptFeedback.blockReason OTHER, 3 tries"}}
COST = "about $2-3 in all at list prices (22.4 min of audio per pass; ~13 passes incl. retries; Gemini 3.1 Pro thinking ~$0.6 the largest item)"

summary = {"date": "2026-10-19", "officially_listed": LISTED, "gemini_gaps": GAPS, "cost_estimate": COST,
           "note": "CER = judge.cer(' '.join(reference), hyp), as score_transcribe_live.py; latency ms, see score.py header",
           "baselines_cer": BASE, "runs": rows}
json.dump(summary, open(os.path.join(HERE, "out", "stt-bakeoff", "summary.json"), "w"), ensure_ascii=False, indent=1)

# Table: system x language CER.
table = {}
for r in rows:
    table.setdefault(r["label"], {})[r["lang"]] = r
print(f"{'system':58} " + " ".join(f"{l:>13}" for l in LANGS))
for name, d in BASE.items():
    print(f"{name:58} " + " ".join(f"{d[l]:13.1%}" for l in LANGS))
for name, d in table.items():
    cells = []
    for l in LANGS:
        r = d.get(l)
        if not r:
            cells.append(f"{'-':>13}")
        elif "cer" not in r:
            cells.append(f"{'ERR':>13}")
        else:
            lat = r.get("sentence_latency_ms_median") or r.get("request_ms_median")
            cells.append(f"{r['cer']:6.1%}{'' if lat is None else f' {lat/1000:5.1f}s':>7}")
    print(f"{name:58} " + " ".join(cells))
print("\n(live: CER + median sentence latency; per-sentence batch: CER + median request round trip)")
for r in rows:
    if r["lang"] in ("lo", "km") and "script" in r:
        print(f"  script {r['system']:30} {r['lang']} {r['script']}")
