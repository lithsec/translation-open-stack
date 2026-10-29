# SimulStreaming's JSONL (simulstreaming_whisper.py, computationally aware real-time
# simulation from the file, --vac) -> the stream_partials.py shape.
#
# SimulStreaming emits only what AlignAtt has decided: each line adds text and nothing
# is revised, so every partial is fully "stable". A segment ends when the voice activity
# controller (Silero) hears its end ("is_final": true); that segment's text is a final.
# emission_time is seconds since the simulation started = the clip's clock.
#   python3 -I simul_to_partials.py IN.jsonl OUT.json [stats.json]
import json, sys

src, out = sys.argv[1], sys.argv[2]
partials, finals, seg, words = [], [], "", []
for line in open(src):
    line = line.strip()
    if not line.startswith("{"):
        continue
    d = json.loads(line)
    t = round(d["emission_time"] * 1000, 1)
    if d.get("text"):
        seg += d["text"]
        words += d.get("words") or []
        txt = " ".join(seg.split())
    if d.get("text") and not d.get("is_final"):   # a final's own words go with the final
        partials.append({"t": t, "text": txt, "offsetMs": round(1000 * (words[0]["start"] if words else d.get("start", 0)), 1),
                         "stable": len(txt.split())})
    if d.get("is_final"):
        txt = " ".join(seg.split())
        if txt:
            a = 1000 * (words[0]["start"] if words else d.get("start", 0))
            b = 1000 * (words[-1]["end"] if words else d.get("end", a / 1000))
            finals.append({"t": t, "text": txt, "offsetMs": round(a, 1), "durationMs": round(max(1, b - a), 1)})
        seg, words = "", []
txt = " ".join(seg.split())
if txt:   # audio ended inside a segment
    a = 1000 * (words[0]["start"] if words else 0)
    finals.append({"t": partials[-1]["t"], "text": txt, "offsetMs": round(a, 1),
                   "durationMs": round(max(1, 1000 * words[-1]["end"] - a) if words else 1, 1)})
json.dump({"model": "SimulStreaming AlignAtt, Whisper large-v3", "err": "", "partials": partials, "finals": finals},
          open(out, "w"), ensure_ascii=False, indent=1)
print(out, len(partials), "partials", len(finals), "finals")
