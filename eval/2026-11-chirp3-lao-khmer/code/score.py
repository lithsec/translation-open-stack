# Character error (spaces and punctuation removed: Khmer and Lao don't separate words with spaces) and the final's
# delay after the voice actually stops (last 30 ms frame above -40 dBFS... relative to the clip's peak).
import array, json, math, os, sys, unicodedata

DATA = sys.argv[1]
RUNS = sys.argv[2:]


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFC", s).lower() if not (c.isspace() or unicodedata.category(c).startswith("P")))


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def speech_end_s(path):
    x = array.array("h", open(path, "rb").read())
    n = 480  # 30 ms
    rms = [math.sqrt(sum(v * v for v in x[i:i + n]) / n) for i in range(0, len(x) - n, n)]
    peak = max(rms) or 1
    last = max((i for i, r in enumerate(rms) if r > peak * 0.05), default=len(rms) - 1)  # 26 dB under the peak
    return (last + 1) * n / 16000


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))] if xs else None


for run in RUNS:
    rows = json.load(open(run))
    cfg = "km_kh" if "_km" in run else "lo_la"
    errs = chars = 0
    lat, fp, errors, empty = [], [], 0, 0
    for r in rows:
        if "error" in r:
            errors += 1
            continue
        ref, hyp = norm(r["ref"]), norm(r["hyp"])
        if not hyp: empty += 1
        errs += lev(ref, hyp)
        chars += len(ref)
        if r.get("last_final_after_start_s") is not None:
            end = speech_end_s(os.path.join(DATA, cfg, "pcm", r["file"].replace(".wav", ".raw")))
            lat.append(r["last_final_after_start_s"] - end)
        if r.get("first_partial_after_start_s") is not None: fp.append(r["first_partial_after_start_s"])
    print(f"{os.path.basename(run):16} n={len(rows)} errors={errors} empty={empty} CER={100 * errs / max(chars, 1):.1f}%  "
          f"final after voice stops p50={pct(lat, 50):.2f}s p90={pct(lat, 90):.2f}s  first partial p50={pct(fp, 50):.2f}s")
