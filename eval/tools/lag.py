#!/usr/bin/env python3
"""How far behind the speaker a listener hears each piece, from an event log.

    python3 lag.py run.jsonl --wav clip.wav [--out stats.json] [--pieces] [--text out.txt] [--source-text src.txt]

Reads the event log pace.py writes (README.md, "Event log") and prints JSON:

- first_audio_s: speech start to the first voiced sound of the translation, as played.
- piece_lag_p50_s / p90: for each piece, from the moment its speech STARTS to
  the first voiced sound of its translation as played (after any earlier
  translation still playing). Also from its speech END (piece_end_lag_*).
- final_lag_s: the speaker's last word to the end of the last translated audio.
- pieces, piece_s_p50/p90/max, piece_units_p50/p90/max (words, or characters
  with --units chars), pieces_without_audio, backlog, usage totals.

Playing: output audio is played in arrival order, each chunk when it arrives or
when the previous one ends, whichever is later. "Voiced" is the chunk's first
10 ms frame over the level pace.py marks (`on`), so streamed silence does not
count as audio.

Which audio belongs to which piece decides the per-piece figures:

- by offsets, when the log carries the service's own markers (`marker` events
  with a piece id and an output offset, or `audio` events tagged with a piece):
  a chunk belongs to the piece whose marker covers its offset in the output
  stream. This counts a backlog correctly: a piece's first sound is its own,
  however late it plays.
- by arrival, otherwise: a chunk belongs to the latest piece whose `input`
  arrived before it. When the voice is backlogged, the tail of the previous
  piece arrives after the next `input` and is taken for the next piece's
  start, so per-piece lag is UNDER-reported (first audio and final lag are
  not affected). The output says which was used ("attribution").

Speech start and end come from the clip (--wav: frames over a fifth of the
90th-percentile RMS), or --speech-start/--speech-end in seconds. Per-piece
lag from speech start needs the pieces' times (`start_ms`/`end_ms` on the
`input` events, which omni-stt reports and the stack does not); without them
the per-piece figures are from the input's arrival instead and say so.
Standard library and numpy.
"""
import argparse
import json
import sys
import wave

import numpy as np

SLACK_MS = 50            # an input logged just after its first audio still owns it


def read_events(path):
    ev = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ev.append(json.loads(line))
    return [e for e in ev if e.get("t") is not None]


def speech_bounds(wav):
    """(start_ms, end_ms) of speech in the clip: the first and last 20 ms frame
    whose RMS reaches a fifth of the 90th percentile."""
    with wave.open(wav) as w:
        rate = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)
    f = rate // 50
    n = len(x) // f
    rms = np.sqrt((x[:n * f].reshape(n, f) ** 2).mean(axis=1))
    loud = np.nonzero(rms >= 0.2 * np.percentile(rms, 90))[0]
    if len(loud) == 0:
        return None, None
    return loud[0] * 20.0, (loud[-1] + 1) * 20.0


def playout(events):
    """Each audio chunk with when it starts to play (`st`) and its queueing
    delay (`q`), in arrival order."""
    play_end, out = 0.0, []
    for e in events:
        if e["kind"] != "audio":
            continue
        dur = e["samples"] / e["rate"] * 1000
        st = max(e["t"], play_end)
        out.append(dict(t=e["t"], st=st, dur=dur, on=e.get("on"), off=e.get("off"),
                        offset=e.get("offset"), samples=e["samples"], piece=e.get("piece"), q=st - e["t"]))
        play_end = st + dur
    return out


def pieces_of(events):
    """One record per `input` event: its text, times, the translation text
    that followed it (a `done`, else the `translation` deltas) and its index."""
    inputs = [e for e in events if e["kind"] == "input"]
    out = []
    for i, inp in enumerate(inputs):
        t0 = inp["t"]
        t1 = inputs[i + 1]["t"] if i + 1 < len(inputs) else float("inf")
        done = next((e for e in events if e["kind"] == "done" and t0 - SLACK_MS <= e["t"] < t1), None)
        deltas = [e.get("text", "") for e in events if e["kind"] == "translation" and t0 - SLACK_MS <= e["t"] < t1]
        out.append(dict(i=i, text=inp.get("text", ""), t=t0, t_next=t1, piece=inp.get("piece"),
                        start_ms=inp.get("start_ms"), end_ms=inp.get("end_ms"),
                        translation=done.get("text", "") if done else "".join(deltas)))
    return out


