"""
Rooms (?room=): one speaker's audio, translated once per listener language and
fanned out. Room and ROOMS (the rooms open now, keyed by token subject), the
connection that joins one (handle_room: primary, promotion when it leaves),
and what a room does with its audio: an utterance at a time (room_utterance:
passthrough, priority decode) or, in simultaneous mode (?stream=1), a pass at a
time (room_pass: LocalAgreement, trimming, the clause and agree policies).
Part of the server (server/server.py is the entry point).
"""
import asyncio, json, os, time

from engines.base import RATE, VAD_RATE
from engines.common import float_to_pcm16
from translation_context import TranslationMemory
from pipeline import (PASSTHROUGH_MIN_CONF, PASSTHROUGH_MIN_S, STREAM_PASS_MS, STREAM_MAX_WORDS,
                      STREAM_MIN_WORDS, STREAM_COMMA_WORDS, STREAM_TRIM, STREAM_TRIM_S,
                      SWITCH_MIN_CONF, SWITCH_FREE_S, TRAILING_KEEP_MS,
                      endpointing, min_speech_ms, short_turn, common_prefix_words, forced_cut)
from connection import AudioMeter, Fanout, clean, send_json, send_speech, too_fast


class Room:
    """Connections that share ONE audio source — the app's real shape: it
    streams the same microphone to a session per target language. Without
    this, the fanout bench transcribed the identical clip seven times and
    queued seven MT decodes single-file; the last language came back ~15s
    after the first. With it: VAD once, ASR once, ONE batched MT generate,
    TTS in parallel. The first connection in the room drives the audio;
    the rest have their (identical) audio drained and discarded.

    A room belongs to ONE token subject: ROOMS is keyed by (subject, ?room=),
    so two tenants who both say ?room=main get two rooms and never hear, drive
    or displace each other. Within a subject any number of connections may
    listen to the same language; each gets the output, and one leaving takes
    only itself out."""

    def __init__(self, edition=None):
        self.edition = edition     # whose translators and voices the room uses (EDITION=both: per room)
        self.members = {}          # ws -> lang, in joining order
        self.primary = None        # the connection whose audio we process
        import numpy as np
        self.buf = np.zeros(0, dtype=np.float32)
        self.quiet_ms = 0.0
        self.vad = None  # the room's own speech detector (pipe.new_vad), made on first audio
        self.boost = None  # and the gain for its copy of the audio (audio_in.QuietBoost)
        # No utterance until a human has actually spoken. The benches never
        # exposed this: their clips speak immediately. A LIVE microphone idles,
        # and without this gate silence alone satisfied the endpoint — the
        # server transcribed ever-growing silence buffers on a loop, whisper
        # hallucinated subtitle credits into them ("Subtitulado...",
        # "Société Radio-Canada" — its classic silence artifacts), MADLAD
        # translated the credits, and real speech queued behind it all.
        self.speech_seen = False
        # The reader must never block on the pipeline: utterances go through
        # this queue to the worker, so the socket keeps draining (and VAD keeps
        # listening) while one is synthesised.
        self.queue = None
        self.worker = None
        self.heartbeat = None
        # Last language we were CONFIDENT about, for utterances too short to
        # identify on their own.
        self.last_src = None
        # Detected language awaiting proof that the pass was speech, so a
        # cough cannot make itself the room's language.
        self.lid_commit = None
        # Simultaneous mode, decided by whoever opens the room (?stream=1), and its commit
        # policy (?policy=): "clause" or "agree" (agree.py: lang -> AgreeTurn for this turn).
        self.stream = False
        self.policy = "clause"
        self.agree = {}
        self.since_asr_ms = 0.0
        self.last_pass = ""       # previous pass's text, for LocalAgreement
        self.translated_n = 0     # words already translated AND spoken
        # The actual words spoken, for aligning the next pass by TEXT rather
        # than by a count that a re-transcription can invalidate.
        self.spoken_words = []
        # Buffer trimming (LITHOS_TRIM=1). fixed_words is transcription that
        # can no longer change because its audio has left the decode window;
        # trimmed_audio keeps the raw samples for the same-language relay at
        # turn end; turn_gen guards a trim landing after the buffer was reset.
        self.fixed_words = []
        self.trimmed_audio = []
        self.turn_gen = 0
        self.turn_src = None      # language of the turn in progress
        # Connections that said ?priority=1 — the room's PA feed. Their
        # languages are translated in their own decode, ahead of the batch.
        self.priority_ws = set()
        # The previous pieces for the translator (?context=1 on the primary, a
        # room-wide setting like `stream`; translation_context.py). Off here;
        # the primary replaces it when it joins.
        self.context = TranslationMemory(False)

    @property
    def priority(self):
        """Languages a ?priority=1 connection is listening to."""
        return {self.members[w] for w in self.priority_ws if w in self.members}

    def pairs(self):
        """(lang, ws) for every connection, several per language possible."""
        return [(lg, w) for w, lg in self.members.items()]

    def groups(self):
        """lang -> [ws]: each language once, with everyone listening to it."""
        out = {}
        for w, lg in self.members.items():
            out.setdefault(lg, []).append(w)
        return out


