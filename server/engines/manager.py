"""The engines one server runs, and how a language is routed to them.

Pipeline (server.py) owns one EngineSet. It decides, per language:

  recognition   asr = "<name>[:<arg>]" for the SOURCE language, if that engine
                is running and supports it; otherwise Whisper.
  translation   translator = "<name>" for each TARGET language (default
                "hymt"), if running and supporting it; otherwise MADLAD. One
                batched call per engine; MADLAD pivots sources an engine does
                not know into English first, and fills in any target an engine
                leaves out.
  voice         the chain: `voice = [...]` in the language's table if given,
                else every running voice that supports the language, by
                priority (kokoro, voxcpm, coqui, piper, mms; a new engine
                goes first), then the last-resort voice (eSpeak NG, which
                languages.toml need not name). The first that returns audio
                speaks. VoxCPM2 at capacity waits briefly for a slot, then
                returns None, so its overflow goes down the chain. A streaming
                voice in the chain takes the sentence in streaming mode, with
                the rest of the chain as its fallback.

Nothing here knows a model by name except the two fallbacks (whisper, madlad)
and the default translator (hymt), which are what the stack has always done.

Licences (server/licences.py): the EngineSet runs in one edition,
ctx.options["edition"] (server.py --edition, from EDITION; default nonprofit).
In "commercial" it enforces the licence data itself, whatever the caller
passed in: the language table is re-derived with stack_config.apply_edition()
before any engine is built (so Piper never even opens a non-commercial voice),
an engine whose own licence is not allowed (MMS-TTS; an unclassified plug-in)
is never constructed even if its flag is on, every chain is filtered again when
it is built, and a non-commercial item left anywhere is a RuntimeError.
"""
import threading
from concurrent.futures import Future

import engines
import licences
from engines.base import AudioStream
from engines.common import gpu_used_mb, split_sentences, voice_sentences

# The fallbacks: always loaded, and what serves a language whose configured
# engine is not running.
FALLBACK_RECOGNIZER = "whisper"
FALLBACK_TRANSLATOR = "madlad"
DEFAULT_TRANSLATOR = "hymt"

# Load order of the built-in engines (the order server.py loaded them in
# before the split, so GPU allocation is laid out as before); others follow,
# by name.
LOAD_ORDER = ["whisper", "omni", "cosyvoice", "coqui", "voxcpm", "hymt", "kokoro", "madlad", "piper", "mms", "espeak"]


