#!/usr/bin/env python3
"""Regression test for simultaneous-mode commit alignment. No GPU, no server.

room_flush used to slice the turn by index -- words[translated_n:] -- which
assumes the prefix never changes between passes. A live read showed it does:

    But listen, my dear friend, in this kind of weather,
    But listen, my dear friend, and then came the sound of t
    But listen, my dear friends, then came the sound of the

and the final pass hands room_flush the whole re-transcription. Slicing that
by a count from an earlier, differently-worded pass re-speaks words already
said or skips words never said -- reported as "it's adding lines".

    python -m pytest tests/test_streaming.py
"""
import pytest

import support

mod = support.stack_server()        # as server.py re-exports them
resume_point = mod.resume_point
trim_point = mod.trim_point
common_prefix_words = mod.common_prefix_words

CASES = [
    # (spoken so far, new transcription, expected emission)
    ([], "But listen my dear friend", "But listen my dear friend"),

    # stable prefix -- the ordinary case
    ("But listen, my dear friend,",
     "But listen, my dear friend, and then came the sound",
     "and then came the sound"),

    ("payment and have received the receipt",
     "payment and have received the receipt for tickets and for the hotel room",
     "for tickets and for the hotel room"),

    # a word DROPPED from the prefix shifts every index after it. By index
    # this emits "for the hotel room" and the listener loses "and".
    ("and have received the receipt for tickets",
     "have received the receipt for tickets and for the hotel room",
     "and for the hotel room"),

    # a word INSERTED in the prefix shifts the other way
    ("Honestly my dear friends I know",
     "Honestly my dear friends I know that if you will follow",
     "that if you will follow"),
]


TRIM_CASES = [
    # (segment end times, buffer seconds, trim threshold, expected cut)
    ([3.1, 6.2, 9.0], 9.0, 8.0, 6.2),   # long buffer: cut at 2nd-to-last end
    ([3.1, 6.2, 9.0], 7.0, 8.0, None),  # under threshold: leave alone
    ([9.0], 9.0, 8.0, None),            # one segment: nothing safely fixed
    ([], 9.0, 8.0, None),               # no segments (omni path)
    ([0.4, 9.0], 9.0, 8.0, None),       # cut too early to be worth the churn
]


def simulate_trimmed_turn():
    """Three passes over one turn, a trim between passes 2 and 3.

    The invariant trimming must preserve: LocalAgreement sees the same
    full-turn text whether or not audio left the decode window, because the
    fixed prefix is prepended verbatim. A break here re-speaks or drops words.
    """
    last_pass = ""
    committed_log = []

    def do_pass(fixed, tail_text):
        nonlocal last_pass
        full = (" ".join(fixed) + " " + tail_text).strip() if fixed else tail_text
        committed = common_prefix_words(last_pass, full)
        last_pass = full
        committed_log.append(" ".join(committed))
        return committed

    # pass 1: no trim yet
    do_pass([], "yes then come with the receipt")
    # pass 2: same prefix, more words -> commits through the agreed prefix
    c2 = do_pass([], "yes then come with the receipt for tickets and for")
    # trim: first segment becomes fixed text, decode window now starts later
    fixed = "yes then come with the receipt".split()
    # pass 3: tail-only transcription, fixed prefix prepended
    c3 = do_pass(fixed, "for tickets and for the hotel room")
    ok = (" ".join(c2) == "yes then come with the receipt"
          and " ".join(c3) == "yes then come with the receipt for tickets and for")
    return ok, committed_log


@pytest.mark.parametrize("spoken, new, want", CASES)
def test_resume_point(spoken, new, want):
    sp, nw = spoken.split() if spoken else [], new.split()
    got = " ".join(nw[resume_point(sp, nw):])
    assert got == want, f"after {spoken!r}, new {new!r}"


@pytest.mark.parametrize("ends, buf_s, trim_s, want", TRIM_CASES)
def test_trim_point(ends, buf_s, trim_s, want):
    assert trim_point(ends, buf_s, trim_s) == want


def test_trimmed_turn_agreement():
    ok, log = simulate_trimmed_turn()
    assert ok, f"trimmed-turn agreement, commits were: {log}"

