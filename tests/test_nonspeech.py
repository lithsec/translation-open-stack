#!/usr/bin/env python3
"""Regression test for the non-speech filter. No GPU, no server, no models.

Every DROP case below was produced by this pipeline from a real recording:
eight coughs (ESC-50 class 24) streamed through the stack came back as
"Cough, cough, cough.", "ぷっぷっ" and "ご視聴ありがとうございました", and the
Spanish listeners heard "Tos, tos, tos." Confidence cannot separate these --
they arrive at no_speech_prob 0.50-0.66, the same range as quiet real speech --
so the filter reads the content instead.

Every KEEP case is something a congregation actually says. "Holy, holy, holy."
is here because an earlier version of the repetition rule dropped it.

    python -m pytest tests/test_nonspeech.py
"""
import pytest

import support

mod = support.stack_server()        # the filter, as server.py re-exports it
is_nonspeech = mod.is_nonspeech

DROP = [
    "Cough, cough, cough.", "Cough, cough.", "Tos, tos, tos.",
    "ぷっぷっ", "ご視聴ありがとうございました", "ご視聴ありがとうございます",
    "[Music]", "(coughing)", "*cough*", "♪♪♪", "...", "  ", "!?",
    "Ha, ha, ha.", "ha ha", "Uh, uh.", "Laughter", "APPLAUSE",
    "Gracias por su comentario.", "Thanks for watching!",
]

KEEP = [
    "Amen.", "Yes.", "Hallelujah.", "Praise the Lord.", "Amen, amen.",
    "Holy, holy, holy.", "Holy, holy, holy, Lord God Almighty.",
    "Glory, glory, hallelujah.", "No, no, no, I mean it.",
    "Thank you.", "Thank you very much.", "Gracias.",
    "The Lord is my shepherd; I shall not want.",
    "Good morning, and welcome to our service today.",
    "He restoreth my soul.",
]


# Real segments from a measured run, with the no_speech_prob whisper reported
# for each. The short-noise rule is a SECONDARY gate on one- or two-token
# segments; these cases pin the margin it depends on (real short speech topped
# out at 0.223, coughs bottomed out at 0.501).
MEASURED = [
    # (text, no_speech_prob, should_drop)
    ("Oh", 0.650, True),
    ("Coo-coo.", 0.555, True),
    ("Cough cough", 0.707, True),
    ("Cough, cough, cough.", 0.521, True),
    ("ぷっぷっ", 0.660, True),
    ("I'm out.", 0.501, True),
    ("Amen.", 0.048, False),
    ("Yas.", 0.223, False),
    ("Hallelujah!", 0.084, False),
    ("Praise the Lord.", 0.047, False),
    ("Thank you very much.", 0.013, False),
    ("Holy, holy, holy.", 0.100, False),
    ("The Lord is my shepherd, I shall not want.", 0.035, False),
]


def drops(text, no_speech):
    """The whole segment decision, as transcribe() applies it."""
    return (is_nonspeech(text)
            or (mod.content_units(text) <= mod.SHORT_NOISE_UNITS
                and no_speech > mod.SHORT_NOISE_P))


@pytest.mark.parametrize("text", DROP)
def test_drops(text):
    assert is_nonspeech(text), f"MISS (should drop): {text!r}"


@pytest.mark.parametrize("text", KEEP)
def test_keeps(text):
    assert not is_nonspeech(text), f"FALSE POSITIVE (should keep): {text!r}"


@pytest.mark.parametrize("text, no_speech, want", MEASURED)
def test_measured_segments(text, no_speech, want):
    assert drops(text, no_speech) == want, f"WRONG (measured): {text!r} p={no_speech} -> drop={not want}"

