# One scorer for every arm. Hypothesis: every final the recogniser returned, in audio order, joined (the whole clip).
# Two references:
#   text  the FLEURS written text (<lang>.txt.json), as November's round
#   said  what the readers said (witness.py, gemini-pro-latest, as October); a sentence without an answer takes
#         October's committed "said" text (../2026-10-unseen/results.json english_said) if it has one, else its text
# Two normalisations:
#   nov   November's (../2026-11-talk-soniox/round_hearing.py norm): NFKC, lower case, letters and digits only for CER;
#         words for WER split on anything that isn't a letter or digit. Digits are left as digits.
#   oct   October's (../2026-10-whisper-vs-azure/score.py norm): NFKC, digits spelled out with num2words, lower case,
#         punctuation to spaces; CER with spaces removed.
# CER = Levenshtein distance / reference length, per clip; a November figure is the mean of sets a and b, as November.
#
#   python3 -I score.py WORK OUT.json
import json, os, re, statistics, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-whisper-vs-azure"))
import score as octs  # noqa: E402  (norm, align)

W = sys.argv[1]
CLIP = {"oct-en": "oct/clips_reg/en", "oct-pt": "oct/clips_reg/pt", "nova-en": "nov/clips_a/en",
        "novb-en": "nov/clips_b/en", "nova-pt": "nov/clips_a/pt", "novb-pt": "nov/clips_b/pt"}


OCT_SAID = json.load(open(os.path.join(HERE, "..", "2026-10-unseen", "results.json")))["english_said"]


def nov_chars(s):
    return [c for c in unicodedata.normalize("NFKC", s).lower() if c.isalnum()]


def nov_words(s):
    return re.findall(r"\w+", unicodedata.normalize("NFKC", s).lower().replace("_", " "))


def rate(ref, hyp):
    return round(100 * octs.align(ref, hyp)[0] / max(1, len(ref)), 2)


def scores(ref, hyp, lang):
    o_ref, o_hyp = octs.norm(ref, lang), octs.norm(hyp, lang)
    return {"nov": {"cer": rate(nov_chars(ref), nov_chars(hyp)), "wer": rate(nov_words(ref), nov_words(hyp))},
            "oct": {"cer": rate(list(o_ref.replace(" ", "")), list(o_hyp.replace(" ", ""))),
                    "wer": rate(o_ref.split(), o_hyp.split())}}


def refs(cid):
    text = json.load(open(os.path.join(W, CLIP[cid] + ".txt.json")))
    p = os.path.join(W, "said", cid + ".json")
    said = {r["i"]: r.get("said") for r in json.load(open(p))} if os.path.exists(p) else {}
    if cid == "oct-en":
        for i, t in OCT_SAID.items():
            said[int(i)] = said.get(int(i)) or t
    return {"text": " ".join(text), "said": " ".join(said.get(i) or t for i, t in enumerate(text)) if said else None}


def hyp(p):
    d = json.load(open(p))
    assert not d.get("err"), (p, d.get("err"))
    return " ".join(f["text"] for f in sorted(d["finals"], key=lambda f: f["offsetMs"])), len(d["finals"])


rows = []
out = os.path.join(W, "out")
for run in sorted(os.listdir(out)):
    for rec in sorted(os.listdir(os.path.join(out, run))):
        for f in sorted(os.listdir(os.path.join(out, run, rec))):
            cid = f[:-5]
            h, n = hyp(os.path.join(out, run, rec, f))
            r = refs(cid)
            row = {"run": run, "recogniser": rec, "clip": cid, "finals": n,
                   "text": scores(r["text"], h, cid[-2:])}
            if r["said"]:
                row["said"] = scores(r["said"], h, cid[-2:])
            rows.append(row)

# Runs r1, r2: this round's one setup (stream.py). Run "orig": each earlier round's own script, English only
# (October: ../2026-10-mai-streaming-followup/stream.py pin and ../2026-10-whisper-vs-azure/azure_stream.py; November:
# ../2026-11-talk-soniox/stt_azure.py), reported separately.
# Per language x clip set x recogniser: mean over runs (November: mean of sets a and b per run first).
summary = {}
for lang in ("en", "pt"):
    for cs in ("oct", "nov"):
        for rec in ("azure", "mai"):
            per_run = {}
            for r in rows:
                if r["run"] != "orig" and r["recogniser"] == rec and r["clip"].endswith(lang) and r["clip"].startswith(cs):
                    per_run.setdefault(r["run"], []).append(r)
            if not per_run:
                continue
            cell = {}
            for ref in ("text", "said"):
                for nm in ("nov", "oct"):
                    for m in ("cer", "wer"):
                        vals = []
                        for rs in per_run.values():
                            if all(ref in x for x in rs):
                                vals.append(statistics.mean(x[ref][nm][m] for x in rs))
                        if vals:
                            cell[f"{ref}/{nm}/{m}"] = {"mean": round(statistics.mean(vals), 2),
                                                       "runs": [round(v, 2) for v in vals]}
            summary[f"{lang}|{cs}|{rec}"] = cell
json.dump({"rows": rows, "summary": summary}, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
for k, c in summary.items():
    print(k, {m: (v["mean"], v["runs"]) for m, v in c.items() if m.endswith("cer")})
