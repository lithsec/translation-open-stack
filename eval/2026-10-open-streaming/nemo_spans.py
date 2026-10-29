# Audio spans for nemo_stream.py's finals from when their words appeared, instead of the
# VAD turn: Silero missed the quietest English readers (about -60 dBFS), so some finals
# carry several sentences while their turn span covers only the last one, which put
# chunks on the wrong sentence. The model emits a word within one chunk (560 ms) of
# hearing it, so a final's span is taken as [first partial of its segment - 560 ms,
# its last new word's arrival]. Only the chunk placement in analyze_open.py uses it.
#   python3 -I nemo_spans.py REC.json...   (rewrites in place; keeps the VAD span as vadOffsetMs/vadDurationMs)
import json, sys

CHUNK = 560
for p in sys.argv[1:]:
    d = json.load(open(p))
    if d.get("spans_from") == "word arrival":
        continue
    parts = sorted(d["partials"], key=lambda x: x["t"])
    prev_t = -1
    for f in d["finals"]:
        mine = [x for x in parts if prev_t < x["t"] <= f["t"]]
        f["vadOffsetMs"], f["vadDurationMs"] = f["offsetMs"], f["durationMs"]
        if mine:
            a = max(0.0, mine[0]["t"] - CHUNK)
            last = mine[-1]["t"]
            f["offsetMs"], f["durationMs"] = round(a, 1), round(max(1.0, last - a), 1)
        prev_t = f["t"]
    d["spans_from"] = "word arrival"
    json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
    print(p, len(d["finals"]))
