# Azure real-time diarization (diarize.py) against ground truth, beside the ECAPA signals:
#   speaker change   delay (truth change -> first result that names a different speaker) and
#                    |result offset - change|; ECAPA: the cosine-dip trigger (known 1 s after the change)
#   confusion        share of labelled speech time whose label maps (best one-to-one by overlap) to
#                    a different true speaker, DER-style (missed speech reported apart)
#   consistency      for speakers who come back (R2, R3; the bleed owner), share of their turns
#                    whose majority label is that speaker's usual label
#   false new        extra labels on one speaker (R1)
#   latency          final arrival - end of its audio, against plain recognition on the same clips
#   language         dia_lid finals' languages scored like the other switch approaches
#
#   python3 -I dia_analyze.py SWITCH_DIR OUT.json
import collections, glob, json, os, statistics as st, sys
import numpy as np

D, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec = importlib.util.spec_from_file_location("an", os.path.join(os.path.dirname(os.path.abspath(__file__)), "analyze.py"))
LOC = {"en-US": "en", "es-MX": "es", "fr-FR": "fr", "pt-BR": "pt", "ja-JP": "ja"}


def load(p):
    return json.load(open(p))


def truth_of(name):
    for d in ("clips", "diaclips", "bleed"):
        p = os.path.join(D, d, name + ".json")
        if os.path.exists(p):
            g = load(p)
            segs = g["segments"]
            if d == "bleed":
                segs = [dict(s, spk=("owner" if s["who"] == "owner" else f"{s['who']}{k}")) for k, s in enumerate(segs)]
            elif d == "clips":   # every FLEURS utterance is a different reader
                segs = [dict(s, spk=f"r{k}") for k, s in enumerate(segs)]
            return segs
    raise FileNotFoundError(name)


def changes(segs):
    out = []
    for i in range(1, len(segs)):
        if segs[i]["spk"] != segs[i - 1]["spk"] and segs[i]["start"] >= segs[i - 1]["end"] - 0.05:
            out.append((segs[i]["start"], segs[i]["spk"]))
    return out


def frames(a, b):
    """50 ms frame indices covering [a, b): one grid for truth and labels alike."""
    return range(int(np.ceil(a / 0.05)), int(np.floor(b / 0.05)))


def label_timeline(finals):
    lab = {}
    for f in finals:
        if f["spk"] in (None, "Unknown"):
            continue
        for i in frames(f["offset"], f["offset"] + f["duration"]):
            lab[i] = f["spk"]
    return lab


def confusion(segs, finals):
    lab = label_timeline(finals)
    truth = {}
    for s in segs:
        for i in frames(s["start"], s["end"]):
            truth[i] = s["spk"]
    ov = collections.Counter((truth[t], lab[t]) for t in lab if t in truth)
    used_t, used_l, mapping = set(), set(), {}
    for (tr, lb), n in ov.most_common():
        if tr not in used_t and lb not in used_l:
            mapping[lb] = tr
            used_t.add(tr)
            used_l.add(lb)
    both = [t for t in lab if t in truth]
    wrong = sum(1 for t in both if mapping.get(lab[t]) != truth[t])
    missed = sum(1 for t in truth if t not in lab)
    return {"labelled_s": round(len(both) * 0.05, 1), "confusion_pct": round(100 * wrong / max(1, len(both)), 1),
            "missed_speech_pct": round(100 * missed / max(1, len(truth)), 1), "labels": len({lab[t] for t in lab})}


def consistency(segs, finals):
    lab = label_timeline(finals)
    per = collections.defaultdict(list)
    for s in segs:
        c = collections.Counter(lab.get(i) for i in frames(s["start"], s["end"]))
        c.pop(None, None)
        per[s["spk"]].append(c.most_common(1)[0][0] if c else None)
    tot = ok = unl = 0
    for spk, labs in per.items():
        if len(labs) < 2:
            continue
        usual = collections.Counter(l for l in labs if l).most_common(1)
        usual = usual[0][0] if usual else None
        unl += sum(1 for l in labs if l is None)          # turns Azure returned nothing for
        tot += sum(1 for l in labs if l is not None)
        ok += sum(1 for l in labs if l is not None and l == usual)
    return {"returning_turns": tot, "same_label_pct": round(100 * ok / max(1, tot), 1), "unlabelled_turns": unl}


