"""What a translator may read besides the piece it is translating: the last
pieces heard and how the last one was translated (?context=1, docs/dev/protocol.md).

A short piece (a breath-cut clause of a few seconds) is translated alone today,
and a name or a thread of argument that the previous piece settled is lost on
it. Measured 2026-10-21 (eval/2026-10-continuous-ht): cutting a news read at
breaths halved the delay but took the translation judge's score from 2.52 to
2.15-2.21 (0-3), and sending the previous two pieces and the last translation
as context only, with a cloud LLM, brought it back to 2.52-2.67. This module
keeps that memory for the stack's own translators; whether it helps Hy-MT2 is
not measured yet (server/engines/hymt.py).

One TranslationMemory per pipeline: a room's, or a solo connection's. It is
off unless the client asked, and then:

- it holds the last PIECES source pieces (their text as heard, oldest first)
  and, per target language, the newest translation;
- the text is bounded (SOURCE_CHARS over the pieces, TRANSLATION_CHARS per
  target, the END of a text kept when it is cut), so a prompt can never grow
  past that whatever is said;
- it forgets everything when the source language changes (the hello's src,
  or the route src detected per utterance) and after IDLE_S without a piece:
  a translation that reaches the room half a minute later is a new subject,
  and a piece in another language is another speaker.

before(src) hands the translators the context for the next piece (None when
there is nothing, or the memory is off); after(src, text, translations)
records the piece once it is translated. With the memory off, before() is
None and after() does nothing, so the translation calls are the ones the
stack always made (tests/test_translation_context.py proves it).
"""
import threading
import time

PIECES = 2
SOURCE_CHARS = 600
TRANSLATION_CHARS = 300
IDLE_S = 30.0


def tail(text, limit):
    """The last `limit` characters of a text, cut at a word where one is near."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    space = cut.find(" ")
    # Drop the word fragment the cut landed in, unless that leaves too little.
    if 0 < space < limit // 4:
        cut = cut[space + 1:]
    return cut


class TranslationMemory:
    def __init__(self, enabled=False, clock=time.monotonic, pieces=PIECES, source_chars=SOURCE_CHARS,
                 translation_chars=TRANSLATION_CHARS, idle_s=IDLE_S):
        self.enabled = bool(enabled)
        self.clock = clock
        self.max_pieces = max(0, int(pieces))
        self.source_chars = max(0, int(source_chars))
        self.translation_chars = max(0, int(translation_chars))
        self.idle_s = float(idle_s)
        self._lock = threading.Lock()
        self.reset()

    def reset(self, src=None):
        self.src = src
        self.pieces = []            # source text, oldest first
        self.translations = {}      # target language -> the newest translation
        self.last_at = None         # when the last piece was recorded (clock())

    def _settle(self, src, now):
        """Forget what no longer applies: another source language, or too long ago."""
        if src != self.src or (self.last_at is not None and now - self.last_at > self.idle_s):
            self.reset(src)

    def before(self, src):
        """The context for the next piece in `src`, or None when there is none.

        {"pieces": [earlier source text, oldest first], "translations":
        {lang: its newest translation}} -- copies, so the caller may hold it
        across the calls that translate one piece (a room's priority decode
        and then the rest) while the memory moves on."""
        if not self.enabled:
            return None
        with self._lock:
            self._settle(src, self.clock())
            if not self.pieces:
                return None
            return {"pieces": list(self.pieces), "translations": dict(self.translations)}

    def after(self, src, text, translations):
        """Record a translated piece: its source text and {lang: translation}."""
        if not self.enabled:
            return
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            now = self.clock()
            self._settle(src, now)
            self.pieces.append(text)
            self.pieces = self.pieces[-self.max_pieces:] if self.max_pieces else []
            self._bound_pieces()
            for lang, tr in (translations or {}).items():
                tr = (tr or "").strip()
                if tr:
                    self.translations[lang] = tail(tr, self.translation_chars)
            self.last_at = now

    def _bound_pieces(self):
        """At most source_chars over the kept pieces: the oldest go first, and
        a single piece longer than the budget keeps its end."""
        budget = self.source_chars
        kept = []
        for piece in reversed(self.pieces):
            if budget <= 0:
                break
            if len(piece) > budget:
                if not kept:
                    kept.append(tail(piece, budget))
                break
            kept.append(piece)
            budget -= len(piece)
        self.pieces = list(reversed(kept))
