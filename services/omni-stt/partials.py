"""Partial text while an utterance is still being spoken (STT_PARTIALS=1; off
by default: it costs the GPU about 3-4x per utterance).

omni-stt sends text only when a piece ends: the listener waits the whole piece
plus its recognition. With partials on, the connection re-transcribes the
growing buffer about every STT_PARTIAL_MS (1500) of new audio and sends

    {"type":"partial", "text": <the whole current hypothesis>, ...}
    {"type":"stable",  "text": <the committed prefix>, "delta": <its new words>, ...}

and then, when the piece ends, the usual "language" and "inputTranscript"
messages, whose text is exactly what it would be without partials (the final
decode is the same call on the same audio; partial passes only read a copy of
the buffer). Design: docs/dev/omni-stt-partials.md.

Three parts, none of which knows the server:

- PartialTracker: the stability rule. A word prefix that two consecutive
  passes agree on is committed; the committed prefix only grows (never a
  retraction); once a hypothesis no longer starts with the committed prefix,
  nothing more is committed until the piece's final text replaces it all.
- PassScheduler: when a pass is due (audio since the last pass, time since
  the last pass, one pass in flight at a time, skipped while the GPU queue
  has work waiting: finals first).
- PartialStream: one connection's passes, driven from the streaming loop
  (after_feed / piece_ended / close), submitting to the Batcher like a final.
"""
import asyncio
import os
import time

RATE = 16000
ENABLED = os.environ.get("STT_PARTIALS", "0") == "1"
INTERVAL_MS = max(250, int(os.environ.get("STT_PARTIAL_MS", "1500")))


