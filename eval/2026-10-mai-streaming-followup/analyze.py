# Scores the follow-up runs with ../2026-10-whisper-vs-azure/score.py (one scorer for
# every system, against what was said) and breaks the gap down:
#   - Table: Azure standard streaming and MAI streaming on the whole clip (from
#     ../2026-10-mai-streaming-pipelines), MAI streaming pinned to the clip's
#     locale and MAI streaming one gold sentence per session (stream.py), and MAI
#     batch and Azure fast transcription per sentence (../2026-10-whisper-vs-azure).
#   - Japanese: CER again after both sides are converted to their kana reading
#     (pykakasi), so a word written in kanji on one side and kana on the other, or
#     a numeral against its reading, no longer counts as an error.
#   - English: each word error (against what was said) placed by where it falls
#     in the recogniser's finals: within one word of a final's edge, inside a run
#     of two or more deleted words, an inserted repeat of a neighbouring word, or
#     a substitution or single deletion inside a final.
#
#   python3 -I analyze.py RUNS.json OUT.json
# RUNS: {"refs": {lang: {"said", "text"}}, "runs": [{"lang", "system", "kind", "path"}]}
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-whisper-vs-azure"))
import score as S   # noqa: E402

try:
    import pykakasi   # pip install pykakasi==2.3.0
    KKS = pykakasi.kakasi()
except ImportError:   # the kana pass is skipped without it
    KKS = None


def kana(s):
    s = S.norm(s, "ja")
    return "".join(x["hira"] for x in KKS.convert(s)).replace(" ", "")


def path(ref, hyp):
    """Levenshtein alignment as a list of (ref index or None, hyp index or None)."""
    n, m = len(ref), len(hyp)
    D = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        D[i][0] = i
    for j in range(m + 1):
        D[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i][j] = min(D[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]), D[i - 1][j] + 1, D[i][j - 1] + 1)
    out, i, j = [], n, m
    while i or j:
        if i and j and D[i][j] == D[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            out.append((i - 1, j - 1)); i -= 1; j -= 1
        elif i and D[i][j] == D[i - 1][j] + 1:
            out.append((i - 1, None)); i -= 1
        else:
            out.append((None, j - 1)); j -= 1
    return out[::-1]


def english_breakdown(refs_said, finals):
    """Word errors of a finals run, by where they fall."""
    ref = S.tokens(" ".join(refs_said), "en")
    hyp, edge = [], []
    for f in sorted(finals, key=lambda f: f["offsetMs"]):
        t = S.tokens(f["text"], "en")
        for k, w in enumerate(t):
            hyp.append(w)
            edge.append(k == 0 or k == len(t) - 1 or k == 1 or k == len(t) - 2)   # within one word of an edge
    p = path(ref, hyp)
    cats = {"boundary": 0, "dropped_run": 0, "repeat": 0, "inside": 0}
    last_hyp = -1
    for idx, (i, j) in enumerate(p):
        if j is not None:
            last_hyp = j
        if i is not None and j is not None and ref[i] == hyp[j]:
            continue
        # The hyp position this error sits at: its own, or the nearest aligned one.
        near = j if j is not None else max(0, last_hyp if last_hyp >= 0 else 0)
        nxt = next((jj for _, jj in p[idx + 1:] if jj is not None), near)
        at_edge = bool(hyp) and (edge[min(near, len(hyp) - 1)] or edge[min(nxt, len(hyp) - 1)])
        run = 0
        if i is not None and j is None:   # deletion: length of the deletion run it belongs to
            a = idx
            while a > 0 and p[a - 1][1] is None and p[a - 1][0] is not None:
                a -= 1
            b = idx
            while b + 1 < len(p) and p[b + 1][1] is None and p[b + 1][0] is not None:
                b += 1
            run = b - a + 1
        if i is None and j is not None and ((j > 0 and hyp[j] == hyp[j - 1]) or (j + 1 < len(hyp) and hyp[j] == hyp[j + 1])):
            cats["repeat"] += 1
        elif run >= 2:
            cats["dropped_run"] += 1
        elif at_edge:
            cats["boundary"] += 1
        else:
            cats["inside"] += 1
    cats["ref_words"] = len(ref)
    cats["finals"] = len(finals)
    cats["edge_word_share"] = round(sum(edge) / max(1, len(edge)), 2)   # how much of the text sits near an edge
    return cats


def finals_of(run):
    d = json.load(open(run["path"]))
    return d["finals"]


if __name__ == "__main__":
    man = json.load(open(sys.argv[1]))
    refs = {}
    for lang, r in man["refs"].items():
        said = {w["i"]: w.get("said") for w in json.load(open(r["said"]))}
        text = json.load(open(r["text"]))
        refs[lang] = ([said.get(i) or t for i, t in enumerate(text)], text)
    res = {"cer": [], "ja_kana": [], "en_breakdown": {}}
    for run in man["runs"]:
        lang = run["lang"]
        hyp = S.hyp_text({"path": run["path"], "kind": run["kind"]})
        s = S.score(lang, *refs[lang], hyp)
        n_pieces = None
        d = json.load(open(run["path"]))
        if run["kind"] == "finals":
            n_pieces = len(d["finals"])
        row = {"lang": lang, "system": run["system"], "said": s["said"], "text": s["text"],
               "dropped": len(s["dropped"]), "missing_starts": len(s["missing_starts"]), "pieces": n_pieces}
        res["cer"].append(row)
        print(lang, run["system"], s["said"], row["dropped"], row["missing_starts"], n_pieces, flush=True)
        if lang == "ja" and KKS:
            ref_k, hyp_k = kana(" ".join(refs[lang][0])), kana(hyp)
            k = round(100 * S.align(list(ref_k), list(hyp_k))[0] / max(1, len(ref_k)), 1)
            res["ja_kana"].append({"system": run["system"], "cer": s["said"]["cer"], "cer_kana": k})
        if lang == "en" and run["kind"] == "finals":
            res["en_breakdown"][run["system"]] = english_breakdown(refs[lang][0], d["finals"])
    json.dump(res, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"ja_kana": res["ja_kana"], "en_breakdown": res["en_breakdown"]}, indent=1))
