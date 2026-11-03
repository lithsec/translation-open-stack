"""
One connection, from the moment guarded() (server.py) admits it: handle()
parses and validates the request (parse_request), sends the hello and serves
it as a room member (rooms.handle_room), a --streaming connection
(handle_streaming: LocalAgreement, clause by clause) or a solo connection
(route=to, cands). Part of the server (server/server.py is the entry point).
"""
import asyncio, json

from engines.base import RATE, VAD_RATE
from translation_context import TranslationMemory
from pipeline import STREAM_POLICY, endpointing, min_speech_ms, short_turn, quietest_cut, common_prefix_words, \
    forced_cut
from connection import AudioMeter, CLOSE_BAD_REQUEST, MAX_CANDS, ROOM_ID_RE, clean, speak_to, too_fast
from rooms import handle_room


async def handle_streaming(ws, pipe, src, lang, edition=None, memory=None):
    """Translate WHILE the speaker talks.

    Every second the whole current utterance is re-transcribed; words identical
    in two consecutive passes are COMMITTED (ASR flicker never reaches the
    room); committed text past the last translation point is translated and
    spoken when a clause completes (punctuation, or 12 words of nothing).
    The re-transcribe grows with the utterance, so cost rises within a turn —
    distil at ~10x realtime keeps that fine for sermon-length turns; the
    utterance reset on silence bounds it.
    """
    import numpy as np

    buf = np.zeros(0, dtype=np.float32)
    quiet_ms = 0.0
    last_pass = ""
    committed_n = 0      # words already committed
    translated_n = 0     # words already translated+spoken
    since_asr_ms = 0.0
    vad = pipe.new_vad()
    meter = AudioMeter()
    loop = asyncio.get_running_loop()
    memory = memory or TranslationMemory(False)   # the previous clauses, for ?context=1
    from audio_in import AudioIn, QuietBoost, QUIET_ASR, vad_block  # numpy: loaded with the rest, not at import
    conn_in = AudioIn("streaming client")
    endpoint_ms, _, _, max_utterance_s = endpointing(src)
    boost = QuietBoost()   # the VAD's copy of a quiet talker, brought up (audio_in.py)

    async def flush(words, force=False):
        nonlocal translated_n
        pending = words[translated_n:]
        if not pending:
            return
        clause_end = 0
        for i, w in enumerate(pending):
            if w and w[-1] in ".,;:!?":
                clause_end = i + 1
        if not clause_end and (force or len(pending) >= 12):
            clause_end = len(pending)
        if not clause_end:
            return
        segment = " ".join(pending[:clause_end])
        translated_n += clause_end
        context = memory.before(src)
        translated = await loop.run_in_executor(None, pipe.translate, segment, lang, src, context, edition)
        memory.after(src, segment, {lang: translated})
        await ws.send(json.dumps({"type": "transcript", "delta": translated + " "}))
        await speak_to(ws, pipe, translated, lang, edition)

    async for msg in ws:
        if not meter.take(len(msg)):
            await too_fast(ws, "streaming client")
            return
        if not isinstance(msg, bytes):
            continue
        # Fixed 96 ms blocks, whatever size of message the client sends (audio_in.py, issue #13).
        for pcm16 in conn_in.feed(msg):
            loud = boost(pcm16)
            buf = np.concatenate([buf, loud if QUIET_ASR else pcm16])
            chunk_ms = len(pcm16) / VAD_RATE * 1000
            prob = vad_block(vad, loud)
            quiet_ms = 0.0 if prob > 0.5 else quiet_ms + chunk_ms
            since_asr_ms += chunk_ms

            # The turn ends on a pause, or at MAX_UTTERANCE_S whatever the speaker
            # does (the buffer is re-transcribed every pass, so it must stay short).
            forced = len(buf) / VAD_RATE >= max_utterance_s
            if forced or (quiet_ms >= endpoint_ms and len(buf) >= VAD_RATE // 2):
                # Turn over: everything not yet committed is now final.
                cut = quietest_cut(buf) if forced else len(buf)
                text = await loop.run_in_executor(None, pipe.transcribe, buf[:cut], src)
                words = text.split()
                if words:
                    await ws.send(json.dumps({"type": "inputTranscript", "text": text}))
                    await flush(words, force=True)
                buf = buf[cut:]
                last_pass, committed_n, translated_n, quiet_ms = "", 0, 0, 0.0
                continue

            if since_asr_ms < 1000 or len(buf) < VAD_RATE:
                continue
            since_asr_ms = 0.0
            text = await loop.run_in_executor(None, pipe.transcribe, buf, src)
            agreed = common_prefix_words(last_pass, text)
            last_pass = text
            if len(agreed) > committed_n:
                committed_n = len(agreed)
                await flush(agreed)


class BadRequest(ValueError):
    """A query parameter this server does not accept; the message is for the client."""


def _code(value):
    """A language code as the engines name it: "pt-BR" -> "pt"."""
    return value.strip().replace("_", "-").split("-")[0].lower()


def parse_request(q, pipe):
    """The connection's parameters, validated against what this server serves.

    An unknown language used to go straight to the engines (each unknown ?lang
    one more translation and voice per utterance, or an exception deep in the
    pipeline), and every value reached the log verbatim. Now anything
    unexpected is refused up front with a BadRequest naming the parameter."""
    def arg(name, default=""):
        return q.get(name, [default])[0]

    served = list(getattr(pipe, "langs", None) or [])
    srcs = list(getattr(pipe, "srcs", None) or ["en"])
    known = set(served) | set(srcs) | {"en"}

    lang = arg("lang", "es")
    if served and lang not in served:
        if _code(lang) not in served:
            raise BadRequest(f"lang {clean(lang, 24)!r} is not served here; this server translates into: "
                             + ", ".join(served))
        lang = _code(lang)

    src = arg("src", "en")
    if src not in ("auto", "en") and src not in srcs:
        if _code(src) not in srcs and _code(src) != "en":
            raise BadRequest(f"src {clean(src, 24)!r} is not a source this server takes; use auto or one of: "
                             + ", ".join(["en"] + [c for c in srcs if c != "en"]))
        src = _code(src)

    route = arg("route")
    if route not in ("", "to"):
        raise BadRequest(f"route {clean(route, 24)!r} is not understood; the only value is 'to'")

    cands = None
    raw = [c for c in arg("cands").split(",") if c.strip()]
    if raw:
        if len(raw) > MAX_CANDS:
            raise BadRequest(f"cands names {len(raw)} languages; at most {MAX_CANDS}")
        cands = {_code(c) for c in raw}
        unknown = sorted(c for c in cands if c not in known)
        if unknown:
            raise BadRequest("cands has languages this server does not know: "
                             + ", ".join(clean(c, 12) for c in unknown[:MAX_CANDS]))

    room = arg("room") or None
    if room is not None and not ROOM_ID_RE.fullmatch(room):
        raise BadRequest("room must be 1-64 letters, digits, '-' or '_'")

    # Simultaneous mode's commit policy (?stream=1 rooms): "clause" (the default) or "agree" (agree.py).
    policy = arg("policy") or STREAM_POLICY
    if policy not in ("clause", "agree"):
        raise BadRequest(f"policy {clean(policy, 24)!r} is not understood; use clause or agree")

    flag = lambda name: arg(name, "0") not in ("0", "", "false")  # noqa: E731
    return {"lang": lang, "src": src, "route_to": route == "to", "cands": cands, "room": room,
            "stream": flag("stream"), "priority": flag("priority"), "context": flag("context"),
            "policy": policy}


async def handle(ws, pipe, sub="open", edition=None):
    """One connection, from the subject guarded() admitted, served in `edition`
    (connection_edition: whose translators and voices it gets)."""
    import numpy as np
    from urllib.parse import urlparse, parse_qs

    url = urlparse(ws.request.path)
    q = parse_qs(url.query)
    # Who may connect, and how many at once: guarded() (stack_auth.py).
    try:
        req = parse_request(q, pipe)
    except BadRequest as e:
        print(f"[stack] {clean(sub, 24)}: refused request: {clean(e, 200)}", flush=True)
        await ws.send(json.dumps({"type": "error", "detail": str(e)}))
        await ws.close(code=CLOSE_BAD_REQUEST, reason="bad request")
        return
    lang, src = req["lang"], req["src"]
    # The app always asks for src=auto (the hybrid: whoever speaks, route
    # them). A sermon-only deployment without --xeng cannot honour that —
    # DOWNGRADE to English rather than refuse, so one client works against
    # every server shape and the hello says what it actually got.
    if src == "auto" and (not pipe.lid or pipe.asr_multi is None):
        print("[stack] src=auto requested but LID/--xeng not loaded — serving src=en")
        src = "en"
    elif src != "en" and pipe.asr_multi is None:
        await ws.send(json.dumps({"type": "error", "detail": "server not started with --xeng"}))
        await ws.close()
        return
    hello = {"type": "hello", "lang": lang, "src": src, "rate": RATE,
             "mode": "streaming" if getattr(pipe, "streaming", False) else "utterance",
             "edition": edition or pipe.default_edition}
    # ?context=1: the previous pieces go to the translator as context
    # (translation_context.py). Echoed only when asked, so the hello a client
    # without it sees is the one it always saw.
    if req["context"]:
        hello["context"] = True
    await ws.send(json.dumps(hello))
    print(f"[stack] client: {src} -> {lang}" + (" (context)" if req["context"] else ""))

    if req["room"]:
        # Shared-pipeline mode (see Room). src is fixed per room. The room is
        # this subject's: another token's ?room=main is a different room.
        await handle_room(ws, pipe, (sub, req["room"], edition), lang, src, req["stream"], req["priority"],
                          req["context"], req["policy"])
        return

    if getattr(pipe, "streaming", False):
        # Streaming needs a fixed source: LocalAgreement commits words from a
        # single ASR stream, and swapping models mid-utterance would reset the
        # agreement every pass. auto stays an utterance-mode feature.
        if src == "auto":
            await ws.send(json.dumps({"type": "error", "detail": "--streaming needs a fixed ?src"}))
            await ws.close()
            return
        await handle_streaming(ws, pipe, src, lang, edition, TranslationMemory(req["context"]))
        return

    # route=to (Lithos Talk): translate whatever is spoken INTO `lang`, and skip
    # speech already in `lang`. A two-way conversation runs one connection per
    # direction on the same microphone, so each must ignore its own language
    # rather than send it on to English (the PA routing below).
    route_to = req["route_to"]
    # ?cands=en,es: the only languages this conversation uses (Lithos Talk). Auto
    # detection chooses among these instead of every --srcs language.
    cands = req["cands"]
    # The previous pieces for the translator, if asked for (?context=1). One
    # memory per connection: it forgets on a route change and after 30 s idle.
    memory = TranslationMemory(req["context"])
    buf = np.zeros(0, dtype=np.float32)
    quiet_ms = 0.0
    speech_seen = False
    vad = pipe.new_vad()
    meter = AudioMeter()
    from audio_in import AudioIn, QuietBoost, QUIET_ASR, vad_block  # numpy: loaded with the rest, not at import
    conn_in = AudioIn(clean(sub, 24))
    endpoint_ms, _, _, max_utterance_s = endpointing(src)
    min_ms = min_speech_ms(src)
    boost = QuietBoost()   # the VAD's copy of a quiet talker, brought up (audio_in.py)

    async for msg in ws:
        if not meter.take(len(msg)):
            await too_fast(ws, clean(sub, 24))
            return
        if not isinstance(msg, bytes):
            continue
        # Fixed 96 ms blocks, whatever size of message the client sends (audio_in.py, issue #13).
        for pcm16 in conn_in.feed(msg):
            loud = boost(pcm16)
            buf = np.concatenate([buf, loud if QUIET_ASR else pcm16])
            # Endpoint on Silero: an utterance ends after endpoint_ms without speech.
            chunk_ms = len(pcm16) / VAD_RATE * 1000
            prob = vad_block(vad, loud)
            if prob > 0.5:
                speech_seen = True
                quiet_ms = 0.0
            else:
                quiet_ms += chunk_ms
            if not speech_seen:
                buf = buf[-(VAD_RATE // 2):]  # idle mic: pre-roll only (see Room)
                continue
            # No pause for MAX_UTTERANCE_S: cut anyway, as rooms do. Without this
            # a client that never paused grew one buffer without limit.
            buf_s = len(buf) / VAD_RATE
            forced = buf_s >= max_utterance_s
            if not forced and (quiet_ms < endpoint_ms or len(buf) < VAD_RATE):  # not ended, or under 1 s of audio
                continue
            if not forced and short_turn(buf_s, quiet_ms, endpoint_ms, min_ms):
                continue   # a short piece: wait for the rest of its sentence

            if forced:
                cut, how = await forced_cut(pipe, buf, src, "en", cands)
                print(f"[stack] solo: forced cut at {cut / VAD_RATE:.1f}s of {buf_s:.1f}s ({how})", flush=True)
                utterance, buf, quiet_ms = buf[:cut], buf[cut:], 0.0   # still talking: speech_seen stays
            else:
                utterance, buf, quiet_ms = buf, np.zeros(0, dtype=np.float32), 0.0
                speech_seen = False
            loop = asyncio.get_running_loop()

            # Auto-route per utterance: English in -> the requested language out;
            # anything else in -> ENGLISH out. That is the app's PA behaviour
            # (roomMicOrOtherLang) expressed as routing.
            this_src, this_lang = src, lang
            if src == "auto":
                detected = await loop.run_in_executor(None, pipe.identify, utterance, cands)
                this_src = detected or "en"
                if route_to:
                    await ws.send(json.dumps({"type": "route", "src": this_src, "lang": lang}))
                    if this_src == lang:
                        continue  # already in this direction's language: the other direction's job
                else:
                    this_lang = lang if this_src == "en" else "en"
                    await ws.send(json.dumps({"type": "route", "src": this_src, "lang": this_lang}))

            text = await loop.run_in_executor(None, pipe.transcribe, utterance, this_src)
            if not text:
                continue
            await ws.send(json.dumps({"type": "inputTranscript", "text": text}))
            context = memory.before(this_src)
            translated = await loop.run_in_executor(None, pipe.translate, text, this_lang, this_src, context,
                                                        edition)
            memory.after(this_src, text, {this_lang: translated})
            await ws.send(json.dumps({"type": "transcript", "delta": translated}))
            print(f"[stack] solo {this_src}->{this_lang}: {len(text)} chars heard, {len(translated)} out", flush=True)
            await speak_to(ws, pipe, translated, this_lang, edition)