class PartialTracker:
    """feed(hypothesis) -> (partial, stable_delta or None).

    partial: the hypothesis as given (stripped). stable_delta: the words
    committed by this pass (a string), or None when nothing new became
    stable. The commit rule, by whole whitespace-separated words:

    - the leading words the previous pass and this one agree on are stable;
    - the committed prefix never shrinks, and it is extended only while the
      current hypothesis still starts with it (a hypothesis that has
      rewritten a committed word commits nothing more: the final text, which
      replaces every partial, sorts that out);
    - passes under different keys (the language ID's guess for the pass)
      never agree with each other.

    For scripts written without spaces a "word" is a whole run of text, so
    commits are rarer there; see the design doc."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.prev = None            # the previous pass's words
        self.prev_key = None
        self.stable_words = []
        self.passes = 0

    @property
    def stable(self):
        return " ".join(self.stable_words)

    def feed(self, hypothesis, key=None):
        text = (hypothesis or "").strip()
        words = text.split()
        self.passes += 1
        delta = None
        if self.prev is not None and key == self.prev_key:
            common = 0
            for a, b in zip(self.prev, words):
                if a != b:
                    break
                common += 1
            n = len(self.stable_words)
            if common > n and words[:n] == self.stable_words:
                delta = " ".join(words[n:common])
                self.stable_words = words[:common]
        self.prev, self.prev_key = words, key
        return text, delta


class PassScheduler:
    """Whether a partial pass is due now.

    due(audio_ms, busy=False): the buffer holds interval_ms more audio than
    at the last pass, at least min_gap_ms of wall time have gone by since it
    started, no pass is in flight, and (busy) nothing is waiting for the GPU.
    A skipped pass is not forgotten: due() is asked again on the next block
    and says yes as soon as the reason has gone. started(audio_ms) /
    finished() bracket a pass; reset() starts a new piece."""

    def __init__(self, interval_ms=None, min_gap_ms=0, clock=None):
        self.interval_ms = INTERVAL_MS if interval_ms is None else max(1, int(interval_ms))
        self.min_gap_ms = max(0, int(min_gap_ms))
        self.clock = clock or (lambda: time.monotonic() * 1000)
        self.reset()

    def reset(self):
        self.last_audio_ms = 0
        self.last_at = None
        self.inflight = False

    def due(self, audio_ms, busy=False):
        if self.inflight or busy:
            return False
        if audio_ms - self.last_audio_ms < self.interval_ms:
            return False
        if self.last_at is not None and self.clock() - self.last_at < self.min_gap_ms:
            return False
        return True

    def started(self, audio_ms):
        self.inflight = True
        self.last_audio_ms = audio_ms
        self.last_at = self.clock()

    def finished(self):
        self.inflight = False


def queue_busy(batcher):
    """Whether the Batcher has utterances waiting (a final decode or another
    pass): a partial pass then waits its turn rather than lengthening the
    batch a final is in. Read without the lock: a stale answer only moves a
    pass by one block."""
    queues = getattr(batcher, "queues", None)
    if not queues:
        return False
    return any(len(q) for q in queues.values())


class PartialStream:
    """One /listen connection's partial passes.

    submit(kind, pcm, arg) is the Batcher's (an awaitable); send(dict) sends
    a message. after_feed(seg, utts) is called after every Segmenter.feed
    with what it returned; piece_ended() when the piece ends without it
    (a flush); close() when the connection ends."""

    def __init__(self, langs, transcribe, submit, send, interval_ms=None, busy=None,
                 who="", log=print, rate=RATE, min_gap_ms=0, clock=None):
        self.langs = list(langs)
        self.transcribe = set(transcribe)
        self.submit = submit
        self.send = send
        self.busy = busy or (lambda: False)
        self.who = who
        self.log = log
        self.rate = rate
        self.tracker = PartialTracker()
        self.scheduler = PassScheduler(interval_ms, min_gap_ms, clock)
        self.gen = 0                # bumped when a piece ends: late results are dropped
        self.task = None
        self.lang = None            # the language the current piece's passes use
        self.stats = {"passes": 0, "audio_s": 0.0, "sent": 0, "dropped": 0}

    def after_feed(self, seg, utts):
        """Called with every Segmenter.feed result. A finished utterance ends
        the piece (its final follows by the usual path); then, if speech is in
        the buffer and a pass is due, one is started over a copy of it."""
        if utts:
            self.piece_ended()
        if not getattr(seg, "speech_seen", False) or not len(seg.buf):
            return
        audio_ms = len(seg.buf) * 1000 / self.rate
        if not self.scheduler.due(audio_ms, self.busy()):
            return
        pcm = seg.buf.copy()
        start_ms = int(seg.buf_start * 1000 / self.rate)
        end_ms = int((seg.buf_start + len(pcm)) * 1000 / self.rate)
        self.scheduler.started(audio_ms)
        self.task = asyncio.get_running_loop().create_task(self._pass(pcm, start_ms, end_ms, self.gen))

    def piece_ended(self):
        """The piece's final is on its way: stop its passes. A pass still
        waiting for the GPU is cancelled, and the Batcher drops it unrun."""
        self.gen += 1
        self.tracker.reset()
        self.scheduler.reset()
        self.lang = None
        if self.task is not None and not self.task.done():
            self.task.cancel()
            self.stats["dropped"] += 1
        self.task = None

    def close(self):
        self.piece_ended()
        if self.stats["passes"]:
            s = self.stats
            self.log(f"[stt] {self.who}: {s['passes']} partial passes over {s['audio_s']:.0f}s of audio, "
                     f"{s['sent']} messages, {s['dropped']} passes dropped", flush=True)

    async def _pass(self, pcm, start_ms, end_ms, gen):
        try:
            if len(self.langs) == 1:
                lang, conf = self.langs[0], 1.0
            else:
                lang, conf = await self.submit("lid", pcm, self.langs)
            if gen != self.gen or lang not in self.transcribe:
                return
            text = await self.submit("asr", pcm, lang)
            self.stats["passes"] += 1
            self.stats["audio_s"] += len(pcm) / self.rate
            if gen != self.gen or not text:
                return
            partial, delta = self.tracker.feed(text, key=lang)
            self.lang = lang
            span = {"lang": lang, "confidence": round(conf, 3), "start_ms": start_ms, "end_ms": end_ms}
            await self.send({"type": "partial", "text": partial, **span})
            self.stats["sent"] += 1
            if delta:
                await self.send({"type": "stable", "text": self.tracker.stable, "delta": delta, **span})
                self.stats["sent"] += 1
        except asyncio.CancelledError:
            pass
        except Exception as e:  # a failed pass is only a missing partial
            self.log(f"[stt] {self.who}: partial pass failed: {type(e).__name__}", flush=True)
        finally:
            if gen == self.gen:         # (a pass of an ended piece has already been reset)
                self.scheduler.finished()
