# Fast-mode replay on the conversational clips: Azure standard partials -> phrase (max 8) or whole
# sentences -> Gemma 4 31B (OpenRouter, zero retention). VARIANT=cur (the phrase round's prompts)
# or con (plus the concise instruction of ../2026-10-voice-rate-compact/translate.py).
#   CLIPS_ROOT=... OPENROUTER_API_KEY=... VARIANT=cur|con python3 -I run_mt.py WORK
import concurrent.futures as cf, importlib.util, os, sys
WORK = sys.argv[1]; V = os.environ["VARIANT"]
SIMDIR = os.environ.get("SIMDIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "2026-10-simultaneous-phrases"))
sys.argv = [sys.argv[0], WORK]
spec = importlib.util.spec_from_file_location("simulate", os.path.join(SIMDIR, "simulate.py"))
sim = importlib.util.module_from_spec(spec); spec.loader.exec_module(sim)
CONCISE = ("Speak like a professional interpreter: keep every fact, name, number, negation and qualifier; drop filler, "
           "repetition and redundant words; prefer shorter phrasing.")
if V == "con":
    _s, _p = sim.sentence_prompt, sim.phrase_prompt
    sim.sentence_prompt = lambda text, a, b, h: _s(text, a, b, h).replace("Keep numbers, names and negation exact.", f"Keep numbers, names and negation exact. {CONCISE}")
    sim.phrase_prompt = lambda so, sp, new, a, b, h: _p(so, sp, new, a, b, h).replace("Keep numbers, names and negation exact.", f"Keep numbers, names and negation exact. {CONCISE}")
sim.SYSTEMS = {f"P8-{V}": {"rec": "std", "mode": "phrase", "max": 8, "mt": "gemma31"},
               f"S-{V}": {"rec": "std", "mode": "sentence", "mt": "gemma31"}}
DIRS = ["en-es", "en-pt", "en-fr", "es-en", "fr-en"]
jobs = [(n, "conv", d) for n in sim.SYSTEMS for d in DIRS]
with cf.ThreadPoolExecutor(10) as ex:
    for r in ex.map(lambda j: sim.run_stream(*j), jobs): print(*r, flush=True)
