# One scorer for every system: CER (characters, spaces removed) and WER (not for
# Japanese) on the whole clip's text, after the same normalisation for every system
# and reference (Unicode NFKC; digits spelled out with num2words, "11th" as an
# ordinal, "1,000" and "1.000" as one number; lower case; punctuation to spaces), against
# "what was said" (../2026-10-unseen witness.py) and against the written text.
# The clip's hypothesis is every piece the system returned, in order, joined.
#
# Per sentence, from the alignment against what was said:
#   dropped        >= 80% of the sentence's reference tokens deleted
#   missing start  two or more of its first three words deleted (Japanese: three or
#                  more of its first five characters), in sentences not dropped
#
#   python3 -I score.py MANIFEST.json OUT.json
# MANIFEST: {"refs": {lang: {"said": witness.json, "text": <lang>.txt.json}},
#            "runs": [{"lang", "pattern", "system", "kind", "path"}]}
#   kind: sentences  {"sentences": [{"i", "text"}]}             (systems 1 and 4)
#         finals     {"finals": [{"text", "offsetMs"}]}         (system 3)
#         live       e2e_client output: events of kind "input"  (system 2)
import json, re, sys, unicodedata
from num2words import num2words   # pip install num2words==0.5.14

N2W = {"en": "en", "es": "es", "pt": "pt_BR", "fr": "fr", "ja": "ja"}
ORD = re.compile(r"(\d+)(st|nd|rd|th|º|ª|e|er|ère|ème)\b", re.I)


def spell(s, lang):
    """Digits to words, so "11th" and "eleventh", "12" and "twelve" score alike."""
    lg = N2W.get(lang, "en")
    s = re.sub(r"(?<=\d)[,.](?=\d{3}\b)", "", s)            # 1,000 / 1.000 -> 1000
    s = ORD.sub(lambda m: " " + num2words(int(m.group(1)), lang=lg, to="ordinal") + " ", s)
    return re.sub(r"\d+", lambda m: " " + num2words(int(m.group(0)), lang=lg) + " ", s)


def norm(s, lang="en"):
    s = spell(unicodedata.normalize("NFKC", s), lang).lower()
    s = re.sub(r"[^\w\s]|_", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s, lang):
    s = norm(s, lang)
    return list(s.replace(" ", "")) if lang == "ja" else s.split()


def align(ref, hyp):
    """Levenshtein with backtrace: per reference token, 'm', 's' or 'd'; plus the counts."""
    n, m = len(ref), len(hyp)
    prev = list(range(m + 1))
    back = [[0] * (m + 1) for _ in range(n + 1)]
    for j in range(1, m + 1):
        back[0][j] = 2
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        back[i][0] = 1
        r = ref[i - 1]
        for j in range(1, m + 1):
            sub = prev[j - 1] + (r != hyp[j - 1])
            dele = prev[j] + 1
            ins = cur[j - 1] + 1
            best = min(sub, dele, ins)
            cur[j] = best
            back[i][j] = 0 if best == sub else (1 if best == dele else 2)
        prev = cur
    dist = prev[m]
    ops = [None] * n
    i, j = n, m
    while i > 0 or j > 0:
        b = back[i][j]
        if i > 0 and j > 0 and b == 0:
            ops[i - 1] = "m" if ref[i - 1] == hyp[j - 1] else "s"
            i, j = i - 1, j - 1
        elif i > 0 and (j == 0 or b == 1):
            ops[i - 1] = "d"
            i -= 1
        else:
            j -= 1
    return dist, ops


def hyp_text(run):
    d = json.load(open(run["path"]))
    if run["kind"] == "sentences":
        return " ".join(s["text"] for s in sorted(d["sentences"], key=lambda s: s["i"]))
    if run["kind"] == "finals":
        return " ".join(f["text"] for f in sorted(d["finals"], key=lambda f: f["offsetMs"]))
    return " ".join(e["text"] for e in d["events"] if e.get("kind") == "input")


def score(lang, refs_said, refs_text, hyp):
    out = {}
    for name, refs in (("said", refs_said), ("text", refs_text)):
        ref_joined = " ".join(refs)
        c_ref, c_hyp = list(norm(ref_joined, lang).replace(" ", "")), list(norm(hyp, lang).replace(" ", ""))
        cer = align(c_ref, c_hyp)[0] / max(1, len(c_ref))
        r = {"cer": round(100 * cer, 1)}
        if lang != "ja":
            w_ref, w_hyp = tokens(ref_joined, lang), tokens(hyp, lang)
            r["wer"] = round(100 * align(w_ref, w_hyp)[0] / max(1, len(w_ref)), 1)
        out[name] = r
    # Per sentence, against what was said.
    per = [tokens(s, lang) for s in refs_said]
    flat = [t for p in per for t in p]
    _, ops = align(flat, tokens(hyp, lang))
    k, dropped, missing = 0, [], []
    head, need = (5, 3) if lang == "ja" else (3, 2)
    for i, p in enumerate(per):
        o = ops[k:k + len(p)]
        k += len(p)
        if p and sum(x == "d" for x in o) >= 0.8 * len(p):
            dropped.append(i)
        elif sum(x == "d" for x in o[:head]) >= need:
            missing.append(i)
    out["dropped"], out["missing_starts"] = dropped, missing
    return out


if __name__ == "__main__":
    man = json.load(open(sys.argv[1]))
    refs = {}
    for lang, r in man["refs"].items():
        said = {w["i"]: w.get("said") for w in json.load(open(r["said"]))}
        text = json.load(open(r["text"]))
        refs[lang] = ([said.get(i) or t for i, t in enumerate(text)], text)
    res = []
    for run in man["runs"]:
        s = score(run["lang"], *refs[run["lang"]], hyp_text(run))
        res.append({k: run[k] for k in ("lang", "pattern", "system")} | {"note": run.get("note", "")} | s)
        print(run["lang"], run["pattern"], run["system"], s["said"], len(s["dropped"]), len(s["missing_starts"]), flush=True)
    json.dump(res, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