# (token subject, room id) -> Room. The subject is part of the key on purpose:
# see Room.
ROOMS = {}


# Utterances waiting on the pipeline before we start shedding the oldest.
MAX_PENDING_UTTERANCES = 3


async def room_heartbeat(room, room_id):
    """Say what the room is doing every few seconds.

    A room can stop translating while every connection stays open and no error
    is raised — a wedged worker, a queue that never drains, a buffer that never
    endpoints, or no primary at all. From outside they are indistinguishable:
    captions simply stop. This prints the state that tells them apart.
    """
    last = None
    while True:
        await asyncio.sleep(5)
        try:
            qsize = room.queue.qsize() if room.queue else -1
            state = (
                f"members={len(room.members)} primary={'yes' if room.primary else 'NONE'} "
                f"queue={qsize} buf={len(room.buf) / VAD_RATE:.1f}s "
                f"speech_seen={room.speech_seen} quiet={room.quiet_ms:.0f}ms "
                f"worker={'alive' if room.worker and not room.worker.done() else 'DEAD'}"
            )
            if state != last:
                print(f"[stack] room {room_id}: {state}", flush=True)
                last = state
        except Exception as e:
            print(f"[stack] heartbeat failed: {e}", flush=True)
            return


async def room_worker(pipe, room, src):
    """Process utterances in order, off the read path."""
    while True:
        job = await room.queue.get()
        if job is None:
            return
        try:
            kind, audio = job[0], job[1]
            if kind == "utt":
                await room_utterance(pipe, room, audio, src)
            else:
                await room_pass(pipe, room, audio, src, job[2],
                                job[3] if len(job) > 3 else None)
        except Exception as e:
            print(f"[stack] {job[0]} failed: {e}", flush=True)


