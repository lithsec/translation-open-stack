# Character and word error of each recogniser against the FLEURS text, pooled per language and set.
# Normalisation as ../2026-10-language-short-check/score.py (NFKC, lowercase, letters and digits only),
# plus two folds so spelling conventions aren't counted as errors: Romanian ş/ţ (cedilla) -> ș/ț
# (comma below), Russian ё -> е. Romanian also gets the share of its reference diacritics (ă â î ș ț)
# that come back without them ("diacritics lost"), counted on aligned characters.
#   python3 -I score_asr.py WORK   -> WORK/asr_scores.json
import difflib, json, sys, unicodedata
from pathlib import Path

WORK = Path(sys.argv[1])
FOLD = str.maketrans({"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț", "ё": "е", "Ё": "Е"})
RO_DIA = set("ăâîșț")
STRIP = {"ă": "a", "â": "a", "î": "i", "ș": "s", "ț": "t"}


def norm(s):
    s = unicodedata.normalize("NFKC", s).translate(FOLD).lower()
    return "".join(c if c.isalnum() else " " for c in s)


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def refs(lang):
    out = {}
    for st in ("a", "b"):
        for i, t in enumerate(json.load(open(WORK / f"clips_{st}_reg" / f"{lang}.txt.json"))):
            out[f"{st}{i:02d}"] = t
    return out


def dia_lost(ref, hyp):
    r, h = norm(ref).replace(" ", ""), norm(hyp).replace(" ", "")
    lost = tot = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, r, h, autojunk=False).get_opcodes():
        if op == "equal":
            tot += sum(c in RO_DIA for c in r[i1:i2])
        elif op == "replace" and i2 - i1 == j2 - j1:
            for a, b in zip(r[i1:i2], h[j1:j2]):
                if a in RO_DIA:
                    tot += 1
                    lost += STRIP[a] == b
    return lost, tot


res = {}
for f in sorted((WORK / "asr").glob("*.json")):
    d = json.load(open(f))
    sysname = f.stem
    for lang in ("de", "ru", "ro"):
        if lang not in d:
            continue
        R = refs(lang)
        for st in ("a", "b", "all"):
            rows = [r for r in d[lang] if st == "all" or r["id"].startswith(st)]
            ce = cn = we = wn = 0
            dl = dt = 0
            for r in rows:
                ref, hyp = norm(R[r["id"]]), norm(r["text"])
                ce += lev(ref.replace(" ", ""), hyp.replace(" ", "")); cn += len(ref.replace(" ", ""))
                we += lev(ref.split(), hyp.split()); wn += len(ref.split())
                if lang == "ro":
                    a, b = dia_lost(R[r["id"]], r["text"]); dl += a; dt += b
            cell = {"cer": round(100 * ce / cn, 1), "wer": round(100 * we / wn, 1), "n": len(rows),
                    "empty": sum(1 for r in rows if not r["text"].strip()),
                    "rtf": round(sum(r["decode_s"] for r in rows) / sum(r["audio_s"] for r in rows), 3)}
            if lang == "ro":
                cell["diacritics_lost_pct"] = round(100 * dl / dt, 1) if dt else None
            res.setdefault(sysname, {}).setdefault(lang, {})[st] = cell
json.dump(res, open(WORK / "asr_scores.json", "w"), indent=1)
for s, v in res.items():
    print(s, {l: (c["all"]["cer"], c["all"]["wer"], c["all"].get("diacritics_lost_pct")) for l, c in v.items()})
