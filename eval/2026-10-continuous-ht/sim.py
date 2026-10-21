# sim.py <omni-stt server.py> <probs.npz> <ref_ht.json>: drive omni-stt's own Segmenter (its source is
# exec'd from server.py) with the clip's 96 ms blocks and per-window Silero speech probabilities, for
# several pause settings, and print one JSON row per setting. No network, no GPU: it only shows where
# the segmenter would cut the clip.
#   probs.npz: x = 16 kHz float audio, p = Silero probability per 512-sample window (see pauses.py)
#   ref_ht.json: {"sentences": [{"start": s, "end": s, ...}]}, approximate sentence ends of the clip
import sys, json, numpy as np

src = open(sys.argv[1]).read()
code = src[src.index("def quietest_cut"):src.index("def vad_windows")]
# (The rows below name every setting they change; CUT_EARLY_S is 0 here, the server's 4.0, so the rows
# without it run the segmenter as it was before the progressive pause cut.)
G = dict(VAD_RATE=16000, VAD_LAG_MS=64, TRAILING_KEEP_MS=250, SHORT_TURN_ENDPOINT_MS=700, ENDPOINT_MS=300,
         MAX_UTTERANCE_S=6.0, MIN_SPEECH_MS=400, CUT_WINDOW_S=3.5, CUT_DIP_PROB=0.5, CUT_DIP_MS=96, CUT_ENDPOINT_MS=200,
         CUT_EARLY_S=0.0)
exec(code, G)
Segmenter = G["Segmenter"]
d = np.load(sys.argv[2]); x, p = d["x"], d["p"]
ref_ends = [s["end"] for s in json.load(open(sys.argv[3]))["sentences"]][:-1]
R, B = 16000, 1536


def gap_at(sample):
    """Length (ms) of the run of Silero windows under 0.5 at or next to a cut sample."""
    w = min(len(p) - 1, sample // 512)
    lo = w
    while lo > 0 and p[lo - 1] < 0.5:
        lo -= 1
    hi = w
    while hi < len(p) and p[hi] < 0.5:
        hi += 1
    if p[w] >= 0.5:   # cut in a speech window: check the neighbour (VAD lag)
        for ww in (w - 1, w + 1, w - 2):
            if 0 <= ww < len(p) and p[ww] < 0.5:
                return gap_at(ww * 512) // 2  # half credit: edge of a dip
        return 0
    return (hi - lo) * 32


def run(prog_after=None, **kw):
    s = Segmenter(**kw)
    if prog_after is not None:   # "progressive": a short pause ends a turn once it passes prog_after s
        s.cut_window_s = s.max_s - prog_after
    utts, kinds = [], []
    for k in range(len(x) // B):
        blk = x[k * B:(k + 1) * B]
        quiet_before = s.quiet_ms
        over = (len(s.buf) + B) / R >= s.max_s and s.speech_seen
        for u, a, b in s.feed(blk, [float(v) for v in p[k * 3:k * 3 + 3]]):
            utts.append((a, b, (k + 1) * B / R * 1000))
            # "early": ended by the progressive pause cut, on less quiet than ENDPOINT_MS.
            kinds.append("cap" if over else ("near" if len(s.buf) else
                         ("early" if quiet_before + B / R * 1000 < s.endpoint_ms else "end")))
    for u, a, b in (s.flush() if s.speech_seen else []):
        utts.append((a, b, len(x) / R * 1000)); kinds.append("end")
    dur = np.array([(b - a) / 1000 for a, b, _ in utts])
    cuts = [(int(b * 16), kd) for (a, b, _), kd in zip(utts[:-1], kinds[:-1])]
    gaps = np.array([gap_at(c) for c, _ in cuts])
    return {"pieces": len(utts), "len_p50_s": round(float(np.median(dur)), 1),
            "len_p90_s": round(float(np.percentile(dur, 90)), 1), "len_max_s": round(float(dur.max()), 1),
            "cuts_at_cap": sum(1 for _, kd in cuts if kd == "cap"),
            "cuts_early": sum(1 for _, kd in cuts if kd == "early"),
            "cuts_mid_speech": int((gaps < 96).sum()),
            "cuts_near_sentence_end": sum(1 for (a, b, _) in utts[:-1] if min(abs(b / 1000 - e) for e in ref_ends) <= 1.0),
            "pieces_under_1_5_s": int((dur < 1.5).sum()),
            "first_piece_out_s": round(utts[0][2] / 1000, 1)}


CFGS = [
    ("700 ms pause, 15 s cap (live setting before)", {}, dict(endpoint_ms=700, max_s=15)),
    ("300 ms pause, 6 s cap (code defaults)", {}, dict(endpoint_ms=300, max_s=6)),
    ("300 ms pause, 8 s cap", {}, dict(endpoint_ms=300, max_s=8)),
    ("300 ms pause, 10 s cap", {}, dict(endpoint_ms=300, max_s=10)),
    ("300 ms pause, 10 s cap, 1 s minimum speech (run 'breath300')", {}, dict(endpoint_ms=300, max_s=10, min_speech_ms=1000)),
    ("400 ms pause, 10 s cap, 1 s minimum speech", {}, dict(endpoint_ms=400, max_s=10, min_speech_ms=1000)),
    ("200 ms pause, 8 s cap", {}, dict(endpoint_ms=200, max_s=8)),
    ("200 ms pause, 10 s cap", {}, dict(endpoint_ms=200, max_s=10)),
    ("200 ms pause, 10 s cap, 1 s minimum speech (run 'breath')", {}, dict(endpoint_ms=200, max_s=10, min_speech_ms=1000)),
    ("150 ms pause, 8 s cap", {}, dict(endpoint_ms=150, max_s=8)),
    ("300 ms pause, 10 s cap, 100 ms pause accepted after 4 s", dict(prog_after=4), dict(endpoint_ms=300, max_s=10, cut_endpoint_ms=100)),
    # The progressive pause cut (CUT_EARLY_S): past 4 s the quiet that ends a piece falls from the pause
    # setting to CUT_ENDPOINT_MS (200 ms) at the cap. With a 200 ms pause there is nothing to fall from.
    ("200 ms pause, 10 s cap, 1 s minimum speech, progressive from 4 s (defaults now)", {},
     dict(endpoint_ms=200, max_s=10, min_speech_ms=1000, cut_early_s=4)),
    ("200 ms pause, 10 s cap, 1 s minimum speech, progressive from 4 s down to 100 ms", {},
     dict(endpoint_ms=200, max_s=10, min_speech_ms=1000, cut_early_s=4, cut_endpoint_ms=100)),
    ("300 ms pause, 10 s cap, 1 s minimum speech, progressive from 4 s", {},
     dict(endpoint_ms=300, max_s=10, min_speech_ms=1000, cut_early_s=4)),
    ("400 ms pause, 10 s cap, 1 s minimum speech, progressive from 4 s", {},
     dict(endpoint_ms=400, max_s=10, min_speech_ms=1000, cut_early_s=4)),
    ("700 ms pause, 15 s cap, progressive from 4 s", {}, dict(endpoint_ms=700, max_s=15, cut_early_s=4)),
]
rows = []
for name, extra, kw in CFGS:
    r = run(**extra, **kw)
    r["setting"] = name
    r["params"] = kw | ({"short_pause_after_s": extra["prog_after"]} if extra else {})
    rows.append(r)
print(json.dumps(rows, indent=1))
