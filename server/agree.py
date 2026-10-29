"""The "agree" commit policy for simultaneous mode (?stream=1 with ?policy=agree, or LITHOS_STREAM_POLICY=agree).

Simultaneous mode's default speaks a turn clause by clause: the committed words are cut at a sentence end, a comma
after STREAM_COMMA_WORDS, or STREAM_MAX_WORDS, and each piece is translated on its own. Agree lets the translator
decide instead. At each pass that commits new words, Gemma translates the whole turn so far; only the words two
successive translations agree on, beyond what is already spoken, are spoken. A word is never taken back. When the
turn ends, one call completes the translation given what was spoken.

Measured on recorded streaming recognition, en<->es and en<->fr (eval/2026-10-llm-commit-policy): with MAI's
transcripts agree scored 69.2 out of English and 82.2 into English, against 65.0 and 71.1 for the 8-word phrase rule
and 68.8 and 89.0 for whole sentences, first audio 4.4-4.9 s into a sentence against 3.8-4.2 s (phrases) and
9.9-11.0 s (sentences). Live Translation runs the same policy on the phones of managed rooms (lithos-server
src/agree.ts), with the target list below.

Only directions Gemma serves (the target's llmmt, or the source's for into English) agree, and only those in
AGREE_TARGETS / AGREE_SOURCES_TO_EN: the others in the room keep the clause rule.
"""
import os

# Out of English: targets whose translation settles from the start before the sentence ends (lithos-server
# src/agree.ts AGREE_TARGETS; es and fr measured live here, eval/2026-10-agree-live). Not the verb-late targets
# Live Translation lets agree anyway (de, hi, tr): live on the stack en->de lost 6.6 points to whole utterances
# (67.8 against 74.4, eval/2026-10-thought-live), and on Bedrock agree trailed sentences by 11.7 (de), 12.4 (hi)
# and 9.6 (tr) (eval/2026-10-complete-thought-endpointing). Those wait for whole clauses instead.
AGREE_TARGETS = frozenset({"es", "fr", "pt", "it", "ro", "ru", "pl", "id", "vi", "zh"})
# Into English: the speakers measured (es, fr). Hindi and Turkish broke down into English (two prefixes agree on a
# guessed verb: 60.5 and 66.7 against 90+ for whole sentences, eval/2026-10-llm-commit-policy-bedrock-de-hi-tr).
AGREE_SOURCES_TO_EN = frozenset({"es", "fr"})
# More untranslated words than this and the latest translation is spoken whole, agreed or not: without it a turn of
# irregular pauses could hold 13-17 s of speech (the eval's slowest tenth).
AGREE_MAX_PENDING = int(os.environ.get("LITHOS_AGREE_MAX_PENDING", 10))
# Translation calls a turn may make before it waits for the end (one at the end is always made).
AGREE_MAX_CALLS = int(os.environ.get("LITHOS_AGREE_MAX_CALLS", 8))


def eligible(src, tgt):
    """Whether src -> tgt may agree (the translator must also be Gemma: see AgreeTurn)."""
    if src == "en":
        return tgt in AGREE_TARGETS
    return tgt == "en" and src in AGREE_SOURCES_TO_EN


def lcp(a, b):
    """Length of the common start of two word lists."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def prefix_prompt(a, b, so_far):
    return (f"Translate this {a} sentence prefix, transcribed from live speech while the speaker is still talking "
            f"(it may contain recognition errors and is probably unfinished), into natural {b}. Translate only what "
            f"has been said; do not guess how it ends. Output only the {b}.\nPrefix: {so_far}")


def finish_prompt(a, b, sentence, spoken):
    return (f"You are a live interpreter translating {a} speech into spoken {b}. The {a} comes from live speech "
            f"recognition and may contain errors. Spoken words cannot be taken back.\n"
            f"The speaker has finished this {a} text: \"{sentence}\"\n"
            f"Already spoken in {b} for it: \"{spoken}\"\n"
            f"Output ONLY the {b} words that complete the translation so that, together with what was already spoken, "
            f"it covers the whole text. Never repeat or contradict what was already spoken. If nothing is missing, "
            f"output nothing. Keep numbers, names and negation exact.")


class AgreeTurn:
    """One target language's agree state for one turn. `ask(prompt)` sends a prompt to the target's Gemma and
    returns its text (raises on failure); `head` goes before every prompt (the previous pieces, for ?context=1)."""

    def __init__(self, ask, a, b, head=""):
        self.ask, self.a, self.b = (lambda prompt: ask(head + prompt)), a, b
        self.spoken = []        # target words already spoken
        self.last = []          # the previous translation of the turn so far
        self.asked_n = 0        # committed source words at the last call
        self.covered_n = 0      # committed source words at the last time something was spoken
        self.calls = 0
        self.failed = False     # a failed call ends agree for this turn: the end translates the rest

    def step(self, committed):
        """Committed source words so far -> the target text to speak now ("" for nothing)."""
        if self.failed or len(committed) <= self.asked_n or self.calls >= AGREE_MAX_CALLS:
            return ""
        self.asked_n = len(committed)
        self.calls += 1
        try:
            tr = self.ask(prefix_prompt(self.a, self.b, " ".join(committed))).split()
        except Exception as e:
            print(f"[stack] agree {self.a}->{self.b} failed ({e}): the end of the turn translates the rest", flush=True)
            self.failed = True
            return ""
        prev, self.last = self.last, tr
        upto = lcp(tr, prev)
        if len(committed) - self.covered_n > AGREE_MAX_PENDING:
            upto = len(tr)     # too much waiting: speak the latest translation
        # Only a continuation of what was spoken: a translation that rewrites the spoken start waits.
        if lcp(tr, self.spoken) < len(self.spoken) or upto <= len(self.spoken):
            return ""
        out = tr[len(self.spoken):upto]
        self.spoken += out
        self.covered_n = len(committed)
        return " ".join(out)

    def finish(self, sentence, translate_whole):
        """The turn is over: the rest of the translation. `translate_whole(sentence)` translates it as utterance
        mode would, used when nothing was spoken yet."""
        if not self.spoken:
            return translate_whole(sentence)
        try:
            rest = self.ask(finish_prompt(self.a, self.b, sentence, " ".join(self.spoken)))
        except Exception as e:
            print(f"[stack] agree {self.a}->{self.b} finish failed ({e})", flush=True)
            return ""
        rest = rest.strip().strip('"').strip()
        self.spoken += rest.split()
        return rest
