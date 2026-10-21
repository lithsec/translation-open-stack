"""Scores client.mjs runs on make_continuous.py's clips: where omni-stt's cuts
land, and what they do to the words.

    python3 score.py --audio audio --refs ../2026-10-real-voices/sentences RUN.json [RUN.json ...] [--json out.json]

RUN.json: services/omni-stt/client.mjs --out (one stream, or {"streams": [...]}),
each stream named by its file (audio/<lang>.wav). Per stream:

  utts         utterances with a transcript
  len_med/p90/max   utterance length, seconds (start_ms..end_ms)
  short        utterances under 3 s (the "3 words, 2.2 s" leftovers)
  cuts         boundaries between consecutive utterances
  in_gap       cuts inside a 100-250 ms gap between two sentences (±60 ms):
               certainly not mid-word
  split_words  (space-separated languages: ht, en) cuts where the last word
               before and the first word after join into one reference word
               better than either alone ("mache" + "y" for "machey"): a word
               cut in two. Found on a word alignment of the joined text with
               the joined references (rapidfuzz Levenshtein opcodes).
  damaged      (ht, en) cuts whose neighbourhood is not clean: the last word
               before or the first after is not the reference word aligned to
               it, or reference words between them are missing (a word lost
               at the cut, the usual result of cutting inside one), split_words
               included
  bnd_cer      character error rate in a 10-character window of the reference
               around each cut (every language), against cer for the clip:
               what a cut costs where it lands
  long_cuts, long_bnd_cer, long_damaged   the same for the cuts after an
               utterance of LONG_S (11.4 s) or more: the cap's cuts (forced,
               or early in its last 3.5 s), not a pause that ended a turn
  cer          judge.cer(joined references, joined transcripts)
"""
import argparse
import json
import os
import statistics
import sys
import types
import unicodedata
from pathlib import Path

from rapidfuzz.distance import Levenshtein

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "2026-10-real-voices"))
sys.modules.setdefault("vertex", types.SimpleNamespace(gemini=None))  # judge.py imports it; cer() doesn't use it
from judge import cer, norm  # noqa: E402

SPACED = {"ht", "en", "fr", "es"}
GAP_SLACK_MS = 60
WINDOW = 5
LONG_S = 11.4


def words(text):
    out = []
    for w in unicodedata.normalize("NFKC", text).lower().split():
        w = "".join(c for c in w if c.isalnum())
        if w:
            out.append(w)
    return out


def h2r_map(ref, hyp):
    """For each hyp position, the ref position it aligns to (an insertion: the
    ref position after it), from Levenshtein opcodes; plus per-ref-position
    error flags (a substituted or deleted ref unit, or an insertion before it)."""
    m = [0] * (len(hyp) + 1)
    err = [0] * (len(ref) + 1)
    for tag, i1, i2, j1, j2 in Levenshtein.opcodes(ref, hyp):
        for k in range(j1, j2):
            m[k] = min(i1 + (k - j1), i2 - 1) if tag in ("equal", "replace") and i2 > i1 else i1
        if tag != "equal":
            for i in range(i1, max(i2, i1 + 1)):
                err[min(i, len(ref))] = 1
    m[len(hyp)] = len(ref)
    return m, err


def score(run, marks, refs, lang):
    us = [u for u in run["utterances"] if u.get("text")]
    lens = sorted((u["end_ms"] - u["start_ms"]) / 1000 for u in us)
    sents = [(m["start"] * 1000, m["end"] * 1000) for m in marks]
    cuts = [u["end_ms"] for u in us[:-1]]
    in_gap = sum(1 for c in cuts if any(e - GAP_SLACK_MS <= c <= s + GAP_SLACK_MS
                                        for (_, e), (s, _) in zip(sents, sents[1:])))
    row = {"lang": lang, "utts": len(us), "len_med": round(statistics.median(lens), 1),
           "len_p90": round(lens[int(0.9 * (len(lens) - 1))], 1), "len_max": round(lens[-1], 1),
           "short": sum(1 for x in lens if x < 3), "cuts": len(cuts), "in_gap": in_gap,
           "cer": cer(" ".join(refs), " ".join(u["text"] for u in us))}
    # Character windows around each cut.
    rc = norm(" ".join(refs))
    hc, bounds = "", []
    for u in us:
        hc += norm(u["text"])
        bounds.append(len(hc))
    m, err = h2r_map(rc, hc)
    wins = []
    long_ = [(u["end_ms"] - u["start_ms"]) / 1000 >= LONG_S for u in us[:-1]]
    for b in bounds[:-1]:
        r = m[b] if b < len(hc) else len(rc)
        lo, hi = max(0, r - WINDOW), min(len(rc), r + WINDOW)
        wins.append(sum(err[lo:hi]) / max(1, hi - lo))
    row["bnd_cer"] = round(statistics.mean(wins), 3) if wins else None
    lw = [w for w, k in zip(wins, long_) if k]
    row["long_cuts"] = len(lw)
    row["long_bnd_cer"] = round(statistics.mean(lw), 3) if lw else None
    if lang in SPACED:
        rw = words(" ".join(refs))
        hw, wb = [], []
        for u in us:
            hw += words(u["text"])
            wb.append(len(hw))
        mw, _ = h2r_map(rw, hw)
        split = damaged = long_damaged = 0
        for j, k in zip(wb[:-1], long_):
            if j == 0 or j >= len(hw):
                continue
            a, b = hw[j - 1], hw[j]
            ra, rb = mw[j - 1], mw[j]
            if not (rb == ra + 1 and rw[ra] == a and rb < len(rw) and rw[rb] == b):
                damaged += 1
                long_damaged += k
            cands = {x for r in (mw[j - 1], mw[j]) for x in (r - 1, r, r + 1) if 0 <= x < len(rw)}
            for x in cands:
                r = rw[x]
                if a == r or b == r:
                    continue
                joined = Levenshtein.normalized_similarity(a + b, r)
                if joined >= 0.75 and joined > max(Levenshtein.normalized_similarity(a, r),
                                                   Levenshtein.normalized_similarity(b, r)) + 0.15:
                    split += 1
                    break
        row["split_words"] = split
        row["damaged"] = damaged
        row["long_damaged"] = long_damaged
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="make_continuous.py's output: <lang>.json marks")
    ap.add_argument("--refs", required=True, help="the reference sentences: <lang>.json (a list of strings)")
    ap.add_argument("--json")
    ap.add_argument("runs", nargs="+")
    a = ap.parse_args()
    rows = []
    for p in a.runs:
        d = json.load(open(p))
        for run in d.get("streams", [d]):
            lang = Path(run["file"]).stem
            marks = json.load(open(os.path.join(a.audio, f"{lang}.json")))["sentences"]
            refs = json.load(open(os.path.join(a.refs, f"{lang}.json")))
            rows.append({"run": Path(p).stem} | score(run, marks, refs, lang))
    cols = ["run", "lang", "utts", "len_med", "len_p90", "len_max", "short", "cuts", "in_gap", "split_words", "damaged",
            "bnd_cer", "long_cuts", "long_damaged", "long_bnd_cer", "cer"]
    print(" ".join(f"{c[:12]:>12}" for c in cols))
    for r in rows:
        print(" ".join(f"{str(r.get(c, '-')):>12}" for c in cols))
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
