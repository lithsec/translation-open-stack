# ../2026-10-complete-thought-endpointing/simulate_ct.py, unchanged, for en<->ht, en<->km and en<->lo. This file
# only adds the three languages' names, Khmer and Lao words (words.py: they write no spaces between words), the
# omni-stt recordings (convert_omni.py) and the sol arms in every direction. The arms, per direction:
#   S-sol-<rec>     whole sentences: one sol call per recogniser final (production's sentence for these languages)
#   ctb-gs-<rec>    CT (b), Gemma decides, sol translates the committed thought
#   ctb-sol-<rec>   CT (b), sol decides and translates (out of English, the reg clips only: sol is slow and
#                   costly per check)
#   ctb-<rec>       CT (b), Gemma decides and translates (for reference)
#   cta-gs-o3       ht->en only: CT (a) (commit on the first "complete"), Gemma decides, sol translates
# Hearing (<rec>): en "mai" (MAI-Transcribe-2-Streaming, partials and finals, as before); ht "o3" (omni-stt
# omniASR_LLM_300M: per-piece finals only), with "o3p" (its prototype partials) for Gemma-only CT (b);
# km and lo: sentences on "o7" (the 7B's finals), the CT arms on "o7c" (the 7B's finals plus the CTC 3B
# streaming track's live text).
#
#   CLIPS_ROOT=... FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=... <venv with boto3, numpy>/bin/python simulate.py WORK [system...]
import concurrent.futures as cf
import importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import words  # noqa: E402

os.environ.setdefault("RECS", "mai,o3,o3p,o7,o7c")
os.environ.setdefault("CT_SOL_VARIANT", "b")
spec = importlib.util.spec_from_file_location(
    "simulate_ct", os.path.join(HERE, "..", "2026-10-complete-thought-endpointing", "simulate_ct.py"))
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)
so = ct.so
so.NAMES.update({"ht": "Haitian Creole", "km": "Khmer", "lo": "Lao", "en": "English"})
so.toks, so.joined = words.toks, words.joined

REC = {"en-ht": ("mai", "mai"), "en-km": ("mai", "mai"), "en-lo": ("mai", "mai"),
       "ht-en": ("o3", "o3"), "km-en": ("o7", "o7c"), "lo-en": ("o7", "o7c")}


def arms(d, pattern):
    s, c = REC[d]
    out = [f"S-sol-{s}", f"ctb-gs-{c}", f"ctb-{c}"]
    if pattern == "reg" and s == "mai":
        out.append(f"ctb-sol-{c}")
    if d == "ht-en":
        out += ["ctb-o3p", "cta-gs-o3"]
    return out


ct.SOL_ONLY_DIRS = set(REC)
# ht->en only: CT (a), Gemma decides on the first "complete", sol translates. With finals only, every decision
# point is a new final, which changes the tail and so clears the last check: (b)'s two agreeing checks can then
# never happen, and (b) commits only by its 2 s fallback. (a) needs one check.
ct.sp.SYSTEMS["cta-gs-o3"] = {"rec": "o3", "mode": "ct", "variant": "a", "mt": "sol", "decider": ct.sp.MT_TAG}

# Foundry refused some Haitian Creole requests with HTTP 400 (the earlier run met its content filter there). As
# Live Translation does (../2026-10-continuous-ht), a refused request is sent again without its context; if that
# is refused too, nothing is spoken for it. Every refusal is logged to WORK/refusals.jsonl.
import json, re, threading  # noqa: E402

_sol, _rlock = ct.sol_call, threading.Lock()


def sol_call(prompt):
    try:
        return _sol(prompt)
    except RuntimeError as e:
        if "HTTP 400" not in str(e):
            raise
    bare = re.sub(r"Earlier sentences \(context only, already spoken\):\n(?:- .*\n)*", "", prompt)
    rec = {"retried_without_context": bare != prompt, "refused_again": False}
    try:
        out = _sol(bare) if bare != prompt else None
    except RuntimeError as e:
        if "HTTP 400" not in str(e):
            raise
        out = None
    if out is None:
        rec["refused_again"] = True
        out = ("", 0.0, "foundry-refused", 0, 0)
    with _rlock:
        open(os.path.join(sys.argv[1], "refusals.jsonl"), "a").write(json.dumps(rec) + "\n")
    return out


ct.sol_call = sol_call

if __name__ == "__main__":
    only = set(sys.argv[2:])
    pats = os.environ.get("PATTERNS", "reg,irr").split(",")
    dirs = os.environ.get("DIRS", ",".join(REC)).split(",")
    jobs = [(n, p, d) for p in pats for d in dirs for n in arms(d, p) if not only or n in only]
    with cf.ThreadPoolExecutor(int(os.environ.get("THREADS", "6"))) as ex:
        for r in ex.map(lambda j: ct.run(*j), jobs):
            print(*r, flush=True)
