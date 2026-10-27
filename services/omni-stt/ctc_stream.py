"""A streaming text track for Khmer and Lao: Meta's Omnilingual CTC 3B, decoded
in chunks while the speaker talks (STT_CTC_STREAM=1 loads it; off by default;
a connection opts in with ?stream=ctc).

The LLM cards (300M, 7B) cannot stream: their decoder prefills a whole
utterance and then writes its text, so partials.py can only decode the growing
buffer again. A CTC model gives one label per 20 ms frame of audio, so the
frames that are old enough can be committed once and never decoded again:

    every CHUNK (STT_CTC_CHUNK_MS, 500) of new audio, one pass over
        [commit edge - LEFT (STT_CTC_LEFT_MS, 8000), now]
    the frames up to now - LOOKAHEAD (1 or 2 s; ?lookahead=, STT_CTC_LOOKAHEAD_MS)
        are committed: their text goes out once, as "committed", and is never revised
    the frames after that are the revisable tail, sent as "partial"
    when the segmenter ends a turn (a pause), one more pass commits everything

so a client sees text about half a second after speech starts and committed
text LOOKAHEAD later. The look-ahead is the right-context the encoder needs:
a frame decoded with less than ~1 s of audio after it is often wrong.

The script mask: before the argmax, every output token whose text has a letter
or mark outside the language's script (Basic Latin letters, digits, spaces and
punctuation stay allowed: names and numbers) is ruled out, so a chunk the
model is unsure of cannot drift into another script.

The per-utterance finals are unchanged: the server's existing decoder (the 7B
for Khmer and Lao) still sends each piece's "inputTranscript", which is the
text of record. Design and measurements: eval/2026-10-ctc-stream/README.md.

Messages, connection-wide (not per piece: committed text is one append-only
stream for the connection, so a client can cut sentences from it):

    {"type":"partial","track":"ctc","text":<the tail after the committed text>,
     "lang":"km","start_ms":<the commit edge>,"end_ms":<audio heard>}
    {"type":"committed","track":"ctc","text":<the newly committed text>,
     "lang":"km","start_ms":<previous commit edge>,"end_ms":<new commit edge>,
     "end":<true when this commit closes a turn>}

Four parts: Committer (the commit rule over frame labels; no model),
script_mask (the mask, from a tokenizer's pieces), CTCModel (the GPU side, with
its own worker thread and CUDA stream, batching every connection's passes) and
CTCStream (one connection's schedule and messages).
"""
import asyncio
import collections
import os
import threading
import time
import unicodedata

RATE = 16000
FRAME = 320                         # 20 ms: one CTC output frame
ENABLED = os.environ.get("STT_CTC_STREAM", "0") == "1"
CARD = os.environ.get("STT_CTC_CARD", "omniASR_CTC_3B")
LANGS = tuple(c.strip() for c in os.environ.get("STT_CTC_LANGS", "km,lo").split(",") if c.strip())
CHUNK_MS = min(1000, max(250, int(os.environ.get("STT_CTC_CHUNK_MS", "500"))))
LEFT_MS = max(1000, int(os.environ.get("STT_CTC_LEFT_MS", "8000")))
LOOKAHEADS_S = (1, 2)
LOOKAHEAD_MS = int(os.environ.get("STT_CTC_LOOKAHEAD_MS", "2000"))
BATCH_MAX = max(1, int(os.environ.get("STT_CTC_BATCH_MAX", "16")))
# A trace of noise (about -80 dBFS) under every window: beside exact digital
# silence (a muted mic, a client's zero padding) the 3B's frames on quiet
# speech went wrong (a quiet FLEURS Lao sentence after 0.5 s of zeros lost
# most of its letters); a real microphone's own noise floor is far above it.
DITHER = float(os.environ.get("STT_CTC_DITHER", "1e-4"))
# Speech heard this recently (by the VAD) keeps a pass every CHUNK; while the
# VAD hears none, a pass every QUIET_MS. Audio is never skipped undecoded: on
# quiet distant speech Silero passes 0.5 on as little as half of the words
# (FLEURS Lao, 2026-10-27), and skipping what it missed lost them.
SPEECH_HANG_MS = 400
QUIET_MS = max(CHUNK_MS, int(os.environ.get("STT_CTC_QUIET_MS", "2000")))

