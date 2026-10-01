"""The three engine interfaces: Recognizer, Translator, Voice.

An engine is one class in one file under server/engines/ (or in a directory
named by STACK_ENGINES_PATH), decorated with @register. docs/dev/adding-an-engine.md
walks through writing one; server/engines/_template.py is a copy-me skeleton.

Rules every engine keeps, because the pipeline depends on them:

- Module import must be cheap and need only the standard library.
  stack_config.py imports every engine to validate languages.toml (on the
  macOS system Python too); torch, transformers and friends are imported
  inside load() or the method that needs them.
- load() runs once, at start, before "ready". It may raise: an exception there
  stops the server (loud beats silent, docs/dev/lessons-learned.md §10). An engine
  whose absence should only degrade the service catches its own errors, prints
  why, and leaves self.available False; the pipeline then falls back.
- Calls arrive from worker threads, several at once. An engine that is not
  thread-safe says so with its lock policy (Voice) or holds its own lock
  (Hy-MT2 does).
"""
import contextlib

# The pipeline's audio rates: every voice hands back 24 kHz mono PCM16 (the
# protocol's rate); every recogniser gets 16 kHz float32 mono (Silero's and
# Whisper's).
RATE = 24000
VAD_RATE = 16000


class AudioStream:
    """A sentence's audio still being made: an iterator of PCM16 chunks.

    next() may block for seconds (VoxCPM2 waits for a GPU slot, then for each
    chunk), so server.send_speech iterates each stream on a thread of its own,
    never on the shared TTS pool, and closes it on that same thread."""
    def __init__(self, chunks):
        self.chunks = chunks


class Context:
    """What an engine is given: the device, the configuration, the server's
    flags and the pipeline's shared services.

    device    the default device: "cuda", "cuda:<n>", "mps" or "cpu"
    devices   {engine name: device}, from [devices] / the profile (resolved;
              "default" is `device`). An engine loads on self.device, which
              reads this; ctx.device_for(name) is the same for any name.
    models    languages.toml [models], merged over the defaults (every model's repo/revision)
    table     languages.toml's language tables ({lang: {key: value}})
    tables    stack_config.tables(table): the derived lookups (KOKORO_VOICES, ...)
    langs     the languages people listen in (--langs)
    srcs      the source languages expected (--srcs)
    options   the server's flags, as a dict (asr_model, mt_ct2, hymt, kokoro, ...)
    voice_lock(lang)  the lock that serialises one language's voice model
    engine(kind, name)  another running engine, or None: an engine may build
              on one that is already loaded (engines/_template.py uses MADLAD)
    """
    def __init__(self, device="cpu", models=None, table=None, tables=None, langs=(), srcs=(),
                 options=None, voice_lock=None, devices=None):
        self.device = device
        self.devices = dict(devices or {})
        self.models = models or {}
        self.table = table or {}
        self.tables = tables or {}
        self.langs = list(langs)
        self.srcs = list(srcs)
        self.options = options or {}
        self.voice_lock = voice_lock or (lambda lang: contextlib.nullcontext())
        # Whether any voice follows `name` in `lang`'s chain (set by the EngineSet). A voice
        # with nothing behind it waits for capacity instead of handing the sentence to silence.
        self.voice_after = lambda lang, name: True
        self.engine = lambda kind, name: None

    def device_for(self, name):
        """Where engine `name` loads: its [devices] entry, else the default."""
        return self.devices.get(name) or self.device

    def option(self, key, default=None):
        v = self.options.get(key, default)
        return default if v is None else v


class Engine:
    """What all three kinds share."""
    kind = None           # "recognizer" | "translator" | "voice"
    name = None           # the name languages.toml uses
    title = None          # for log lines, e.g. "Hy-MT2"
    # Keys (and defaults) accepted under [models.<name>] in languages.toml, for
    # an engine whose models stack_config.MODEL_DEFAULTS does not already name.
    models = {}
    # The type of this engine's per-language value, `<name> = ...` in a
    # language's table (a voice name, a repo, `true`). None: no such key.
    lang_key = None
    # The weights' licence, for `stack_config.py check` and docs/licences.md.
    licence = ""
    # Its class for EDITION=commercial, when server/licences.py has no entry for
    # this engine (an out-of-tree one): "permissive" | "attribution" |
    # "share-alike" | "noncommercial" | "unclear". None = unclear, which
    # commercial refuses to load. licence_url / licence_obligation: the source,
    # and the credit an attribution or share-alike licence requires.
    licence_class = None
    licence_url = ""
    licence_obligation = ""

    def __init__(self, ctx):
        self.ctx = ctx
        self.available = False

    @classmethod
    def enabled(cls, ctx):
        """Load this engine at all? Default: when a served language names it
        in languages.toml. The built-in engines follow the server's flags."""
        return any(_names(entry, cls) for lang, entry in ctx.table.items()
                   if lang in set(ctx.langs) | set(ctx.srcs))

    @classmethod
    def check_lang(cls, lang, value):
        """An error message for a bad per-language value, or None."""
        return None

    @property
    def device(self):
        """The device this engine loads on ([devices] in languages.toml or the
        profile; the server's default otherwise). Use this, not ctx.device."""
        return self.ctx.device_for(self.name)

    def load(self):
        """Load weights. Set self.available when the engine can serve."""
        self.available = True

    def setting(self, lang, default=None):
        """This engine's per-language value (`<name> = ...` in [lang])."""
        return self.ctx.table.get(lang, {}).get(self.name, default)

    def model(self, key, default=None):
        """A value from [models.<name>]."""
        return self.ctx.models.get(self.name, {}).get(key, default)


