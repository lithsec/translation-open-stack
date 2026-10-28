# Who decides when to speak: a fixed phrase rule, or the translator? Replays recorded streaming
# recognition (MAI-Transcribe-2-Streaming and Nemotron 3.5 ASR streaming, from
# ../2026-10-open-streaming and ../2026-10-simultaneous-phrases) through five policies, all with
# one translator: Gemma 4 31B (gemma-4-31b-it) on the Gemini API, temperature 0, thinking minimal.
#
# Words are committed exactly as ../2026-10-open-streaming/simulate_open.py (two partials agree,
# a recogniser's "stable" words, a 300 ms audio pause, or the final), and every policy gets the
# same commits. A "decision point" is any commit event that added words, taken only when the
# previous call has finished (one call at a time per stream, as there).
#   P8      the phrase rule of simulate_open.py (4-8 words, clause word or comma, pause)
#   S       one call per recogniser final
#   judge   at each decision point Gemma answers SEND or WAIT for the words not yet translated;
#           on SEND the continuation prompt of P8 translates them (two calls in a row)
#   decide  at each decision point Gemma gets the sentence so far and what is already spoken, and
#           returns the next words to speak, or WAIT
#   agree   at each decision point Gemma translates the whole sentence so far; only the words two
#           successive translations agree on, beyond what is already spoken, are spoken (local
#           agreement, as simultaneous mode does for recognition)
# In all three new policies, the recogniser's final ends the sentence: one call speaks the rest,
# and more than MAX_PENDING untranslated words force a send.
#
#   CLIPS_ROOT=<dir with clips_reg/ clips_irr/> GEMINI_API_KEY=... python3 -I simulate_policy.py WORK [system...]
# Reads WORK/rec/<rec>_<pattern>_<lang>.json; writes WORK/sim/<system>/<pattern>_<src>-<tgt>.json
import concurrent.futures as cf
import collections, json, os, sys, threading, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "2026-10-open-streaming"))
import simulate_open as so  # noqa: E402  (reads sys.argv[1] as WORK at import)

WORK = sys.argv[1]
MODEL = os.environ.get("GEMMA_MODEL", "gemma-4-31b-it")
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
MAX_PENDING = 14
RECS = [r for r in os.environ.get("RECS", "mai,nemo").split(",") if r]
SYSTEMS = {}
for r in RECS:
    SYSTEMS[f"P8-{r}"] = {"rec": r, "mode": "phrase", "max": 8, "mt": "gemma31-gapi"}
    SYSTEMS[f"S-{r}"] = {"rec": r, "mode": "sentence", "mt": "gemma31-gapi"}
    for p in ("judge", "decide", "agree"):
        SYSTEMS[f"{p}-{r}"] = {"rec": r, "mode": p, "mt": "gemma31-gapi"}


# The key's tier allows 30 requests a minute to this model: calls wait for a slot (the wait is not
# part of the call's measured time, so the replay's timeline is unaffected), and a 429 is retried.
RPM = int(os.environ.get("RPM", "28"))
_slots, _lock = collections.deque(), threading.Lock()


def slot():
    while True:
        with _lock:
            now = time.time()
            while _slots and now - _slots[0] > 60:
                _slots.popleft()
            if len(_slots) < RPM:
                _slots.append(now)
                return
            wait = 60 - (now - _slots[0]) + 0.05
        time.sleep(wait)


def post(url, body, headers):
    for attempt in range(40):
        slot()
        try:
            return so.post(url, body, headers, tries=1)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(20)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(10)
    raise RuntimeError("still rate-limited")


