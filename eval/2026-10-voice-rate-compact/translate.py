# The concise ("interpreter-style") translations: the same replay as
# ../2026-10-simultaneous-phrases/simulate.py (Azure standard real-time partials of the
# unseen English clips, the same commit policy, Gemma 4 31B on OpenRouter with zero data
# retention), with one instruction added to its prompts. The current-prompt runs are that
# round's P8-gemma31-std and S-gemma31-std, reused as they are (copied in as P8-cur, S-cur).
#
#   CLIPS_ROOT=<dir with clips_reg/ clips_irr/> OPENROUTER_API_KEY=... python3 -I translate.py WORK
# Writes WORK/sim/{P8-con,S-con}/<pattern>_en-<tgt>.json
import concurrent.futures as cf
import importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = sys.argv[1]
sys.argv = [sys.argv[0], WORK]   # simulate.py reads WORK at import
spec = importlib.util.spec_from_file_location("simulate", os.path.join(HERE, "..", "2026-10-simultaneous-phrases", "simulate.py"))
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)

CONCISE = ("Speak like a professional interpreter: keep every fact, name, number, negation and qualifier; drop filler, "
           "repetition and redundant words; prefer shorter phrasing.")
_sentence, _phrase = sim.sentence_prompt, sim.phrase_prompt
sim.sentence_prompt = lambda text, a, b, history: _sentence(text, a, b, history).replace(
    "Keep numbers, names and negation exact.", f"Keep numbers, names and negation exact. {CONCISE}")
sim.phrase_prompt = lambda so_far, spoken, new, a, b, history: _phrase(so_far, spoken, new, a, b, history).replace(
    "Keep numbers, names and negation exact.", f"Keep numbers, names and negation exact. {CONCISE}")
sim.SYSTEMS = {"P8-con": {"rec": "std", "mode": "phrase", "max": 8, "mt": "gemma31"},
               "S-con": {"rec": "std", "mode": "sentence", "mt": "gemma31"}}
DIRS = ["en-es", "en-pt", "en-fr"]

if __name__ == "__main__":
    jobs = [(n, p, d) for n in sim.SYSTEMS for p in ("reg", "irr") for d in DIRS]
    with cf.ThreadPoolExecutor(int(os.environ.get("THREADS", "12"))) as ex:
        for r in ex.map(lambda j: sim.run_stream(*j), jobs):
            print(*r, flush=True)
