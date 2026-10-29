# ../2026-10-simultaneous-phrases/simulate.py for the open streaming recognisers, with
# three changes (everything else, the commit rule, the phrase rule, both prompts and
# the timing, is that file's):
#   1. the translator is Gemma 4 31B 4-bit served by vLLM on the pod (OpenAI-compatible
#      chat, VLLM_URL, model VLLM_MODEL), temperature 0, max_tokens 400, thinking off;
#   2. a partial may carry "stable": the number of its leading words the recogniser has
#      already made final (the CTC track's committed text, SimulStreaming's and the
#      cache-aware model's append-only output); they are committed at once, as if two
#      partials had agreed on them;
#   3. the systems and directions below (en<->es, en<->fr).
#
# Replays a recogniser's real partial/final timeline (stream_partials.py) through a
# commit policy, translates each committed chunk with a real API call (continuation
# prompt), and records when each chunk would be spoken.
#
# Stable words: a word is committed once it is unchanged across two consecutive
# partials, at a 300 ms pause in the audio (a client-side VAD: everything heard so far),
# or when the final arrives (its remaining words). Committed words are lined up with
# the latest hypothesis by edit distance, since a recogniser may rewrite earlier words.
# Japanese is compared by character.
#
# Policies (POLICY below, one table per (source, target) pair; any pair can also be
# forced into another mode for the experiment):
#   phrase    send the pending stable words when there are >= min and either a clause
#             word or a comma follows, the audio has paused 300 ms, or max is reached
#   sentence  one call per recogniser final (today's route style)
#
# Timing (ms on the clip's clock, = audio time since the clip's first sample):
#   commit t_c; translation starts at max(t_c, previous call done) (one call at a time
#   per stream, because each continuation needs the previous one's output); done =
#   start + measured wall time. Spoken = done + the voice's measured time to first
#   audio (tts.py). "queued" also waits for the previous chunk's audio to finish.
#
#   CLIPS_ROOT=<dir with clips_reg/ clips_irr/> VLLM_URL=http://127.0.0.1:8101/v1 python3 -I simulate_open.py WORK [system...]
# Reads WORK/rec/<rec>_<pattern>_<lang>.json; writes WORK/sim/<system>/<pattern>_<src>-<tgt>.json
import concurrent.futures as cf
import json, os, re, sys, time, unicodedata, urllib.error, urllib.request

WORK = sys.argv[1]
NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French", "ja": "Japanese"}
DIRS = ["en-es", "en-fr", "es-en", "fr-en"]
PATTERNS = ["reg", "irr"]

CLAUSE = {
    "en": {"and", "but", "because", "which", "who", "that", "while", "when", "although", "so", "or", "where", "if", "since"},
    "es": {"y", "pero", "porque", "que", "cuando", "mientras", "aunque", "donde", "si", "o", "pues"},
    "pt": {"e", "mas", "porque", "que", "quando", "enquanto", "embora", "onde", "se", "ou", "pois"},
    "fr": {"et", "mais", "parce", "que", "qui", "quand", "pendant", "bien", "où", "si", "ou", "car", "lorsque"},
    "it": {"e", "ma", "perché", "che", "quando", "mentre", "anche", "dove", "se", "o"},
}
# The per-language table: what a production route would use.
POLICY = {}
for a, b in [("en", "es"), ("en", "pt"), ("en", "fr"), ("en", "it")]:
    POLICY[(a, b)] = POLICY[(b, a)] = {"mode": "phrase", "min": 4, "max": 8}
for a, b in [("en", "de"), ("en", "zh")]:
    POLICY[(a, b)] = POLICY[(b, a)] = {"mode": "clause", "min": 6, "max": 14}
for a, b in [("en", "ja"), ("en", "ko")]:
    POLICY[(a, b)] = POLICY[(b, a)] = {"mode": "sentence"}

# Systems measured. "phrase" systems force phrase mode on every pair, so the Japanese
# directions show what phrase mode would do there (the table says sentence).
RECS = [r for r in os.environ.get("RECS", "simul,ctc,nemo").split(",") if r]
SYSTEMS = {}
for r in RECS:
    SYSTEMS[f"P8-{r}"] = {"rec": r, "mode": "phrase", "max": 8, "mt": "gemma31q"}
    SYSTEMS[f"S-{r}"] = {"rec": r, "mode": "sentence", "mt": "gemma31q"}
JA_MIN, JA_MAX = 8, 18      # Japanese source in phrase mode: characters, not words
PAUSE_MS = 300
VLLM_URL = os.environ.get("VLLM_URL", "http://127.0.0.1:8101/v1").rstrip("/")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "google/gemma-4-31B-it-qat-w4a16-ct")


