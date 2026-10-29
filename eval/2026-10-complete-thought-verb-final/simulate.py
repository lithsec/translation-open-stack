# ../2026-10-complete-thought-endpointing/simulate_ct.py, unchanged, for the verb-final directions: en->ja, ko, fa, ur,
# bn, ta and ja, ko, fa, hi->en. This file adds the languages' names, Japanese words (words.py), production's hearing
# and translator per direction, and one new arm, the room decider. The arms, per direction:
#   S-<rec> / S-sol-<rec>   whole sentences (one call per recogniser final) with production's translator for that
#                           direction (the Live Translation Worker's testroutes.ts gemmaTranslates on mai-gemma/hybrid-gemma: sol out
#                           of English into ja and fa, sol into English from ja, ko and hi, Gemma otherwise); where
#                           production is sol, Gemma sentences as well (for the sol-vs-Gemma rule)
#   ctb-<rec>               CT (b), Gemma decides and translates
#   ctb-gs-<rec>            CT (b), Gemma decides, sol translates the committed thought
#   agree-<rec>             Agree (Gemma), except into Japanese: Agree compares translations word by word on
#                           spaces, and Japanese output has none
#   room-<rec>              new, en->ja, en->ko and en->ur together: ONE CT (b) decision stream on the English
#                           (Gemma, asked only COMPLETE N or WAIT, no translation), then one translation call per
#                           target per committed thought, with production's translator (sol into ja, Gemma into ko
#                           and ur). The decider does not wait for the translations; each target's translations run
#                           one at a time. room-g-<rec>: the same decisions, Japanese translated by Gemma.
# Hearing (<rec>): "mai" (MAI-Transcribe-2-Streaming, locale pinned) for ja and fa, which LT's MAI list
# (src/shared/best-routes.ts TABLE_MAI_LANGS) holds; "az" (Azure's standard real-time recogniser, locale pinned) for en,
# ko and hi, which it doesn't.
#
#   CLIPS_ROOT=... FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=... <venv with boto3, numpy>/bin/python simulate.py WORK [system...]
import concurrent.futures as cf
import importlib.util, json, os, re, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import words  # noqa: E402

os.environ.setdefault("RECS", "az,mai")
os.environ.setdefault("CT_SOL_VARIANT", "b")
spec = importlib.util.spec_from_file_location(
    "simulate_ct", os.path.join(HERE, "..", "2026-10-complete-thought-endpointing", "simulate_ct.py"))
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)
so, sp = ct.so, ct.sp
so.NAMES.update({"en": "English", "ja": "Japanese", "ko": "Korean", "fa": "Persian", "ur": "Urdu", "bn": "Bengali",
                 "ta": "Tamil", "hi": "Hindi"})
so.toks, so.joined = words.toks, words.joined

REC = {"en": "az", "ko": "az", "hi": "az", "ja": "mai", "fa": "mai"}
SOL_PROD = {"en-ja", "en-fa", "ja-en", "ko-en", "hi-en"}
DIRS = ["en-ja", "en-ko", "en-fa", "en-ur", "en-bn", "en-ta", "ja-en", "ko-en", "fa-en", "hi-en"]
ROOM = ["ja", "ko", "ur"]


def arms(d):
    r = REC[d.split("-")[0]]
    out = [f"S-sol-{r}", f"S-{r}"] if d in SOL_PROD else [f"S-{r}"]
    out += [f"ctb-{r}", f"ctb-gs-{r}"]
    if not d.endswith("-ja"):
        out.append(f"agree-{r}")
    return out


ct.SOL_ONLY_DIRS = set(DIRS)

# Foundry may refuse a request with HTTP 400 (its content filter): as Live Translation does, it is sent again without
# its context; if that is refused too, nothing is spoken for it. Every refusal goes to WORK/refusals.jsonl.
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


# ---------------- the room decider ----------------
def room_prompt(history, words_, targets):
    names = ", ".join(so.NAMES[t] for t in targets)
    numbered = " ".join(f"{i + 1}:{w}" for i, w in enumerate(words_))
    ctx = ("Earlier thoughts (context only, already translated):\n" + "\n".join(f"- {s}" for s in history[-2:]) + "\n"
           if history else "")
    return (f"You are deciding, for live interpreters, when an English speaker has finished a thought. The interpreters "
            f"translate it into {names} (languages that may put the verb last) while the speaker is still talking. The "
            f"English comes from live speech recognition: it may contain errors and has little or no punctuation. "
            f"Spoken words cannot be taken back.\n{ctx}"
            f"Words heard so far that have not been translated yet, numbered:\n{numbered}\n\n"
            f"Do words 1 to N, for some N, form a complete thought: a whole sentence or a whole clause that can be "
            f"translated into each of those languages now, without waiting for more, so that no translation will need "
            f"to change whatever the speaker says next? A part that still needs words not yet said (a verb, an object, "
            f"the rest of a clause, the noun after an article or preposition) is not complete.\n"
            f"If yes, answer only: COMPLETE N, with the largest such N. If not, answer exactly: WAIT")


