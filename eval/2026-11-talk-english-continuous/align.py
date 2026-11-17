# Text alignment of a run's finals to the read sentences, used instead of audio offsets: MAI-Transcribe-2-Streaming's
# offsets and durations run behind and short (a final holding sentence 13 of set a, read at 117.4-125.1 s, says
# 127.0-131.0 s), so grouping by offset (../2026-10-translator-shootout/shootout.py group) moves its text into the
# wrong sentences. Both recognisers are aligned the same way.
#   sentences(finals, gold)   the finals joined and cut where the read sentences end (shootout.py split_like)
#   cuts(finals, gold)        per final: does it end inside a read sentence (mid-sentence: 10 or more characters from
#                             both ends of the sentence it ends in), and does it span two or more sentences (joined)
import difflib, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-translator-shootout"))
from shootout import split_like  # noqa: E402


def sentences(finals, gold):
    return split_like(" ".join(f["text"] for f in finals), gold)


def cuts(finals, gold):
    low = lambda s: s.lower()
    hyp, ends, pos = "", [], 0
    for f in finals:
        hyp += ("" if not hyp else " ") + f["text"]
        ends.append(len(hyp))
    g = " ".join(gold)
    spans, p = [], 0
    for s in gold:
        spans.append((p, p + len(s)))
        p += len(s) + 1
    sm = difflib.SequenceMatcher(None, low(hyp), low(g), autojunk=False)
    blocks = sm.get_matching_blocks()

    def to_gold(i):
        best = None
        for a, b, n in blocks:
            if a <= i <= a + n:
                return b + (i - a)
            if a > i:
                return b if best is None else best
            best = b + n
        return len(g)

    def sent_of(gi):
        for k, (a, b) in enumerate(spans):
            if gi <= b:
                return k
        return len(spans) - 1

    out, start = [], 0
    for e in ends:
        ge, gs = to_gold(e), to_gold(start)
        k = sent_of(ge)
        a, b = spans[k]
        out.append({"mid": ge - a >= 10 and b - ge >= 10, "joined": sent_of(gs + 1) != k})
        start = e + 1
    return out