def change_detection(segs, res):
    """Azure: first final or labelled partial whose audio starts after the change minus 0.3 s and
    whose speaker differs from the previous labelled result."""
    items = sorted([r for r in res["finals"] + res["partials"] if r["spk"] not in (None, "Unknown")], key=lambda r: r["arrived"])
    out = []
    for c, _ in changes(segs):
        prev = [r for r in items if r["offset"] + r["duration"] <= c + 0.2]
        prev_spk = prev[-1]["spk"] if prev else None
        hit = next((r for r in items if r["offset"] >= c - 0.3 and r["spk"] != prev_spk), None)
        out.append({"change": c, "delay": round(hit["arrived"] - c, 2) if hit else None,
                    "cut_err": round(hit["offset"] - c, 2) if hit else None})
    return out


def ecapa_detection(name, segs, thr=0.45):
    p = os.path.join(D, "feat", name + ".json")
    if not os.path.exists(p):
        return None
    f = load(p)
    t, sim = np.array(f["spk"]["t"]), np.array(f["spk"]["across"])
    trig = [t[i] for i in range(1, len(t) - 1) if sim[i] < thr and sim[i] <= sim[i - 1] and sim[i] <= sim[i + 1]]
    out = []
    for c, _ in changes(segs):
        hit = next((x for x in trig if abs(x - c) <= 0.75), None)
        out.append({"change": c, "delay": round(hit + 1.0 - c, 2) if hit is not None else None,
                    "cut_err": round(hit - c, 2) if hit is not None else None})
    false = sum(1 for x in trig if all(abs(x - c) > 0.75 for c, _ in changes(segs)))
    return {"detect": out, "false_triggers": false, "minutes": len(f["vad"]["p"]) * f["vad"]["frame_s"] / 60}


def bleed_as_owner(segs, finals):
    """Bleed clips: share of non-owner speech (owner silent) that Azure labels with the owner's usual label,
    and share it returns no result for."""
    lab = label_timeline(finals)
    own, oth = set(), set()
    for s in segs:
        (own if s["spk"] == "owner" else oth).update(frames(s["start"], s["end"]))
    only = oth - own
    c = collections.Counter(lab[i] for i in own if i in lab)
    if not c or not only:
        return None
    o = c.most_common(1)[0][0]
    return {"bleed_frames": len(only), "as_owner": sum(1 for i in only if lab.get(i) == o),
            "unlabelled": sum(1 for i in only if i not in lab)}


def latency(res):
    return [r["arrived"] - (r["offset"] + r["duration"]) for r in res["finals"]]


rows = {}
for p in sorted(glob.glob(os.path.join(D, "dia", "*__dia_*.json"))):
    res = load(p)
    name, mode = res["clip"], res["mode"]
    try:
        segs = truth_of(name)
    except FileNotFoundError:
        continue
    row = {"err": res["err"], "confusion": confusion(segs, res["finals"]), "consistency": consistency(segs, res["finals"]),
           "change": change_detection(segs, res), "labels": sorted({f["spk"] for f in res["finals"]}),
           "latency": latency(res)}
    if mode == "dia_pin":
        row["ecapa"] = ecapa_detection(name, segs)
        row["ecapa_by_threshold"] = {str(th): ecapa_detection(name, segs, th) for th in (0.15, 0.25, 0.35, 0.45)}
    if name.startswith("bleed_"):
        row["bleed_as_owner"] = bleed_as_owner(segs, res["finals"])
    if mode == "dia_lid":
        langs = [(f["offset"], LOC.get(f["lang"] or "", "?")) for f in res["finals"]]
        row["langs_seen"] = sorted({l for _, l in langs})
    rows[f"{name}|{mode}"] = row

# plain recognition latency on the same clips (az pinned English finals from recognize.py)
plain = []
for p in glob.glob(os.path.join(D, "rec", "*__az_en.json")):
    r = load(p)
    plain += [f["arrived"] - (f["offset"] + f["duration"]) for f in r["finals"]]


