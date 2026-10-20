# Audio degradation test (2026-10-19): scores out/stt-degrade/raw/<recogniser>/<cond>/<lang>.json
# as out/stt-bakeoff/score.py does: CER = judge.cer(" ".join(reference), hyp),
# hyp = the run's final texts joined with spaces (Azure: display text, as before).
#
#   .venv/bin/python out/stt-degrade/score.py   (from eval/2026-10-real-voices)
#   -> out/stt-degrade/summary.json + table.md (also printed)
import json, os, sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "2026-09-model-eval", "scripts"))
sys.path.insert(0, HERE)
from judge import cer  # noqa: E402

D = os.path.join(HERE, "out", "stt-degrade")
RECS = {"azure": ("Azure Speech (real time, eastus)", ("en", "ja", "km", "lo")),
        "omni": ("Omnilingual ASR (omni-stt, Cloud Run)", ("en", "km", "lo", "ht"))}
CONDS = [("clean", "clean (same-day baseline)"),
         ("reverb", "hall reverb, RT60 1.5 s, DRR 0 dB"),
         ("noise10", "crowd/HVAC noise, SNR 10 dB"),
         ("noise5", "crowd/HVAC noise, SNR 5 dB"),
         ("revnoise10", "reverb + noise 10 dB (room mic)"),
         ("hfp_nb", "Bluetooth HFP narrowband (8 kHz CVSD)"),
         ("hfp_wb", "Bluetooth HFP wideband (16 kHz mSBC)"),
         ("opus12", "Opus 12 kbit/s"),
         ("opus24", "Opus 24 kbit/s"),
         ("revnoise10_hpnorm", "room mic + HPF 80 Hz + loudnorm"),
         ("revnoise10_afftdn", "room mic + afftdn denoise"),
         ("revnoise10_rnn", "room mic + RNNoise (arnndn)")]


def ref(lang):
    return " ".join(json.load(open(os.path.join(HERE, "sentences", f"{lang}.json"))))


def one(job):
    rec, cond, lang = job
    p = os.path.join(D, "raw", rec, cond, f"{lang}.json")
    if not os.path.exists(p):
        return job, None
    r = json.load(open(p))
    if r.get("err"):
        return job, {"err": r["err"]}
    hyp = " ".join(f["text"] for f in r["finals"] if f.get("text"))
    return job, {"cer": cer(ref(lang), hyp), "finals": len(r["finals"]), "transcript": hyp}


if __name__ == "__main__":
    jobs = [(rec, c, l) for rec, (_, langs) in RECS.items() for c, _ in CONDS for l in langs]
    with ProcessPoolExecutor() as ex:
        res = dict(ex.map(one, jobs))
    lines = ["| condition | " + " | ".join(f"{rec} {l}" for rec, (_, ls) in RECS.items() for l in ls)
             + " | Azure mean Δ | Omni mean Δ |",
             "|---|" + "---:|" * (sum(len(ls) for _, ls in RECS.values()) + 2)]
    rows = []
    for c, label in CONDS:
        cells, deltas = [], {r: [] for r in RECS}
        for rec, (_, langs) in RECS.items():
            for l in langs:
                r, base = res.get((rec, c, l)), res.get((rec, "clean", l))
                if not r:
                    cells.append("-")
                    continue
                if "cer" not in r:
                    cells.append("ERR")
                    continue
                d = r["cer"] - base["cer"] if base and "cer" in base else None
                if d is not None:
                    deltas[rec].append(d)
                cells.append(f"{r['cer']:.1%}" + ("" if c == "clean" or d is None else f" ({d * 100:+.1f})"))
                rows.append({"recogniser": rec, "cond": c, "lang": l, **{k: v for k, v in r.items()},
                             "delta_vs_clean": None if d is None else round(d, 3)})
        means = [("" if c == "clean" or not deltas[r] else f"{sum(deltas[r]) / len(deltas[r]) * 100:+.1f}") for r in RECS]
        lines.append(f"| {label} | " + " | ".join(cells) + " | " + " | ".join(means) + " |")
    lines.append("")
    lines.append("CER; in brackets the change from the same-day clean run, in percentage points. "
                 "Mean Δ = average of the four languages' changes.")
    table = "\n".join(lines)
    print(table)
    open(os.path.join(D, "table.md"), "w").write(table + "\n")
    json.dump({"date": "2026-10-19", "recognisers": {k: v[0] for k, v in RECS.items()},
               "conditions": dict(CONDS),
               "audio": json.load(open(os.path.join(D, "conditions.json"))),
               "note": "CER = judge.cer(' '.join(reference), ' '.join(final texts)), as out/stt-bakeoff/score.py",
               "runs": rows}, open(os.path.join(D, "summary.json"), "w"), ensure_ascii=False, indent=1)
