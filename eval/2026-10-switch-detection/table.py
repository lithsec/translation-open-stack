# Summary tables from analyze.py's output.   python3 -I table.py ANALYSIS.json OUT.json
import json, statistics as st, sys

A = json.load(open(sys.argv[1]))["clips"]
APP = ["baseline_azure_lid", "azure_diarization_lid", "a_fixed2s", "b_pause", "c_frame", "c_frame_vl1", "c_frame_wh1", "d_speaker", "e_warn", "f_dual", "combo_fcde"]
PAIRS = ["es", "fr", "pt", "ja"]


def med(v):
    v = [x for x in v if x is not None]
    return round(st.median(v), 2) if v else None


def p90(v):
    v = sorted(x for x in v if x is not None)
    return round(v[min(len(v) - 1, int(0.9 * len(v)))], 2) if v else None


out = {}
for fam in ("az", "mai"):
    for app in APP:
        row = {}
        for sc in ("S1", "S2", "S3"):
            pairs = PAIRS + (["ht"] if fam == "az" else [])
            ds, cs, miss, n = [], [], 0, 0
            for x in pairs:
                key = f"{sc}_{x}|{'none' if x == 'ht' else fam}"
                r = A.get(key, {}).get(app)
                if not r:
                    continue
                for d in r["detect"]:
                    n += 1
                    if d["delay"] is None:
                        miss += 1
                    else:
                        ds.append(d["delay"])
                        cs.append(abs(d["cut_err"]))
            row[sc] = {"switches": n, "missed": miss, "delay_p50": med(ds), "delay_p90": p90(ds), "cut_err_p50": med(cs)}
        agg = {"cer_e": 0, "cer_n": 0, "wer_e": 0, "wer_n": 0, "del": 0, "ins": 0, "wrong": 0, "units": 0}
        for sc in ("S1", "S2"):
            for x in PAIRS:
                r = A.get(f"{sc}_{x}|{fam}", {}).get(app)
                if r and r.get("score"):
                    for k in agg:
                        agg[k] += r["score"][k]
        s3 = {"wrong": 0, "units": 0}
        for x in PAIRS:
            r = A.get(f"S3_{x}|{fam}", {}).get(app)
            if r and r.get("score"):
                s3["wrong"] += r["score"]["wrong"]
                s3["units"] += r["score"]["units"]
        ctl = {"switch_clips": 0, "false": 0}
        for x in PAIRS:
            r = A.get(f"ctl_{x}|{fam}", {}).get(app)
            if r:
                ctl["switch_clips"] += 1
                ctl["false"] += len(r["events"])
        r = A.get("ctl_en|az", {}).get(app)
        if r:
            ctl["switch_clips"] += 1
            ctl["false"] += len(r["events"])
        row["text_S1S2"] = {"cer": round(100 * agg["cer_e"] / max(1, agg["cer_n"]), 1),
                            "wer": round(100 * agg["wer_e"] / max(1, agg["wer_n"]), 1),
                            "deleted_words": agg["del"], "inserted_words": agg["ins"],
                            "wrong_lang_pct": round(100 * agg["wrong"] / max(1, agg["units"]), 1)}
        row["S3_wrong_lang_pct"] = round(100 * s3["wrong"] / max(1, s3["units"]), 1)
        row["false_switches_on_one_language"] = ctl
        out[f"{fam}|{app}"] = row
json.dump(out, open(sys.argv[2], "w"), indent=1)
for k, r in out.items():
    print(k, "| S1", r["S1"]["delay_p50"], r["S1"]["missed"], "| S2", r["S2"]["delay_p50"], r["S2"]["missed"], "| S3", r["S3"]["delay_p50"], r["S3"]["missed"],
          "| cut", r["S2"]["cut_err_p50"], "| CER", r["text_S1S2"]["cer"], "WER", r["text_S1S2"]["wer"], "wrong", r["text_S1S2"]["wrong_lang_pct"], "S3wrong", r["S3_wrong_lang_pct"], "| false", r["false_switches_on_one_language"]["false"])
