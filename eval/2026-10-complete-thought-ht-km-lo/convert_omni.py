# omni-stt recordings (stream_omni.py) -> the replay's recording format (stream_partials.py's: partials
# [{t, text, stable?}] and finals [{t, text, offsetMs, durationMs, words}]), so the earlier harness replays them.
#
#   o3   Haitian Creole, omniASR_LLM_300M: finals only (one per piece; the service sends no text while a piece is
#        spoken). A piece's words have no times of their own: the replay spreads them over the time since the
#        previous words (as for MAI partials), which only matters for reporting.
#   o3p  the same with STT_PARTIALS=1 (a prototype, off in production): each "partial" (the whole hypothesis of
#        the piece so far) is a partial; "stable" (the prefix two passes agree on) sets how many of its words are
#        committed at once.
#   o7   Khmer or Lao, the 7B's finals only (the text of record; production's sentences).
#   o7c  the 7B's finals plus the CTC 3B streaming track's live text between them, as Live Translation's solo
#        Khmer or Lao room reads it (live-translation src/main/providers/omni-ctc.ts): the live text is the
#        committed text not yet covered by a 7B piece (a commit belongs to the piece that covers most of its
#        audio), then the latest revisable tail. Each live-text change is a partial whose committed words count as
#        stable; each 7B piece is a final, and right after it the live text past it is sent again as a partial.
#
#   python3 -I convert_omni.py OUT_DIR WORK/rec
import glob, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import words  # noqa: E402

OUT, REC = sys.argv[1], sys.argv[2]
os.makedirs(REC, exist_ok=True)


def final(m):
    return {"t": m["t"], "text": m["text"], "offsetMs": m["start_ms"], "durationMs": m["end_ms"] - m["start_ms"], "words": []}


for p in sorted(glob.glob(os.path.join(OUT, "*.json"))):
    tag, pattern, lang = os.path.basename(p)[:-5].split("_")
    J = json.load(open(p))
    ms = sorted(J["messages"], key=lambda m: m["t"])
    if tag in ("o3", "o3p"):
        partials, finals, cur, stable = [], [], "", 0
        for m in ms:
            if m["type"] == "partial":
                cur = m["text"]
                partials.append({"t": m["t"], "text": cur, "stable": stable})
            elif m["type"] == "stable":
                stable = len(words.toks(m["text"], lang))
                partials.append({"t": m["t"], "text": cur or m["text"], "stable": stable})
            elif m["type"] == "inputTranscript":
                finals.append(final(m))
                cur, stable = "", 0
        json.dump({"lang": lang, "model": tag, "partials": partials, "finals": finals},
                  open(os.path.join(REC, f"{tag}_{pattern}_{lang}.json"), "w"), ensure_ascii=False, indent=1)
        print(tag, pattern, lang, len(partials), "partials", len(finals), "finals")
        continue
    # o7c: socket 0 the 7B, socket 1 the streaming track
    fin = [final(m) for m in ms if m["sock"] == 0 and m["type"] == "inputTranscript"]
    json.dump({"lang": lang, "model": "o7", "partials": [], "finals": fin},
              open(os.path.join(REC, f"o7_{pattern}_{lang}.json"), "w"), ensure_ascii=False, indent=1)
    commits, tail, tail_end, covered, partials = [], "", 0.0, 0.0, []

    def live():
        c = "".join(x["text"] for x in commits if (x["start_ms"] + x["end_ms"]) / 2 > covered)
        return c, c + tail

    for m in ms:
        if m["sock"] == 1 and m["type"] == "committed":
            commits.append(m)
            tail = ""
        elif m["sock"] == 1 and m["type"] == "partial":
            tail, tail_end = m["text"], m["end_ms"]
        elif m["sock"] == 0 and m["type"] == "inputTranscript":
            covered = m["end_ms"]
            if tail_end <= covered:   # a tail that heard no further than the piece is the piece's too
                tail = ""
        else:
            continue
        c, text = live()
        if m["sock"] == 0:
            if text.strip():
                partials.append({"t": m["t"] + 0.1, "text": text, "stable": len(words.toks(c, lang))})
            continue
        if text.strip():
            partials.append({"t": m["t"], "text": text, "stable": len(words.toks(c, lang))})
    json.dump({"lang": lang, "model": "o7c", "partials": partials, "finals": fin},
              open(os.path.join(REC, f"o7c_{pattern}_{lang}.json"), "w"), ensure_ascii=False, indent=1)
    print("o7c", pattern, lang, len(partials), "partials", len(fin), "finals")
