# Switch detection, simulated causally from the recorded signals (features.py on the pod,
# recognize.py from the Mac). Every approach turns the signals available at time t into
# decisions (t_detect, language, t_cut). The words a user would get are then taken from the
# recognisers actually listening at each moment:
#   single-recogniser approaches (a, b, d, e): the stream pinned to the language decided at the
#     time each word was spoken; words before a detected switch stay with the old language
#     unless the approach can cut back (b, c, d re-recognise from the cut point out of the
#     buffered audio, simulated with the other pinned stream's words from that point)
#   (f) dual: both pinned streams run all the time; the language labels pick the stream
#   baseline: Azure's own continuous language ID finals as they came (and the same from Azure's
#     diarization with continuous language ID, dia_lid, when diarize.py ran it)
#
#   python3 -I analyze.py SWITCH_DIR OUT.json      (SWITCH_DIR: clips/, feat/, rec/)
import glob, json, os, re, sys
import numpy as np

D, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(D, "pylib"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "2026-10-whisper-vs-azure"))
from score import tokens, align  # noqa: E402

PAIRS = ["es", "fr", "pt", "ja"]
LOC = {"en-US": "en", "es-MX": "es", "fr-FR": "fr", "pt-BR": "pt", "ja-JP": "ja"}
MAI_LAG = 0.35          # a MAI partial arrives ~0.3-0.35 s after the audio it covers (earlier rounds)
COMPUTE = 0.05          # detector compute after a window ends
P = {"h": 1.0, "k": 3, "m": 0.5, "spk": 0.45, "warn_conf": 0.5}


def load(p):
    return json.load(open(p))


def vad_speech(feat, t):
    v = feat["vad"]["p"]
    i = int(t / feat["vad"]["frame_s"])
    return 0 <= i < len(v) and v[i] > 0.5


def pair_score(feat, key, x, i):
    L = feat["langs"]
    a, b = L.index("en"), L.index(x)
    if key.startswith("vl"):
        v = feat[key]["logp"][i]
        return v[b] - v[a]
    v = feat[key]["p"][i]
    return float(np.log(v[b] + 1e-4) - np.log(v[a] + 1e-4))


def win(key):
    return {"vl05": 0.5, "vl1": 1.0, "wh1": 1.0, "wh2": 2.0}[key]


def series(feat, key, x):
    t = np.array(feat[key]["t"])
    s = np.array([pair_score(feat, key, x, i) for i in range(len(t))])
    sp = np.array([vad_speech(feat, tt - win(key) / 2) for tt in t])
    return t, s, sp


def lang_of(s, x):
    return x if s > 0 else "en"


# ---------------------------------------------------------------- decision engines -> events
def first_lang(t, s, sp, x):
    for tt, ss, p in zip(t, s, sp):
        if p and abs(ss) > P["h"]:
            return lang_of(ss, x), tt
    return "en", 0.0


def eng_fixed(feat, x):                          # (a) every 2 s, mean pair score over the last 2 s
    t, s, sp = series(feat, "vl1", x)
    cur, t0 = first_lang(t, s, sp, x)
    ev = []
    for T in np.arange(2.0, t[-1] + 0.01, 2.0):
        m = (t > T - 2) & (t <= T) & sp
        if m.sum() < 2:
            continue
        v = s[m].mean()
        if abs(v) > P["m"] and lang_of(v, x) != cur:
            cur = lang_of(v, x)
            ev.append((T + COMPUTE, cur, T + COMPUTE))
    return first_lang(t, s, sp, x)[0], ev


def pauses(feat, min_s=0.15):
    v, fs = feat["vad"]["p"], feat["vad"]["frame_s"]
    out, run = [], 0
    for i, p in enumerate(v):
        if p <= 0.5:
            run += 1
        else:
            if run * fs >= min_s:
                out.append(i * fs)          # speech resumes here
            run = 0
    return out


def eng_pause(feat, x):                          # (b) 1 s after speech resumes after a >=150 ms pause
    t, s, sp = series(feat, "vl1", x)
    cur = first_lang(t, s, sp, x)[0]
    ev = []
    for p in pauses(feat):
        i = np.searchsorted(t, p + 1.0)
        if i >= len(t):
            break
        v = s[i]
        if abs(v) > P["m"] and lang_of(v, x) != cur:
            cur = lang_of(v, x)
            ev.append((t[i] + COMPUTE, cur, p))
    return first_lang(t, s, sp, x)[0], ev