async def room_utterance(pipe, room, utterance, src):
    """One utterance through the shared pipeline, fanned out to every member.

    src="auto" is the hybrid: identify THIS utterance's language, transcribe
    with the right engine (distil / whisper / Omnilingual by resource level),
    then translate to every member language as usual. A Spanish speaker's
    utterance therefore reaches the room's English session as English — the
    PA case — while the Spanish session hears Spanish, which is exactly the
    semantics the cloud providers give the app today.
    """
    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()
    stage = {}
    # lang -> [ws]: each language is translated and synthesised once, and sent
    # to everyone listening to it.
    groups = room.groups()
    everyone = [w for ws_ in groups.values() for w in ws_]
    this_src = src
    lid_conf = 0.0
    lid_commit = None
    if src == "auto":
        detected, lid_conf = await loop.run_in_executor(None, pipe.identify_conf, utterance)
        switching = bool(room.last_src) and detected != room.last_src
        bar = (SWITCH_MIN_CONF
               if switching and len(utterance) / VAD_RATE < SWITCH_FREE_S
               else PASSTHROUGH_MIN_CONF)
        if detected and lid_conf >= bar:
            this_src = detected
            # Do NOT make it sticky yet. Noise can be identified CONFIDENTLY as
            # the wrong language -- a cough was read as Khmer at >=0.75 -- and
            # committing here poisoned room.last_src, so every following
            # utterance went to Khmer too. That is the "src ja / src km while
            # speaking English" in the service log. It sticks below, once the
            # utterance has proved to be speech.
            lid_commit = detected
        else:
            # Measured: 1.5s of Spanish is read as ENGLISH at ~0.5 confidence,
            # on every clip tried — short fragments do not carry the language.
            # Falling back to "en" made every "sí, gracias" an English
            # transcription; the speaker has not changed language since the
            # last utterance we were sure about, so stay there.
            this_src = room.last_src or detected or "en"
        # Known limit: per-utterance ID jitters on very short utterances (a
        # 2-3s fragment misread as a neighbour language in CPU testing).
        # Full-clip accuracy measured 100% constrained; a stickiness window
        # like the app's SourceLanguageTracker is the fix if it shows up on
        # real speech.
        await send_json(everyone, {"type": "route", "src": this_src})
    stage["lid"] = time.perf_counter() - t0
    text = await loop.run_in_executor(None, pipe.transcribe, utterance, this_src)
    stage["asr"] = time.perf_counter() - t0
    if not text:
        return
    if lid_commit:
        room.last_src = lid_commit      # speech, so the language may stick
    await send_json(everyone, {"type": "inputTranscript", "text": text})
    # A listener whose language is the one being SPOKEN gets the microphone
    # itself (the real voice, no model in the path), not a translation into
    # their own language. Only on a language we are SURE of: a misread replaces
    # a translation with raw speech (seen live: Spanish out of an English PA
    # after LID read it as English). Short fragments are where LID jitters, so
    # length is part of the test.
    sure = (src != "auto" or (lid_conf >= PASSTHROUGH_MIN_CONF
                              and len(utterance) / VAD_RATE >= PASSTHROUGH_MIN_S))
    same = [(lg, ws_) for lg, ws_ in groups.items() if lg == this_src] if sure else []
    others = [(lg, ws_) for lg, ws_ in groups.items() if lg != this_src] if sure else list(groups.items())
    if not sure and this_src in groups:
        stage["unsure"] = round(lid_conf, 2)
    if same:
        from scipy.signal import resample_poly
        pcm = resample_poly(utterance, RATE, VAD_RATE)
        passthrough = float_to_pcm16(pcm)
        for lg, ws_ in same:
            for w in ws_:
                try:
                    await w.send(json.dumps({"type": "transcript", "delta": text}))
                    await w.send(passthrough)
                except Exception:
                    pass
        stage["passthrough"] = time.perf_counter() - t0
    if not others:
        stage["done"] = time.perf_counter() - t0
        print("[stack] utterance %.1fs speech | " % (len(utterance) / VAD_RATE)
              + " ".join(f"{k} {v:.2f}s" for k, v in stage.items()), flush=True)
        return
    members = others      # (lang, [ws]), one entry per language
    async def stream_to(lg, w, tr):
        """Send each sentence the moment it is ready, in order, to everyone
        listening to lg (w: their connections)."""
        out = Fanout(w)
        for i, fut in enumerate(pipe.synthesise_futures(tr, lg, room.edition)):
            try:
                audio = await asyncio.wrap_future(fut)
            except Exception as e:
                print(f"[stack] tts failed ({lg}): {e}", flush=True)
                continue
            if audio:
                if i == 0:
                    stage[f"tts1[{lg}]"] = time.perf_counter() - t0
                try:
                    await send_speech(out, audio)
                except Exception:
                    return

    # One batched decode runs until the LONGEST output finishes, so a language
    # nobody in the room is listening to holds up the one they are. The
    # connection that feeds the PA marks itself (?priority=1); it gets its own
    # small decode first and starts speaking while the rest are still being
    # translated. Costs a little total GPU, buys the only latency the room
    # actually experiences.
    prio = room.priority
    order = sorted(range(len(members)), key=lambda i: members[i][0] not in prio)
    # The previous pieces, for a room that asked (?context=1): the same context
    # for both decodes of this piece, remembered once they are both done.
    context = room.context.before(this_src)
    if prio and any(members[i][0] in prio for i in order):
        first = [i for i in order if members[i][0] in prio]
        rest = [i for i in order if members[i][0] not in prio]
        translations = [None] * len(members)
        got = await loop.run_in_executor(
            None, pipe.translate_batch, text, [members[i][0] for i in first], this_src, context,
            room.edition)
        for i, tr in zip(first, got):
            translations[i] = tr
        stage["mt1"] = time.perf_counter() - t0
        for i in first:
            await send_json(members[i][1], {"type": "transcript", "delta": translations[i]})
        speaking = [asyncio.create_task(stream_to(*members[i], translations[i])) for i in first]
        if rest:
            got = await loop.run_in_executor(
                None, pipe.translate_batch, text, [members[i][0] for i in rest], this_src, context,
                room.edition)
            for i, tr in zip(rest, got):
                translations[i] = tr
            for i in rest:
                await send_json(members[i][1], {"type": "transcript", "delta": translations[i]})
        stage["mt"] = time.perf_counter() - t0
        room.context.after(this_src, text, {members[i][0]: translations[i] for i in range(len(members))})
        await asyncio.gather(*speaking,
                             *[stream_to(*members[i], translations[i]) for i in rest])
        stage["done"] = time.perf_counter() - t0
        print("[stack] utterance %.1fs speech | " % (len(utterance) / VAD_RATE)
              + " ".join(f"{k} {v:.2f}s" for k, v in stage.items()), flush=True)
        return
    langs = [lg for lg, _ in members]
    translations = await loop.run_in_executor(None, pipe.translate_batch, text, langs, this_src, context,
                                              room.edition)
    room.context.after(this_src, text, dict(zip(langs, translations)))
    stage["mt"] = time.perf_counter() - t0
    for (lg, w), tr in zip(members, translations):
        await send_json(w, {"type": "transcript", "delta": tr})

    await asyncio.gather(*[
        stream_to(lg, w, tr) for (lg, w), tr in zip(members, translations)
    ])
    stage["done"] = time.perf_counter() - t0
    spoken = len(utterance) / VAD_RATE
    print("[stack] utterance %.1fs speech | " % spoken
          + " ".join(f"{k} {v:.2f}s" for k, v in stage.items()), flush=True)


