# The soniox-hear arm's input: Soniox's own source-language transcript per read sentence, from the streams
# soniox_s2s.py already ran (no new streams). Each direction uses its own stream (en→X: the en→X stream's English
# transcript). The original tokens (translation_status not "translation") are grouped by audio offset exactly as
# soniox_s2s.py groups them: a token belongs to the sentence its midpoint falls in (sentence_of).
#
#   python3 -I soniox_hear.py CLIPS_ROOT OUT [set:src-tgt ...]   (only those, e.g. a:uk-en)
#
# Reads OUT/soniox/<set>/<src>-<tgt>.json (with its finals); writes OUT/soniox_hear/<set>/<src>-<tgt>.sent.json.
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLIPS, OUT = sys.argv[1], sys.argv[2]
ONLY = set(sys.argv[3:])
sys.argv = sys.argv[:1] + [CLIPS, OUT]
os.environ.setdefault("SONIOX_API_KEY", "unused")   # soniox_s2s reads it at import; nothing is streamed here
sys.path.insert(0, HERE)
from soniox_s2s import DIRS, SETS, sentence_of  # noqa: E402

empty = 0
for st in SETS:
    for d in DIRS:
        if ONLY and f"{st}:{d}" not in ONLY:
            continue
        src = d.split("-")[0]
        s = json.load(open(os.path.join(OUT, "soniox", st, f"{d}.json")))
        assert not s["err"], (st, d, s["err"])
        marks = json.load(open(os.path.join(CLIPS, f"clips_{st}", f"{src}.json")))["sentences"]
        out = [""] * len(marks)
        for t in s["finals"]:
            if t.get("translation_status") == "translation" or not t["text"] or t["text"].startswith("<"):
                continue
            if t.get("start_ms") is None:
                continue
            out[sentence_of((t["start_ms"] + (t.get("end_ms") or t["start_ms"])) / 2, marks)] += t["text"]
        out = [x.strip() for x in out]
        empty += sum(1 for x in out if not x)
        p = os.path.join(OUT, "soniox_hear", st, f"{d}.sent.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(out, open(p, "w"), ensure_ascii=False, indent=1)
print(f"{len(ONLY) or len(SETS) * len(DIRS)} transcripts, {empty} empty sentences")
