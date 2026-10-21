#!/usr/bin/env python3
"""Where omni-stt's Segmenter would cut a clip, for several pause settings.

    python3 cutsim.py --probs clip.npz [--server services/omni-stt/server.py]
                      [--settings settings.json | --set "name=endpoint_ms:200,max_s:10" ...]
                      [--ref-ends ref.json] [--out rows.json]

Drives the Segmenter class from omni-stt's own source (the endpointing part of
server.py is exec'd, nothing imported: no torch, no models, no network) with
the clip's 96 ms blocks and per-window Silero probabilities (pauses.py's
--probs file), and prints one JSON row per setting: pieces, their lengths,
how many cuts hit the cap, fell mid-speech (no VAD gap of 96 ms at the cut),
or landed within a second of a reference sentence end (--ref-ends), and when
the first piece would go out. It only shows where the pieces would be cut:
no recognition, network or GPU.

Settings are Segmenter keyword arguments: endpoint_ms, max_s, min_speech_ms,
cut_window_s, cut_dip_prob, cut_dip_ms, cut_endpoint_ms, plus
short_pause_after_s (progressive: a short pause ends a piece once it is this
old, i.e. cut_window_s = max_s - short_pause_after_s). --settings is a JSON
list of {"name": ..., "params": {...}}; --set is "name=key:value,key:value".
Without either, the settings of eval/2026-10-continuous-ht run.

The module settings the Segmenter reads are discovered from server.py's
endpointing section and evaluated from server.py's own assignments
(constants_of below), so a setting added there is picked up here without a
change. Standard library and numpy.
"""
import argparse
import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SERVER = os.path.join(ROOT, "services", "omni-stt", "server.py")
RATE, BLOCK, WINDOW = 16000, 1536, 512

