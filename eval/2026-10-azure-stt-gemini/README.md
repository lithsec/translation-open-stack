# Azure speech-to-text → Gemini voice, October 2026

Does better *hearing* fix Gemini? September's evaluation found Gemini Live's
losses were "mostly mishearings, not mistranslations"
([`docs/dev/model-evaluation.md`](../../docs/dev/model-evaluation.md)). This
round puts Azure's live speech-to-text in front of Gemini — Azure transcribes
the speaker once, each finished sentence goes as text to a Gemini Live session
that says the translation — and runs Gemini Live Translate on the same audio
as the baseline.

| Step | Script |
|---|---|
| Source audio: September's 24 sentences, macOS voices (en, ja, zh) and Meta MMS (km, lo, ht), 0.8 s pauses | `make_audio.py` |
| Azure live speech-to-text, fed in real time | `azure_stt.mjs` |
| Azure's text → Gemini Live (text in, voice out); and Gemini Live Translate on the audio | `gemini_live.mjs pipe` / `live` |
| Blind grading with September's grader and prompt; delay; character error rate of what each one heard | `judge.py` |

Directions: English → Japanese, Mandarin, Khmer, Lao, Haitian Creole, and each
of those → English.

**Delay** is measured per sentence: from the end of the sentence in the clip to
the start of the next translated audio, median over the 24.

Run it all with `bash run.sh <env file with AZURE_SPEECH_KEY and AZURE_SPEECH_REGION>`
(Gemini uses your `gcloud` login and project). Audio, raw outputs and the venv
are not committed; `results.json` is.