def attribute(events, pieces, aud):
    """Give each piece the audio chunks that are its own. Returns the method."""
    starts = [e for e in events if e["kind"] == "marker" and e.get("label", "start") == "start"
              and e.get("offset") is not None]
    tagged = [a for a in aud if a["piece"] is not None]
    if starts or tagged:
        if starts:
            # The output stream in piece order: chunk offsets between two markers.
            bounds = [(m.get("piece"), m["offset"]) for m in starts]
            for a in aud:
                owner = None
                for pid, off in bounds:
                    if a["offset"] is not None and a["offset"] >= off:
                        owner = pid
                a["piece"] = owner
        groups = {}
        for a in aud:
            if a["piece"] is not None:
                groups.setdefault(a["piece"], []).append(a)
        ids = list(groups)
        # Markers name the service's piece ids. Match them to inputs by id when
        # inputs carry one, else in order of appearance (the k-th marked
        # piece is the k-th input that got a translation).
        by_id = {p["piece"]: p for p in pieces if p.get("piece") is not None}
        if by_id:
            for pid, chunks in groups.items():
                if pid in by_id:
                    by_id[pid]["audio"] = chunks
        else:
            with_text = [p for p in pieces if p["translation"]] or pieces
            for p, pid in zip(with_text, ids):
                p["audio"] = groups[pid]
        for p in pieces:
            p.setdefault("audio", [])
        return "offsets"
    for p in pieces:
        p["audio"] = [a for a in aud if p["t"] - SLACK_MS <= a["t"] < p["t_next"]]
    return "arrival"


def first_voice(chunks):
    """When the first voiced sound of these chunks plays (ms), or None."""
    for a in chunks:
        if a["on"] is not None:
            return a["st"] + a["on"]
    return None


def pct(xs, q):
    return round(float(np.percentile(xs, q)) / 1000, 1) if len(xs) else None