def _names(entry, cls):
    """Does this language table name the engine?"""
    if not isinstance(entry, dict):
        return False
    if cls.kind == "translator":
        return entry.get("translator") == cls.name
    if cls.kind == "recognizer":
        return entry.get("asr", "").split(":", 1)[0] == cls.name
    return cls.name in entry or cls.name in (entry.get("voice") or [])


class Recognizer(Engine):
    """Speech -> text for the SOURCE languages that name it (asr = "<name>" or
    "<name>:<arg>"). Languages that name nothing use "whisper"."""
    kind = "recognizer"
    # asr = "<name>:<arg>" required (Omnilingual's language code), optional or refused.
    arg = "none"          # "none" | "optional" | "required"

    def supports(self, lang):
        """Serve this source language? Default: every language whose asr names this engine."""
        return self.ctx.table.get(lang, {}).get("asr", "").split(":", 1)[0] == self.name

    def arg_for(self, lang):
        """The <arg> of asr = "<name>:<arg>" for this language, or None."""
        asr = self.ctx.table.get(lang, {}).get("asr", "")
        return asr.split(":", 1)[1] if ":" in asr else None

    def transcribe(self, pcm16k, lang, want_segments=False):
        """Text heard in 16 kHz float32 audio; with want_segments, (text,
        [(segment_text, end_s), ...]) for streaming-mode buffer trimming ([]
        if the engine has no segment times). Return "" for non-speech: the
        caller treats empty text as nothing said. Filter noise with
        engines.common.is_nonspeech() as Whisper and Omnilingual do."""
        raise NotImplementedError

    def words(self, pcm16k, lang):
        """[(word, end_s), ...] with word timings, for cutting a long buffer at
        a sentence end; None when this engine has none (the cut then falls at
        the quietest point)."""
        return None


class Translator(Engine):
    """Text -> text INTO the target languages that name it (translator =
    "<name>"). MADLAD is the fallback for everything else, and for any target
    this engine leaves out of its answer."""
    kind = "translator"
    # Target languages it can do, for languages.toml validation; None = any.
    languages = None

    def supports(self, lang):
        """Translate into this language?"""
        return self.languages is None or lang in self.languages

    def supports_source(self, lang):
        """Translate FROM this language? If not, the sentences are first
        pivoted into English by MADLAD and handed over with src="en"."""
        return True

    def translate(self, sentences, src, targets, text=None):
        """{lang: translation} for every target. `sentences` is the utterance
        split into sentences (translate each; join with a space, or with
        nothing for zh/ja: engines.common.join_sentences). `text` is the
        utterance as heard, for engines that prefer it whole. A target left
        out, or mapped to "", is translated by MADLAD instead; raising does the
        same for every target."""
        raise NotImplementedError


class Voice(Engine):
    """Text -> 24 kHz mono PCM16 for the languages whose voice chain names it.

    The chain (languages.toml) is tried in order and the first voice that
    returns audio speaks. Returning None passes the sentence to the next voice;
    raising fails the sentence (logged, nothing spoken)."""
    kind = "voice"
    # Place in the default chain, lowest first, when a language has no
    # `voice = [...]` list: kokoro 10, voxcpm 20, coqui 30, piper 40, mms 50.
    # 0 means a voice added to a language is tried before the built-in ones.
    priority = 0
    # A streaming voice (stream() below) takes its sentences in streaming mode,
    # ahead of the rest of the chain, which becomes its fallback. VoxCPM2.
    streaming = False
    # A last-resort voice (eSpeak NG) is appended to the end of every chain
    # whose language it supports(), even after an explicit `voice = [...]`:
    # languages.toml does not have to name it. `<name> = false` in a
    # language's table takes it out there.
    last_resort = False
    # "language": one lock per language around synthesis (the model is not
    # thread-safe; sentences of one utterance arrive on several threads at
    # once; see docs/dev/lessons-learned.md §5). "none": the engine is safe as is.
    # --serial-tts turns every "language" lock into one global lock.
    lock_policy = "language"

    def supports(self, lang):
        """Speak this language? Default: its table names this voice."""
        return self.setting(lang) is not None or self.name in (self.ctx.table.get(lang, {}).get("voice") or [])

    def lock(self, lang):
        """Hold this around the model call (not around loading or resampling)."""
        if self.lock_policy == "none":
            return contextlib.nullcontext()
        return self.ctx.voice_lock(lang)

    def synthesise(self, text, lang):
        """24 kHz mono PCM16 bytes (engines.common.to_pcm16 converts from any
        rate without clicks), or None to let the next voice try."""
        raise NotImplementedError

    def stream(self, text, lang, fallback):
        """Streaming voices only: a generator of 24 kHz PCM16 chunks for one
        sentence. If it cannot start, call fallback() (the rest of the chain)
        and yield its bytes, if any."""
        raise NotImplementedError
