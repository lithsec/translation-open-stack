# Phone bleed: does each method keep the owner's speech and drop everyone else's?
# Decisions are causal at a 50 ms grid (a window's result is usable once it has ended).
#   (a) level      20 ms RMS (100 ms max-smoothed) at least G dB under the owner's running level
#                  (starts at the enrolment level, follows frames accepted as the owner), 300 ms hangover
#   (b) voice      cosine of the latest speaker-embedding window to the owner's enrolment >= TAU,
#                  median of the last 3 windows
#   (c) a and b
#   (d) language   VoxLingua107 log-posterior of the phone's language minus the best other >= DELTA
#   (e) a and b and d
# Thresholds are chosen leave-one-owner-out on the normal-level clips (minimise owner frames
# rejected + bleed frames accepted), then applied to every clip, the quiet-owner ones included.
#
#   python3 -I bleed_analyze.py BLEED_DIR FEAT_DIR OUT.json
import glob, itertools, json, os, statistics as st, sys
import numpy as np

CL, FT, OUT = sys.argv[1:4]
LANGS = ["en", "es", "fr", "pt", "ja", "ht"]
STEP = 0.05
BUF = float(os.environ.get("BUF", "0"))   # decision look-ahead: audio held this long before it is passed on
enrol = json.load(open(os.path.join(FT, "_enrol.json")))
clips = []
for j in sorted(glob.glob(os.path.join(CL, "bleed_*.json"))):
    m = json.load(open(j))
    z = np.load(os.path.join(FT, m["name"] + ".npz"))
    rms = np.load(os.path.join(FT, m["name"] + "_rms.npy"))
    erms = np.load(os.path.join(FT, f"enrol_{m['owner']}_rms.npy"))
    loud = erms[erms > erms.max() * 0.25]
    clips.append({"m": m, "z": {k: z[k] for k in z.files}, "rms": rms, "enrol_level": float(np.sqrt(np.mean(loud ** 2)))})


def grid(c):
    T = np.arange(0, len(c["rms"]) * 0.02, STEP)
    own = np.zeros(len(T), bool)
    oth = np.zeros(len(T), bool)
    for s in c["m"]["segments"]:
        a, b = np.searchsorted(T, s["start"]), np.searchsorted(T, s["end"])
        (own if s["who"] == "owner" else oth)[a:b] = True
    return T, own, oth


def latest(t_arr, T):
    """Index of the latest window that has ended by each grid time plus the hold-back BUF."""
    return np.searchsorted(t_arr, T + BUF, side="right") - 1


def dec_level(c, T, G):
    r = c["rms"]
    sm = np.array([r[max(0, i - 5):i + 1].max() for i in range(len(r))])
    L = c["enrol_level"]
    out = np.zeros(len(T), bool)
    hang = 0.0
    for k, t in enumerate(T):
        i = min(len(sm) - 1, int(t / 0.02))
        j = min(len(sm), int((t + min(BUF, 0.3)) / 0.02) + 1)
        if sm[i:j].max() >= L * 10 ** (-G / 20):
            out[k] = True
            hang = t + 0.3
            L = 0.98 * L + 0.02 * sm[i]          # follow the owner's level
        elif t < hang:
            out[k] = True
    return out


def dec_voice(c, T, TAU, w, secs):
    e = np.array(enrol[c["m"]["owner"]][f"{secs}s_{w}"], np.float32)
    E = c["z"][f"emb{w}"].astype(np.float32)
    cos = E @ e
    med = np.array([np.median(cos[max(0, i - 2):i + 1]) for i in range(len(cos))])
    idx = latest(c["z"][f"t{w}"], T)
    return np.where(idx >= 0, med[np.clip(idx, 0, None)] >= TAU, False)


def dec_lang(c, T, DELTA):
    lang = c["m"]["owner_lang"]
    vl = c["z"]["vl"]
    a = LANGS.index(lang)
    others = [i for i in range(len(LANGS)) if i != a]
    margin = vl[:, a] - vl[:, others].max(axis=1)
    idx = latest(c["z"]["vl_t"], T)
    return np.where(idx >= 0, margin[np.clip(idx, 0, None)] >= DELTA, False)


def metrics(c, acc):
    T, own, oth = grid(c)
    only_oth = oth & ~own
    words_lost = words_own = 0
    bleed_words = bleed_total = 0
    delays_own, delays_rej = [], []
    for s in c["m"]["segments"]:
        a, b = np.searchsorted(T, s["start"]), np.searchsorted(T, s["end"])
        if b <= a:
            continue
        n = len(s["text"].split()) if s.get("text") else max(1, round((s["end"] - s["start"]) * 2.5))
        pos = [a + int((b - a) * (k + 0.5) / n) for k in range(n)]
        if s["who"] == "owner":
            words_own += n
            words_lost += sum(1 for p in pos if not acc[p])
            hit = np.nonzero(acc[a:b])[0]
            delays_own.append(hit[0] * STEP if len(hit) else None)
        else:
            mask = only_oth[a:b]
            for p in pos:
                if only_oth[p]:
                    bleed_total += 1
                    bleed_words += int(acc[p])
            if mask.any():
                seg = acc[a:b][mask]
                rej = np.nonzero(~seg)[0]
                delays_rej.append(rej[0] * STEP if len(rej) else None)
    return {"owner_frames": int(own.sum()), "owner_rejected": int((own & ~acc).sum()),
            "bleed_frames": int(only_oth.sum()), "bleed_accepted": int((only_oth & acc).sum()),
            "owner_words": words_own, "owner_words_lost": words_lost, "bleed_words": bleed_total,
            "bleed_words_accepted": bleed_words, "own_accept_delay": delays_own, "bleed_reject_delay": delays_rej}