def parse_room(text, n):
    m = re.search(r"COMPLETE\s*:?\s*(\d+)", text.strip(), re.I)
    if not m:
        return None
    end = int(m.group(1))
    return end if 1 <= end <= n else None


def run_room(pattern):
    """One decision stream for the room; writes sim/room-<rec>/<pattern>_en-<t>.json per target (and
    sim/room-g-<rec>/<pattern>_en-ja.json). Each file's calls: the shared decisions (kind "decide", "shared": the
    room's target count) and that target's translations."""
    r = REC["en"]
    tr_of = {"ja": "sol", "ko": sp.MT_TAG, "ur": sp.MT_TAG, "ja-g": sp.MT_TAG}
    targets = list(tr_of)
    outs = {t: os.path.join(ct.WORK, "sim", f"room-g-{r}" if t == "ja-g" else f"room-{r}",
                            f"{pattern}_en-{t.split('-')[0]}.json") for t in targets}
    if all(os.path.exists(p) for p in outs.values()):
        return f"room-{r}", pattern, "en-ja,ko,ur", "cached"
    a = "en"
    rec = json.load(open(os.path.join(ct.WORK, "rec", f"{r}_{pattern}_{a}.json")))
    clips = os.path.join(os.environ["CLIPS_ROOT"], f"clips_{pattern}")
    rms = ct.energy(clips, a)
    end_ms = len(rms) * 10 + 6000
    events = [("p", p["t"], p) for p in rec["partials"]] + [("f", f["t"], f) for f in rec["finals"]]
    events += [("v", t, None) for t in so.vad_pauses(clips, a)]
    events += [("k", float(t), None) for t in range(0, int(end_ms), ct.TICK_MS)]
    order = {"f": 0, "v": 1, "p": 2, "k": 3}
    events.sort(key=lambda e: (e[1], order[e[0]]))
    dec_calls, src_hist = [], []
    per = {t: {"chunks": [], "calls": [], "history": [], "busy": 0.0} for t in targets}
    st = {"seg": 0, "busy": 0.0, "prev": [], "cur": [], "times": [], "committed": [], "tail": [], "dirty": False,
          "last_word_t": None, "last_ans": None, "res_end": 0.0, "consumed": 0}

    def translate_all(t, n, kind):
        """Words 1..n of the tail are a thought: each target translates it, queued behind its own last call."""
        ws = st["tail"][:n]
        st["tail"] = st["tail"][n:]
        st["consumed"] += n
        src = so.joined([w["w"] for w in ws], a)
        for tg in targets:
            P, b = per[tg], tg.split("-")[0]
            prompt = (ct.gs_prompt(a, b, P["history"], src) if kind == "ct"
                      else so.sentence_prompt(src, a, b, P["history"]))
            text, wall, prov, pt, ctk = ct.call(tr_of[tg], prompt, 400)
            start = max(t, P["busy"])
            done = start + wall * 1000
            P["busy"] = done
            P["calls"].append({"t": round(t, 1), "kind": "translate", "mt": tr_of[tg], "start": round(start, 1),
                               "done": round(done, 1), "wall_ms": round(wall * 1000), "out": text[:300],
                               "prompt_tokens": pt, "completion_tokens": ctk})
            P["chunks"].append({"segment": ws[-1]["seg"], "t": round(t, 1), "final": False, "kind": kind, "src": src,
                                "out": text.strip(), "src_on": round(ws[0]["on"]), "src_end_t": round(ws[-1]["end"]),
                                "words": len(ws), "quiet_ms": None, "start": round(start, 1), "done": round(done, 1),
                                "wall_ms": round(wall * 1000), "provider": prov, "prompt_tokens": pt,
                                "completion_tokens": ctk})
            P["history"].append((src, text.strip()))
        src_hist.append(src)
        st["last_ans"] = None
        st["dirty"] = bool(st["tail"])

    def times_for(cur, t):
        keep = min(len(st["times"]), len(cur))
        times = st["times"][:keep]
        frm = times[-1][1] if keep else st["res_end"]
        to = max(frm, t - ct.LAG_MS)
        n = len(cur) - keep
        times += [ct.spread(frm, to, i, n) for i in range(n)]
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

    def decide(t):
        if not st["dirty"] or not st["tail"] or t < st["busy"]:
            return
        st["dirty"] = False
        ws = [w["w"] for w in st["tail"]]
        text, wall, prov, pt, ctk = ct.call(sp.MT_TAG, room_prompt(src_hist, ws, ROOM), 16)
        start = max(t, st["busy"])
        done = start + wall * 1000
        st["busy"] = done
        dec_calls.append({"t": round(t, 1), "kind": "decide", "mt": sp.MT_TAG, "shared": len(ROOM), "start": round(start, 1),
                          "done": round(done, 1), "wall_ms": round(wall * 1000), "out": text[:300],
                          "prompt_tokens": pt, "completion_tokens": ctk})
        n = parse_room(text, len(ws))
        if n is None:
            st["last_ans"] = None
            if len(ws) > ct.MAX_TAIL:
                translate_all(done, len(ws), "force")
            return
        absolute = st["consumed"] + n
        ok = st["last_ans"] is not None and st["last_ans"] == absolute
        st["last_ans"] = absolute
        if not ok:
            if len(ws) > ct.MAX_TAIL:
                translate_all(done, len(ws), "force")
            return
        translate_all(done, n, "ct")

    for kind, t, e in events:
        if kind == "p":
            st["prev"], st["cur"] = st["cur"], so.toks(e["text"], a)
            times_for(st["cur"], t)
            commit_upto(max(so.lcp(st["prev"], st["cur"]), min(len(st["cur"]), e.get("stable", 0))), t)
            decide(t)
        elif kind == "v":
            if st["cur"]:
                commit_upto(len(st["cur"]), t)
            decide(t)
        elif kind == "f":
            fin = so.toks(e["text"], a)
            times_for(fin, t)
            seg_words = st["committed"]
            in_tail = [w for w in st["tail"] if w["seg"] == st["seg"]]
            done_n = len(seg_words) - len(in_tail)
            j, _ = so.align_end(seg_words[:done_n], fin)
            before = len(st["tail"])
            st["tail"] = [w for w in st["tail"] if w["seg"] != st["seg"]]
            for i in range(j, len(fin)):
                on, en = st["times"][i] if i < len(st["times"]) else (t - ct.LAG_MS, t - ct.LAG_MS)
                st["tail"].append({"w": fin[i], "seg": st["seg"], "on": on, "end": en})
            if len(st["tail"]) != before:
                st["last_ans"] = None
            st["res_end"] = e["offsetMs"] + e["durationMs"]
            st.update({"seg": st["seg"] + 1, "prev": [], "cur": [], "times": [], "committed": [], "dirty": True,
                       "last_word_t": t})
            decide(t)
        else:
            if st["tail"] and t >= st["busy"]:
                if st["last_word_t"] is not None and t - st["last_word_t"] >= ct.FLUSH_MS and not st["cur"]:
                    translate_all(t, len(st["tail"]), "flush")
                else:
                    decide(t)
    if st["tail"]:
        translate_all(end_ms, len(st["tail"]), "flush")
    for tg in targets:
        b = tg.split("-")[0]
        name = f"room-g-{r}" if tg == "ja-g" else f"room-{r}"
        os.makedirs(os.path.dirname(outs[tg]), exist_ok=True)
        cfg = {"rec": r, "mode": "room", "variant": "b", "mt": tr_of[tg], "decider": sp.MT_TAG, "room": ROOM}
        json.dump({"system": name, "pattern": pattern, "dir": f"en-{b}", "config": cfg, "chunks": per[tg]["chunks"],
                   "calls": dec_calls + per[tg]["calls"]}, open(outs[tg], "w"), ensure_ascii=False, indent=1)
    return f"room-{r}", pattern, "en-ja,ko,ur", f"{len(dec_calls)} decisions, {len(per['ko']['chunks'])} thoughts"


if __name__ == "__main__":
    only = set(sys.argv[2:])
    pats = os.environ.get("PATTERNS", "reg,irr").split(",")
    dirs = os.environ.get("DIRS", ",".join(DIRS)).split(",")
    jobs = [(n, p, d) for p in pats for d in dirs for n in arms(d) if not only or n in only]
    with cf.ThreadPoolExecutor(int(os.environ.get("THREADS", "6"))) as ex:
        futs = [ex.submit(ct.run, *j) for j in jobs]
        if not only or "room" in only:
            futs += [ex.submit(run_room, p) for p in pats]
        for f in cf.as_completed(futs):
            print(*f.result(), flush=True)
