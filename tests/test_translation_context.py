#!/usr/bin/env python3
"""Context from the previous pieces (?context=1): server/translation_context.py,
the engines' `context` argument, and Hy-MT2's prompt. No GPU, no models, no
numpy: the fakes of tests/test_engines.py stand in for the translators.

What it proves:
  - with the option off, every translation call is the one the stack made
    before context existed (same engines, same prompts, same batches);
  - the memory accumulates the last two source pieces and the newest
    translation per language, and never holds more than its bounds;
  - it forgets on a language switch and after 30 s idle (a clock is injected);
  - Hy-MT2's prompt carries the context marked context-only, and the piece to
    translate last; without context it is byte-for-byte the old prompt;
  - MADLAD never sees context, nor does an engine that did not ask for it, nor
    Hy-MT2 on the English pivot (the earlier pieces are in a language it does
    not read).

    python3 tests/test_translation_context.py
"""
import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, HERE)

import stack_config as c  # noqa: E402
from engines import hymt  # noqa: E402
from engines.base import Translator  # noqa: E402
from engines.hymt import HyMT  # noqa: E402
from engines.madlad import Madlad  # noqa: E402
from translation_context import TranslationMemory, tail  # noqa: E402
from test_engines import FakeMadlad, make_set, TEXTS, LANG_SETS  # noqa: E402


class ContextHyMT(HyMT):
    """Hy-MT2's routing with a fake decode that records the context it was given."""
    calls = None

    @classmethod
    def enabled(cls, ctx):
        return True

    def load(self):
        self.available = True
        self.calls = []

    def translate(self, sentences, src, targets, text=None, context=None):
        self.calls.append((list(sentences), src, list(targets), context))
        return {lg: " ".join(f"H{lg}({x})" for x in sentences) for lg in targets}


class OldStyle(Translator):
    """An engine written before `context` existed: the old signature, no takes_context."""
    name = "oldstyle"
    enabled = classmethod(lambda cls, ctx: True)
    calls = None

    def load(self):
        self.available = True
        self.calls = []

    def translate(self, sentences, src, targets, text=None):
        self.calls.append((list(sentences), src, list(targets)))
        return {lg: f"O{lg}({text})" for lg in targets}


def engine_set(langs=("es", "ja", "ht"), srcs=("en", "es", "ht")):
    return make_set(langs=langs, srcs=srcs, translators={"madlad": FakeMadlad, "hymt": ContextHyMT})


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


# ---------------------------------------------------------------- the memory

def test_off_is_nothing():
    m = TranslationMemory(False)
    assert m.before("en") is None
    m.after("en", "First piece.", {"es": "Primera pieza."})
    assert m.before("en") is None and m.pieces == [] and m.translations == {}


def test_accumulates_two_pieces_and_the_newest_translation():
    m = TranslationMemory(True, clock=Clock())
    assert m.before("en") is None                       # nothing yet
    m.after("en", "One.", {"es": "Uno.", "ja": "一。"})
    assert m.before("en") == {"pieces": ["One."], "translations": {"es": "Uno.", "ja": "一。"}}
    m.after("en", "Two.", {"es": "Dos."})
    assert m.before("en") == {"pieces": ["One.", "Two."], "translations": {"es": "Dos.", "ja": "一。"}}
    m.after("en", "Three.", {"es": "Tres.", "ja": "三。"})
    assert m.before("en") == {"pieces": ["Two.", "Three."], "translations": {"es": "Tres.", "ja": "三。"}}
    # before() hands out copies: a caller holding one across a piece's decodes sees no change.
    ctx = m.before("en")
    m.after("en", "Four.", {"es": "Cuatro."})
    assert ctx["pieces"] == ["Two.", "Three."] and m.before("en")["pieces"] == ["Three.", "Four."]
    # Empty pieces and empty translations are not recorded.
    m.after("en", "   ", {"es": "x"})
    m.after("en", "Five.", {"es": "", "ja": None})
    assert m.before("en") == {"pieces": ["Four.", "Five."], "translations": {"es": "Cuatro.", "ja": "三。"}}


def test_bounded_text():
    m = TranslationMemory(True, clock=Clock())
    long = " ".join(f"word{i}" for i in range(200))          # ~1500 characters
    m.after("en", long, {"es": long})
    ctx = m.before("en")
    assert len(ctx["pieces"]) == 1 and len(ctx["pieces"][0]) <= 600
    assert ctx["pieces"][0].endswith("word199") and not ctx["pieces"][0].startswith("word0 ")
    assert len(ctx["translations"]["es"]) <= 300 and ctx["translations"]["es"].endswith("word199")
    # Two pieces over the budget together: the older one goes, the newer stays whole.
    m = TranslationMemory(True, clock=Clock())
    m.after("en", "a" * 400, {})
    m.after("en", "b" * 400, {})
    assert m.before("en")["pieces"] == ["b" * 400]
    m.after("en", "c" * 150, {})
    assert m.before("en")["pieces"] == ["b" * 400, "c" * 150]
    # Whatever is said, the total never passes the bounds.
    m = TranslationMemory(True, clock=Clock())
    for i in range(50):
        m.after("en", f"piece {i} " + "x" * (i * 37 % 900), {"es": "y" * (i * 53 % 900), "ja": "z" * 10})
        ctx = m.before("en")
        assert len(ctx["pieces"]) <= 2 and sum(len(p) for p in ctx["pieces"]) <= 600, i
        assert all(len(t) <= 300 for t in ctx["translations"].values()), i


