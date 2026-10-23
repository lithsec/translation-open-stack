# Cuts every simulated system's spoken output into the read sentences the same way
# Gemini Live's continuous output is cut (../2026-10-es-pt-live-compare/segment.py):
# the system's chunks are joined in order into one stream, a Gemini call names where
# each read sentence's translation starts (its first words, copied verbatim), and the
# stream is cut at those anchors, so the cut can only divide the stream, never change
# a word. One method for every system, so a recogniser that returns several sentences
# in one final is not penalised for where its text lands.
#
#   GEMINI_API_KEY=... python3 -I seg_all.py CLIPS_ROOT WORK
# Writes WORK/seg/<system>/<pattern>_<src>-<tgt>.json: {"out": [...], "spans": [[a, b]], "chunk_of_char": [...]}
import concurrent.futures as cf
import glob, json, os, sys, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT, WORK = sys.argv[1], sys.argv[2]
sys.argv = [sys.argv[0], os.path.join(ROOT, "clips_reg"), WORK]   # segment.py reads CLIPS, OUT at import
spec = importlib.util.spec_from_file_location("segment", os.path.join(HERE, "..", "2026-10-es-pt-live-compare", "segment.py"))
seg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seg)
NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French", "ja": "Japanese"}


def one(path):
    sim = json.load(open(path))
    s, t = sim["dir"].split("-")
    out_p = os.path.join(WORK, "seg", sim["system"], os.path.basename(path))
    if os.path.exists(out_p):
        return out_p, "cached"
    src = json.load(open(os.path.join(ROOT, f"clips_{sim['pattern']}", f"{s}.txt.json")))
    sep = "" if t == "ja" else " "
    stream, owner = "", []
    for k, c in enumerate(sim["chunks"]):
        piece = c["out"].strip()
        if not piece:
            continue
        if stream:
            stream += sep
            owner += [k] * len(sep)
        stream += piece
        owner += [k] * len(piece)
    prompt = f"""Below are {len(src)} {NAMES[s]} sentences that a speaker read aloud, in order, and the continuous {NAMES[t]} output of a live interpreter who translated them as they were spoken. The interpreter may have skipped, merged or garbled some sentences.

For each {NAMES[s]} sentence, give the exact first words (about 4-8 words, or the first 6-12 characters for languages written without spaces) of where ITS translation begins in the interpreter's output, copied character for character from the output. Use "" if that sentence was not translated at all, or if its content only appears merged inside the previous sentence's translation. The starts must appear in the output in order.

{NAMES[s]} sentences:
{json.dumps(src, ensure_ascii=False, indent=0)}

Interpreter output:
{stream}

Return JSON: {{"starts": ["...", ... exactly {len(src)} strings]}}"""
    anchors = []
    for _ in range(3):
        r = seg.gemini(prompt)
        anchors = r.get("starts", []) if isinstance(r, dict) else []
        if len(anchors) == len(src):
            break
    spans = seg.cut(stream, anchors)
    out = [stream[a:b].strip() if a is not None else "" for a, b in spans]
    os.makedirs(os.path.dirname(out_p), exist_ok=True)
    json.dump({"out": out, "spans": spans, "chunk_of_char": owner, "anchors": anchors,
               "anchors_not_found": sum(1 for a in anchors if a and a.strip()) - sum(1 for a, _ in spans if a is not None)},
              open(out_p, "w"), ensure_ascii=False, indent=1)
    return out_p, f"{sum(1 for a, _ in spans if a is not None)}/{len(src)} located"


if __name__ == "__main__":
    paths = sorted(glob.glob(os.path.join(WORK, "sim", "*", "*.json")))
    with cf.ThreadPoolExecutor(6) as ex:
        for p, msg in ex.map(one, paths):
            print(os.path.relpath(p, WORK), msg, flush=True)
