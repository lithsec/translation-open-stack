#!/usr/bin/env python3
"""Regression test for simultaneous-mode commit alignment. No GPU, no server.

room_flush used to slice the turn by index -- words[translated_n:] -- which
assumes the prefix never changes between passes. A live read showed it does:

    But behold, my beloved brother, in this kind of world,
    But behold, my beloved brother, and thus came the voice of t
    But behold, my beloved brethren, thus came the voice of the

and the final pass hands room_flush the whole re-transcription. Slicing that
by a count from an earlier, differently-worded pass re-speaks words already
said or skips words never said -- reported as "it's adding lines".

    python3 tests/test_streaming.py
"""
import importlib.util, pathlib, sys

SERVER = pathlib.Path(__file__).resolve().parent.parent / "server"
sys.path.insert(0, str(SERVER))  # server.py imports stack_config from beside it
spec = importlib.util.spec_from_file_location("stack_server", SERVER / "server.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
resume_point = mod.resume_point
trim_point = mod.trim_point
common_prefix_words = mod.common_prefix_words

CASES = [
    # (spoken so far, new transcription, expected emission)
    ([], "But behold my beloved brother", "But behold my beloved brother"),

    # stable prefix -- the ordinary case
    ("But behold, my beloved brother,",
     "But behold, my beloved brother, and thus came the voice",
     "and thus came the voice"),

    ("water and have received the baptism",
     "water and have received the baptism of fire and of the Holy Ghost",
     "of fire and of the Holy Ghost"),

    # a word DROPPED from the prefix shifts every index after it. By index
    # this emits "of the Holy Ghost" and the listener loses "and".
    ("and have received the baptism of fire",
     "have received the baptism of fire and of the Holy Ghost",
     "and of the Holy Ghost"),

    # a word INSERTED in the prefix shifts the other way
    ("Wherefore my beloved brethren I know",
     "Wherefore my beloved brethren I know that if ye shall follow",
     "that if ye shall follow"),
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
    do_pass([], "yea then come with the baptism")
    # pass 2: same prefix, more words -> commits through the agreed prefix
    c2 = do_pass([], "yea then come with the baptism of fire and of")
    # trim: first segment becomes fixed text, decode window now starts later
    fixed = "yea then come with the baptism".split()
    # pass 3: tail-only transcription, fixed prefix prepended
    c3 = do_pass(fixed, "of fire and of the holy ghost")
    ok = (" ".join(c2) == "yea then come with the baptism"
          and " ".join(c3) == "yea then come with the baptism of fire and of")
    return ok, committed_log


def main():
    bad = 0
    for spoken, new, want in CASES:
        sp, nw = spoken.split() if spoken else [], new.split()
        got = " ".join(nw[resume_point(sp, nw):])
        if got != want:
            print(f"  WRONG after {spoken!r}")
            print(f"    new  : {new}")
            print(f"    got  : {got!r}")
            print(f"    want : {want!r}")
            bad += 1
    for ends, buf_s, trim_s, want in TRIM_CASES:
        got = trim_point(ends, buf_s, trim_s)
        if got != want:
            print(f"  WRONG trim_point({ends}, {buf_s}, {trim_s}) "
                  f"= {got}, want {want}"); bad += 1
    ok, log = simulate_trimmed_turn()
    if not ok:
        print(f"  WRONG trimmed-turn agreement, commits were: {log}"); bad += 1
    print(f"{len(CASES)} alignment cases, {len(TRIM_CASES)} trim cases, "
          f"1 simulated turn, {bad} wrong")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
