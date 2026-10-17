# Real voices, October 2026

The October Azure round again, with people instead of synthetic voices:

| Language | Audio | Reference (graded against) |
|---|---|---|
| English, Japanese, Khmer, Lao | **FLEURS** (google/fleurs, CC BY 4.0): native speakers reading the same 30 FLoRes sentences, one recording per sentence, alternating men and women | FLoRes's own professional translations: English for the others, each language's text for English into it |
| Haitian Creole | **CMU Haitian Creole speech** (speech.cs.cmu.edu/haitian; 1997–98, read by native speakers): 30 sentences from 30 speakers | **Model-made**: Gemini 2.5 Pro translated the sentences once (`make_refs.py`); CMU has no English |

Acknowledgement: Haitian Creole speech data © 2010 Language Technologies
Institute, Carnegie Mellon University, used under its COPYING terms.

Each recording's silence at both ends is trimmed (relative to its own loudness)
and the sentences joined with 0.8 s pauses, as in the synthetic rounds. Read
speech, not preaching: real voices and accents, not spontaneous speech or a
church room's echo.

Directions: English into Japanese, Khmer, Lao, Haitian Creole; Japanese, Khmer,
Lao into English (all three systems); Haitian Creole into English (Gemini Live
only: Azure can't hear Haitian Creole).

    .venv/bin/python fetch_audio.py      # ~1.6 GB streamed, ~30 s of audio kept per sentence set
    python3 make_refs.py                 # English meaning files (Gemini for Haitian Creole)
    bash run.sh <env file with AZURE_SPEECH_KEY and AZURE_SPEECH_REGION>

Scripts other than these come from `../2026-10-azure-stt-gemini`, with the
grader reading each clip's own sentences and references.