GRIDS = {"a": {"G": [3, 6, 9, 12]}, "b": {"TAU": [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]}, "d": {"DELTA": [-4, -3, -2, -1, 0]}}


def decide(c, meth, th, w=1.5, secs=10):
    T, _, _ = grid(c)
    parts = []
    if meth in ("a", "c", "e"):
        parts.append(dec_level(c, T, th["G"]))
    if meth in ("b", "c", "e"):
        parts.append(dec_voice(c, T, th["TAU"], w, secs))
    if meth in ("d", "e"):
        parts.append(dec_lang(c, T, th["DELTA"]))
    return np.logical_and.reduce(parts)


def cost(rows):
    of = sum(r["owner_frames"] for r in rows)
    bf = sum(r["bleed_frames"] for r in rows)
    return sum(r["owner_rejected"] for r in rows) / max(1, of) + sum(r["bleed_accepted"] for r in rows) / max(1, bf)


def combos(meth):
    keys = {"a": ["G"], "b": ["TAU"], "c": ["G", "TAU"], "d": ["DELTA"], "e": ["G", "TAU", "DELTA"]}[meth]
    src = {"G": GRIDS["a"]["G"], "TAU": GRIDS["b"]["TAU"], "DELTA": GRIDS["d"]["DELTA"]}
    for vals in itertools.product(*[src[k] for k in keys]):
        yield dict(zip(keys, vals))


owners = sorted({c["m"]["owner"] for c in clips})
results = {}
METHODS = os.environ.get("METHODS", "abcde")
VARIANTS = [(1.5, 10), (1.0, 10), (1.5, 5), (1.5, 3)] if os.environ.get("WINS", "1.0,1.5") != "1.5" else [(1.5, 10), (1.5, 5), (1.5, 3)]
for meth in METHODS:
    for w, secs in (VARIANTS if meth in "bce" else [(1.5, 10)]):
        tag = f"{meth}" + (f"_w{w}_enrol{secs}s" if meth in "bce" else "")
        rows_by_clip, chosen = {}, {}
        cache = {}
        for o in owners:   # leave this owner out when choosing thresholds
            train = [c for c in clips if c["m"]["owner"] != o and c["m"]["quiet"] == 0]
            best, bt = None, None
            for th in combos(meth):
                key = json.dumps(th, sort_keys=True)
                if key not in cache:
                    cache[key] = {c["m"]["name"]: metrics(c, decide(c, meth, th, w, secs)) for c in clips}
                v = cost([cache[key][c["m"]["name"]] for c in train])
                if best is None or v < best:
                    best, bt = v, th
            chosen[o] = bt
            for c in clips:
                if c["m"]["owner"] == o:
                    rows_by_clip[c["m"]["name"]] = cache[json.dumps(bt, sort_keys=True)][c["m"]["name"]]
        results[tag] = {"thresholds_by_held_out_owner": chosen, "clips": rows_by_clip}


def summarise(rows):
    f = lambda k: sum(r[k] for r in rows)
    od = [d for r in rows for d in r["own_accept_delay"] if d is not None]
    rd = [d for r in rows for d in r["bleed_reject_delay"] if d is not None]
    return {"owner_words_lost_pct": round(100 * f("owner_words_lost") / max(1, f("owner_words")), 1),
            "owner_frames_rejected_pct": round(100 * f("owner_rejected") / max(1, f("owner_frames")), 1),
            "bleed_words_accepted_pct": round(100 * f("bleed_words_accepted") / max(1, f("bleed_words")), 1),
            "bleed_frames_accepted_pct": round(100 * f("bleed_accepted") / max(1, f("bleed_frames")), 1),
            "owner_accept_delay_p50": round(st.median(od), 2) if od else None,
            "bleed_reject_delay_p50": round(st.median(rd), 2) if rd else None}


table = {}
conds = sorted({(c["m"]["kind"], c["m"]["db"]) for c in clips}, key=lambda k: (k[0], -k[1]))
for tag, r in results.items():
    t = {}
    for kind, db in conds:
        for q in (0, -6):
            rows = [r["clips"][c["m"]["name"]] for c in clips if c["m"]["kind"] == kind and c["m"]["db"] == db and c["m"]["quiet"] == q]
            t[f"{kind}{db}_owner{q}dB"] = summarise(rows)
    t["all_normal"] = summarise([r["clips"][c["m"]["name"]] for c in clips if c["m"]["quiet"] == 0])
    t["all_quiet"] = summarise([r["clips"][c["m"]["name"]] for c in clips if c["m"]["quiet"] == -6])
    t["thresholds"] = r["thresholds_by_held_out_owner"]
    table[tag] = t
json.dump(table, open(OUT, "w"), indent=1)
for tag, t in table.items():
    n, q = t["all_normal"], t["all_quiet"]
    print(f"{tag:22s} lost {n['owner_words_lost_pct']:5.1f} / quiet {q['owner_words_lost_pct']:5.1f} | bleed acc {n['bleed_words_accepted_pct']:5.1f} / quiet {q['bleed_words_accepted_pct']:5.1f} | own delay {n['owner_accept_delay_p50']} rej delay {n['bleed_reject_delay_p50']}")