def agg(keys, mode):
    sel = [rows[k] for k in rows if k.endswith("|" + mode) and any(k.startswith(x) for x in keys)]
    ds = [d["delay"] for r in sel for d in r["change"] if d["delay"] is not None]
    cs = [abs(d["cut_err"]) for r in sel for d in r["change"] if d["cut_err"] is not None]
    miss = sum(1 for r in sel for d in r["change"] if d["delay"] is None)
    n = sum(len(r["change"]) for r in sel)
    lt = [x for r in sel for x in r["latency"]]
    tot = sum(r["confusion"]["labelled_s"] for r in sel)
    conf = sum(r["confusion"]["confusion_pct"] * r["confusion"]["labelled_s"] for r in sel) / max(1e-9, tot)
    rt = sum(r["consistency"]["returning_turns"] for r in sel)
    rc = sum(r["consistency"]["same_label_pct"] * r["consistency"]["returning_turns"] for r in sel) / max(1, rt)
    un = sum(r["consistency"]["unlabelled_turns"] for r in sel)
    out = {"clips": len(sel), "changes": n, "missed": miss, "returning_unlabelled_turns": un,
           "delay_p50": round(st.median(ds), 2) if ds else None, "cut_err_p50": round(st.median(cs), 2) if cs else None,
           "confusion_pct": round(conf, 1), "returning_same_label_pct": round(rc, 1) if rt else None,
           "final_latency_p50": round(st.median(lt), 2) if lt else None, "max_labels": max([len(r["labels"]) for r in sel] or [0])}
    ec = [r["ecapa"] for r in sel if r.get("ecapa")]
    if ec:
        eds = [d["delay"] for e in ec for d in e["detect"] if d["delay"] is not None]
        ecs = [abs(d["cut_err"]) for e in ec for d in e["detect"] if d["cut_err"] is not None]
        out["ecapa"] = {"missed": sum(1 for e in ec for d in e["detect"] if d["delay"] is None),
                        "delay_p50": round(st.median(eds), 2) if eds else None,
                        "cut_err_p50": round(st.median(ecs), 2) if ecs else None,
                        "false_triggers": sum(e["false_triggers"] for e in ec)}
    eb = [r["ecapa_by_threshold"] for r in sel if r.get("ecapa_by_threshold") and r["ecapa_by_threshold"].get("0.45")]
    if eb:
        out["ecapa_by_threshold"] = {}
        for th in ("0.15", "0.25", "0.35", "0.45"):
            es_ = [e[th] for e in eb]
            d_ = [d["delay"] for e in es_ for d in e["detect"] if d["delay"] is not None]
            out["ecapa_by_threshold"][th] = {"missed": sum(1 for e in es_ for d in e["detect"] if d["delay"] is None),
                                             "delay_p50": round(st.median(d_), 2) if d_ else None,
                                             "false_triggers_per_min": round(sum(e["false_triggers"] for e in es_) / max(1e-9, sum(e["minutes"] for e in es_)), 1)}
    return out


summary = {
    "switch_S1S2S3_pin": agg(["S1_", "S2_", "S3_"], "dia_pin"),
    "switch_S1S2S3_lid": agg(["S1_", "S2_", "S3_"], "dia_lid"),
    "R2R3_returning_pin": agg(["R2", "R3"], "dia_pin"),
    "R1_one_speaker_pin": {"labels": rows.get("R1|dia_pin", {}).get("labels"), "confusion": rows.get("R1|dia_pin", {}).get("confusion")},
    "bleed_pin": agg(["bleed_"], "dia_pin"),
    "bleed_labelled_as_owner_pct": round(100 * sum(r["bleed_as_owner"]["as_owner"] for k, r in rows.items() if r.get("bleed_as_owner"))
                                         / max(1, sum(r["bleed_as_owner"]["bleed_frames"] for k, r in rows.items() if r.get("bleed_as_owner"))), 1),
    "bleed_unlabelled_pct": round(100 * sum(r["bleed_as_owner"]["unlabelled"] for k, r in rows.items() if r.get("bleed_as_owner"))
                                  / max(1, sum(r["bleed_as_owner"]["bleed_frames"] for k, r in rows.items() if r.get("bleed_as_owner"))), 1),
    "plain_recognition_final_latency_p50": round(st.median(plain), 2) if plain else None,
    "lid_errors": sorted({rows[k]["err"] for k in rows if k.endswith("|dia_lid") and rows[k]["err"]}),
}
json.dump({"summary": summary, "clips": rows}, open(OUT, "w"), indent=1)
print(json.dumps(summary, indent=1))