def trim_point(seg_ends, buf_s, trim_s):
    """Where to cut a long streaming buffer, or None.

    Cut at the end of the second-to-last segment: the most recent boundary is
    still liable to move on the next pass (both reference implementations use
    the same margin -- sents[-2] in whisper_streaming, a 2s sentence_buffer in
    HF speech-to-speech). Requires at least two segments and a buffer over
    trim_s; refuses cuts so early they would churn for no gain.
    """
    if buf_s <= trim_s or len(seg_ends) < 2:
        return None
    cut = seg_ends[-2]
    return cut if cut > 1.0 else None


def resume_point(spoken, words):
    """Where a new transcription continues past what was already SPOKEN.

    room_flush used to slice by index -- words[translated_n:] -- which assumes
    the prefix of the turn never changes. It does. A live read produced, over
    three consecutive passes:

        But behold, my beloved brother, in this kind of world,
        But behold, my beloved brother, and thus came the voice of t
        But behold, my beloved brethren, thus came the voice of the

    and the final pass hands room_flush the WHOLE re-transcription. Slicing
    that by a count derived from an earlier, differently-worded pass lands in
    the wrong place: words already spoken get said again (the reader sees
    lines being added) or a word is skipped.

    So align by text instead. Find where the tail of what was actually spoken
    occurs in the new transcription and continue from there; fall back to the
    old index only when no anchor is found.
    """
    if not spoken:
        return 0
    def key(w):
        return w.strip(".,!?;:\u2014-").lower()
    tail = [key(w) for w in spoken[-3:] if key(w)]
    if tail:
        low = [key(w) for w in words]
        for k in range(len(low) - len(tail), -1, -1):
            if low[k:k + len(tail)] == tail:
                return k + len(tail)
    return min(len(spoken), len(words))


async def room_speak(pipe, room, lg, w, tr):
    """Send one piece of translation, text then speech, to everyone listening to lg (w)."""
    out = Fanout(w)
    try:
        await out.send(json.dumps({"type": "transcript", "delta": tr + " "}))
    except Exception:
        return
    for fut in pipe.synthesise_futures(tr, lg, room.edition):
        try:
            audio = await asyncio.wrap_future(fut)
        except Exception as e:
            print(f"[stack] tts failed ({lg}): {e}", flush=True)
            continue
        if audio:
            try:
                await send_speech(out, audio)
            except Exception:
                return


