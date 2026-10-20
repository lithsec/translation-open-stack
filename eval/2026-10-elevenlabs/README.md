# ElevenLabs, October 2026

Two questions, both about filling gaps the Azure → Gemini pipeline leaves:

1. **Hearing — Scribe v2 Realtime.** Can it hear Haitian Creole live (Azure
   can't)? Run on the real-voice clips (CMU Haitian Creole speakers; FLEURS for
   the others) by [`../2026-10-real-voices/elevenlabs_stt.mjs`](../2026-10-real-voices/elevenlabs_stt.mjs),
   told the language and, for Haitian Creole, not; scored by
   `score_transcribe_live.py` beside Azure, Gemini transcribe-live and
   Omnilingual (same CER, same per-sentence delay).
2. **The voice — Flash v2.5 and v4 Turbo.** As the room's voice after Gemini
   translates the text: time to first audio and how it sounds, on September's
   24 sentences per language (numbers, times, doses, negations) —
   `elevenlabs_tts.mjs`. The models' own lists (19 October 2026): Flash v2.5
   speaks 32 languages, without Persian, Lao, Khmer or Haitian Creole; v4 and
   v4 Turbo speak 94, adding Persian and Lao; no model lists Haitian Creole or
   Khmer. Those are read anyway and marked "not listed".

Run it all with `bash run.sh <file with the key>` (an env file with
`ELEVENLABS_API_KEY=`, or the bare key on its own line). The key needs
speech-to-text and text-to-speech; one without `models_read` still works (the
language list is then not checked). Audio and raw outputs (`out/`) are not
committed.

**Retention:** according to ElevenLabs'
[Zero Retention Mode page](https://elevenlabs.io/docs/eleven-api/resources/zero-retention-mode),
it retains data by default, and zero retention (`enable_logging=false`) is for
Enterprise customers only. This test uses public corpora
only; nothing here says ElevenLabs keeps nothing.

## Results

Not run yet.
