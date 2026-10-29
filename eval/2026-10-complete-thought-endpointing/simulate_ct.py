# "Complete thought" sentence ends: instead of waiting for the recogniser to finalise a segment (about 500 ms
# of silence, or its forced cut), ask Gemma at each decision point whether the words heard so far, not yet
# translated, begin with a complete thought; if they do, speak its translation once and never take it back.
#
# Replays recorded MAI-Transcribe-2-Streaming recognition through these arms (one translator call at a time
# per stream, as in the earlier runs):
#   S-mai, P8-mai, agree-mai   the earlier runs' Sentence, Phrase <=8 and Agree, unchanged
#                              (../2026-10-llm-commit-policy-bedrock/simulate_policy.py through the de/hi/tr
#                              wrapper, which adds the language names, clause words and the Devanagari fix)
#   cta-mai   complete thought, commit on the first "complete"
#   ctb-mai   complete thought, commit only when two successive checks name the same end word
#   ctc-mai   complete thought AND an energy dip at the end word (the boundary cutter's: 60 ms or more of
#             quiet within 120 ms either side of the boundary; quiet = 10 ms frames under 0.1x the p90 of
#             the 10 s before). A pause of 200 ms or more is such a dip too.
#   B8-mai    the scored-boundary cutter ("B8x10", the Live Translation Worker's src/fastphrases.ts BoundaryCutter, ported
#             below without the German guard), for es->en and fr->en; its pieces continue with the phrase
#             prompt (Gemma), a sentence nothing was cut from goes with the sentence prompt.
#   en->fr only, with sol (gpt-6-sol on Azure AI Foundry, deployment from FOUNDRY_DEPLOYMENT, reasoning_effort low, as
#   ../2026-10-llm-commit-policy-bedrock-fr-ar-sw):
#   S-sol-mai          Sentence with sol
#   ct<v>-sol-mai      complete thought, sol decides and translates (variant CT_SOL_VARIANT)
#   ct<v>-gs-mai       complete thought, Gemma decides, sol translates the committed thought
#
# Complete thought, in detail:
#   - Words are committed by the recogniser as in the earlier runs (two partials agree, a 300 ms pause, or the
#     final) and join the "tail": words heard, not yet translated. The tail runs across recogniser finals: a
#     final is not a sentence end here, only a decision point (its spelling and punctuation replace the
#     tail's words of that segment, since they are not translated yet).
#   - A decision point is any event that changed the tail (or a final), taken only when the previous call
#     has finished. Gemma gets the tail as numbered words, with the last two committed thoughts as context,
#     and answers {"end": N, "translation": ...} (words 1..N are a complete thought) or WAIT.
#   - Fallbacks: nothing new heard for FLUSH_MS (the speaker has stopped) or more than MAX_TAIL words waiting:
#     the whole tail is translated as a sentence (or with the last check's translation, if it covered all of it).
#
#   CLIPS_ROOT=... DIRS=... FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=... <venv with boto3, numpy>/bin/python \
#     simulate_ct.py WORK [system...]
# Writes WORK/sim/<system>/<pattern>_<src>-<tgt>.json (chunks and calls, as the earlier runs)
import concurrent.futures as cf
import importlib.util, json, os, re, sys, time, urllib.error, urllib.request, wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "dht", os.path.join(HERE, "..", "2026-10-llm-commit-policy-bedrock-de-hi-tr", "simulate_policy.py"))
dht = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dht)
sp, so = dht.sp, dht.so
WORK = sys.argv[1]
FLUSH_MS = int(os.environ.get("FLUSH_MS", "2000"))
MAX_TAIL = int(os.environ.get("MAX_TAIL", "30"))
TICK_MS = 100
LAG_MS = 200          # an MAI partial's words end this long before the audio sent so far (fastphrases.ts)
DIP_WIN, DIP_FULL, DIP_HALF = 120, 60, 30
CT_SOL_VARIANT = os.environ.get("CT_SOL_VARIANT", "b")
SOL_DEPLOYMENT = os.environ.get("FOUNDRY_DEPLOYMENT", "")   # your gpt-6-sol deployment name (sol arms only)

