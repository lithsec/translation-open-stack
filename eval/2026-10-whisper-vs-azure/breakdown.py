# Where the live stack's English word errors come from, against system 1 (the same
# Whisper on whole sentences): per read sentence, word errors (deletions +
# substitutions from the clip alignment, plus insertions placed at their neighbour)
# for both systems, split into sentences the stack dropped, sentences whose start
# it lost, and the rest.
#   python3 -I breakdown.py MANIFEST.json lang pattern
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score import tokens, align, hyp_text


def per_sentence(per, hyp):
    flat = [t for p in per for t in p]
    _, ops = align(flat, hyp)
    out, k = [], 0
    for p in per:
        o = ops[k:k + len(p)]; k += len(p)
        out.append(sum(x != "m" for x in o))
    return out


man = json.load(open(sys.argv[1])); lang, pat = sys.argv[2], sys.argv[3]
said = {w["i"]: w.get("said") for w in json.load(open(man["refs"][lang]["said"]))}
text = json.load(open(man["refs"][lang]["text"]))
per = [tokens(said.get(i) or t, lang) for i, t in enumerate(text)]
runs = {r["system"]: r for r in man["runs"] if r["lang"] == lang and r["pattern"] == pat}
a = per_sentence(per, tokens(hyp_text(runs["1 whisper_sentence"]), lang))
b = per_sentence(per, tokens(hyp_text(runs["2 stack_live"]), lang))
sc = [s for s in json.load(open(sys.argv[4])) if s["lang"] == lang and s["pattern"] == pat and s["system"] == "2 stack_live"][0]
groups = {"dropped": sc["dropped"], "missing start": sc["missing_starts"]}
groups["rest"] = [i for i in range(len(per)) if i not in sc["dropped"] + sc["missing_starts"]]
n = sum(len(p) for p in per)
print(f"{lang} {pat}: {n} words; deletions+substitutions, Whisper per sentence {sum(a)} -> stack live {sum(b)}")
for g, ids in groups.items():
    print(f"  {g:14s} sentences {ids}: {sum(a[i] for i in ids)} -> {sum(b[i] for i in ids)}")