# Unicode blocks of each language's script (main block, extra block).
SCRIPTS = {
    "km": ((0x1780, 0x17FF), (0x19E0, 0x19FF)),     # Khmer, Khmer Symbols
    "lo": ((0x0E80, 0x0EFF),),                      # Lao
}


class BadParam(ValueError):
    pass


def parse_stream(query, langs, available):
    """(?stream=, ?lookahead=, the connection's langs, whether the server has
    the track) -> None (no track: not asked for) or a dict: {"track": "ctc",
    "lang": ..., "lookahead_ms": ...} when it runs, {"track": None, "reason":
    ...} when it was asked for and cannot. BadParam on a malformed value."""
    want = (query.get("stream") or [""])[0].strip().lower()
    raw_la = (query.get("lookahead") or [""])[0].strip()
    if not want:
        if raw_la:
            raise BadParam("lookahead= needs stream=ctc")
        return None
    if want != "ctc":
        raise BadParam("stream= must be ctc")
    if raw_la:
        try:
            la = float(raw_la)
        except ValueError:
            la = None
        if la not in LOOKAHEADS_S:
            raise BadParam(f"lookahead= must be one of {', '.join(str(x) for x in LOOKAHEADS_S)} (seconds)")
        lookahead_ms = int(la * 1000)
    else:
        lookahead_ms = LOOKAHEAD_MS
    if not available:
        return {"track": None, "reason": "this server has no streaming track (STT_CTC_STREAM)"}
    if len(langs) != 1 or langs[0] not in LANGS:
        return {"track": None, "reason": f"the streaming track serves one-language rooms in {', '.join(LANGS)}"}
    return {"track": "ctc", "lang": langs[0], "lookahead_ms": lookahead_ms}


def hello_field(cfg):
    """What the hello says about the track (only when the client asked)."""
    if cfg["track"] is None:
        return {"track": None, "reason": cfg["reason"]}
    return {"track": "ctc", "lookahead_ms": cfg["lookahead_ms"], "chunk_ms": CHUNK_MS, "left_ms": LEFT_MS}


def collapse(labels, last, blank=0):
    """CTC's rule: drop repeats and blanks. labels after the label `last`
    (a repeat across the boundary is the same token). -> (ids, new last)."""
    out = []
    for x in labels:
        x = int(x)
        if x != last and x != blank:
            out.append(x)
        last = x
    return out, last


