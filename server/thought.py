"""The "thought" commit policy for simultaneous mode (?stream=1 with ?policy=thought, or LITHOS_STREAM_POLICY=thought).

Complete-thought cutting (CT (b)): at each pass that commits new words, one Gemma decision for the room's speaker is
asked whether the words not yet translated BEGIN with a complete thought, "COMPLETE N" or "WAIT". A thought is
committed when two successive decisions name the same end word; it is then translated once per listener language,
by that direction's own translator, and spoken once. The end of the turn translates whatever is left.

Measured in Live Translation's runs (translation-open-stack eval/2026-10-complete-thought-endpointing, Gemma 4 on
Bedrock deciding, MAI's streaming transcripts, en<->es/de/hi/tr/fr): CT (b) 85.0 over ten directions against 80.4
for agree and 92.2 for whole sentences; 2% of its pieces contradicted later and 2% of sentences split mid-clause
(agree: 88%); the slowest tenth of sentences ends 3.8-5.5 s after the speaker stops against 9.3-9.4 s for sentences.
It starts later than agree (6.7-8.2 s after the speaker starts, against 2.2-4.1 s). It beats agree most where agree
guesses a late verb, so THOUGHT_DIRECTIONS holds those (lithos-server src/thought.ts, the directions where Gemma
decides and the direction's own translator translates); with ?policy=thought every other direction agrees where
agree.py takes it and keeps the clause rule otherwise.
"""
import os
import re

# src-tgt: CT (b) against agree and whole sentences in the main run (quality, two-round mean).
THOUGHT_DIRECTIONS = frozenset({
    "en-de",   # 87.9 against 77.5 (agree) and 89.2 (sentences)
    "en-hi",   # 90.0 against 78.8 and 91.2
    "en-tr",   # 87.9 against 83.3 and 92.9
    "de-en",   # 81.6 against 71.9 and 94.7
    "tr-en",   # 84.8 against 77.4 and 90.2
})
# More than this many words waiting: the whole tail is translated as one piece (the evals' fallback).
THOUGHT_MAX_TAIL = int(os.environ.get("LITHOS_THOUGHT_MAX_TAIL", 30))
# The answer is "COMPLETE N" or "WAIT".
THOUGHT_MAX_TOKENS = 16


def eligible(src, tgt):
    return f"{src}-{tgt}" in THOUGHT_DIRECTIONS


def prompt(words, context, src_name, target_names):
    """lithos-server src/thought.ts thoughtPrompt: the FIRST complete sentence or clause, not the largest N."""
    speaker = f"{'an' if src_name[:1] in 'AEIOU' else 'a'} {src_name} speaker"
    names = ", ".join(dict.fromkeys(target_names)) or "the listeners' languages"
    numbered = " ".join(f"{i + 1}:{w}" for i, w in enumerate(words))
    ctx = ("Earlier thoughts (context only, already translated):\n" + "\n".join(f"- {s}" for s in context[-2:]) + "\n"
           if context else "")
    return (f"You are deciding, for live interpreters, when {speaker} has finished a thought. The interpreters "
            f"translate it into {names} while the speaker is still talking. The {src_name} comes from live speech "
            f"recognition: it may contain errors and has little or no punctuation. Spoken words cannot be taken back.\n"
            f"{ctx}Words heard so far that have not been translated yet, numbered:\n{numbered}\n\n"
            f"Do words 1 to N, for some N, form a complete thought: a whole sentence or a whole clause that can be "
            f"translated into each of those languages now, without waiting for more, so that no translation will need "
            f"to change whatever the speaker says next? A part that still needs words not yet said (a verb, an object, "
            f"the rest of a clause, the noun after an article or preposition) is not complete.\n"
            f"If yes, answer only: COMPLETE N, where word N ends the FIRST complete sentence or clause. If the words "
            f"hold more than one complete thought, stop at the end of the first one; never run a thought across a "
            f"sentence end. If not, answer exactly: WAIT")


def parse(text, n):
    """N (1..n) for "COMPLETE N"; None for WAIT or anything else."""
    m = re.search(r"COMPLETE\s*:?\s*(\d+)", text or "", flags=re.I)
    if not m:
        return None
    end = int(m.group(1))
    return end if 1 <= end <= n else None


class ThoughtTurn:
    """The room's one decision stream for one turn. `ask(prompt)` sends a prompt to Gemma (raises on failure);
    `resume(spoken, words)` is where `words` continue past the source words already committed (server.py's
    resume_point, which survives a re-transcription that respells the start)."""

    def __init__(self, ask, resume, src_name, target_names, context=()):
        self.ask, self.resume = ask, resume
        self.src_name, self.target_names, self.context = src_name, list(target_names), list(context)
        self.spoken = []        # source words already committed as thoughts
        self.asked = None       # the tail the last decision saw
        self.last = None        # (N, word N) of the last decision that said COMPLETE
        self.calls = 0
        self.failed = False     # a failed decision ends deciding for this turn: its end translates the rest

    def tail(self, words):
        return words[self.resume(self.spoken, words):]

    def commit(self, piece):
        self.spoken += piece
        self.context.append(" ".join(piece))
        self.asked, self.last = None, None
        return " ".join(piece)

    def step(self, committed):
        """Committed source words so far -> the source text of a thought to translate now, or ""."""
        tail = self.tail(committed)
        if not tail or self.failed:
            return ""
        if len(tail) > THOUGHT_MAX_TAIL:
            return self.commit(tail)
        if tail == self.asked:
            return ""
        self.asked = tail
        self.calls += 1
        try:
            n = parse(self.ask(prompt(tail, self.context, self.src_name, self.target_names)), len(tail))
        except Exception as e:
            print(f"[stack] thought decision failed ({e}): the end of the turn translates the rest", flush=True)
            self.failed = True
            return ""
        if n is None:
            self.last = None
            return ""
        if self.last == (n, tail[n - 1]):      # CT (b): two decisions in a row end at the same word
            return self.commit(tail[:n])
        self.last = (n, tail[n - 1])
        return ""

    def finish(self, words):
        """The turn is over: the source text left to translate."""
        rest = self.tail(words)
        return self.commit(rest) if rest else ""