def key(tok):
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", tok).lower())


def toks(text, lang):
    if lang == "ja":
        return [c for c in text if not c.isspace()]
    return text.split()


def joined(ts, lang):
    return "".join(ts) if lang == "ja" else " ".join(ts)


def lcp(a, b):
    n = 0
    for x, y in zip(a, b):
        if key(x) != key(y):
            break
        n += 1
    return n


def align_end(committed, cur):
    """Index in cur just after the part that corresponds to the committed tokens
    (edit distance, ties to the longer prefix): the hypothesis may have rewritten
    words that were already committed. Also returns that distance (a revision)."""
    a, b = [key(x) for x in committed], [key(x) for x in cur]
    if not a:
        return 0, 0
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            row[j] = min(prev[j - 1] + (a[i - 1] != b[j - 1]), prev[j] + 1, row[j - 1] + 1)
        prev = row
    best = min(range(len(b) + 1), key=lambda j: (prev[j], -j))
    return best, prev[best]


def vad_pauses(clips, lang):
    """Times (ms) at which the audio has been quiet for PAUSE_MS: a client-side VAD.
    Quiet = 20 ms frames below 10% of the sentence's 90th-percentile level (so a quiet
    reader is judged against their own level); the gaps between sentences are quiet."""
    import wave
    import numpy as np
    meta = json.load(open(os.path.join(clips, f"{lang}.json")))
    with wave.open(os.path.join(clips, f"{lang}.wav")) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)
    n = len(x) // 320
    rms = np.sqrt((x[: n * 320].reshape(n, 320) ** 2).mean(axis=1))
    loud = np.zeros(n, bool)
    for s in meta["sentences"]:
        a, b = int(s["start"] * 50), min(n, int(s["end"] * 50) + 1)
        if b > a:
            thr = 0.1 * np.percentile(rms[a:b], 90)
            loud[a:b] = rms[a:b] >= thr
    out, run = [], 0
    for i in range(n):
        run = 0 if loud[i] else run + 1
        if run == PAUSE_MS // 20:
            out.append((i + 1) * 20.0)
    return out


def chunk_plan(rec, src, sys_, pauses=()):
    """Commit timeline -> chunks [{segment, t, toks, final}] (no translation yet)."""
    events = [("p", p["t"], p) for p in rec["partials"]] + [("f", f["t"], f) for f in rec["finals"]]
    events += [("v", t, None) for t in pauses]
    order = {"f": 0, "v": 1, "p": 2}
    events.sort(key=lambda e: (e[1], order[e[0]]))
    phrase = sys_["mode"] == "phrase"
    mn, mx = (JA_MIN, JA_MAX) if src == "ja" else (4, sys_.get("max", 8))
    chunks, seg, revisions = [], 0, 0
    prev, cur, committed, pending = [], [], [], []

    def emit(t, ts, final):
        chunks.append({"segment": seg, "t": round(t, 1), "toks": list(ts), "final": final})

    def try_send(t):
        nonlocal pending
        while phrase and len(pending) >= mn:
            cut = None
            for k in range(mn, len(pending)):
                if src != "ja" and key(pending[k]) in CLAUSE.get(src, ()):
                    cut = k
                    break
                if pending[k - 1].endswith((",", ";", ":", "、", "，")):
                    cut = k
                    break
            if cut is None and len(pending) >= mx:
                cut = mx
            if cut is None:
                return
            emit(t, pending[:cut], False)
            pending = pending[cut:]

    def commit_upto(upto, t):
        nonlocal committed, pending
        start, _ = align_end(committed, cur)
        if upto > start:
            pending += cur[start:upto]
            committed += cur[start:upto]

    for kind, t, e in events:
        if kind == "p":
            prev, cur = cur, toks(e["text"], src)
            if phrase:
                commit_upto(max(lcp(prev, cur), min(len(cur), e.get("stable", 0))), t)
                try_send(t)
        elif kind == "v":
            if phrase and cur:
                commit_upto(len(cur), t)
                if len(pending) >= mn:
                    emit(t, pending, False)
                    pending = []
        else:
            fin = toks(e["text"], src)
            if phrase:
                j, dist = align_end(committed, fin)
                revisions += dist
                rest = pending + fin[j:]
            else:
                rest = fin
            if rest:
                emit(t, rest, True)
            seg += 1
            prev, cur, committed, pending = [], [], [], []
    return chunks, revisions