async def room_flush(pipe, room, words, final):
    """Translate and speak what the committed words allow: by the room's policy for the directions that agree
    (agree.py), by whole clauses for the rest (room_clause_flush).

    A member whose language is the one being spoken is served the microphone at the turn boundary, not a
    piece-by-piece re-speak of their own words."""
    members = [(lg, ws_) for lg, ws_ in room.groups().items() if lg != room.turn_src]
    if room.policy == "agree" and members:
        for lg, _ in members:
            if lg not in room.agree:
                # Made at the turn's first pass with any words; None: this direction keeps the clause rule.
                room.agree[lg] = pipe.agree_turn(room.turn_src, lg, room.context.before(room.turn_src),
                                                room.edition)
        agreeing = [(lg, w) for lg, w in members if room.agree.get(lg) is not None]
        if agreeing:
            await room_agree_flush(pipe, room, words, final, agreeing,
                                   only_agree=len(agreeing) == len(members))
        members = [(lg, w) for lg, w in members if room.agree.get(lg) is None]
    if members:
        await room_clause_flush(pipe, room, words, final, members)


async def room_agree_flush(pipe, room, words, final, members, only_agree):
    """The agree policy for these members (agree.AgreeTurn per language): speak what two successive translations
    of the turn so far agree on; at the end of the turn, the rest."""
    loop = asyncio.get_running_loop()
    text = " ".join(words)

    def one(lg):
        turn = room.agree[lg]
        if final:
            return turn.finish(text, lambda t: pipe.translate_batch(t, [lg], room.turn_src,
                                                                     room.context.before(room.turn_src),
                                                                     room.edition)[0])
        return turn.step(words)

    if not words:
        return
    outs = await asyncio.gather(*[loop.run_in_executor(None, one, lg) for lg, _ in members])
    if final and only_agree:
        # The whole turn as each language heard it, for the next turn's context (a room that also has
        # clause-rule members records their clauses instead).
        room.context.after(room.turn_src, text, {lg: " ".join(room.agree[lg].spoken) for lg, _ in members})
    await asyncio.gather(*[room_speak(pipe, room, lg, w, tr) for (lg, w), tr in zip(members, outs) if tr])


async def room_clause_flush(pipe, room, words, final, members):
    """Translate and speak the committed words that complete a clause.

    Audio cannot be un-said, so only COMMITTED words get here, and only whole
    clauses: MT reorders across a clause boundary, so half a clause is not
    half a translation, it is a wrong one.
    """
    loop = asyncio.get_running_loop()
    pending = words[resume_point(room.spoken_words, words):]
    if not pending:
        return
    # Prefer a SENTENCE end. MADLAD reorders across a clause boundary, so a
    # comma-sized fragment is translated without the context that decides its
    # word order — measured against utterance mode, that is where "los
    # sustantivos que se usan en el mundo" degraded to "los nombres que el
    # mundo dice". Take a comma only once waiting costs more than the context
    # is worth.
    clause_end = 0
    for i, w in enumerate(pending):
        if w and w[-1] in ".!?":
            clause_end = i + 1
    if not clause_end and len(pending) >= STREAM_COMMA_WORDS:
        for i, w in enumerate(pending):
            if w and w[-1] in ",;:":
                clause_end = i + 1
    if not clause_end and (final or len(pending) >= STREAM_MAX_WORDS):
        clause_end = len(pending)
    # A comma two words in is not a clause worth speaking on its own. Measured
    # on a read-aloud: flushing at every punctuation mark produced fragments
    # like "letra mayúscula," and one utterance that was the single word "a",
    # each its own TTS call with its own silence around it. Wait for the next
    # break unless the turn has ended or the backlog is already long.
    if (clause_end and clause_end < STREAM_MIN_WORDS
            and not final and len(pending) < STREAM_MAX_WORDS):
        return
    if not clause_end:
        return
    segment = " ".join(pending[:clause_end])
    room.spoken_words.extend(pending[:clause_end])
    room.translated_n += clause_end
    langs = [lg for lg, _ in members]
    context = room.context.before(room.turn_src)    # the previous clauses, for ?context=1
    translations = await loop.run_in_executor(None, pipe.translate_batch, segment, langs, room.turn_src,
                                              context, room.edition)
    room.context.after(room.turn_src, segment, dict(zip(langs, translations)))
    await asyncio.gather(*[room_speak(pipe, room, lg, w, tr) for (lg, w), tr in zip(members, translations)])


