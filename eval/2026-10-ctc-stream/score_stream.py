# Score eval_client.py outputs.  python3 -I score_stream.py SETDIR OUT.json [OUT2.json ...]
# CER as the 2026-10-26 research score.py: NFKC, lowercase, only str.isalnum() characters, Levenshtein over
# the joined references vs the joined hypotheses ("marks": letters, marks and digits kept).
# committed = the streaming track's committed text per clip; final = the per-piece inputTranscripts joined.
# Latencies (s): first_partial / first_commit = arrival minus the clip's speech onset (energy, -30 dB);
# commit_lag = arrival minus the audio time the commit reaches (end_ms); partial_lag likewise;
# end_commit / final = arrival of the turn-closing commit / the last inputTranscript minus the speech end.
import json, sys, unicodedata

def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]
def norm(s): return "".join(c for c in unicodedata.normalize("NFKC", s).lower() if c.isalnum())
def norm_m(s): return "".join(c for c in unicodedata.normalize("NFKC", s).lower() if unicodedata.category(c)[0] in "LMN")
def cer(refs, hyps, f=norm):
    x, y = f(" ".join(refs)), f(" ".join(hyps)); return round(100 * lev(x, y) / max(1, len(x)), 1)
def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2) if xs else None

def score(setdir, path):
    d = json.load(open(path)); man = {r["i"]: r for r in json.load(open(f"{setdir}/manifest.json"))["rows"][d["lang"]]}
    rows = [r for r in d["rows"] if "msgs" in r]
    errs = len(d["rows"]) - len(rows)
    first = {}
    for r in rows:                      # one row per clip for CER (the first time it was played)
        first.setdefault(r["i"], r)
    refs, com, fin = [], [], []
    for i, r in sorted(first.items()):
        refs.append(man[i]["ref"])
        com.append("".join(m["text"] for m in r["msgs"] if m["type"] == "committed"))
        fin.append(" ".join(m["text"] for m in r["msgs"] if m["type"] == "inputTranscript"))
    L = {k: [] for k in ("first_partial", "first_commit", "commit_lag", "partial_lag", "end_commit", "final")}
    for r in rows:
        ms = r["msgs"]; on, off = r["onset_s"], r["speech_end_s"]
        p = [m for m in ms if m["type"] == "partial" and m["text"]]
        c = [m for m in ms if m["type"] == "committed" and m["text"]]
        if p: L["first_partial"].append(p[0]["t"] - on)
        if c: L["first_commit"].append(c[0]["t"] - on)
        L["commit_lag"] += [m["t"] - (m["end_ms"] / 1000 - 0.5) for m in c if not m.get("end")]
        L["partial_lag"] += [m["t"] - (m["end_ms"] / 1000 - 0.5) for m in p]
        e = [m for m in ms if m["type"] == "committed" and m.get("end")]
        if e: L["end_commit"].append(e[-1]["t"] - off)
        f = [m for m in ms if m["type"] == "inputTranscript"]
        if f: L["final"].append(f[-1]["t"] - off)
    out = {"file": path.split("/")[-1], "lang": d["lang"], "lookahead": d["lookahead"], "streams": d["streams"],
           "clips": len(first), "plays": len(rows), "errors": errs,
           "cer_committed": cer(refs, com), "cer_final": cer(refs, fin),
           "cer_committed_marks": cer(refs, com, norm_m), "cer_final_marks": cer(refs, fin, norm_m)}
    for k, v in L.items():
        out[k] = {"p50": pct(v, .5), "p90": pct(v, .9), "n": len(v)}
    return out

if __name__ == "__main__":
    res = [score(sys.argv[1], p) for p in sys.argv[2:]]
    for o in res:
        lat = " ".join(f'{k} {o[k]["p50"]}/{o[k]["p90"]}' for k in ("first_partial", "first_commit", "commit_lag", "end_commit", "final"))
        print(f'{o["file"]:34s} {o["lang"]} la{o["lookahead"]} x{o["streams"]} clips {o["clips"]} plays {o["plays"]} err {o["errors"]} '
              f'CER committed {o["cer_committed"]} final {o["cer_final"]} | {lat}')
    print(json.dumps(res, ensure_ascii=False))
