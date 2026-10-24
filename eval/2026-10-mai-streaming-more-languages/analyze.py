# Score stream.py's runs: accuracy with ../2026-10-whisper-vs-azure/score.py (the
# same normalisation and alignment; the FLEURS text is the only reference here, so
# "said" = "text"), and latency per sentence from the arrival times:
#   first partial  the first partial of a new segment (the first after a final) that
#                  arrives after the sentence starts, measured from its start
#   final          the last final overlapping the sentence, measured from the end of its
#                  FLEURS recording (which carries trailing silence, so values can be
#                  negative; compare the two systems, not the absolute number)
#
#   python3 -I analyze.py WORK OUT.json      (WORK/data/clips/<lang>.json, WORK/out/<system>_<lang>.json)
import json, os, statistics as st, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "2026-10-whisper-vs-azure"))
import score as sc  # noqa: E402

# Digits spelled in the language where num2words has it (both systems alike either way).
sc.N2W.update({"vi": "vi", "fa": "fa", "ar": "ar", "uk": "uk"})
UNSPACED = {"zh"}          # characters only, scored the way score.py scores Japanese
WORK, OUTP = sys.argv[1], sys.argv[2]
LANGS = ["vi", "fa", "zh", "ar", "sw", "fil", "uk"]


def pct(v, q):
    v = sorted(v)
    return round(v[min(len(v) - 1, int(q * len(v)))]) if v else None


res = []
for lang in LANGS:
    meta = json.load(open(os.path.join(WORK, "data", "clips", f"{lang}.json")))["sentences"]
    refs = [s["text"] for s in meta]
    for system in ("mai", "azure"):
        p = os.path.join(WORK, "out", f"{system}_{lang}.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        finals = sorted(d["finals"], key=lambda f: f["offsetMs"])
        hyp = " ".join(f["text"] for f in finals)
        s = sc.score("ja" if lang in UNSPACED else lang, refs, refs, hyp)
        # A segment's first partial: the first partial after a final (MAI reports
        # offset 0 on every partial, so arrival order is the common ground).
        ev = sorted([(x["arrivedMs"], "p") for x in d["partials"]] + [(f["arrivedMs"], "f") for f in finals])
        seg_starts, after_final = [], True
        for t, k in ev:
            if k == "f":
                after_final = True
            elif after_final:
                seg_starts.append(t)
                after_final = False
        first, fin = [], []
        for m in meta:
            a, b = m["start"] * 1000, m["end"] * 1000
            ps = [t for t in seg_starts if a <= t <= b + 1500]
            if ps:
                first.append(min(ps) - a)
            fs = [f["arrivedMs"] for f in finals if f["offsetMs"] < b and f["offsetMs"] + f["durationMs"] > a]
            if fs:
                fin.append(max(fs) - b)
        row = {"lang": lang, "system": system, "err": d.get("err", ""),
               "cer": s["text"]["cer"], "wer": None if lang in UNSPACED else s["text"].get("wer"),
               "dropped": len(s["dropped"]), "missing_starts": len(s["missing_starts"]),
               "finals": len(finals), "first_partial_p50_ms": pct(first, .5),
               "final_after_end_p50_ms": pct(fin, .5), "final_after_end_p90_ms": pct(fin, .9)}
        res.append(row)
        print(json.dumps(row), flush=True)
json.dump(res, open(OUTP, "w"), indent=1)