for r in sp.RECS:
    for v in "abc":
        sp.SYSTEMS[f"ct{v}-{r}"] = {"rec": r, "mode": "ct", "variant": v, "mt": sp.MT_TAG, "decider": sp.MT_TAG}
    sp.SYSTEMS[f"B8-{r}"] = {"rec": r, "mode": "boundary", "mt": sp.MT_TAG}
    sp.SYSTEMS[f"S-sol-{r}"] = {"rec": r, "mode": "sentence", "mt": "sol"}
    v = CT_SOL_VARIANT
    sp.SYSTEMS[f"ct{v}-sol-{r}"] = {"rec": r, "mode": "ct", "variant": v, "mt": "sol", "decider": "sol"}
    sp.SYSTEMS[f"ct{v}-gs-{r}"] = {"rec": r, "mode": "ct", "variant": v, "mt": "sol", "decider": sp.MT_TAG}
SOL_ONLY_DIRS = {"en-fr"}
BOUNDARY_DIRS = {"es-en", "fr-en"}

# ---------------- translators ----------------
bedrock_call = sp.call


def sol_call(prompt):
    url = os.environ["FOUNDRY_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions"
    body = json.dumps({"model": SOL_DEPLOYMENT, "messages": [{"role": "user", "content": prompt}],
                       "reasoning_effort": "low"}).encode()
    for attempt in range(10):
        t0 = time.time()
        try:
            j = json.load(urllib.request.urlopen(urllib.request.Request(
                url, body, {"Content-Type": "application/json", "api-key": os.environ["FOUNDRY_KEY"]}), timeout=120))
            wall = time.time() - t0
            u = j.get("usage") or {}
            text = ((j.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
            return text, wall, "foundry", u.get("prompt_tokens"), u.get("completion_tokens")
        except urllib.error.HTTPError as e:
            if e.code not in (408, 429, 500, 502, 503, 504) or attempt == 9:
                raise RuntimeError(f"foundry HTTP {e.code}")
        except (urllib.error.URLError, TimeoutError):
            if attempt == 9:
                raise
        time.sleep(3 * (attempt + 1))   # waits are not counted in the call's time


def call(mt, prompt, max_tokens=400):
    return sol_call(prompt) if mt == "sol" else bedrock_call(mt, prompt, max_tokens)


sp.call = so.call = call

# ---------------- the mic's energy (fastphrases.ts EnergyTrack) ----------------
_energy = {}


def energy(clips, lang):
    k = (clips, lang)
    if k not in _energy:
        with wave.open(os.path.join(clips, f"{lang}.wav")) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)
        n = len(x) // 160
        _energy[k] = np.sqrt((x[: n * 160].reshape(n, 160) ** 2).mean(axis=1))
    return _energy[k]


def dip_ms(rms, a, b):
    """Longest run of quiet (ms) between a and b (ms): frames under 0.1x the p90 of the 10 s before a."""
    i0, i1 = max(0, int(a // 10)), min(len(rms) - 1, int(b // 10))
    before = rms[max(0, i0 - 1000):i0]
    if not len(before) or i1 < i0:
        return 0
    thr = 0.1 * np.percentile(before, 90)
    best = cur = 0
    for v in rms[i0:i1 + 1]:
        cur = cur + 1 if v < thr else 0
        best = max(best, cur)
    return best * 10


def spread(a, b, i, n):
    step = (b - a) / n if n else 0
    return (a + i * step, a + (i + 1) * step)


# ---------------- complete thought ----------------
def ct_prompt(a, b, history, words):
    A, B = so.NAMES[a], so.NAMES[b]
    numbered = " ".join(f"{i + 1}:{w}" for i, w in enumerate(words))
    return (f"You are a live interpreter translating {A} speech into spoken {B} while the speaker is still talking. "
            f"The {A} comes from live speech recognition: it may contain errors and has little or no punctuation. "
            f"Spoken words cannot be taken back.\n"
            f"{so.context_block(history, a, b)}"
            f"Words heard so far that have not been translated yet, numbered:\n{numbered}\n\n"
            f"Do words 1 to N, for some N, form a complete thought: a whole sentence or a whole clause that can be "
            f"translated into natural {B} now, without waiting for more, so that its translation will not need to "
            f"change whatever the speaker says next? A part that still needs words not yet said (a verb, an object, "
            f"the rest of a clause, the noun after an article or preposition) is not complete.\n"
            f"If yes, answer only with JSON: {{\"end\": N, \"translation\": \"the {B} translation of words 1 to N "
            f"only\"}}, with the largest such N. If not, answer exactly: WAIT")


def parse_ct(text, n):
    t = text.strip()
    if not t or t.upper().startswith("WAIT"):
        return None
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
        end = int(j.get("end"))
        tr = str(j.get("translation") or "").strip()
    except Exception:
        return None
    if not (1 <= end <= n) or not tr:
        return None
    return end, tr


def gs_prompt(a, b, history, thought):
    A, B = so.NAMES[a], so.NAMES[b]
    return (f"{so.context_block(history, a, b)}Translate this {A} complete thought, transcribed from live speech (it may "
            f"contain recognition errors and has little or no punctuation), into natural {B}. Keep numbers, names and "
            f"negation exact. Output only the {B}.\nThought: {thought}")


def run_ct(name, pattern, d):
    sys_ = sp.SYSTEMS[name]
    a, b = d.split("-")
    out = os.path.join(WORK, "sim", name, f"{pattern}_{d}.json")
    if os.path.exists(out):
        return name, pattern, d, "cached"
    rec = json.load(open(os.path.join(WORK, "rec", f"{sys_['rec']}_{pattern}_{a}.json")))
    clips = os.path.join(os.environ["CLIPS_ROOT"], f"clips_{pattern}")
    rms = energy(clips, a)
    end_ms = len(rms) * 10 + 6000
    events = [("p", p["t"], p) for p in rec["partials"]] + [("f", f["t"], f) for f in rec["finals"]]
    events += [("v", t, None) for t in so.vad_pauses(clips, a)]
    events += [("k", float(t), None) for t in range(0, int(end_ms), TICK_MS)]
    order = {"f": 0, "v": 1, "p": 2, "k": 3}
    events.sort(key=lambda e: (e[1], order[e[0]]))
    variant, decider, mt = sys_["variant"], sys_["decider"], sys_["mt"]
    chunks, calls, history = [], [], []
    # tail: [{"w", "seg", "on", "end"}]; per segment: prev/cur partial words, their times, and how many of the
    # segment's words are committed (to the tail or beyond)
    st = {"seg": 0, "busy": 0.0, "prev": [], "cur": [], "times": [], "committed": [], "tail": [], "seg_done": 0,
          "dirty": False, "last_word_t": None, "last_ans": None, "res_end": 0.0, "consumed": 0}

    def do_call(m, prompt, t, kind):
        text, wall, prov, pt, ct = call(m, prompt, 400)
        start = max(t, st["busy"])
        done = start + wall * 1000
        st["busy"] = done
        calls.append({"t": round(t, 1), "kind": kind, "mt": m, "start": round(start, 1), "done": round(done, 1),
                      "wall_ms": round(wall * 1000), "out": text[:300], "prompt_tokens": pt, "completion_tokens": ct})
        return text, start, done, wall, prov, pt, ct

    def emit(t, n, text, start, done, wall, prov, pt, ct, kind, quiet):
        words = st["tail"][:n]
        st["tail"] = st["tail"][n:]
        st["consumed"] += n
        src = so.joined([w["w"] for w in words], a)
        chunks.append({"segment": words[-1]["seg"], "t": round(t, 1), "final": False, "kind": kind, "src": src,
                       "out": text.strip(), "src_on": round(words[0]["on"]), "src_end_t": round(words[-1]["end"]),
                       "words": len(words), "quiet_ms": quiet, "start": round(start, 1), "done": round(done, 1),
                       "wall_ms": round(wall * 1000), "provider": prov, "prompt_tokens": pt, "completion_tokens": ct})
        history.append((src, text.strip()))
        st["last_ans"] = None
        st["dirty"] = bool(st["tail"])

    def times_for(cur, t):
        keep = min(len(st["times"]), len(cur))
        times = st["times"][:keep]
        frm = times[-1][1] if keep else st["res_end"]
        to = max(frm, t - LAG_MS)
        n = len(cur) - keep
        times += [spread(frm, to, i, n) for i in range(n)]
        st["times"] = times

    def commit_upto(upto, t):
        start, _ = so.align_end(st["committed"], st["cur"])
        if upto > start:
            for i in range(start, upto):
                on, en = st["times"][i] if i < len(st["times"]) else (st["res_end"], st["res_end"])
                st["tail"].append({"w": st["cur"][i], "seg": st["seg"], "on": on, "end": en})
            st["committed"] += st["cur"][start:upto]
            st["dirty"] = True
            st["last_word_t"] = t

    def quiet_after(k, t):
        """Longest quiet run at the boundary after tail word k (1-based), up to now."""
        w = st["tail"][k - 1]
        nxt = st["tail"][k]["on"] if k < len(st["tail"]) else t - LAG_MS
        if k == len(st["tail"]):
            # the frontier: a word heard but not committed yet bounds it too
            j, _ = so.align_end(st["committed"], st["cur"])
            if j < len(st["cur"]) and j < len(st["times"]):
                nxt = st["times"][j][0]
        return dip_ms(rms, w["end"] - DIP_WIN, min(nxt + DIP_WIN, t))

    def flush(t, kind):
        n = len(st["tail"])
        la = st["last_ans"]
        if la and la[0] == st["consumed"] + n and mt == decider:
            text = la[1]
            emit(t, n, text, max(t, st["busy"]), max(t, st["busy"]), 0.0, "reuse", 0, 0, kind, None)
            return
        r = do_call(mt, so.sentence_prompt(so.joined([w["w"] for w in st["tail"]], a), a, b, history), t, kind)
        emit(t, n, *r, kind, None)

    def decide(t):
        if not st["dirty"] or not st["tail"] or t < st["busy"]:
            return
        st["dirty"] = False
        words = [w["w"] for w in st["tail"]]
        r = do_call(decider, ct_prompt(a, b, history, words), t, "ct")
        ans = parse_ct(r[0], len(words))
        if ans is None:
            st["last_ans"] = None
            if len(words) > MAX_TAIL:
                flush(t, "force")
            return
        n, tr = ans
        absolute = st["consumed"] + n
        quiet = quiet_after(n, r[2]) if variant == "c" else None
        ok = (variant == "a" or (variant == "b" and st["last_ans"] is not None and st["last_ans"][0] == absolute)
              or (variant == "c" and quiet >= DIP_FULL))
        st["last_ans"] = (absolute, tr)
        if not ok:
            if len(words) > MAX_TAIL:
                flush(t, "force")
            return
        if mt != decider:   # the decider chose the end; the translator translates that thought
            t2 = r[2]
            r2 = do_call(mt, gs_prompt(a, b, history, so.joined(words[:n], a)), t2, "translate")
            emit(t, n, *r2, "ct", quiet)
        else:
            emit(t, n, tr, *r[1:], "ct", quiet)

    def recheck_c(t):
        """Variant c: the last check named a complete thought but no dip yet; the dip may come as time passes
        (no new call: the same words, the same answer)."""
        la = st["last_ans"]
        if variant != "c" or not la or t < st["busy"]:
            return
        k = la[0] - st["consumed"]
        if 1 <= k <= len(st["tail"]):
            q = quiet_after(k, t)
            if q >= DIP_FULL:
                emit(t, k, la[1], t, t, 0.0, "reuse", 0, 0, "ct", q)

    for kind, t, e in events:
        if kind == "p":
            st["prev"], st["cur"] = st["cur"], so.toks(e["text"], a)
            times_for(st["cur"], t)
            commit_upto(max(so.lcp(st["prev"], st["cur"]), min(len(st["cur"]), e.get("stable", 0))), t)
            decide(t)
        elif kind == "v":
            if st["cur"]:
                commit_upto(len(st["cur"]), t)
            recheck_c(t)
            decide(t)
        elif kind == "f":
            fin = so.toks(e["text"], a)
            times_for(fin, t)
            # the segment's words still in the tail take the final's spelling (they are not translated yet)
            seg_words = st["committed"]
            in_tail = [w for w in st["tail"] if w["seg"] == st["seg"]]
            done_n = len(seg_words) - len(in_tail)
            j, _ = so.align_end(seg_words[:done_n], fin)
            before = len(st["tail"])
            st["tail"] = [w for w in st["tail"] if w["seg"] != st["seg"]]
            for i in range(j, len(fin)):
                on, en = st["times"][i] if i < len(st["times"]) else (t - LAG_MS, t - LAG_MS)
                st["tail"].append({"w": fin[i], "seg": st["seg"], "on": on, "end": en})
            if len(st["tail"]) != before:
                st["last_ans"] = None
            st["res_end"] = e["offsetMs"] + e["durationMs"]
            st.update({"seg": st["seg"] + 1, "prev": [], "cur": [], "times": [], "committed": [], "dirty": True,
                       "last_word_t": t})
            decide(t)
        else:   # tick
            if st["tail"] and t >= st["busy"]:
                if st["last_word_t"] is not None and t - st["last_word_t"] >= FLUSH_MS and not st["cur"]:
                    flush(t, "flush")
                else:
                    recheck_c(t)
                    decide(t)
    if st["tail"]:
        flush(end_ms, "flush")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"system": name, "pattern": pattern, "dir": d, "config": sys_, "chunks": chunks, "calls": calls},
              open(out, "w"), ensure_ascii=False, indent=1)
    return name, pattern, d, f"{len(chunks)} chunks, {len(calls)} calls"


# ---------------- the boundary cutter (B8x10), the Live Translation Worker's src/fastphrases.ts ----------------
CLAUSE_WORDS = {
    "es": set("y pero porque que cuando mientras aunque donde si o pues".split()),
    "fr": set("et mais parce que qui quand pendant bien où si ou car lorsque".split()),
}
CANT_END = {
    "es": set(("el la los las un una unos unas lo al del de a en con por para sin sobre entre hacia hasta desde según "
               "mi mis tu tus su sus nuestro nuestra nuestros nuestras es son está están era eran fue fueron ser estar ha han "
               "había habían he hemos haber se le les me te nos y o pero porque que cuando donde si aunque como muy más menos "
               "cada todo toda todos todas este esta estos estas ese esa esos esas cual cuyo cuya no ni tan").split()),
    "fr": set(("le la les l un une des du de d au aux à en dans sur sous avec pour par sans entre vers chez depuis "
               "mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs est sont était étaient a ont avait avaient "
               "été être avoir se s ne n que qu qui et ou mais parce comme quand où si lorsque très plus moins chaque tout toute "
               "tous toutes ce cet cette ces il elle ils elles je j tu on dont").split()),
}
NEEDS_QUE = {"parce", "bien"}
B = dict(start=6000, deadline=8000, hi=2.0, lo=0.5, lookback=2000, min_words=3)


def wkey(w):
    import unicodedata
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", w).lower()).replace("_", "")


def piece_text(tr):
    """fastphrases.ts pieceText: a non-final piece's single full stop comes off."""
    m = re.search(r"(?<!\.)\.([\"'”’)\]]*)$", tr)
    if not m:
        return tr
    head = tr[:m.start()]
    last = head.split()[-1] if head.split() else ""
    if re.search(r"\.\w+$", last) or re.fullmatch(r"[^\W\d_]", last):
        return tr
    return head + m.group(1)


def run_boundary(name, pattern, d):
    sys_ = sp.SYSTEMS[name]
    a, b = d.split("-")
    out = os.path.join(WORK, "sim", name, f"{pattern}_{d}.json")
    if os.path.exists(out):
        return name, pattern, d, "cached"
    rec = json.load(open(os.path.join(WORK, "rec", f"{sys_['rec']}_{pattern}_{a}.json")))
    clips = os.path.join(os.environ["CLIPS_ROOT"], f"clips_{pattern}")
    rms = energy(clips, a)
    events = [("p", p["t"], p) for p in rec["partials"]] + [("f", f["t"], f) for f in rec["finals"]]
    events += [("v", t, None) for t in so.vad_pauses(clips, a)]
    order = {"f": 0, "v": 1, "p": 2}
    events.sort(key=lambda e: (e[1], order[e[0]]))
    clause, cant = CLAUSE_WORDS[a], CANT_END[a]
    chunks, calls, history = [], [], []
    st = {"seg": 0, "busy": 0.0, "prev": [], "cur": [], "times": [], "committed": [], "pending": [], "sent": [],
          "spoken": [], "cut": False, "gaps": [], "res_end": 0.0, "seg_sent": 0}

    def translate(t, prompt, src, final, is_piece):
        text, wall, prov, pt, ct = call(sys_["mt"], prompt, 400)
        start = max(t, st["busy"])
        done = start + wall * 1000
        st["busy"] = done
        if is_piece:
            text = piece_text(text.strip())
        calls.append({"t": round(t, 1), "kind": "piece" if is_piece else "finish", "start": round(start, 1), "done": round(done, 1),
                      "wall_ms": round(wall * 1000), "out": text[:200], "prompt_tokens": pt, "completion_tokens": ct})
        chunks.append({"segment": st["seg"], "t": round(t, 1), "final": final, "src": src, "out": text.strip(), "start": round(start, 1),
                       "done": round(done, 1), "wall_ms": round(wall * 1000), "provider": prov, "prompt_tokens": pt, "completion_tokens": ct})
        st["spoken"].append(text.strip())

    def times_for(cur, t):
        keep = min(len(st["times"]), len(cur))
        times = st["times"][:keep]
        frm = times[-1][1] if keep else st["res_end"]
        n = len(cur) - keep
        times += [spread(frm, max(frm, t - LAG_MS), i, n) for i in range(n)]
        st["times"] = times

    def commit_upto(upto):
        start, _ = so.align_end(st["committed"], st["cur"])
        for i in range(start, upto):
            on, en = st["times"][i]
            st["pending"].append({"w": st["cur"][i], "on": on, "end": en})
        if upto > start:
            st["committed"] += st["cur"][start:upto]

    def score(k, nxt):
        p = st["pending"]
        prev = p[k - 1]
        dd = dip_ms(rms, prev["end"] - DIP_WIN, nxt["on"] + DIP_WIN)
        s = 1 if dd >= DIP_FULL else 0.5 if dd >= DIP_HALF else 0
        w = wkey(nxt["w"])
        after = p[k + 1] if k + 1 < len(p) else None
        if w in clause and (w not in NEEDS_QUE or (after is not None and wkey(after["w"]) == "que")):
            s += 1
        gap = max(0, nxt["on"] - prev["end"])
        med = float(np.median(st["gaps"])) if st["gaps"] else 0
        s += min(1, max(0, (gap - med) / 100))
        if wkey(prev["w"]) in cant:
            s += -1.5
        return s

    def try_cut(t):
        p = st["pending"]
        if len(p) < B["min_words"]:
            return
        age = t - p[0]["on"]
        if age < B["start"]:
            return
        j, _ = so.align_end(st["committed"], st["cur"])
        nxt = {"w": st["cur"][j], "on": st["times"][j][0], "end": st["times"][j][1]} if j < len(st["cur"]) else None
        cands = [(score(k, p[k] if k < len(p) else nxt), k) for k in range(B["min_words"], len(p) + (1 if nxt else 0))]
        if not cands:
            return
        best = lambda cs: max(cs, key=lambda c: (c[0], c[1]))
        at = None
        if age >= B["deadline"]:
            last_end = p[cands[-1][1] - 1]["end"]
            at = best([c for c in cands if p[c[1] - 1]["end"] >= last_end - B["lookback"]])[1]
        else:
            s, k = best(cands)
            thr = B["hi"] - (B["hi"] - B["lo"]) * (age - B["start"]) / (B["deadline"] - B["start"])
            if s >= thr:
                at = k
        if at is None:
            return
        piece = [w["w"] for w in p[:at]]
        st["seg_sent"] += sum(1 for w in p[:at] if not w.get("carried"))
        st["pending"] = p[at:]
        st["sent"] += piece
        st["cut"] = True
        new = so.joined(piece, a)
        translate(t, so.phrase_prompt(so.joined(st["sent"], a), " ".join(st["spoken"]), new, a, b, history), new, False, True)

    for kind, t, e in events:
        if kind == "p":
            st["prev"], st["cur"] = st["cur"], so.toks(e["text"], a)
            times_for(st["cur"], t)
            commit_upto(so.lcp(st["prev"], st["cur"]))
            try_cut(t)
        elif kind == "v":
            if st["cur"]:
                commit_upto(len(st["cur"]))
                try_cut(t)
        else:
            fin = so.toks(e["text"], a)
            times_for(fin, t)
            for i in range(1, len(st["times"])):
                st["gaps"].append(st["times"][i][0] - st["times"][i - 1][1])
            carried = [w for w in st["pending"] if w.get("carried")]
            j, _ = so.align_end(st["sent"][len(st["sent"]) - st["seg_sent"]:] if st["seg_sent"] else [], fin)
            rest = fin[j:]
            sentence = so.joined(fin, a)
            if e["durationMs"] >= 19000 and st["cut"]:
                # Azure's/MAI's forced cut after a cut: nothing is sent, the unsent words carry over (carriedTail:
                # a half-said last word goes, the cut's full stop comes off) and the piece clock keeps running
                keep = list(rest)
                if keep and re.search(r"\w-$", keep[-1]):
                    keep.pop()
                if keep:
                    keep[-1] = re.sub(r"[.?!…]+$", "", keep[-1]) or keep[-1]
                times = st["times"][j:] if len(st["times"]) >= len(fin) else [(t - LAG_MS, t - LAG_MS)] * len(rest)
                st["pending"] = carried + [{"w": w, "on": times[i][0], "end": times[i][1], "carried": True}
                                           for i, w in enumerate(keep)]
                st["res_end"] = e["offsetMs"] + e["durationMs"]
                st.update({"prev": [], "cur": [], "times": [], "committed": [], "seg_sent": 0})
                try_cut(t)
                continue
            if carried:
                rest = [w["w"] for w in carried] + rest
            if st["cut"]:
                if rest:
                    new = so.joined(rest, a)
                    translate(t, so.phrase_prompt(so.joined(st["sent"] + rest, a), " ".join(st["spoken"]), new, a, b, history), new, True, False)
            else:
                translate(t, so.sentence_prompt(sentence, a, b, history), sentence, True, False)
            history.append((so.joined(st["sent"] + rest, a) if st["cut"] else sentence, " ".join(st["spoken"])))
            st["res_end"] = e["offsetMs"] + e["durationMs"]
            st.update({"seg": st["seg"] + 1, "prev": [], "cur": [], "times": [], "committed": [], "pending": [],
                       "sent": [], "spoken": [], "cut": False, "seg_sent": 0})
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"system": name, "pattern": pattern, "dir": d, "config": sys_, "chunks": chunks, "calls": calls},
              open(out, "w"), ensure_ascii=False, indent=1)
    return name, pattern, d, f"{len(chunks)} chunks, {len(calls)} calls, cut {sum(1 for c in calls if c['kind'] == 'piece')}"


def run(name, pattern, d):
    m = sp.SYSTEMS[name]["mode"]
    if ("sol" in name or "-gs-" in name) and d not in SOL_ONLY_DIRS:
        return name, pattern, d, "skip"
    if m == "boundary":
        return run_boundary(name, pattern, d) if d in BOUNDARY_DIRS else (name, pattern, d, "skip")
    if m == "ct":
        return run_ct(name, pattern, d)
    return sp.run(name, pattern, d)


if __name__ == "__main__":
    only = set(sys.argv[2:])
    pats = os.environ.get("PATTERNS", "reg,irr").split(",")
    dirs = os.environ.get("DIRS", "en-es,es-en,en-de,de-en,en-hi,hi-en,en-tr,tr-en,en-fr,fr-en").split(",")
    jobs = [(n, p, d) for p in pats for d in dirs for n in sp.SYSTEMS if not only or n in only]
    with cf.ThreadPoolExecutor(int(os.environ.get("THREADS", "6"))) as ex:
        for r in ex.map(lambda j: run(*j), jobs):
            if r[3] != "skip":
                print(*r, flush=True)