def analyse(events, speech_start=None, speech_end=None, units="words"):
    aud = playout(events)
    pieces = pieces_of(events)
    method = attribute(events, pieces, aud)
    voiced = [a for a in aud if a["on"] is not None]
    timed = [p for p in pieces if p["start_ms"] is not None and p["end_ms"] is not None]
    if speech_start is None and timed:
        speech_start = min(p["start_ms"] for p in timed)
    if speech_end is None and timed:
        speech_end = max(p["end_ms"] for p in timed)

    def count(s):
        return len("".join(s.split())) if units == "chars" else len(s.split())

    for p in pieces:
        p["first_voice"] = first_voice(p["audio"])
        p["lag_start"] = p["first_voice"] - p["start_ms"] if p["first_voice"] is not None and p["start_ms"] is not None else None
        p["lag_end"] = p["first_voice"] - p["end_ms"] if p["first_voice"] is not None and p["end_ms"] is not None else None
        p["lag_input"] = p["first_voice"] - p["t"] if p["first_voice"] is not None else None
    lag_start = [p["lag_start"] for p in pieces if p["lag_start"] is not None]
    lag_end = [p["lag_end"] for p in pieces if p["lag_end"] is not None]
    lag_input = [p["lag_input"] for p in pieces if p["lag_input"] is not None]
    lengths = [p["end_ms"] - p["start_ms"] for p in timed]
    sizes = [count(p["text"]) for p in pieces]
    usage = [e for e in events if e["kind"] == "usage"]
    minutes = int(max((e["t"] for e in events), default=0) // 60000) + 1
    res = {
        "attribution": method,
        "attribution_note": ("the service's offsets or markers: a backlogged voice is counted" if method == "offsets"
                             else "by arrival: per-piece lag is under-reported when the voice is backlogged"),
        "speech_start_s": round(speech_start / 1000, 2) if speech_start is not None else None,
        "speech_end_s": round(speech_end / 1000, 2) if speech_end is not None else None,
        "first_audio_s": (round((first_voice(aud) - speech_start) / 1000, 1)
                          if voiced and speech_start is not None else None),
        "final_lag_s": (round((voiced[-1]["st"] + voiced[-1]["off"] - speech_end) / 1000, 1)
                        if voiced and speech_end is not None else None),
        "pieces": len(pieces),
        "pieces_with_times": len(timed),
        "pieces_without_audio": sum(1 for p in pieces if p["first_voice"] is None),
        "pieces_without_translation": sum(1 for p in pieces if not p["translation"]),
        "piece_s_p50": pct(lengths, 50), "piece_s_p90": pct(lengths, 90),
        "piece_s_max": round(max(lengths) / 1000, 1) if lengths else None,
        f"piece_{units}_p50": int(np.median(sizes)) if sizes else None,
        f"piece_{units}_p90": int(np.percentile(sizes, 90)) if sizes else None,
        f"piece_{units}_max": max(sizes) if sizes else None,
        "piece_lag_p50_s": pct(lag_start, 50), "piece_lag_p90_s": pct(lag_start, 90),
        "piece_end_lag_p50_s": pct(lag_end, 50), "piece_end_lag_p90_s": pct(lag_end, 90),
        "input_to_audio_p50_s": pct(lag_input, 50), "input_to_audio_p90_s": pct(lag_input, 90),
        "piece_lag_note": ("from each piece's speech start (start_ms)" if lag_start
                           else "no piece times in the log: input_to_audio is from the input's arrival"),
        "backlog_max_s": round(max((a["q"] for a in aud), default=0) / 1000, 1),
        "backlog_max_by_minute_s": [round(max([a["q"] for a in aud if m * 60000 <= a["t"] < (m + 1) * 60000] or [0]) / 1000, 1)
                                    for m in range(minutes)],
        "voiced_output_s": round(sum(a["off"] - a["on"] for a in voiced) / 1000, 1),
        "audio_chunks": len(aud),
        "errors": [e.get("detail", "")[:120] for e in events if e["kind"] == "error"][:10],
    }
    if usage:
        res["usage"] = {
            "calls": len(usage),
            "non_200": sum(1 for u in usage if u.get("status") not in (None, 200)),
            "prompt": sum(u.get("prompt") or 0 for u in usage),
            "cached": sum(u.get("cached") or 0 for u in usage),
            "completion": sum(u.get("completion") or 0 for u in usage),
            "reasoning": sum(u.get("reasoning") or 0 for u in usage),
            "ms_p50": pct([u["ms"] for u in usage if u.get("ms") is not None], 50),
            "ms_p90": pct([u["ms"] for u in usage if u.get("ms") is not None], 90),
        }
    return res, pieces


def main(argv=None):
    ap = argparse.ArgumentParser(description="per-piece lag from a pace.py event log")
    ap.add_argument("log", help="event log (JSON lines)")
    ap.add_argument("--wav", help="the clip, for its speech start and end")
    ap.add_argument("--speech-start", type=float, help="seconds; overrides --wav")
    ap.add_argument("--speech-end", type=float, help="seconds; overrides --wav")
    ap.add_argument("--units", choices=("words", "chars"), default="words", help="chars for ja, zh, ko")
    ap.add_argument("--out", help="write the JSON here too")
    ap.add_argument("--pieces", action="store_true", help="print one line per piece")
    ap.add_argument("--text", help="write the translation (all pieces, in order) to this file, for judge.py")
    ap.add_argument("--source-text", help="write what was heard (all inputs, in order) to this file")
    args = ap.parse_args(argv)

    start = end = None
    if args.wav:
        start, end = speech_bounds(args.wav)
    if args.speech_start is not None:
        start = args.speech_start * 1000
    if args.speech_end is not None:
        end = args.speech_end * 1000
    events = read_events(args.log)
    res, pieces = analyse(events, start, end, args.units)
    text = json.dumps(res, indent=1, ensure_ascii=False)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    if args.text:
        sep = "" if args.units == "chars" else " "
        with open(args.text, "w", encoding="utf-8") as f:
            f.write(sep.join(p["translation"] for p in pieces if p["translation"]) + "\n")
    if args.source_text:
        sep = "" if args.units == "chars" else " "
        with open(args.source_text, "w", encoding="utf-8") as f:
            f.write(sep.join(p["text"] for p in pieces) + "\n")
    if args.pieces:
        print("piece  start s  len s  lag s (from start)  from input s  text", file=sys.stderr)
        for p in pieces:
            s = f"{p['start_ms'] / 1000:7.1f}" if p["start_ms"] is not None else "      -"
            ln = f"{(p['end_ms'] - p['start_ms']) / 1000:5.1f}" if p["end_ms"] is not None and p["start_ms"] is not None else "    -"
            lag = f"{p['lag_start'] / 1000:6.1f}" if p["lag_start"] is not None else "     -"
            li = f"{p['lag_input'] / 1000:6.1f}" if p["lag_input"] is not None else "     -"
            print(f"{p['i']:5d}  {s}  {ln}  {lag}              {li}        {p['text'][:60]}", file=sys.stderr)


if __name__ == "__main__":
    main()