# The endpointing section of server.py (quietest_cut .. vad_windows) reads
# module-level settings such as ENDPOINT_MS. They are discovered from the
# section itself (every UPPER_CASE name it uses) and evaluated from server.py's
# own assignment of each, so a setting added there is picked up without a
# change here. Only these assignment forms are evaluated:
#   NAME = int(os.environ.get("NAME", "300"))      NAME = float(os.environ.get(...))
#   NAME = 700                                     NAME = 256 * 1024
# A name with no such assignment falls back to FALLBACK (the values at the
# time of writing) and is reported; one not even there stops the run.
SECTION_START, SECTION_END = "def quietest_cut", "def vad_windows"
ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*) = (.+?)\s*(#.*)?$", re.M)
SAFE_VALUE = re.compile(r'^(int|float)\(os\.environ\.get\("[A-Z0-9_]+", "[0-9.]+"\)\)$'
                        r"|^[0-9][0-9.]*( [*+] [0-9][0-9.]*)*$")
NAME_IN_CODE = re.compile(r"(?<![\w.])([A-Z][A-Z0-9_]{2,})(?![\w(])")
FALLBACK = dict(VAD_RATE=16000, VAD_LAG_MS=64, TRAILING_KEEP_MS=250, SHORT_TURN_ENDPOINT_MS=700, ENDPOINT_MS=300,
                MAX_UTTERANCE_S=6.0, MIN_SPEECH_MS=400, CUT_WINDOW_S=3.5, CUT_DIP_PROB=0.5, CUT_DIP_MS=96,
                CUT_ENDPOINT_MS=200)

DEFAULT_SETTINGS = [
    {"name": "700 ms pause, 15 s cap", "params": {"endpoint_ms": 700, "max_s": 15}},
    {"name": "300 ms pause, 6 s cap (code defaults)", "params": {"endpoint_ms": 300, "max_s": 6}},
    {"name": "300 ms pause, 8 s cap", "params": {"endpoint_ms": 300, "max_s": 8}},
    {"name": "300 ms pause, 10 s cap", "params": {"endpoint_ms": 300, "max_s": 10}},
    {"name": "300 ms pause, 10 s cap, 1 s minimum speech", "params": {"endpoint_ms": 300, "max_s": 10, "min_speech_ms": 1000}},
    {"name": "400 ms pause, 10 s cap, 1 s minimum speech", "params": {"endpoint_ms": 400, "max_s": 10, "min_speech_ms": 1000}},
    {"name": "200 ms pause, 8 s cap", "params": {"endpoint_ms": 200, "max_s": 8}},
    {"name": "200 ms pause, 10 s cap", "params": {"endpoint_ms": 200, "max_s": 10}},
    {"name": "200 ms pause, 10 s cap, 1 s minimum speech", "params": {"endpoint_ms": 200, "max_s": 10, "min_speech_ms": 1000}},
    {"name": "150 ms pause, 8 s cap", "params": {"endpoint_ms": 150, "max_s": 8}},
    {"name": "300 ms pause, 10 s cap, 100 ms pause accepted after 4 s",
     "params": {"endpoint_ms": 300, "max_s": 10, "cut_endpoint_ms": 100, "short_pause_after_s": 4}},
]


def constants_of(src):
    """The module-level settings the endpointing section of server.py's source
    reads, evaluated from the file's own assignments: {name: value}, plus the
    names that had to come from FALLBACK."""
    section = src[src.index(SECTION_START):src.index(SECTION_END)]
    section = re.sub(r"#.*", "", re.sub(r'"""[\s\S]*?"""', "", section))     # code only, not its comments
    assigned = {}
    for name, value, _ in ASSIGNMENT.findall(src[:src.index(SECTION_START)]):
        if SAFE_VALUE.match(value):
            assigned.setdefault(name, value)
    names = sorted(set(NAME_IN_CODE.findall(section)) & (set(assigned) | set(FALLBACK)))
    g, missing = {"os": os}, []
    for name in names:
        if name in assigned:
            exec(f"{name} = {assigned[name]}", g)       # the same expression server.py evaluates
        else:
            missing.append(name)
            g[name] = FALLBACK[name]
    unknown = sorted(n for n in set(NAME_IN_CODE.findall(section)) - set(names)
                     if re.search(rf"^{n} = ", src[:src.index(SECTION_START)], re.M))
    if unknown:
        raise SystemExit(f"cutsim: cannot evaluate {', '.join(unknown)} from server.py "
                         "(an assignment form constants_of does not accept)")
    return {k: g[k] for k in names}, missing


def segmenter_from_source(src, label="server.py"):
    """The Segmenter class, exec'd from server.py's endpointing section with
    the constants read from the same source."""
    consts, missing = constants_of(src)
    if missing:
        print(f"cutsim: {', '.join(missing)} not assigned in {label}; using built-in defaults", file=sys.stderr)
    g = {"os": os}
    g.update(consts)
    exec(src[src.index(SECTION_START):src.index(SECTION_END)], g)
    return g["Segmenter"], consts


def load_segmenter(server_path):
    return segmenter_from_source(open(server_path, encoding="utf-8").read(), server_path)


def gap_at(p, sample, thr=0.5):
    """Length (ms) of the run of VAD windows under thr at or next to a cut sample."""
    w = min(len(p) - 1, sample // WINDOW)
    if p[w] >= thr:                      # cut in a speech window: check the neighbours (VAD lag)
        for ww in (w - 1, w + 1, w - 2):
            if 0 <= ww < len(p) and p[ww] < thr:
                return gap_at(p, ww * WINDOW, thr) // 2        # half credit: the edge of a dip
        return 0
    lo = w
    while lo > 0 and p[lo - 1] < thr:
        lo -= 1
    hi = w
    while hi < len(p) and p[hi] < thr:
        hi += 1
    return (hi - lo) * WINDOW * 1000 // RATE


def simulate(Segmenter, x, p, params, ref_ends=None):
    kw = dict(params)
    prog_after = kw.pop("short_pause_after_s", None)
    s = Segmenter(**kw)
    if prog_after is not None:
        s.cut_window_s = s.max_s - prog_after
    utts, kinds = [], []
    for k in range(len(x) // BLOCK):
        blk = x[k * BLOCK:(k + 1) * BLOCK]
        over = (len(s.buf) + BLOCK) / RATE >= s.max_s and s.speech_seen
        for _, a, b in s.feed(blk, [float(v) for v in p[k * 3:k * 3 + 3]]):
            utts.append((a, b, (k + 1) * BLOCK / RATE * 1000))
            kinds.append("cap" if over else ("near" if len(s.buf) else "end"))
    for _, a, b in (s.flush() if s.speech_seen else []):
        utts.append((a, b, len(x) / RATE * 1000))
        kinds.append("end")
    if not utts:
        return {"pieces": 0}
    dur = np.array([(b - a) / 1000 for a, b, _ in utts])
    cuts = [(int(b * RATE / 1000), kd) for (a, b, _), kd in zip(utts[:-1], kinds[:-1])]
    gaps = np.array([gap_at(p, c) for c, _ in cuts]) if cuts else np.zeros(0)
    row = {
        "pieces": len(utts),
        "len_p50_s": round(float(np.median(dur)), 1),
        "len_p90_s": round(float(np.percentile(dur, 90)), 1),
        "len_max_s": round(float(dur.max()), 1),
        "cuts_at_cap": sum(1 for _, kd in cuts if kd == "cap"),
        "cuts_near_cap": sum(1 for _, kd in cuts if kd == "near"),
        "cuts_mid_speech": int((gaps < 96).sum()),
        "pieces_under_1_5_s": int((dur < 1.5).sum()),
        "first_piece_out_s": round(utts[0][2] / 1000, 1),
    }
    if ref_ends:
        row["cuts_near_sentence_end"] = sum(1 for (a, b, _) in utts[:-1] if min(abs(b / 1000 - e) for e in ref_ends) <= 1.0)
    return row


def parse_set(spec):
    name, _, body = spec.partition("=")
    params = {}
    for kv in body.split(","):
        k, _, v = kv.partition(":")
        params[k.strip()] = float(v) if "." in v else int(v)
    return {"name": name.strip(), "params": params}


def load_ref_ends(path):
    d = json.load(open(path, encoding="utf-8"))
    if isinstance(d, dict):
        d = d["sentences"]
    ends = [s["end"] if isinstance(s, dict) else float(s) for s in d]
    return ends[:-1]          # the last end is the end of the clip, not a cut


def main(argv=None):
    ap = argparse.ArgumentParser(description="simulate omni-stt's Segmenter on a clip")
    ap.add_argument("--probs", required=True, help="npz with x (16 kHz float audio) and p (Silero per window), from pauses.py")
    ap.add_argument("--server", default=SERVER, help="omni-stt's server.py")
    ap.add_argument("--settings", help="JSON list of {name, params}")
    ap.add_argument("--set", action="append", default=[], help='"name=endpoint_ms:200,max_s:10" (repeatable)')
    ap.add_argument("--ref-ends", help="JSON: sentence end times in seconds (a list, or {sentences: [{end}]})")
    ap.add_argument("--out", help="write the rows here too")
    args = ap.parse_args(argv)

    Segmenter, consts = load_segmenter(args.server)
    d = np.load(args.probs)
    x, p = d["x"], d["p"]
    settings = DEFAULT_SETTINGS
    if args.settings:
        settings = json.load(open(args.settings, encoding="utf-8"))
    if args.set:
        settings = [parse_set(s) for s in args.set]
    ref_ends = load_ref_ends(args.ref_ends) if args.ref_ends else None
    rows = []
    for st in settings:
        r = simulate(Segmenter, x, p, st["params"], ref_ends)
        r["setting"] = st["name"]
        r["params"] = st["params"]
        rows.append(r)
    out = {"constants": consts, "rows": rows}
    text = json.dumps(out, indent=1)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
