# pauses.py <probs.npz>: how long the quiet gaps in the clip are, and how much speech runs between them.
# A gap is a run of Silero windows (32 ms each) whose speech probability is under the threshold,
# counted between the first and last speech window. Prints JSON.
import sys, json, numpy as np

d = np.load(sys.argv[1]); p = d["p"]; W = 32
out = []
for thr in (0.5, 0.35, 0.2):
    sp = p >= thr
    n = len(p)
    first = int(np.argmax(sp)); last = n - 1 - int(np.argmax(sp[::-1]))
    runs, i = [], first
    while i <= last:
        if not sp[i]:
            j = i
            while j <= last and not sp[j]:
                j += 1
            runs.append((j - i) * W); i = j
        else:
            i += 1
    runs = np.array(runs); span_s = (last - first + 1) * W / 1000

    def phrases(k):
        """Speech between two gaps of at least k ms (s): median, p90, max."""
        i, start, o = first, first, []
        while i <= last:
            if not sp[i]:
                j = i
                while j <= last and not sp[j]:
                    j += 1
                if (j - i) * W >= k:
                    o.append((i - start) * W / 1000); start = j
                i = j
            else:
                i += 1
        o = np.array(o)
        return {"p50_s": round(float(np.median(o)), 1), "p90_s": round(float(np.percentile(o, 90)), 1), "max_s": round(float(o.max()), 1)}

    out.append({"threshold": thr, "span_s": round(span_s), "gaps": len(runs),
                "gaps_at_least_ms": {str(k): int((runs >= k).sum()) for k in (80, 120, 160, 200, 300, 500)},
                "gaps_per_min_at_least_ms": {str(k): round(float((runs >= k).sum() / span_s * 60)) for k in (200, 300, 500)},
                "speech_between_gaps_at_least_ms": {str(k): phrases(k) for k in (96, 160, 200, 300, 500)}})
print(json.dumps(out, indent=1))