def test_tail_cuts_at_a_word():
    assert tail("short", 10) == "short"
    assert tail("alpha beta gamma delta", 11) == "gamma delta"
    assert tail("x" * 50, 10) == "x" * 10


def test_reset_on_language_switch():
    m = TranslationMemory(True, clock=Clock())
    m.after("en", "Hello there.", {"es": "Hola."})
    m.after("en", "How are you?", {"es": "¿Cómo estás?"})
    assert m.before("en") is not None
    assert m.before("es") is None                       # another speaker: nothing carries over
    m.after("es", "Muy bien.", {"en": "Very well."})
    assert m.before("es") == {"pieces": ["Muy bien."], "translations": {"en": "Very well."}}
    assert m.before("en") is None                       # and back again: gone
    # after() in a new language also starts afresh.
    m.after("en", "Good.", {"es": "Bien."})
    assert m.before("en") == {"pieces": ["Good."], "translations": {"es": "Bien."}}


def test_reset_after_idle():
    clock = Clock()
    m = TranslationMemory(True, clock=clock)
    m.after("en", "One.", {"es": "Uno."})
    clock.t = 29.9
    assert m.before("en")["pieces"] == ["One."]
    m.after("en", "Two.", {"es": "Dos."})               # at 29.9: the clock restarts
    clock.t = 59.0
    assert m.before("en")["pieces"] == ["One.", "Two."]
    clock.t = 59.9 + 0.2
    assert m.before("en") is None                       # 30.2 s since the last piece
    m.after("en", "Three.", {"es": "Tres."})
    assert m.before("en") == {"pieces": ["Three."], "translations": {"es": "Tres."}}
    # A piece recorded after a long gap starts afresh too.
    clock.t = 200.0
    m.after("en", "Four.", {"es": "Cuatro."})
    assert m.before("en") == {"pieces": ["Four."], "translations": {"es": "Cuatro."}}


# ---------------------------------------------------------------- the engines

def test_context_off_is_the_same_calls():
    """Every translation the pipeline makes with a disabled memory is the one
    it makes with no memory at all: same engines, same batches, same prompts."""
    for src in ("en", "es", "ht"):
        for langs in LANG_SETS:
            plain = engine_set()
            off = engine_set()
            memory = TranslationMemory(False)
            for text in TEXTS:
                want = plain.translate_batch(text, langs, src)
                got = off.translate_batch(text, langs, src, context=memory.before(src))
                memory.after(src, text, dict(zip(langs, got)))
                assert got == want, (src, langs, text)
            for name in ("madlad", "hymt"):
                assert off.engines["translator"][name].calls == plain.engines["translator"][name].calls, (src, langs)
            # Hy-MT2 was called without any context at all, as before.
            assert all(call[3] is None for call in off.engines["translator"]["hymt"].calls)
            assert all(len(call) == 3 or call[3] is None for call in plain.engines["translator"]["hymt"].calls)


def test_context_reaches_hymt_only():
    es = engine_set()
    memory = TranslationMemory(True, clock=Clock())
    langs = ["es", "ja", "ht"]                          # es, ja: Hy-MT2; ht: MADLAD
    first = es.translate_batch("The station is closed.", langs, "en", context=memory.before("en"))
    memory.after("en", "The station is closed.", dict(zip(langs, first)))
    second = es.translate_batch("It opens at nine.", langs, "en", context=memory.before("en"))
    memory.after("en", "It opens at nine.", dict(zip(langs, second)))
    hy = es.engines["translator"]["hymt"].calls
    assert hy[0][3] is None                              # the first piece: nothing to give
    assert hy[1][3] == {"pieces": ["The station is closed."],
                        "translations": {"es": first[0], "ja": first[1], "ht": first[2]}}
    assert hy[1][0] == ["It opens at nine."] and hy[1][2] == ["es", "ja"]
    # MADLAD's decodes are the plain ones, context or not.
    plain = engine_set()
    plain.translate_batch("The station is closed.", langs, "en")
    plain.translate_batch("It opens at nine.", langs, "en")
    assert es.engines["translator"]["madlad"].calls == plain.engines["translator"]["madlad"].calls
    assert second[2] == "M(<2ht> It opens at nine.)"