async def room_pass(pipe, room, audio, src, final, ctx=None):
    """One pass over the turn so far: re-transcribe, commit, speak.

    Words identical across two consecutive passes are committed — the same
    LocalAgreement-2 rule handle_streaming() uses, so ASR flicker never
    reaches the room. The buffer is not cleared between passes; the turn ends
    on the same endpoint rule utterance mode uses.
    """
    loop = asyncio.get_running_loop()
    if len(audio) < VAD_RATE // 2:
        return
    members = room.pairs()     # (lang, ws), one per connection
    if not members:
        return
    t0 = time.perf_counter()

    if room.turn_src is None:
        if src != "auto":
            room.turn_src = src
        else:
            detected, conf = await loop.run_in_executor(None, pipe.identify_conf, audio)
            switching = bool(room.last_src) and detected != room.last_src
            bar = (SWITCH_MIN_CONF
                   if switching and len(audio) / VAD_RATE < SWITCH_FREE_S
                   else PASSTHROUGH_MIN_CONF)
            if (detected and conf >= bar
                    and len(audio) / VAD_RATE >= PASSTHROUGH_MIN_S):
                room.turn_src = detected
                # Deferred for the same reason as the utterance path: a noise
                # burst identified confidently as the wrong language must not
                # become the room's sticky source. Committed after the pass
                # proves to be speech.
                room.lid_commit = detected
            elif final:
                room.turn_src = room.last_src or detected or "en"
            else:
                # Too little audio to name the language, and committing words
                # transcribed by the wrong model is not recoverable once
                # spoken. Wait for the next pass.
                return
        for _, w in members:
            try:
                await w.send(json.dumps({"type": "route", "src": room.turn_src}))
            except Exception:
                pass

    fixed = (ctx or {}).get("fixed") or []
    text, segs = await loop.run_in_executor(
        None, lambda: pipe.transcribe(audio, room.turn_src, want_segments=True))
    # With trimming, `audio` is only the tail of the turn; the fixed words are
    # transcription whose audio has already left the window. Prepending them
    # keeps everything downstream -- LocalAgreement, the clause gate, the
    # spoken-word alignment -- working on the whole turn, unchanged.
    full_text = (" ".join(fixed) + " " + text).strip() if fixed else text
    words = full_text.split()
    if room.lid_commit:
        room.last_src = room.lid_commit
        room.lid_commit = None
    if final:
        committed = words          # the turn is over: everything is final
    else:
        committed = common_prefix_words(room.last_pass, full_text)
        room.last_pass = full_text
    if final and full_text:
        for _, w in members:
            try:
                await w.send(json.dumps({"type": "inputTranscript", "text": full_text}))
            except Exception:
                pass
    spoke = room.translated_n
    await room_flush(pipe, room, committed, final)

    # Trim AFTER speaking, so it never delays a commit. Only on an interim
    # pass, only in the turn the audio came from (gen), and only at the end of
    # the second-to-last segment -- the last is still liable to move.
    if (STREAM_TRIM and not final
            and (ctx or {}).get("gen") == room.turn_gen):
        cut = trim_point([e for _, e in segs], len(audio) / VAD_RATE,
                         STREAM_TRIM_S)
        if cut:
            n = int(cut * VAD_RATE)
            if n <= len(room.buf):
                room.trimmed_audio.append(audio[:n])
                room.buf = room.buf[n:]
                add = " ".join(t for t, _ in segs[:-1]).split()
                room.fixed_words.extend(add)
                print("[stack] trimmed %.1fs (%d words fixed, %.1fs left)" % (
                    cut, len(add), len(room.buf) / VAD_RATE), flush=True)

    if final:
        if room.turn_src and any(lg == room.turn_src for lg, _ in members):
            import numpy as np
            from scipy.signal import resample_poly
            # The relay is the WHOLE turn: trimming removed audio from the
            # decode window, not from what a same-language member is owed.
            raw = ((ctx or {}).get("raw") or []) + [audio]
            pcm = resample_poly(np.concatenate(raw) if len(raw) > 1 else audio,
                                RATE, VAD_RATE)
            relay = float_to_pcm16(pcm)
            for lg, w in members:
                if lg != room.turn_src:
                    continue
                try:
                    await w.send(json.dumps({"type": "transcript", "delta": full_text}))
                    await w.send(relay)
                except Exception:
                    pass
        turn_s = (sum(len(a) for a in (ctx or {}).get("raw") or [])
                  + len(audio)) / VAD_RATE
        print("[stack] turn %.1fs speech | %d words | pass %.2fs%s" % (
            turn_s, len(words), time.perf_counter() - t0,
            "" if room.turn_src is None else " | src " + room.turn_src), flush=True)
        room.last_pass = ""
        room.translated_n = 0
        room.spoken_words = []
        room.agree = {}
        room.turn_src = None
    elif room.translated_n > spoke:
        print("[stack] commit %d->%d words at %.1fs buffered (%.2fs)" % (
            spoke, room.translated_n, len(audio) / VAD_RATE,
            time.perf_counter() - t0), flush=True)


