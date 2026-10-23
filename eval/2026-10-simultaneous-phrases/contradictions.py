# Contradiction rate of phrase-by-phrase output: for each read sentence, the chunks a
# system spoke one after another, judged against the finished sentence. A chunk is
# "wrong" when what it says turns out wrong once the whole sentence is known (a guess
# the rest contradicts, a wrong grammatical role or word order that changes the
# meaning, a repetition of an earlier chunk, or a word that later chunks had to take
# back). Blind: phrase systems shuffled under letters, one call per direction and
# pause pattern, the same grader as grade.py.
#
#   GEMINI_API_KEY=... python3 -I contradictions.py contra_jobs.json contra.json
import concurrent.futures as cf
import json, os, random, sys, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("grade", os.path.join(HERE, "..", "2026-10-es-pt-live-compare", "grade.py"))
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)


def one(job):
    s, t = job["src"], job["tgt"]
    labels = list(job["systems"])
    random.Random(job["id"]).shuffle(labels)
    names = {chr(65 + i): m for i, m in enumerate(labels)}
    blocks = [f"### System {L}\n" + json.dumps(job["systems"][m], ensure_ascii=False) for L, m in names.items()]
    n = len(job["source"])
    p = f"""Live interpreters translated {G.NAMES[s]} speech into spoken {G.NAMES[t]} phrase by phrase, while the speaker was still talking. Each system's entry is a list aligned to the {n} source sentences; each item is the list of chunks that system spoke for that sentence, in order. Spoken words cannot be taken back.

For every sentence and system, count how many chunks turned out WRONG once the whole sentence is known: a chunk that guessed something the rest of the sentence contradicts, put a word in a role or order that changes the meaning, repeated what an earlier chunk already said, or said something a later chunk had to correct. Do NOT count a chunk as wrong only because it is awkward, or because the source itself was misheard in a way the full sentence also carries.

Source sentences ({G.NAMES[s]}):
{json.dumps(job["source"], ensure_ascii=False)}

Reference meaning (English):
{json.dumps(job["reference"], ensure_ascii=False)}

Systems:
{chr(10).join(blocks)}

Return JSON: {{"A": [{{"i": 0, "chunks": 3, "wrong": 0, "note": "..."}}, ... {n} items], "B": [...], ...}}; "chunks" is the number of chunks in that item; a note of at most 8 words only when wrong > 0."""
    for _ in range(4):
        try:
            res, usage = G.gemini(p)
        except json.JSONDecodeError:
            continue
        if isinstance(res, dict) and all(isinstance(res.get(L), list) and len(res[L]) >= n - 1 for L in names):
            print("judged", job["id"], flush=True)
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
    print("judged", len(R))


if __name__ == "__main__":
    main()