def test_no_context_on_the_english_pivot():
    """A Haitian Creole speaker: the pieces are pivoted through English, and the
    earlier pieces (in Haitian Creole) are not handed to Hy-MT2."""
    es = engine_set()
    memory = TranslationMemory(True, clock=Clock())
    es.translate_batch("Bonjou tout moun.", ["es"], "ht", context=memory.before("ht"))
    memory.after("ht", "Bonjou tout moun.", {"es": "Hola a todos."})
    ctx = memory.before("ht")
    assert ctx["pieces"] == ["Bonjou tout moun."]
    es.translate_batch("Mèsi anpil.", ["es"], "ht", context=ctx)
    hy = es.engines["translator"]["hymt"].calls
    assert len(hy) == 2 and hy[1][1] == "en" and hy[1][3] is None


def test_an_engine_without_takes_context_is_called_the_old_way():
    table = dict(c.DEFAULTS)
    table["de"] = {"translator": "oldstyle"}
    es = make_set(table, translators={"madlad": FakeMadlad, "hymt": ContextHyMT, "oldstyle": OldStyle},
                  langs=("de", "es"))
    ctx = {"pieces": ["Earlier."], "translations": {"de": "Früher.", "es": "Antes."}}
    assert es.translate_batch("Now.", ["de", "es"], "en", context=ctx) == ["Ode(Now.)", "Hes(Now.)"]
    assert es.engines["translator"]["oldstyle"].calls == [(["Now."], "en", ["de"])]
    assert es.engines["translator"]["hymt"].calls[0][3] == ctx
    # The fixture and template engines keep the old signature and never ask for context.
    assert Translator.takes_context is False and Madlad.takes_context is False and HyMT.takes_context is True
    assert "context" in inspect.signature(HyMT.translate).parameters
    assert "context" not in inspect.signature(Madlad.translate).parameters


def test_a_target_left_out_still_falls_back_to_madlad():
    class Partial(ContextHyMT):
        def translate(self, sentences, src, targets, text=None, context=None):
            super().translate(sentences, src, targets, text, context)
            return {lg: f"H{lg}" for lg in targets if lg != "ja"}

    es = make_set(langs=("es", "ja"), translators={"madlad": FakeMadlad, "hymt": Partial})
    ctx = {"pieces": ["Earlier."], "translations": {}}
    assert es.translate_batch("Now.", ["es", "ja"], "en", context=ctx) == ["Hes", "M(<2ja> Now.)"]


# ---------------------------------------------------------------- Hy-MT2's prompt

OLD_PROMPT = ("Translate the following text into Spanish. Note that you should only output "
              "the translated result without any additional explanation:\n\nIt opens at nine.")


def test_hymt_prompt_without_context_is_unchanged():
    assert hymt.prompt("es", "It opens at nine.") == OLD_PROMPT
    assert hymt.prompt("es", "It opens at nine.", None) == OLD_PROMPT
    assert hymt.prompt("es", "It opens at nine.", {"pieces": [], "translations": {}}) == OLD_PROMPT


def test_hymt_prompt_with_context():
    ctx = {"pieces": ["The station is closed.", "Until the morning."],
           "translations": {"es": "Hasta la mañana.", "ja": "朝まで。"}}
    p = hymt.prompt("es", "It opens at nine.", ctx)
    assert p.endswith(OLD_PROMPT)                                   # the piece to translate comes last
    head = p[:-len(OLD_PROMPT)]
    assert "The station is closed.\nUntil the morning." in head    # the pieces, oldest first
    assert "Hasta la mañana." in head and "朝まで。" not in head     # only this target's translation
    assert "for context only" in head and "Do not translate it" in head and "Do not repeat it" in head
    assert head.index("The station is closed.") < head.index("Hasta la mañana.")
    # No translation yet for this target: only the pieces.
    q = hymt.prompt("ja", "It opens at nine.", {"pieces": ["The station is closed."], "translations": {}})
    assert q.endswith(hymt.prompt("ja", "It opens at nine.")) and "The station is closed." in q
    assert "translated into" not in q


def test_only_new_drops_a_repeated_previous_translation():
    ctx = {"pieces": ["x"], "translations": {"es": "Hasta la mañana."}}
    assert hymt.only_new("Abre a las nueve.", "es", ctx) == "Abre a las nueve."
    assert hymt.only_new("Hasta la mañana. Abre a las nueve.", "es", ctx) == "Abre a las nueve."
    assert hymt.only_new("Hasta la mañana.", "es", ctx) == "Hasta la mañana."      # nothing else: keep it
    assert hymt.only_new("Abre a las nueve.", "es", None) == "Abre a las nueve."
    assert hymt.only_new("Abre a las nueve.", "ja", ctx) == "Abre a las nueve."


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