def call(mt, prompt, max_tokens=400):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens, "thinkingConfig": {"thinkingLevel": "MINIMAL"}}}
    total, text = 0.0, ""
    for _ in range(3):
        j, wall = post(URL, body, {"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
        total += wall
        parts = ((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        if text:
            break
    u = j.get("usageMetadata") or {}
    return text, total, "gemini-api", u.get("promptTokenCount"), u.get("candidatesTokenCount")


# The phrase and sentence systems are simulate_open.py's own loop with this translator.
so.call, so.SYSTEMS, so.WORK = call, SYSTEMS, WORK


def head(a, b, history, so_far, spoken, paused):
    A, B = so.NAMES[a], so.NAMES[b]
    return (f"You are a live interpreter translating {A} speech into spoken {B} while the speaker is still talking. "
            f"The {A} comes from live speech recognition and may contain errors. Spoken words cannot be taken back.\n"
            f"{so.context_block(history, a, b)}"
            f"Current {A} sentence so far (the speaker has not necessarily finished it): \"{so_far}\"\n"
            f"Already spoken in {B} for this sentence: \"{spoken}\"\n"
            + ("The speaker has just paused.\n" if paused else ""))


def judge_prompt(a, b, history, so_far, spoken, pending, paused):
    B = so.NAMES[b]
    return (head(a, b, history, so_far, spoken, paused)
            + f"Words not yet translated: \"{pending}\"\n"
            f"Should the interpreter translate and speak those words now, or wait for more? Answer SEND if their {B} "
            f"translation can be spoken now and will not need to be changed, reordered or completed by words not yet "
            f"said (for example, a verb or object still to come that {B} needs earlier). Otherwise answer WAIT. "
            f"Answer with one word: SEND or WAIT.")


def decide_prompt(a, b, history, so_far, spoken, paused):
    B = so.NAMES[b]
    return (head(a, b, history, so_far, spoken, paused)
            + f"Decide whether to speak now. If you can say more of the {B} translation now, without guessing words the "
            f"speaker has not said and without anything you would have to contradict later, output ONLY the {B} words "
            f"that continue what was already spoken (they may cover only part of what was said). If not, output exactly "
            f"WAIT. Never repeat what was already spoken. Keep numbers, names and negation exact.")


def finish_prompt(a, b, history, sentence, spoken):
    A, B = so.NAMES[a], so.NAMES[b]
    return (f"You are a live interpreter translating {A} speech into spoken {B}. The {A} comes from live speech "
            f"recognition and may contain errors. Spoken words cannot be taken back.\n"
            f"{so.context_block(history, a, b)}"
            f"The speaker has finished this {A} sentence: \"{sentence}\"\n"
            f"Already spoken in {B} for it: \"{spoken}\"\n"
            f"Output ONLY the {B} words that complete the translation so that, together with what was already spoken, "
            f"it covers the whole sentence. Never repeat or contradict what was already spoken. If nothing is missing, "
            f"output nothing. Keep numbers, names and negation exact.")


def prefix_prompt(a, b, history, so_far):
    A, B = so.NAMES[a], so.NAMES[b]
    return (f"{so.context_block(history, a, b)}Translate this {A} sentence prefix, transcribed from live speech while "
            f"the speaker is still talking (it may contain recognition errors and is probably unfinished), into "
            f"natural {B}. Translate only what has been said; do not guess how it ends. Output only the {B}.\n"
            f"Prefix: {so_far}")


def run_policy(name, pattern, d):
    sys_ = SYSTEMS[name]
    a, b = d.split("-")
    out = os.path.join(WORK, "sim", name, f"{pattern}_{d}.json")
    if os.path.exists(out):
        return name, pattern, d, "cached"
    rec = json.load(open(os.path.join(WORK, "rec", f"{sys_['rec']}_{pattern}_{a}.json")))
    clips = os.path.join(os.environ["CLIPS_ROOT"], f"clips_{pattern}")
    events = [("p", p["t"], p) for p in rec["partials"]] + [("f", f["t"], f) for f in rec["finals"]]
    events += [("v", t, None) for t in so.vad_pauses(clips, a)]
    order = {"f": 0, "v": 1, "p": 2}
    events.sort(key=lambda e: (e[1], order[e[0]]))
    mode = sys_["mode"]
    chunks, calls, history = [], [], []
    st = {"seg": 0, "busy": 0.0, "prev": [], "cur": [], "committed": [], "src_unspoken": [], "spoken": [],
          "last_tr": [], "dirty": False, "pause_asked": False}

    def do_call(prompt, t, kind, max_tokens=400):
        text, wall, prov, pt, ct = call(sys_["mt"], prompt, max_tokens)
        start = max(t, st["busy"])
        done = start + wall * 1000
        st["busy"] = done
        calls.append({"t": round(t, 1), "kind": kind, "start": round(start, 1), "done": round(done, 1), "wall_ms": round(wall * 1000),
                      "out": text[:200], "prompt_tokens": pt, "completion_tokens": ct})
        return text, start, done, wall, prov, pt, ct

    def emit(t, text, start, done, wall, prov, pt, ct, final):
        src = so.joined(st["src_unspoken"], a)
        st["src_unspoken"] = []
        if text.strip():
            st["spoken"].append(text.strip())
        chunks.append({"segment": st["seg"], "t": round(t, 1), "final": final, "src": src, "out": text.strip(), "start": round(start, 1),
                       "done": round(done, 1), "wall_ms": round(wall * 1000), "provider": prov, "prompt_tokens": pt, "completion_tokens": ct})

    def commit_upto(upto):
        start, _ = so.align_end(st["committed"], st["cur"])
        if upto > start:
            new = st["cur"][start:upto]
            st["committed"] += new
            st["src_unspoken"] += new
            st["dirty"], st["pause_asked"] = True, False

    def decide(t, paused):
        # new words, or a pause not yet put to the translator (the same words, now known to be followed by silence)
        if not (st["dirty"] or (paused and not st["pause_asked"])) or t < st["busy"] or not st["src_unspoken"]:
            return
        st["dirty"] = False
        st["pause_asked"] = st["pause_asked"] or paused
        so_far, spoken = so.joined(st["committed"], a), " ".join(st["spoken"])
        force = len(st["src_unspoken"]) > MAX_PENDING
        if mode == "judge":
            if len(st["src_unspoken"]) < 2 and not paused:
                return
            if not force:
                ans, *_ = do_call(judge_prompt(a, b, history, so_far, spoken, so.joined(st["src_unspoken"], a), paused), t, "judge", 8)
                if "SEND" not in ans.upper():
                    return
            r = do_call(so.phrase_prompt(so_far, spoken, so.joined(st["src_unspoken"], a), a, b, history), t, "translate")
            emit(t, *r, False)
        elif mode == "decide":
            if force:
                r = do_call(so.phrase_prompt(so_far, spoken, so.joined(st["src_unspoken"], a), a, b, history), t, "translate")
                emit(t, *r, False)
                return
            r = do_call(decide_prompt(a, b, history, so_far, spoken, paused), t, "decide")
            if r[0].strip().upper().strip(".") != "WAIT" and r[0].strip():
                emit(t, *r, False)
        elif mode == "agree":
            r = do_call(prefix_prompt(a, b, history, so_far), t, "prefix")
            tr = r[0].split()
            prev, st["last_tr"] = st["last_tr"], tr
            spoken_w = " ".join(st["spoken"]).split()
            agreed = so.lcp(tr, prev)
            if so.lcp(tr, spoken_w) == len(spoken_w) and agreed > len(spoken_w):
                emit(t, " ".join(tr[len(spoken_w):agreed]), *r[1:], False)

    for kind, t, e in events:
        if kind == "p":
            st["prev"], st["cur"] = st["cur"], so.toks(e["text"], a)
            commit_upto(max(so.lcp(st["prev"], st["cur"]), min(len(st["cur"]), e.get("stable", 0))))
            decide(t, False)
        elif kind == "v":
            if st["cur"]:
                commit_upto(len(st["cur"]))
                decide(t, True)
        else:
            fin = so.toks(e["text"], a)
            j, _ = so.align_end(st["committed"], fin)
            st["src_unspoken"] += fin[j:]
            sentence = so.joined(fin, a)
            if st["spoken"]:
                r = do_call(finish_prompt(a, b, history, sentence, " ".join(st["spoken"])), t, "finish")
            else:
                r = do_call(so.sentence_prompt(sentence, a, b, history), t, "finish")
            emit(t, *r, True)
            history.append((sentence, " ".join(st["spoken"])))
            st.update({"seg": st["seg"] + 1, "prev": [], "cur": [], "committed": [], "src_unspoken": [], "spoken": [], "last_tr": [], "dirty": False, "pause_asked": False})
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"system": name, "pattern": pattern, "dir": d, "config": sys_, "chunks": chunks, "calls": calls},
              open(out, "w"), ensure_ascii=False, indent=1)
    return name, pattern, d, f"{len(chunks)} chunks, {len(calls)} calls"


def run(name, pattern, d):
    if SYSTEMS[name]["mode"] in ("phrase", "sentence"):
        return so.run_stream(name, pattern, d)
    return run_policy(name, pattern, d)


if __name__ == "__main__":
    only = set(sys.argv[2:])
    pats = os.environ.get("PATTERNS", ",".join(so.PATTERNS)).split(",")
    dirs = os.environ.get("DIRS", ",".join(so.DIRS)).split(",")
    jobs = [(n, p, d) for p in pats for d in dirs for n in SYSTEMS if not only or n in only]
    with cf.ThreadPoolExecutor(int(os.environ.get("THREADS", "16"))) as ex:
        for r in ex.map(lambda j: run(*j), jobs):
            print(*r, flush=True)