def eng_frame(feat, x, key="vl05", boost=None):  # (c) smoothed frame scores, hysteresis, cut back
    t, s, sp = series(feat, key, x)
    cur = first_lang(t, s, sp, x)[0]
    ev, hist = [], []
    for i in range(len(t)):
        if not sp[i]:
            continue
        hist.append((t[i], s[i]))
        sm = np.mean([h[1] for h in hist[-P["k"]:]])
        h = P["h"]
        if boost and any(b <= t[i] <= b + 1.5 for b in boost):
            h = P["h"] / 2
        new = lang_of(sm, x)
        if new != cur and abs(sm) > h:
            # cut: the earliest window in the last 3 s from which every score is on the new side
            cut = t[i] - win(key) / 2
            for tt, ss in reversed(hist[:-1]):
                if tt < t[i] - 3 or lang_of(ss, x) != new:
                    break
                cut = tt - win(key) / 2
            # snap to a pause within 0.4 s
            v, fs = feat["vad"]["p"], feat["vad"]["frame_s"]
            best = None
            for j in range(int((cut - 0.4) / fs), int((cut + 0.4) / fs)):
                if 0 <= j < len(v) and v[j] <= 0.5:
                    if best is None or abs(j * fs - cut) < abs(best - cut):
                        best = j * fs
            ev.append((t[i] + COMPUTE, new, best if best is not None else cut))
            cur = new
    return first_lang(t, s, sp, x)[0], ev


def spk_triggers(feat):
    a = feat["spk"]
    t, sim = np.array(a["t"]), np.array(a["across"])
    out = []
    for i in range(1, len(t) - 1):
        if sim[i] < P["spk"] and sim[i] <= sim[i - 1] and sim[i] <= sim[i + 1]:
            out.append(t[i])                     # change at t[i]; known at t[i] + 1.0
    return out


def eng_speaker(feat, x):                        # (d) on a speaker change, check the 1 s after it
    t, s, sp = series(feat, "vl1", x)
    cur = first_lang(t, s, sp, x)[0]
    ev = []
    for c in spk_triggers(feat):
        i = np.searchsorted(t, c + 1.0)
        if i >= len(t):
            break
        if abs(s[i]) > P["m"] and lang_of(s[i], x) != cur:
            cur = lang_of(s[i], x)
            ev.append((c + 1.0 + COMPUTE, cur, c))
    return first_lang(t, s, sp, x)[0], ev


def warn_triggers(rec_en, rec_x, x, events_fn):
    """(e) the active Azure-pinned stream's own warning signs, as they arrived: a final with low
    confidence, or a partial that rewrote 3+ earlier words, or under 1 word/s of growth over 2 s."""
    out = []
    for lang, r in (("en", rec_en), (x, rec_x)):
        prev = []
        for p in r["partials"]:
            w = p["text"].split()
            keep = 0
            while keep < min(len(w), len(prev)) and w[keep] == prev[keep]:
                keep += 1
            if len(prev) - keep >= 3:
                out.append((p["arrived"], lang))
            prev = w
        for f in r["finals"]:
            if (f.get("confidence") or 1) < P["warn_conf"]:
                out.append((f["arrived"], lang))
    return sorted(out)


def eng_warn(feat, x, rec_en, rec_x):
    t, s, sp = series(feat, "vl1", x)
    cur = first_lang(t, s, sp, x)[0]
    ev = []
    for a, lang in warn_triggers(rec_en, rec_x, x, None):
        if lang != cur:                          # only the stream actually listening raises warnings
            continue
        i = np.searchsorted(t, a) - 1
        if i < 0:
            continue
        if abs(s[i]) > P["m"] and lang_of(s[i], x) != cur:
            cur = lang_of(s[i], x)
            ev.append((a + COMPUTE, cur, a))
    return first_lang(t, s, sp, x)[0], ev


def eng_combo(feat, x, rec_en, rec_x):           # f + c + d + e (1 s windows): triggers halve the hysteresis
    boost = spk_triggers(feat) + [a for a, _ in warn_triggers(rec_en, rec_x, x, None)]
    return eng_frame(feat, x, "vl1", boost=[b for b in boost])


# ---------------------------------------------------------------- words from the recognisers
def units(text, lang):
    return list(re.sub(r"\s", "", text)) if lang == "ja" else text.split()


