# Character (and, for spaced scripts, word) error of each recogniser against the
# FLEURS text, pooled over the language's 20 sentences. Normalisation as
# eval/2026-10-real-voices/judge.py: NFKC, lowercase, letters and digits only
# (words: split on anything else). Numbers are not spelled out: a recogniser
# writing "2016" where the text says it in words is counted wrong, the same for every system.
#
#   python3 -I score.py WORK   -> WORK/asr_scores.json
import json, os, sys, unicodedata

WORK = sys.argv[1]
SPACED = {"vi", "fa", "kea", "ar", "sw", "fil", "uk"}


def chars(s):
    return [c for c in unicodedata.normalize("NFKC", s).lower() if c.isalnum()]


def words(s):
    t = "".join(c if c.isalnum() else " " for c in unicodedata.normalize("NFKC", s).lower())
    return t.split()


def ed(a, b):
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i]
        for j in range(1, len(b) + 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1])))
        prev = cur
    return prev[-1]


def main():
    sentences = json.load(open(os.path.join(WORK, "sentences.json")))
    out = {}
    for f in sorted(os.listdir(os.path.join(WORK, "asr"))):
        system, lang = f[:-5].split("_", 1)
        hyp = json.load(open(os.path.join(WORK, "asr", f)))
        refs = sentences[lang]
        ce = cn = we = wn = 0
        empty = 0
        for r, h in zip(refs, hyp):
            empty += not h["text"]
            a, b = chars(r["text"]), chars(h["text"])
            ce += ed(a, b); cn += len(a)
            if lang in SPACED:
                a, b = words(r["text"]), words(h["text"])
                we += ed(a, b); wn += len(a)
        s = [h["s"] for h in hyp if h.get("s") is not None]
        out.setdefault(lang, {})[system] = {
            "cer": round(100 * ce / cn, 1), "wer": round(100 * we / wn, 1) if wn else None,
            "empty": empty, "p50_s": sorted(s)[len(s) // 2] if s else None}
    json.dump(out, open(os.path.join(WORK, "asr_scores.json"), "w"), indent=1)
    for lang, v in out.items():
        print(lang, "  ".join(f"{k}: CER {x['cer']}" + (f" WER {x['wer']}" if x["wer"] is not None else "") + (f" empty {x['empty']}" if x["empty"] else "") for k, x in v.items()))


if __name__ == "__main__":
    main()
