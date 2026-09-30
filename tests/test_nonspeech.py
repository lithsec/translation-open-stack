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

    python3 tests/test_nonspeech.py
"""
import importlib.util, pathlib, sys

SERVER = pathlib.Path(__file__).resolve().parent.parent / "server"
sys.path.insert(0, str(SERVER))  # server.py imports stack_config from beside it
spec = importlib.util.spec_from_file_location("stack_server", SERVER / "server.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
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


def main():
    bad = 0
    for t in DROP:
        if not is_nonspeech(t):
            print(f"  MISS (should drop): {t!r}"); bad += 1
    for t in KEEP:
        if is_nonspeech(t):
            print(f"  FALSE POSITIVE (should keep): {t!r}"); bad += 1
    for text, p, want in MEASURED:
        if drops(text, p) != want:
            print(f"  WRONG (measured): {text!r} p={p} -> "
                  f"drop={drops(text, p)}, expected {want}"); bad += 1
    print(f"{len(DROP)} drop-cases, {len(KEEP)} keep-cases, "
          f"{len(MEASURED)} measured segments, {bad} wrong")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
