# Fast mode (phrase by phrase) for English -> Haitian Creole, Khmer and Lao, against whole
# sentences. The English side is the recorded Azure standard partials already replayed in
# ../2026-10-simultaneous-phrases (read news, unseen clips, regular and irregular pauses) and
# ../2026-10-concise-conversational (the AMI meeting excerpt): the commit policy's chunks
# depend only on the English, so this script reuses those chunk plans (segment, commit time,
# English words) and translates each chunk into the new targets with a real API call,
# one call at a time per stream, timed exactly as simulate.py times them.
#
# Systems: P8-<mt> (phrases, max 8 words, continuation prompt) and S-<mt> (one call per
# recogniser final), mt = sol (gpt-5.6-sol on Foundry, reasoning off) or gemma31 (Gemma 4
# 31B on OpenRouter, restricted to named zero-retention hosts, no fallback).
#
#   PLANS=<dir> OPENROUTER_API_KEY=... FOUNDRY_KEY=... python3 -I mt.py WORK
# PLANS holds <pattern>_P8.json / <pattern>_S.json chunk plans (see plans()).
# Writes WORK/sim/<system>/<pattern>_en-<tgt>.json in simulate.py's format.
import concurrent.futures as cf
import importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = sys.argv[1]
sys.argv = [sys.argv[0], WORK]
spec = importlib.util.spec_from_file_location("simulate", os.path.join(HERE, "..", "2026-10-simultaneous-phrases", "simulate.py"))
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)
sim.NAMES.update({"ht": "Haitian Creole", "km": "Khmer", "lo": "Lao"})

# Gemma: only these hosts (on OpenRouter's zero-retention list for the model, US-based),
# never another; the same block Talk and Live Translation send.
HOSTS = ["deepinfra", "crusoe", "parasail", "coreweave", "sambanova"]


def call(mt, prompt):
    if mt == "sol":
        return sim.call("sol", prompt)
    body = {"model": "google/gemma-4-31b-it", "messages": [{"role": "user", "content": prompt}], "max_tokens": 400,
            "temperature": 0, "usage": {"include": True}, "reasoning": {"enabled": False},
            "provider": {"zdr": True, "data_collection": "deny", "only": HOSTS, "allow_fallbacks": False}}
    total, text, j = 0.0, "", {}
    for _ in range(3):
        j, wall = sim.post("https://openrouter.ai/api/v1/chat/completions", body, {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
        total += wall
        text = ((j.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if text:
            break
    u = j.get("usage") or {}
    return text, total, j.get("provider"), u.get("prompt_tokens"), u.get("completion_tokens")


PATTERNS = ["reg", "irr", "conv"]
TARGETS = ["ht", "km", "lo"]
SYSTEMS = {"P8-sol": ("P8", "sol"), "P8-gemma31": ("P8", "gemma31"), "S-sol": ("S", "sol"), "S-gemma31": ("S", "gemma31")}


def run(name, pattern, tgt):
    mode, mt = SYSTEMS[name]
    out = os.path.join(WORK, "sim", name, f"{pattern}_en-{tgt}.json")
    if os.path.exists(out):
        return name, pattern, tgt, "cached"
    plan = json.load(open(os.path.join(os.environ["PLANS"], f"{pattern}_{mode}.json")))
    chunks = [{k: c[k] for k in ("segment", "t", "final", "src")} for c in plan]
    history, seg_src, seg_spoken, cur_seg, busy = [], [], [], -1, 0.0
    for c in chunks:
        if c["segment"] != cur_seg:
            if cur_seg >= 0 and seg_src:
                history.append((" ".join(seg_src), " ".join(seg_spoken)))
            cur_seg, seg_src, seg_spoken = c["segment"], [], []
        seg_src.append(c["src"])
        if mode == "S":
            prompt = sim.sentence_prompt(c["src"], "en", tgt, history)
        else:
            prompt = sim.phrase_prompt(" ".join(seg_src), " ".join(seg_spoken), c["src"], "en", tgt, history)
        text, wall, prov, pt, ct = call(mt, prompt)
        start = max(c["t"], busy)
        done = start + wall * 1000
        busy = done
        seg_spoken.append(text)
        c.update({"out": text, "start": round(start, 1), "done": round(done, 1), "wall_ms": round(wall * 1000),
                  "provider": prov, "prompt_tokens": pt, "completion_tokens": ct})
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"system": name, "pattern": pattern, "dir": f"en-{tgt}", "config": {"mode": mode, "mt": mt}, "chunks": chunks},
              open(out, "w"), ensure_ascii=False, indent=1)
    return name, pattern, tgt, f"{len(chunks)} chunks"


if __name__ == "__main__":
    jobs = [(n, p, t) for n in SYSTEMS for p in PATTERNS for t in TARGETS]
    with cf.ThreadPoolExecutor(int(os.environ.get("THREADS", "12"))) as ex:
        for r in ex.map(lambda j: run(*j), jobs):
            print(*r, flush=True)