def post(url, body, headers, tries=14):
    data = json.dumps(body).encode()
    for attempt in range(tries):
        t0 = time.time()
        try:
            j = json.load(urllib.request.urlopen(urllib.request.Request(url, data, {"Content-Type": "application/json", **headers}), timeout=90))
            return j, time.time() - t0
        except urllib.error.HTTPError as e:
            if e.code not in (408, 429, 500, 502, 503, 504) or attempt == tries - 1:
                raise
            ra = e.headers.get("retry-after")
            if ra and ra.replace(".", "", 1).isdigit():   # the wait is not counted in the call's time
                time.sleep(float(ra) + 1)
                continue
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(3 * (attempt + 1))


def call(mt, prompt):
    body = {"model": VLLM_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 400, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False}}
    total = 0.0
    for _ in range(3):
        j, wall = post(f"{VLLM_URL}/chat/completions", body, {})
        total += wall
        text = ((j.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if text:
            break
    u = j.get("usage") or {}
    return text, total, "vllm-pod", u.get("prompt_tokens"), u.get("completion_tokens")


def context_block(history, a, b):
    if not history:
        return ""
    lines = "\n".join(f"- {s} => {t}" for s, t in history[-2:])
    return f"Earlier sentences (context only, already spoken):\n{lines}\n"


def sentence_prompt(text, a, b, history):
    A, B = NAMES[a], NAMES[b]
    return (f"{context_block(history, a, b)}Translate this {A} sentence, transcribed from live speech (it may contain recognition "
            f"errors), into natural {B}. Keep numbers, names and negation exact. Output only the {B}.\nSentence: {text}")


def phrase_prompt(so_far, spoken, new, a, b, history):
    A, B = NAMES[a], NAMES[b]
    return (f"You are a live interpreter translating {A} speech into spoken {B} phrase by phrase, while the speaker is still "
            f"talking. The {A} comes from live speech recognition and may contain errors.\n"
            f"{context_block(history, a, b)}"
            f"Current {A} sentence so far: \"{so_far}\"\n"
            f"Already spoken in {B} for this sentence: \"{spoken}\"\n"
            f"New {A} words to translate now: \"{new}\"\n"
            f"Output ONLY the {B} words that continue what was already spoken so that it now covers the new words. "
            f"Never repeat or contradict what was already spoken. Keep numbers, names and negation exact. "
            f"If the {B} word order needs words that have not been said yet, translate what you can so the speech still "
            f"flows. Output nothing else.")


def run_stream(name, pattern, d):
    sys_ = SYSTEMS[name]
    a, b = d.split("-")
    out = os.path.join(WORK, "sim", name, f"{pattern}_{d}.json")
    if os.path.exists(out):
        return name, pattern, d, "cached"
    rp = os.path.join(WORK, "rec", f"{sys_['rec']}_{pattern}_{a}.json")
    if not os.path.exists(rp):
        return name, pattern, d, "no recording"
    rec = json.load(open(rp))
    if rec.get("err"):
        return name, pattern, d, "rec error"
    clips = os.path.join(os.environ["CLIPS_ROOT"], f"clips_{pattern}")
    chunks, revisions = chunk_plan(rec, a, sys_, vad_pauses(clips, a) if sys_["mode"] == "phrase" else ())
    history, seg_src, seg_spoken, cur_seg, busy = [], [], [], -1, 0.0
    for c in chunks:
        if c["segment"] != cur_seg:
            if cur_seg >= 0 and seg_src:
                history.append((joined(seg_src, a), " ".join(seg_spoken)))
            cur_seg, seg_src, seg_spoken = c["segment"], [], []
        new = joined(c["toks"], a)
        seg_src += c["toks"]
        if sys_["mode"] == "sentence":
            prompt = sentence_prompt(new, a, b, history)
        else:
            prompt = phrase_prompt(joined(seg_src, a), (" " if b != "ja" else "").join(seg_spoken), new, a, b, history)
        text, wall, prov, pt, ct = call(sys_["mt"], prompt)
        start = max(c["t"], busy)
        done = start + wall * 1000
        busy = done
        seg_spoken.append(text)
        c.update({"src": new, "out": text, "start": round(start, 1), "done": round(done, 1), "wall_ms": round(wall * 1000),
                  "provider": prov, "prompt_tokens": pt, "completion_tokens": ct})
        del c["toks"]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"system": name, "pattern": pattern, "dir": d, "config": sys_, "revised_tokens": revisions, "chunks": chunks}, open(out, "w"), ensure_ascii=False, indent=1)
    return name, pattern, d, f"{len(chunks)} chunks"


if __name__ == "__main__":
    only = set(sys.argv[2:])
    jobs = [(n, p, d) for n in SYSTEMS for p in PATTERNS for d in DIRS if not only or n in only]
    with cf.ThreadPoolExecutor(int(os.environ.get("THREADS", "16"))) as ex:
        for r in ex.map(lambda j: run_stream(*j), jobs):
            print(*r, flush=True)