def words_az(r, lang):
    out = []
    for f in r["finals"]:
        ws = f.get("words") or []
        if ws:
            for w in ws:
                for u in units(w["w"], lang):
                    out.append((w["o"] + w["d"] / 2, u))
        else:
            us = units(f["text"], lang)
            for k, u in enumerate(us):
                out.append((f["offset"] + f["duration"] * (k + 0.5) / max(1, len(us)), u))
    return out


def words_mai(r, lang):
    """MAI gives no word timings: a unit's time is the arrival of the partial that first showed it,
    minus the partial lag. Finals are matched to the last partial's units by position."""
    seen = []
    for p in r["partials"]:
        us = units(p["text"], lang)
        k = 0
        while k < min(len(us), len(seen)) and us[k] == seen[k][1]:
            k += 1
        seen = seen[:k] + [(p["arrived"] - MAI_LAG, u) for u in us[k:]]
        # a new utterance starts: partial texts shrink when a final has gone out
    out, times = [], []
    # simpler and robust: walk partials and finals in arrival order
    pts = sorted([("p", p["arrived"], p["text"]) for p in r["partials"]] + [("f", f["arrived"], f["text"]) for f in r["finals"]],
                 key=lambda e: e[1])
    cur = []
    for kind, arr, text in pts:
        us = units(text, lang)
        if kind == "p":
            k = 0
            while k < min(len(us), len(cur)) and us[k] == cur[k][1]:
                k += 1
            cur = cur[:k] + [(arr - MAI_LAG, u) for u in us[k:]]
        else:
            for j, u in enumerate(us):
                tt = cur[j][0] if j < len(cur) else (cur[-1][0] if cur else arr - MAI_LAG)
                out.append((tt, u))
            cur = []
    return out


def words_base(r):
    out = []
    for f in r["finals"]:
        lang = LOC.get(f.get("lang") or "", "en")
        ws = f.get("words") or []
        if ws:
            for w in ws:
                for u in units(w["w"], lang):
                    out.append((w["o"] + w["d"] / 2, u, lang, f["arrived"]))
        else:
            us = units(f["text"], lang)
            for k, u in enumerate(us):
                out.append((f["offset"] + f["duration"] * (k + 0.5) / max(1, len(us)), u, lang, f["arrived"]))
    return out


# ---------------------------------------------------------------- labelling and scoring
def labels_at(init, ev, t, backcut):
    """The language the system listens in for audio at time t, once everything has settled."""
    cur = init
    for td, lang, cut in ev:
        edge = cut if backcut else td
        if t >= edge:
            cur = lang
    return cur


def score(clip, hyp, x):
    """hyp: (time, unit, attributed language). Per truth segment: its hypothesis units by time,
    CER and WER (not ja) against its text; wrong-language: units attributed to a language other
    than the segment's."""
    segs = clip["segments"]
    agg = {"cer_e": 0, "cer_n": 0, "wer_e": 0, "wer_n": 0, "del": 0, "ins": 0, "wrong": 0, "units": 0}
    for k, s in enumerate(segs):
        lo = s["start"] - 0.15 if k == 0 else (segs[k - 1]["end"] + s["start"]) / 2
        hi = s["end"] + 0.15 if k == len(segs) - 1 else (s["end"] + segs[k + 1]["start"]) / 2
        mine = [h for h in hyp if lo <= h[0] < hi]
        agg["units"] += len(mine)
        agg["wrong"] += sum(1 for h in mine if h[2] != s["lang"])
        if s.get("text") is None:
            continue
        txt = (" " if s["lang"] != "ja" else "").join(h[1] for h in mine)
        rc, hc = tokens(s["text"], s["lang"]), tokens(txt, s["lang"])
        rc, hc = "".join(rc).replace(" ", ""), "".join(hc).replace(" ", "")
        d, ops = align(list(rc), list(hc))
        agg["cer_e"] += d
        agg["cer_n"] += len(rc)
        if s["lang"] != "ja":
            rw, hw = tokens(s["text"], s["lang"]), tokens(txt, s["lang"])
            d, ops = align(rw, hw)
            agg["wer_e"] += d
            agg["wer_n"] += len(rw)
            agg["del"] += ops.count("d")
            agg["ins"] += max(0, d - ops.count("s") - ops.count("d"))
    return agg