class EngineSet:
    def __init__(self, ctx, serial_tts=False, classes=None):
        """classes: {kind: {name: class}} to use instead of the registry (tests)."""
        self.ctx = ctx
        # One lock PER MODEL, not one lock for the GPU.
        #
        # The single lock came from when MMS was the only GPU voice; it
        # serialised every language and showed up as a staircase in the stage
        # log. Removing it outright was wrong, and the reasoning was wrong with
        # it: "the models are per-language objects, so there is no shared state"
        # ignores that an utterance is split into SENTENCES, each submitted to
        # the pool separately. Several threads then call the same Kokoro
        # pipeline, or the same Coqui synthesiser, at once — and neither is
        # thread-safe. The operator heard that as robotic tremors in Spanish
        # and Haitian, the two languages served by exactly those engines.
        #
        # Per-model locks keep what the change was for (different languages
        # overlap) and give back what it broke (one language's sentences are
        # serialised through its own model). --serial-tts still forces the old
        # single lock. (Keyed by language: each language has its own model or
        # pipeline in every locked engine.)
        self._serial_tts = serial_tts
        self._tts_locks = {}
        self._tts_locks_guard = threading.Lock()
        self.gpu_tts_lock = threading.Lock()  # used only when --serial-tts
        ctx.voice_lock = self.voice_lock
        ctx.voice_after = self.voice_after
        ctx.engine = self.get
        classes = classes or engines.registry()
        self._apply_edition(ctx)
        self.engines = {k: {} for k in engines.KINDS}
        for kind in engines.KINDS:
            for name, cls in classes.get(kind, {}).items():
                if not cls.enabled(ctx):
                    continue
                if name not in licences.PER_ITEM and not self._allowed(name, None, cls):
                    li = licences.lookup(name, cls=cls)
                    print(f"[licence] {self.edition}: NOT loading {kind} {name} "
                          f"({licences.SYMBOL[li.cls]} {li.licence}: {li.reason})", flush=True)
                    continue
                self.engines[kind][name] = cls(ctx)
        self._chains = {}
        self._assert_clean()

    # ------------------------------------------------------------ licences

    def _apply_edition(self, ctx):
        """Re-derive the language table for the edition (stack_config.apply_edition),
        whatever table the caller passed in."""
        import stack_config
        self.edition = stack_config.edition(ctx.options.get("edition") or "nonprofit")
        self.reviews = stack_config.validate_reviews(dict(ctx.options.get("licence_review") or {}))
        self.unclear_ok = bool(ctx.options.get("allow_unclear")) or stack_config.allow_unclear()
        table, self.licence_report = stack_config.apply_edition(ctx.table, self.edition, self.reviews,
                                                                self.unclear_ok)
        if self.edition == "commercial":
            ctx.table = table
            ctx.tables = stack_config.tables(table)
        elif any("commercial" in e for e in ctx.table.values() if isinstance(e, dict)):
            # nonprofit: the table as written, without the commercial alternatives.
            ctx.table = table

    def _allowed(self, name, value, cls=None):
        li = licences.lookup(name, value if isinstance(value, str) else None, cls=cls)
        return licences.allowed(li, self.edition, licences.item_id(name, value) in self.reviews, self.unclear_ok)

    def _assert_clean(self):
        """Belt and braces: in commercial, no language may still name a voice
        that is not allowed, and no disallowed engine may exist."""
        if self.edition != "commercial":
            return
        for lang, entry in self.ctx.table.items():
            for name in [k for k in entry if k in self.engines["voice"] or k in engines.registry("voice")] \
                    + list(entry.get("voice") or []):
                if not self._allowed(name, entry.get(name), type(self.engines["voice"].get(name))
                                     if name in self.engines["voice"] else None):
                    raise RuntimeError(f"licence: [{lang}] {name} {entry.get(name)!r} is not allowed in commercial")
        for kind, es in self.engines.items():
            for name, eng in es.items():
                if name not in licences.PER_ITEM and not self._allowed(name, None, type(eng)):
                    raise RuntimeError(f"licence: {kind} {name} is not allowed in commercial")

    # ------------------------------------------------------------ lifecycle

    def load(self, names=None):
        """Load the named engines (default: all not yet loaded), in LOAD_ORDER."""
        pending = [(k, n, e) for k, es in self.engines.items() for n, e in es.items()
                   if not getattr(e, "_loaded", False) and (names is None or n in names)]
        rank = {n: i for i, n in enumerate(LOAD_ORDER)}
        pending.sort(key=lambda t: (rank.get(t[1], len(LOAD_ORDER)), t[1]))
        for kind, name, eng in pending:
            if name not in rank:
                print(f"[stack] loading {kind} {name} ({type(eng).__module__})…", flush=True)
            eng._loaded = True
            dev = self.ctx.device_for(name)
            before = gpu_used_mb(dev)
            eng.load()
            after = gpu_used_mb(dev)
            # Per model and card: the numbers a [devices] split is planned from.
            if before is not None and after is not None and after != before:
                print(f"[stack] {name} on {dev}: +{(after - before) / 1024:.1f} GB "
                      f"({after / 1024:.1f} GB in use there)", flush=True)
        if names is None:
            for kind, name, eng in pending:
                eng.wait_ready()
            self._report()
            self._licence_log()

    def _report(self):
        """Say which served languages asked for an engine that is not running."""
        served = set(self.ctx.langs) | set(self.ctx.srcs)
        missing = {}
        for lang in sorted(served):
            entry = self.ctx.table.get(lang, {})
            want = entry.get("translator", DEFAULT_TRANSLATOR)
            if lang in self.ctx.langs and self.translator_for(lang).name != want:
                missing.setdefault(("translator", want, FALLBACK_TRANSLATOR), []).append(lang)
            asr = entry.get("asr", FALLBACK_RECOGNIZER).split(":", 1)[0]
            if lang in self.ctx.srcs and self.recognizer_for(lang).name != asr:
                missing.setdefault(("recogniser", asr, FALLBACK_RECOGNIZER), []).append(lang)
        for (kind, want, fb), langs in missing.items():
            print(f"[stack] {kind} {want} not running — {fb} serves {','.join(langs)}", flush=True)

    def _licence_log(self):
        """Per served language: the voice chain that will actually run, its
        licences, what was left out, and TEXT ONLY where nothing is left."""
        if self.edition != "commercial":
            print(f"[licence] edition {self.edition}: every configured voice may load "
                  "(non-commercial use only; EDITION=commercial filters by licence)", flush=True)
            return
        print("[licence] edition commercial: only ✅ permissive and ⚠️ attribution/share-alike voices and models",
              flush=True)
        if self.unclear_ok:
            print("[licence] !!! COMMERCIAL_ALLOW_UNCLEAR=1: ❓ unclear items may load — you asserted your own "
                  "review of every one !!!", flush=True)
        global_ob = {}
        for lang in self.ctx.langs:
            chain = self.chain(lang)
            parts = []
            for eng in chain:
                value = eng.setting(lang)
                li = licences.lookup(eng.name, value if isinstance(value, str) else None, cls=type(eng))
                parts.append(f"{eng.name}{' ' + value if isinstance(value, str) else ''} {licences.SYMBOL[li.cls]}")
                if eng.name in licences.GLOBAL_OBLIGATION:
                    global_ob.setdefault(eng.name, (li, []))[1].append(lang)
                elif li.cls in (licences.ATTRIBUTION, licences.SHARE_ALIKE):
                    print(f"[licence] {lang} voice {eng.name} {value}: {li.obligation or li.licence}", flush=True)
                elif li.cls == licences.UNCLEAR:
                    print(f"[licence] {lang} voice {eng.name} {value}: ❓ loaded after review "
                          f"({self.reviews.get(licences.item_id(eng.name, value), 'COMMERCIAL_ALLOW_UNCLEAR=1')})",
                          flush=True)
            for name, value, li in self.licence_report.get(lang, {}).get("dropped", []):
                print(f"[licence] {lang}: left out {name} ({licences.SYMBOL[li.cls]} {li.cls})", flush=True)
            if chain:
                print(f"[licence] {lang}: voice {' > '.join(parts)}", flush=True)
            else:
                print(f"[licence] {lang}: TEXT ONLY in commercial (no commercially licensed voice)", flush=True)
        for name, (li, langs) in global_ob.items():
            print(f"[licence] voice {name} ({len(langs)} languages): {li.obligation or li.licence}", flush=True)

    def get(self, kind, name):
        eng = self.engines[kind].get(name)
        return eng if eng is not None and eng.available else None

    def voice_lock(self, lang):
        """The lock guarding ONE language's model, so its sentences serialise
        while other languages run alongside."""
        if self._serial_tts:
            return self.gpu_tts_lock
        with self._tts_locks_guard:
            if lang not in self._tts_locks:
                self._tts_locks[lang] = threading.Lock()
            return self._tts_locks[lang]

    # ------------------------------------------------------------ recognition

    def recognizer_for(self, src):
        name = self.ctx.table.get(src, {}).get("asr", FALLBACK_RECOGNIZER).split(":", 1)[0]
        eng = self.get("recognizer", name)
        if eng is not None and eng.supports(src):
            return eng
        return self.engines["recognizer"][FALLBACK_RECOGNIZER]

    def transcribe(self, pcm16k, src="en", want_segments=False):
        return self.recognizer_for(src).transcribe(pcm16k, src, want_segments=want_segments)

    # ------------------------------------------------------------ translation

    def translator_for(self, lang):
        name = self.ctx.table.get(lang, {}).get("translator", DEFAULT_TRANSLATOR)
        eng = self.get("translator", name)
        if eng is not None and eng.supports(lang):
            return eng
        return self.engines["translator"][FALLBACK_TRANSLATOR]

    def translate_batch(self, text, langs, src=None):
        """ONE batched call per translator for every target language — the
        second half of the economic claim. Seven sequential decodes serialized
        the GPU and put the last language ~15s behind the first; a batch of
        seven is one forward pass per step and they all finish together."""
        sentences = split_sentences(text)
        src = src or "en"
        base = self.engines["translator"][FALLBACK_TRANSLATOR]
        groups = {}
        for lg in langs:
            groups.setdefault(self.translator_for(lg).name, []).append(lg)
        out = {}
        # MADLAD's own languages first, as before the split.
        if base.name in groups:
            out.update(base.translate(sentences, src, groups.pop(base.name), text=text))
        for name, targets in groups.items():
            eng = self.engines["translator"][name]
            # A source this engine does not know (a Haitian Creole speaker for
            # Hy-MT2) pivots through English, MADLAD's strongest direction.
            pivot, via = sentences, src
            if not eng.supports_source(src):
                pivot, via = base.to_english(sentences), "en"
            try:
                got = eng.translate(pivot, via, targets, text=text if pivot is sentences else None) or {}
            except Exception as e:
                print(f"[stack] {eng.title or name} failed ({e}) — MADLAD instead", flush=True)
                got = {}
            for lg in targets:
                out[lg] = got.get(lg) or base.translate_text(text, lg)
        return [out[lg] for lg in langs]

    # ------------------------------------------------------------ voices

    def chain(self, lang):
        """The voices that may speak `lang`, in the order they are tried."""
        if lang in self._chains:
            return self._chains[lang]
        voices = self.engines["voice"]
        front = [e for e in voices.values() if getattr(e, "front", False)]
        explicit = self.ctx.table.get(lang, {}).get("voice")
        last = sorted((e for e in voices.values() if getattr(e, "last_resort", False)),
                      key=lambda e: (e.priority, e.name))
        if explicit:
            chosen = [e for e in front if e.name not in explicit]
            chosen = sorted(chosen, key=lambda e: e.priority) + [voices[n] for n in explicit if n in voices]
        else:
            chosen = sorted((e for e in voices.values() if e not in last), key=lambda e: (e.priority, e.name))
        # The last resort (eSpeak NG) goes at the end, named or not.
        chosen = [e for e in chosen if e not in last] + last
        chain = [e for e in chosen if e.available and e.supports(lang)]
        if self.edition == "commercial":
            ok = [e for e in chain if self._allowed(e.name, e.setting(lang), type(e))]
            for e in chain:
                if e not in ok:
                    print(f"[licence] {lang}: refusing {e.name} in commercial", flush=True)
            chain = ok
        self._chains[lang] = chain
        return chain

    def voice_after(self, lang, name):
        """True when some voice follows `name` in `lang`'s chain."""
        names = [e.name for e in self.chain(lang)]
        return name in names and names.index(name) < len(names) - 1

    def synthesise(self, text, lang, exclude=()):
        """24 kHz mono PCM16 bytes, or None when this language is text-only."""
        # Empty or punctuation-only text crashes VITS-family TTS (MMS:
        # "narrow(): length must be non-negative") — and there is nothing to
        # say anyway.
        if not text or not any(c.isalnum() for c in text):
            return None
        for eng in self.chain(lang):
            if eng.name in exclude:
                continue
            out = eng.synthesise(text, lang)
            if out is not None:
                return out
        return None

    def synthesise_futures(self, text, lang, pool):
        """Submit this utterance sentence-by-sentence and return the futures,
        in order, immediately.

        Piper runs at roughly 1.6x real time, which is fast enough to stream
        but nowhere near fast enough to WAIT for: the old path synthesised a
        whole utterance (3.5s for 5.6s of audio) before sending a byte, and
        since the room processed utterances one at a time, ASR+MT+TTS came to
        ~6.2s of work per 5s of speech. Slower than real time means the lag
        does not just start high, it GROWS for as long as someone keeps
        talking — which is exactly what the operator reported.

        Sentences are independent, so they go out to a pool and decode
        concurrently; yielding the futures in order keeps playback sequential
        while the tail of the utterance is still being made.
        """
        sentences = voice_sentences(text)
        streamer = next((e for e in self.chain(lang) if e.streaming), None)
        if streamer is not None:
            # A streaming voice (VoxCPM2) sends each sentence as it is
            # generated. The streams open lazily, in order, when the sender
            # reaches them: the service makes one voice at a time, so opening
            # them all at once would only queue them. The sender iterates each
            # on its own thread (server.send_speech), not on `pool`: a stream
            # may wait seconds for a VoxCPM2 slot, and the fallback runs there.
            done = []
            for sent in sentences:
                f = Future()
                fallback = (lambda s=sent: self.synthesise(s, lang, exclude=(streamer.name,)))
                f.set_result(AudioStream(streamer.stream(sent, lang, fallback)))
                done.append(f)
            return done
        return [pool.submit(self.synthesise, sent, lang) for sent in sentences]