async def handle_room(ws, pipe, key, lang, src, stream=False, priority=False, context=False, policy="clause"):
    """One connection in the room `key`: (token subject, ?room= id, edition). The
    edition is part of the key, so a room's voices are always its members' edition."""
    import numpy as np

    room_id = f"{clean(key[0], 24)}/{key[1]}"   # for the log; the id itself is validated
    room = ROOMS.get(key)
    if room is None:
        room = ROOMS[key] = Room(key[2] if len(key) > 2 else None)
    room.members[ws] = lang
    if priority:
        room.priority_ws.add(ws)
    meter = AudioMeter()
    from audio_in import AudioIn, QuietBoost, QUIET_ASR, vad_block  # numpy: loaded with the rest, not at import
    conn_in = AudioIn(f"room {room_id}")
    endpoint_ms, long_utterance_s, long_endpoint_ms, max_utterance_s = endpointing(src)
    min_ms = min_speech_ms(src)
    is_primary = room.primary is None
    if is_primary:
        room.primary = ws
        room.stream = stream
        room.policy = policy
        room.context = TranslationMemory(context)
        room.queue = asyncio.Queue()
        room.worker = asyncio.create_task(room_worker(pipe, room, src))
        if os.environ.get("LITHOS_ROOM_HEARTBEAT") == "1":
            room.heartbeat = asyncio.create_task(room_heartbeat(room, room_id))
    mode = ("simultaneous, " + room.policy) if room.stream else "utterance"
    print(f"[stack] room {room_id}: +{lang}{' (primary, ' + mode + ')' if is_primary else ''}")

    try:
        async for msg in ws:
            # Every connection is metered, the discarded ones too: their
            # frames still cost a read.
            if not meter.take(len(msg)):
                await too_fast(ws, f"room {room_id}")
                return
            if not isinstance(msg, bytes):
                continue
            # Consult the CURRENT primary, not a flag captured at join: a
            # session promoted after the original primary left must start
            # driving the room immediately.
            if ws is not room.primary:
                continue  # same audio as the primary — drain and discard
            # Fixed 96 ms blocks, whatever size of message the client sends (audio_in.py, issue #13).
            for pcm16 in conn_in.feed(msg):
                if room.vad is None:
                    room.vad = pipe.new_vad()
                    room.boost = QuietBoost()   # a quiet talker, brought up for the VAD (audio_in.py)
                loud = room.boost(pcm16)
                room.buf = np.concatenate([room.buf, loud if QUIET_ASR else pcm16])
                chunk_ms = len(pcm16) / VAD_RATE * 1000
                prob = vad_block(room.vad, loud)
                if prob > 0.5:
                    room.speech_seen = True
                    room.quiet_ms = 0.0
                else:
                    room.quiet_ms += chunk_ms
                if not room.speech_seen:
                    # Idle mic: keep only a half-second pre-roll so the eventual
                    # first word arrives with its onset, not with minutes of room
                    # tone in front of it.
                    room.buf = room.buf[-(VAD_RATE // 2):]
                    room.turn_gen += 1   # origin moved: no stale trim may land
                    continue
                if room.stream and room.speech_seen:
                    room.since_asr_ms += chunk_ms
                    # Coalesce: never stack passes behind a slow one, or the
                    # commits fall further behind the speaker every second.
                    if (room.since_asr_ms >= STREAM_PASS_MS
                            and len(room.buf) >= VAD_RATE and room.queue.empty()):
                        room.since_asr_ms = 0.0
                        room.queue.put_nowait(("pass", room.buf.copy(), False,
                                               {"gen": room.turn_gen,
                                                "fixed": list(room.fixed_words)}))
                buf_s = len(room.buf) / VAD_RATE
                # Long buffer -> settle for a clause gap; very long -> cut anyway.
                need_ms = endpoint_ms if buf_s < long_utterance_s else long_endpoint_ms
                forced = buf_s >= max_utterance_s
                if not forced and (room.quiet_ms < need_ms or len(room.buf) < VAD_RATE):
                    continue
                if not forced and short_turn(buf_s, room.quiet_ms, need_ms, min_ms):
                    continue   # a short piece: wait for the rest of its sentence
                if forced:
                    # No pause for MAX_UTTERANCE_S (a speech, a reading): cut after the
                    # last sentence the recogniser heard, carrying the unfinished one
                    # into the next utterance, so the translation gets whole
                    # sentences. Awaited here on purpose: audio arriving meanwhile
                    # waits in the socket, so the carry stays in order. Without a
                    # sentence or clause end, the least bad instant as before.
                    cut, how = await forced_cut(pipe, room.buf, src, room.last_src)
                    print(f"[stack] room {room_id}: forced cut at {cut / VAD_RATE:.1f}s of "
                          f"{len(room.buf) / VAD_RATE:.1f}s ({how})", flush=True)
                    utterance, room.buf = room.buf[:cut], room.buf[cut:]
                    room.quiet_ms = 0.0
                else:
                    # Hand over the SPEECH, not the pause that ended it. Whisper
                    # fills silence with polite filler it has seen at the end of
                    # captioned video — "gracias por su comentario", "thanks for
                    # watching" — and MADLAD dutifully translates the invention.
                    # The endpoint already measured the trailing quiet; drop all
                    # but a short tail so no word loses its release.
                    trail = int(VAD_RATE * max(0.0, room.quiet_ms - TRAILING_KEEP_MS) / 1000)
                    utterance = room.buf[:-trail] if 0 < trail < len(room.buf) else room.buf
                    room.buf, room.quiet_ms = np.zeros(0, dtype=np.float32), 0.0
                room.speech_seen = forced  # still talking: keep listening, no pre-roll trim
                # The turn is over: snapshot what trimming carried for the final
                # pass, then start the next turn clean. The gen bump also voids
                # any in-flight interim pass's right to trim the new buffer.
                trim_ctx = {"gen": room.turn_gen, "fixed": room.fixed_words,
                            "raw": room.trimmed_audio}
                room.fixed_words, room.trimmed_audio = [], []
                room.turn_gen += 1
                if room.stream:
                    room.queue.put_nowait(("pass", utterance, True, trim_ctx))
                    room.since_asr_ms = 0.0
                    continue
                if room.queue.qsize() >= MAX_PENDING_UTTERANCES:
                    # Never silently: a drop here is the pipeline losing to a
                    # talker, and the operator needs to see it in the log.
                    dropped = await room.queue.get()
                    print(f"[stack] room {room_id}: pipeline behind, dropped "
                          f"{len(dropped[1]) / VAD_RATE:.1f}s utterance", flush=True)
                room.queue.put_nowait(("utt", utterance))
    finally:
        # Only this connection leaves: another listener of the same language stays.
        room.members.pop(ws, None)
        room.priority_ws.discard(ws)
        if room.primary is ws:
            # PROMOTE a survivor: the primary is the only connection whose audio
            # is processed, so without one the room goes deaf while the other
            # members stay connected. A room outlives any one connection (the app
            # opens a session per language and any of them can blip).
            survivor = next(iter(room.members), None)
            room.primary = survivor
            if survivor is None:
                if room.worker:
                    room.worker.cancel()
                    room.worker = None
                if room.heartbeat:
                    room.heartbeat.cancel()
                    room.heartbeat = None
            else:
                print(f"[stack] room {room_id}: primary left, promoted a survivor", flush=True)
                # That buffer belonged to the old connection's audio; a new
                # speaker's first words must not be glued onto its tail.
                room.buf = np.zeros(0, dtype=np.float32)
                room.fixed_words, room.trimmed_audio = [], []
                room.agree = {}
                room.turn_gen += 1
                room.quiet_ms = 0.0
                room.speech_seen = False
        if not room.members and ROOMS.get(key) is room:
            ROOMS.pop(key, None)