def detection(clip, init, ev):
    """Per true switch: delay to the first event into the new language, and |cut - switch|."""
    sw = clip["switches"]
    segs = clip["segments"]
    out = []
    for k, s in enumerate(sw):
        new = next(g["lang"] for g in segs if abs(g["start"] - s) < 1e-3)
        nxt = sw[k + 1] if k + 1 < len(sw) else 1e9
        hit = [e for e in ev if s - 0.5 <= e[0] < nxt + 0.5 and e[1] == new]
        if hit:
            out.append({"switch": s, "delay": round(hit[0][0] - s, 3), "cut_err": round(hit[0][2] - s, 3)})
        else:
            out.append({"switch": s, "delay": None, "cut_err": None})
    return out


def run_clip(name, x, rec_family):
    clip = load(os.path.join(D, "clips", f"{name}.json"))
    feat = load(os.path.join(D, "feat", f"{name}.json"))
    R = lambda kind, lang: load(os.path.join(D, "rec", f"{name}__{kind}_{lang}.json"))
    fam = rec_family
    words = {}
    for lang in ("en", x):
        try:
            r = R(fam, lang)
        except FileNotFoundError:
            continue
        words[lang] = words_az(r, lang) if fam == "az" else words_mai(r, lang)
    az_en, az_x = R("az", "en") if os.path.exists(os.path.join(D, "rec", f"{name}__az_en.json")) else {"partials": [], "finals": []}, \
        R("az", x) if os.path.exists(os.path.join(D, "rec", f"{name}__az_{x}.json")) else {"partials": [], "finals": []}
    res = {}
    engines = {
        "a_fixed2s": (lambda: eng_fixed(feat, x), False, False),
        "b_pause": (lambda: eng_pause(feat, x), True, False),
        "c_frame": (lambda: eng_frame(feat, x, "vl05"), True, False),
        "c_frame_vl1": (lambda: eng_frame(feat, x, "vl1"), True, False),
        "c_frame_wh1": (lambda: eng_frame(feat, x, "wh1"), True, False),
        "d_speaker": (lambda: eng_speaker(feat, x), True, False),
        "e_warn": (lambda: eng_warn(feat, x, az_en, az_x), False, False),
        "f_dual": (lambda: eng_frame(feat, x, "vl1"), True, True),
        "combo_fcde": (lambda: eng_combo(feat, x, az_en, az_x), True, True),
    }
    for k, (fn, backcut, dual) in engines.items():
        init, ev = fn()
        hyp = []
        if words:
            for lang, ws in words.items():
                for tt, u in ws:
                    if labels_at(init, ev, tt, backcut) == lang:
                        hyp.append((tt, u, lang))
        hyp.sort()
        res[k] = {"init": init, "events": [list(map(lambda v: round(v, 3) if isinstance(v, float) else v, e)) for e in ev],
                  "detect": detection(clip, init, ev), "score": score(clip, hyp, x) if words else None}
    for key, path in (("baseline_azure_lid", os.path.join(D, "rec", f"{name}__base_{x}.json")),
                      ("azure_diarization_lid", os.path.join(D, "dia", f"{name}__dia_lid.json"))):
        if not os.path.exists(path):
            continue
        b = load(path)
        hyp = [(t, u, l) for t, u, l, _ in words_base(b)]
        evb, cur = [], None
        for f in sorted(b["partials"] + b["finals"], key=lambda f: f["arrived"]):
            lang = LOC.get(f.get("lang") or "")
            if lang and lang != cur:
                if cur is not None:
                    evb.append((f["arrived"], lang, f["offset"]))
                cur = lang
        first = LOC.get((b["finals"] or [{}])[0].get("lang") or "", "en")
        res[key] = {"events": [[round(e[0], 3), e[1], round(e[2], 3)] for e in evb],
                    "detect": detection(clip, first, evb), "score": score(clip, hyp, x)}
    return res


out = {"params": P, "clips": {}}
for x in PAIRS + ["ht"]:
    for s in ("S1", "S2", "S3", "ctl"):
        name = f"{s}_{x}"
        for fam in ("az", "mai"):
            if x == "ht":
                fam = "none"
            out["clips"][f"{name}|{fam}"] = run_clip(name, x, fam)
            if x == "ht":
                break
    out["clips"]["ctl_en|az"] = run_clip("ctl_en", "es", "az")
json.dump(out, open(OUT, "w"), indent=0)
print("ok", len(out["clips"]))
