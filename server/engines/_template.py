"""A new engine, in one file: copy this to server/engines/<name>.py (or into a
directory listed in STACK_ENGINES_PATH), rename the class and `name`, and
name it in languages.toml. Files starting with "_" are never loaded, so this
one is inert until copied. Walk-through: docs/dev/adding-an-engine.md.

This example is a complete, working translator with no new model: MADLAD with
a different prompting strategy. The stock MADLAD engine translates an
utterance sentence by sentence (it dropped sentences when given several at
once); this one hands it the whole utterance in one prompt. It borrows the
MADLAD already loaded, so it costs no memory. Try it on one language:

    cp server/engines/_template.py server/engines/madlad_whole.py
    # languages.toml
    [ro]
    piper = "ro_RO-mihai-medium"
    translator = "madlad_whole"
    madlad = "ro"

    python3 server/stack_config.py check      # "mt=madlad_whole" for ro
    # restart, then: python3 tools/smoke.py --langs ro

Licence: none of its own (it runs MADLAD, Apache 2.0). A real engine with its
own weights adds a row to docs/licences.md.
"""
from engines import register
from engines.base import Translator


@register
class MadladWhole(Translator):
    # The name languages.toml uses: translator = "madlad_whole".
    name = "madlad_whole"
    # For log lines ("madlad_whole failed (...) — MADLAD instead").
    title = "MADLAD, whole utterance"
    licence = "Apache-2.0 (MADLAD's)"
    # Target languages it can do, checked by `stack_config.py check`; None = any.
    languages = None
    # Settings under [models.madlad_whole] in languages.toml, with defaults.
    # Read them with self.model("max_words").
    models = {"max_words": "60"}

    # enabled(ctx): inherited. The engine loads when a served language names it.

    def load(self):
        """Once, at start. Import heavy libraries HERE, not at the top of the
        file: stack_config.py imports every engine file to validate
        languages.toml, on machines without torch. Raise to stop the server;
        or print why and leave self.available False to let MADLAD serve."""
        self.madlad = self.ctx.engine("translator", "madlad")
        if self.madlad is None:
            print("[stack] madlad_whole: MADLAD is not running — MADLAD serves its languages anyway")
            return
        self.max_words = int(self.model("max_words", "60"))
        self.available = True

    def supports_source(self, lang):
        """MADLAD reads any language, so no English pivot is needed."""
        return True

    def translate(self, sentences, src, targets, text=None):
        """{lang: translation}. Called from a worker thread, possibly while
        another utterance is being translated: keep no per-call state on self,
        or hold a lock (engines/hymt.py does). A target left out, or "", is
        translated by MADLAD instead, whole; raising does that for all."""
        whole = text if text is not None else " ".join(sentences)
        if len(whole.split()) > self.max_words:
            # Too long for one prompt: MADLAD's own sentence-by-sentence path.
            return self.madlad.translate(sentences, src, targets, text=text)
        outs = self.madlad.generate([f"<2{self.madlad.tag(lg)}> {whole}" for lg in targets])
        return dict(zip(targets, (o.strip() for o in outs)))


# A voice or a recogniser has the same shape; the methods differ (engines/base.py):
#
#   @register
#   class MyVoice(Voice):
#       name = "myvoice"           # [xx] myvoice = "<speaker>"; voice = ["myvoice", "piper"]
#       lang_key = str             # the type of that per-language value
#       lock_policy = "language"   # not thread-safe: one sentence at a time per language
#       def load(self): ...
#       def supports(self, lang): return self.available and self.setting(lang) is not None
#       def synthesise(self, text, lang):
#           pcm, rate = ...                     # float32 mono at the model's rate
#           return to_pcm16(peak_normalise(pcm), rate)   # engines.common: 24 kHz PCM16, no clicks
#
#   @register
#   class MyASR(Recognizer):
#       name = "myasr"             # [xx] asr = "myasr" (or "myasr:<code>" with arg = "required")
#       def load(self): ...
#       def transcribe(self, pcm16k, lang, want_segments=False):
#           text = ...                                    # 16 kHz float32 in
#           if is_nonspeech(text): text = ""              # engines.common: coughs, captions
#           return (text, []) if want_segments else text
