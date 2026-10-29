# ../2026-10-complete-thought-ht-km-lo/split.py with this run's languages in the names. That file:
# ../2026-10-complete-thought-endpointing/split.py with Haitian Creole, Khmer and Lao in the language names. That file:
# The split-thought check, beside ../2026-10-simultaneous-phrases/contradictions.py (same jobs, same blind
# shuffle, same grader): for each read sentence and arm, the chunks the arm spoke for it, in order, and how
# many of them (all but the sentence's last) stop in the middle of a clause, so the listener hears an
# unfinished thought and a pause before the rest (a subject with no verb yet, a verb with its object still to
# come, an article or preposition with no noun). A chunk that ends at a clause or sentence boundary is not a
# split, even when the sentence goes on.
#
#   GEMINI_API_KEY=... python3 -I split.py split_jobs.json split.json
import concurrent.futures as cf
import importlib.util, json, os, random, sys

os.environ.setdefault("GRADER", "gemini-flash-latest")
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("grade", os.path.join(HERE, "..", "2026-10-es-pt-live-compare", "grade.py"))
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
G.NAMES.update({"en": "English", "ja": "Japanese", "ko": "Korean", "fa": "Persian", "ur": "Urdu", "bn": "Bengali", "ta": "Tamil", "hi": "Hindi"})


def one(job):
    s, t = job["src"], job["tgt"]
    labels = list(job["systems"])
    random.Random(job["id"] + "split").shuffle(labels)
    names = {chr(65 + i): m for i, m in enumerate(labels)}
    blocks = [f"### System {L}\n" + json.dumps(job["systems"][m], ensure_ascii=False) for L, m in names.items()]
    n = len(job["source"])
    p = f"""Live interpreters translated {G.NAMES[s]} speech into spoken {G.NAMES[t]} chunk by chunk. Each chunk is voiced on its own, with a pause before the next one. Each system's entry is a list aligned to the {n} source sentences; each item is the list of chunks that system spoke for that sentence, in order.

For every sentence and system, count how many chunks, other than the item's last chunk, STOP IN THE MIDDLE OF A THOUGHT: the chunk ends inside a clause, so the listener hears an unfinished piece (for example a subject with no verb yet, a verb whose object is still to come, an article, preposition or auxiliary with nothing after it, or half of a fixed expression). A chunk that ends at the end of a clause or sentence is NOT a split, even if the sentence continues in the next chunk. Judge the {G.NAMES[t]} chunks as heard.

Source sentences ({G.NAMES[s]}):
{json.dumps(job["source"], ensure_ascii=False)}

Systems:
{chr(10).join(blocks)}

Return JSON: {{"A": [{{"i": 0, "chunks": 3, "split": 0, "note": "..."}}, ... {n} items], "B": [...], ...}}; "chunks" is the number of chunks in that item; a note of at most 8 words only when split > 0."""
    for _ in range(4):
        try:
            res, usage = G.gemini(p)
        except json.JSONDecodeError:
            continue
        if isinstance(res, dict) and all(isinstance(res.get(L), list) and len(res[L]) >= n - 1 for L in names):
            print("split", job["id"], flush=True)
            return job["id"], {names[L]: res[L] for L in names}
    raise SystemExit(f"failed on {job['id']}")


def main():
    jobs = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    R = json.load(open(out)) if os.path.exists(out) else {}
    todo = [j for j in jobs if j["id"] not in R and j["systems"]]
    with cf.ThreadPoolExecutor(4) as ex:
        for k, v in ex.map(one, todo):
            R[k] = v
            json.dump(R, open(out, "w"), ensure_ascii=False, indent=1)
    print("split", len(R))


if __name__ == "__main__":
    main()