class Committer:
    """The commit rule over one connection's frame labels; no model, no clock.

    Positions are stream sample indices (16 kHz). window(now) gives the audio
    a pass decodes; apply(labels, start, now, final) takes that pass's labels
    and returns (new committed ids, tail ids). The commit edge stays on the
    frame grid of the pass that set it, and a pass's window starts on that
    grid, so a frame is never committed twice or skipped.

    joins(prev_id, next_id) -> True when two tokens must not be split (a
    vowel sign or other combining mark after its base; anything after a
    Khmer coeng): the edge then moves back to where prev's frames start, so
    committed text never ends inside a grapheme cluster."""

    def __init__(self, lookahead_ms, left_ms=LEFT_MS, blank=0, joins=None):
        self.lookahead = int(lookahead_ms * RATE / 1000)
        self.left = int(left_ms * RATE / 1000)
        self.blank = blank
        self.joins = joins
        self.edge = 0                # stream sample index: everything before it is committed
        self.last = blank            # the label of the last committed frame
        self.ids = []                # the last few committed ids (context for detokenizing)

    def window(self, now):
        """The pass's audio: (start, now), start on the edge's frame grid."""
        back = min(self.left, self.edge) // FRAME * FRAME
        return self.edge - back, now

    def apply(self, labels, start, now, final=False):
        k0 = (self.edge - start) // FRAME
        if final:
            k1 = len(labels)
        else:
            k1 = min(len(labels), max(0, (now - self.lookahead - start)) // FRAME)
        k1 = max(k0, k1)
        if not final and self.joins is not None:
            k1 = self._unsplit(labels, k0, k1)
        new, self.last = collapse(labels[k0:k1], self.last, self.blank)
        if final:
            # Everything heard is committed; the next pass starts at `now`
            # (a frame past the labels the encoder gave is silence or a fraction).
            self.edge = max(self.edge, now)
            self.last = self.blank
        else:
            self.edge = start + k1 * FRAME
        tail, _ = collapse(labels[k1:], self.last, self.blank) if not final else ([], None)
        self.ids = (self.ids + new)[-8:]
        return new, tail

    def _unsplit(self, labels, k0, k1):
        """k1, moved back while the last token before it and the first after
        it join. A token belongs where its run of frames starts."""
        toks, last = [], self.last          # (id, first frame), as collapse sees them
        for k in range(k0, len(labels)):
            x = int(labels[k])
            if x != last and x != self.blank:
                toks.append((x, k))
            last = x
        i = sum(1 for _, k in toks if k < k1)     # toks[:i] would be committed
        moved = False
        while 0 < i < len(toks) and self.joins(toks[i - 1][0], toks[i][0]):
            i -= 1
            moved = True
        return toks[i][1] if moved else k1


def delta_text(detok, context, ids):
    """The text `ids` add after `context` (ids): SentencePiece drops the space
    of a leading word marker, so decode them together and take the difference."""
    if not ids:
        return ""
    if not context:
        return detok(ids)
    before = detok(context)
    both = detok(list(context) + list(ids))
    if both.startswith(before):
        return both[len(before):]
    return (" " if both[:1] != before[:1] else "") + detok(ids)


def allowed_char(ch, blocks):
    if unicodedata.category(ch)[0] not in "LM":
        return True                              # digits, spaces, punctuation, symbols
    if ch.isascii():
        return True                              # Basic Latin letters: names
    return any(a <= ord(ch) <= b for a, b in blocks)


def script_mask(pieces, lang):
    """[the text of each output token] -> [bool: allowed for lang]. A token is
    ruled out when any of its letters or marks is outside lang's script and
    Basic Latin."""
    blocks = SCRIPTS[lang]
    return [all(allowed_char(ch, blocks) for ch in (p or "")) for p in pieces]


COENG = "\u17d2"                    # Khmer: the next consonant is written below this one


def joiner(pieces):
    """[the text of each output token] -> joins(prev_id, next_id): whether a
    commit may not fall between the two (Committer). A token that starts with
    a combining mark (a vowel sign, a tone mark) belongs to the one before it;
    so does any token after one that ends with the Khmer coeng."""
    attach = {i for i, p in enumerate(pieces) if p and unicodedata.category(p[0]).startswith("M")}
    trail = {i for i, p in enumerate(pieces) if p and p.endswith(COENG)}
    return lambda prev, nxt: nxt in attach or prev in trail


# ---------------------------------------------------------------- the model (GPU)

def _resolve(fut, result, err):
    if fut.done():
        return
    if err is not None:
        fut.set_exception(err)
    else:
        fut.set_result(result)


class CTCModel:
    """The CTC card, one worker thread for every connection's passes.

    submit(pcm, lang) -> awaitable label array. The worker takes every pass
    waiting (up to STT_CTC_BATCH_MAX), runs them through the encoder in one
    padded batch on its own CUDA stream (so a pass need not wait for the LLM
    decoder's batch on the Batcher's thread), adds each row's script mask and
    takes the argmax. A pass whose future was given up on is dropped unrun."""

    def __init__(self, device, card=CARD, langs=LANGS, load=True, pipeline=None):
        self.device = device
        self.card = card
        self.langs = tuple(langs)
        self.cond = threading.Condition()
        self.queue = collections.deque()
        self.stats = {"batches": 0, "items": 0, "max": 0, "busy_s": 0.0, "audio_s": 0.0}
        self.load_s = None
        self.memory_gb = None
        if load:
            self._load(pipeline)
        self.thread = threading.Thread(target=self._run, name="ctc-worker", daemon=True)
        self.thread.start()

    def _load(self, pipeline=None):
        """pipeline: the recogniser's own, when it is this card (a service
        whose per-piece card is the CTC card itself keeps one copy)."""
        import torch
        t0 = time.time()
        before = torch.cuda.memory_allocated() if str(self.device).startswith("cuda") else 0
        if pipeline is not None:
            self.pipe = pipeline
        else:
            from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline
            kw = {"device": self.device}
            if str(self.device).startswith("cpu"):
                kw["dtype"] = torch.float32
            self.pipe = ASRInferencePipeline(model_card=self.card, **kw)
        self.dtype = next(self.pipe.model.parameters()).dtype
        vocab = self.pipe.tokenizer.vocab_info.size
        pieces = [self.detok([i]) if i != 0 else "" for i in range(vocab)]
        self.joins = joiner(pieces)
        self.masks = {}
        for lang in self.langs:
            ok = torch.tensor(script_mask(pieces, lang), device=self.device)
            ok[0] = True                                   # the blank
            self.masks[lang] = torch.where(ok, 0.0, float("-inf")).to(self.device)
        self.stream = torch.cuda.Stream() if str(self.device).startswith("cuda") else None
        if str(self.device).startswith("cuda"):
            torch.cuda.synchronize()
            self.memory_gb = round((torch.cuda.memory_allocated() - before) / 1e9, 2)
        self.load_s = round(time.time() - t0, 1)
        print(f"[stt] {self.card} (streaming track, {','.join(self.langs)}"
              f"{', shares the recogniser' if pipeline is not None else ''}) loaded in {self.load_s}s"
              + (f", {self.memory_gb} GB" if self.memory_gb is not None else ""), flush=True)

    def detok(self, ids):
        import torch
        if not ids:
            return ""
        return self.pipe.token_decoder(torch.tensor(list(ids), dtype=torch.int64))

    def labels_batch(self, items):
        """[(pcm16k float32, lang), ...] -> [label array per item]."""
        import torch
        from fairseq2.nn import BatchLayout
        with torch.inference_mode():
            lens = [len(p) for p, _ in items]
            x = torch.zeros(len(items), max(lens), device=self.device)
            gen = torch.Generator(device=self.device).manual_seed(0) if DITHER > 0 else None
            for i, (pcm, _) in enumerate(items):
                w = torch.as_tensor(pcm, dtype=torch.float32, device=self.device)
                if gen is not None:
                    w = w + DITHER * torch.randn(w.shape, generator=gen, device=self.device)
                x[i, :len(pcm)] = torch.nn.functional.layer_norm(w, w.shape)   # the pipeline's normalize_audio
            x = x.to(self.dtype)
            layout = BatchLayout(x.shape, seq_lens=lens, device=x.device)
            logits, out_layout = self.pipe.model(x, layout)
            out = []
            for i, (_, lang) in enumerate(items):
                n = int(out_layout.seq_lens[i])
                lg = logits[i, :n].float() + self.masks[lang]
                out.append(lg.argmax(-1))
            return [o.cpu().numpy() for o in out]

    def transcribe_batch(self, items):
        """[(pcm16k, lang), ...] -> [text, ...]: whole pieces, greedy and
        masked like the passes. The finals of a service whose recogniser is
        this card: unmasked, the 3B wrote short Lao pieces in Thai script."""
        texts = []
        for labels in self._call(items):
            ids, _ = collapse(labels, -1)
            texts.append(self.detok(ids).strip())
        return texts

    def warm(self):
        import numpy as np
        rng = np.random.default_rng(0)
        noise = (rng.standard_normal(RATE * 9) * 0.01).astype(np.float32)
        for lang in self.langs:
            self._call([(noise, lang)])
            self._call([(noise[: RATE * 2], lang), (noise, lang)])

    def _call(self, items):
        if self.stream is None:
            return self.labels_batch(items)
        import torch
        with torch.cuda.stream(self.stream):
            out = self.labels_batch(items)
        self.stream.synchronize()
        return out

    def submit(self, pcm, lang):
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        with self.cond:
            self.queue.append((pcm, lang, loop, fut))
            self.cond.notify()
        return fut

    def _run(self):
        while True:
            with self.cond:
                while not self.queue:
                    self.cond.wait()
                live = [job for job in self.queue if not job[3].done()]
                jobs = live[:BATCH_MAX]
                self.queue.clear()
                self.queue.extend(live[BATCH_MAX:])
            if not jobs:
                continue
            t0 = time.monotonic()
            try:
                results = self._call([(p, lang) for p, lang, _, _ in jobs])
                outcomes = [(r, None) for r in results]
            except Exception as e:  # noqa: BLE001  a failed batch fails its passes: they are only partials
                outcomes = [(None, RuntimeError(f"streaming pass failed: {type(e).__name__}"))] * len(jobs)
            st = self.stats
            st["batches"] += 1
            st["items"] += len(jobs)
            st["max"] = max(st["max"], len(jobs))
            st["busy_s"] += time.monotonic() - t0
            st["audio_s"] += sum(len(j[0]) for j in jobs) / RATE
            for (_, _, loop, fut), (res, err) in zip(jobs, outcomes):
                try:
                    loop.call_soon_threadsafe(_resolve, fut, res, err)
                except RuntimeError:
                    pass


# ---------------------------------------------------------------- one connection

class CTCStream:
    """One /listen connection's streaming track.

    feed(block, prob) with every 16 kHz block the Segmenter gets (prob: the
    block's highest VAD probability); turn_ended() when the Segmenter ends a
    turn on a pause (not a forced cut mid-speech); close() at the end.
    submit(pcm, lang) is CTCModel.submit; send(dict) sends a message; detok
    turns ids into text. One pass is in flight at a time: a slow GPU makes the
    passes rarer and longer, never queued up."""

    def __init__(self, lang, lookahead_ms, submit, send, detok, blank=0, chunk_ms=CHUNK_MS,
                 left_ms=LEFT_MS, who="", log=print, clock=None, joins=None):
        self.lang = lang
        self.submit = submit
        self.send = send
        self.detok = detok
        self.who = who
        self.log = log
        self.clock = clock or time.monotonic
        self.committer = Committer(lookahead_ms, left_ms, blank, joins)
        self.chunk = int(chunk_ms * RATE / 1000)
        self.hang = int(SPEECH_HANG_MS * RATE / 1000)
        self.quiet = max(self.chunk, int(QUIET_MS * RATE / 1000))
        self.audio = []              # (stream start, block) since the window's earliest start
        self.total = 0               # samples fed
        self.last_speech = None      # stream sample index where the latest speech block ended
        self.last_pass = 0           # `now` of the latest pass
        self.task = None
        self.flush_wanted = False
        self.shown_tail = ""
        self.stats = {"passes": 0, "audio_s": 0.0, "committed": 0, "partials": 0,
                      "first_partial_ms": None, "first_commit_ms": None}
        self._speech_at = None       # wall clock of the first speech (for the stats)

    def feed(self, block, prob):
        start = self.total
        self.total += len(block)
        self.audio.append((start, block))
        if prob > 0.5:
            self.last_speech = self.total
            if self._speech_at is None:
                self._speech_at = self.clock()
        self._trim()
        self._maybe_pass()

    def turn_ended(self):
        """The speaker paused: commit everything heard, by one more pass."""
        if self.last_speech is not None and self.last_speech > self.committer.edge:
            self.flush_wanted = True
            self._maybe_pass()

    async def drain(self):
        """Wait for the pass in flight and any it starts (a flush's last pass)."""
        while self.task is not None and not self.task.done():
            await asyncio.wait([self.task])

    def close(self):
        if self.task is not None and not self.task.done():
            self.task.cancel()
        s = self.stats
        if s["passes"]:
            self.log(f"[stt] {self.who}: streaming track: {s['passes']} passes over {s['audio_s']:.0f}s of audio, "
                     f"{s['committed']} commits, {s['partials']} partials", flush=True)

    # -- internals

    def _trim(self):
        keep_from = self.committer.window(self.total)[0]
        while len(self.audio) > 1 and self.audio[0][0] + len(self.audio[0][1]) <= keep_from:
            self.audio.pop(0)

    def _pcm(self, start, end):
        import numpy as np
        parts = []
        for s, b in self.audio:
            e = s + len(b)
            if e <= start or s >= end:
                continue
            parts.append(b[max(0, start - s): len(b) - max(0, e - end)])
        return np.concatenate(parts).astype(np.float32) if parts else np.zeros(0, np.float32)

    def _speaking(self):
        return self.last_speech is not None and self.total - self.last_speech <= self.hang

    def _maybe_pass(self):
        if self.task is not None and not self.task.done():
            return
        if self.flush_wanted:
            self.flush_wanted = False
            self._start(final=True)
            return
        if self.total - self.last_pass < (self.chunk if self._speaking() else self.quiet):
            return
        self._start(final=False)

    def _start(self, final):
        start, now = self.committer.window(self.total)
        if now - start < 400:            # less than the encoder's first frame
            return
        self.last_pass = now
        pcm = self._pcm(start, now)
        self.task = asyncio.get_running_loop().create_task(self._pass(pcm, start, now, final))

    async def _pass(self, pcm, start, now, final):
        cancelled = False
        try:
            labels = await self.submit(pcm, self.lang)
            self.stats["passes"] += 1
            self.stats["audio_s"] += len(pcm) / RATE
            c = self.committer
            old_edge, context = c.edge, list(c.ids)
            new, tail = c.apply(labels, start, now, final)
            ms = lambda pos: int(pos * 1000 / RATE)   # noqa: E731
            if new or final:
                text = delta_text(self.detok, context, new)
                if text or final:
                    await self.send({"type": "committed", "track": "ctc", "text": text, "lang": self.lang,
                                     "start_ms": ms(old_edge), "end_ms": ms(c.edge), "end": bool(final)})
                    self.stats["committed"] += 1
                    if self.stats["first_commit_ms"] is None and text.strip() and self._speech_at is not None:
                        self.stats["first_commit_ms"] = int((self.clock() - self._speech_at) * 1000)
            tail_text = delta_text(self.detok, c.ids, tail).strip() if tail else ""
            if tail_text != self.shown_tail:
                self.shown_tail = tail_text
                await self.send({"type": "partial", "track": "ctc", "text": tail_text, "lang": self.lang,
                                 "start_ms": ms(c.edge), "end_ms": ms(now)})
                self.stats["partials"] += 1
                if self.stats["first_partial_ms"] is None and tail_text and self._speech_at is not None:
                    self.stats["first_partial_ms"] = int((self.clock() - self._speech_at) * 1000)
        except asyncio.CancelledError:
            cancelled = True
        except Exception as e:  # noqa: BLE001  a failed pass is only a missing partial
            self.log(f"[stt] {self.who}: streaming pass failed: {type(e).__name__}", flush=True)
        finally:
            self._trim()
            if not cancelled:
                # The audio grew while this pass ran, or a flush is waiting.
                self.task = None
                self._maybe_pass()
