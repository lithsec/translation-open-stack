# End-to-end latency of the live translation routes, October 2026

How long a listener waits, after the speaker finishes a sentence, before the
translation starts to sound in their ear, for each route Live Translation
(LT) offers, with quality graded alongside so speed is not judged blind.

Date: 2026-10-20. Run from a Mac on a US Northeast (Massachusetts) wired
connection, so the round trip to each cloud is included. Every cloud
endpoint was in the US: Azure Speech eastus, Azure AI Foundry eastus
(DataZoneStandard), Google's Gemini API (global endpoint), and omni-stt on
Cloud Run (US East).

Seconds; p50 / p90 over 40 sentences (2 rounds × 20). "Stop" is the moment the speaker finishes the sentence. Negative = it was already speaking. Routes are sorted by speed within each direction. Quality is the judge's mean as % of the maximum; missing = sentences with no translation.

| Pair | Route | Stop → first audio p50 / p90 (s) | Stop → audio of last words p50 / p90 | Stop → first caption p50 | Start → first audio p50 | Stop → end of its audio p50 | Voiced before speaker finished | Quality (missing) |
|---|---|---|---|---|---|---|---|---|
| en-es | `azure-gemini-stream` | -3.7 / 1.2 | – | -3.8 | 2.7 | 6.1 | 83% | 35% (10/40) |
| en-es | `gemini-lt` | -5.0 / -2.5 | – | -5.1 | 1.9 | 3.2 | 100% | 57% (0/40) |
| en-es | `azure-foundry` | 1.5 / 3.5 | 2.3 / 3.6 | 1.2 | 8.1 | 8.9 | 33% | 64% (0/40) |
| en-es | `azure-gemini` | 2.3 / 7.4 | 5.3 / 9.2 | 2.0 | 9.9 | 11.4 | 23% | 57% (1/40) |
| es-en | `azure-gemini-stream` | -5.3 / -1.0 | – | -5.3 | 3.8 | 6.1 | 91% | 27% (17/40) |
| es-en | `gemini-lt` | -6.6 / -2.9 | – | -6.8 | 1.7 | 3.2 | 100% | 70% (0/40) |
| es-en | `azure-foundry` | -1.6 / 2.1 | 2.1 / 3.0 | -1.8 | 6.4 | 7.6 | 70% | 61% (0/40) |
| es-en | `azure-gemini` | 0.7 / 3.9 | 5.2 / 8.5 | 0.4 | 9.4 | 10.0 | 40% | 60% (0/40) |
| en-ja | `azure-gemini-stream` | -2.5 / 2.0 | – | -2.9 | 3.7 | 6.1 | 75% | 51% (0/40) |
| en-ja | `gemini-lt` | -4.6 / -2.4 | – | -5.0 | 2.3 | 3.1 | 100% | 42% (0/40) |
| en-ja | `azure-foundry` | 1.9 / 3.5 | 2.5 / 4.2 | 1.6 | 8.7 | 9.8 | 25% | 69% (0/40) |
| en-ja | `azure-gemini` | 2.9 / 6.4 | 4.7 / 8.8 | 2.3 | 10.3 | 10.2 | 18% | 42% (1/40) |
| km-en | `azure-gemini-stream` | -7.4 / -4.1 | – | -7.4 | 3.2 | 4.8 | 97% | 39% (0/40) |
| km-en | `gemini-lt` | -8.5 / -3.1 | – | -8.9 | 3.5 | 3.3 | 100% | 36% (0/40) |
| km-en | `azure-gemini` | -3.0 / 3.4 | 4.1 / 7.9 | -3.0 | 8.5 | 9.0 | 64% | 33% (1/40) |
| km-en | `azure-foundry` | -2.1 / 3.6 | 4.4 / 7.2 | -2.7 | 8.9 | 9.2 | 65% | 45% (0/40) |
| ht-en | `gemini-lt` | -6.4 / -1.8 | – | -7.5 | 3.1 | 2.9 | 90% | 31% (0/40) |
| ht-en | `ht-exception` | 4.4 / 5.8 | 4.6 / 7.0 | 4.1 | 12.9 | 9.7 | 12% | 73% (0/40) |
| en-ht | `gemini-lt` | -4.4 / -2.2 | – | -4.7 | 1.9 | 2.9 | 100% | 55% (0/40) |
| en-ht | `ht-voice-coqui` | 2.5 / 4.2 | 3.3 / 4.9 | 2.3 | 9.2 | 13.2 | 17% | 68% (0/40) |
| en-ht | `ht-voice-gemini` | 3.8 / 6.7 | 5.1 / 6.8 | 2.2 | 10.8 | 13.9 | 14% | 67% (0/40) |


## Routes

These are Live Translation's own provider classes (LT `main` at `dcd52c7`,
`src/main/providers/*`), each wrapped in its reconnecting session as the
app's audio router wraps it. They were run from a scratch copy (`harness/setup_lt.sh`). The
code was not changed apart from two passive `__probe` hooks in `azure.ts`
(`harness/azure-probes.patch`) that log each Azure or Omnilingual final with
its audio span. Key and log helpers are replaced by stubs that read
the environment.

| Route | What it is | Models |
|---|---|---|
| `azure-foundry` | Azure + Foundry: Azure STT (150 ms segmentation, LT's setting) → Foundry deployment translates each final → Azure neural voice | Azure Speech SDK 1.52; `gpt-5.6-sol-us` (reasoning low); locale default voice |
| `azure-gemini` | Azure + Gemini, sentence mode: each Azure final to a fresh Gemini Live session that translates and speaks it | `gemini-2.5-flash-native-audio-preview-09-2025` (LT's default voice model) |
| `azure-gemini-stream` | Azure + Gemini, streaming mode: Azure's stable partial words to one Gemini Live session, 3 words at a time | `gemini-3.8-live` (what LT recommends for this mode) |
| `gemini-lt` | Gemini Live Translate, speech to speech, target language only, voice Kore | `gemini-3.5-live-translate-preview` |
| `ht-exception` | Haitian Creole exception, speaker language on auto: omni-stt `/listen` (Omnilingual) hears the room beside Azure, Foundry translates its Haitian sentences, the English Azure voice speaks | omni-stt (Cloud Run), `gpt-5.6-sol-us` |
| `ht-voice-gemini` | English → Haitian Creole on Azure + Foundry, Gemini reading the translation (LT's default Haitian voice) | Gemini 2.5 native audio, read mode |
| `ht-voice-coqui` | the same with omni-stt `/speak?voice=coqui` (Coqui VITS OpenBible) | omni-stt |

Open stack (RunPod): not run. No stack pod was running, and starting one was
out of scope for this round. September's measurement stands: about 0.8 s from
the speaker stopping to the first audio.

## Audio and method

- Clips (`build_clips.py`): 20 read sentences per language. English, Japanese
  and Khmer are FLEURS (google/fleurs, CC BY 4.0), and Spanish is FLEURS
  es_419. All four are the same 20 FLoRes sentences, so FLoRes's own text is
  the reference in every direction. Haitian Creole is CMU Haitian Creole
  speech (© 2010 LTI, Carnegie Mellon University, used under its COPYING
  terms). Its English references were written by Gemini 2.5 Pro (see
  `../2026-10-real-voices`). Between sentences there is a seeded pause of
  1.0–2.0 s, the same pauses in every language. The audio is not committed.
- Streaming: 100 ms chunks of 16 kHz PCM16 at real-time pace. Each chunk is
  sent when its 100 ms ends, as a microphone delivers it, and every
  timestamp is on that timeline. The room is opened 1.5 s before the clip
  starts. For the omni-stt routes it is 5 s, and both of omni-stt's sockets
  are first woken (Cloud Run scales to zero; a cold start is about 40 s,
  paid once per service, not per sentence). After the clip, room tone runs
  until 10 s pass with no output.
- Speech start and end come from the audio itself, not from the padded
  sentence marks.
- First audio means the first voiced 10 ms frame (RMS above about −47 dBFS),
  not the first byte. Gemini Live Translate streams silence continuously.
- Which output belongs to which sentence:
  - Pipelines are matched exactly: each final's audio span maps to a
    sentence, and each caption carries its final's source text.
  - Streaming routes are matched by gemini-3.5-flash. It labels each
    transcript piece with its source sentence, and each voiced chunk takes
    the label of the latest piece that arrived by 250 ms after it. See the
    header of `analyze.py`.
- Two full rounds (`r2`, `r3`). Sessions ran in parallel, a few at a time.
  The Foundry runs were never run alongside each other, because the
  deployment's quota is 50 requests/min: four together hit 429 in a
  discarded first attempt.
- Quality: gemini-3.5-flash grades each sentence 0–3, using the
  real-voices rubric: 3 is correct and natural, 0 is wrong or missing. It
  also flags critical errors (a number, name or negation wrong). The score
  shown is the mean as a percentage of 3.

    bash harness/setup_lt.sh <live-translation checkout> origin/main <scratch>
    python3 build_clips.py ../2026-10-real-voices <clips>
    set -a; . <your env file, see harness/env.example>; set +a
    bash harness/round.sh <scratch> <clips> r2 <runs>      # Foundry runs: one at a time
    EVAL_LOCATION="..." python3 analyze.py <clips> <runs> results.json

`results.json` has one entry per route and direction. It holds p50/p90 of
every measure, the share of sentences voiced before the speaker finished,
and quality. The `metric_notes` field defines each measure.

## What it shows

- **Pipelines, after the speaker stops:** use the "audio of last words"
  column. Azure + Foundry is the fastest pipeline in every direction. It
  starts the sentence's last segment 2.1–2.5 s after the stop (p90
  3.0–4.2 s) into Spanish, English and Japanese, and 4.4 s from Khmer.
  Azure + Gemini, sentence at a time, takes 4–5 s, because each Gemini Live
  session needs 1.5–3 s before it starts speaking. Azure + Foundry also
  graded best of the pipelines (61–69%; 45% from Khmer).
- **The negative numbers are real.** Azure ends a segment on a 150 ms
  pause, so 25–70% of sentences reach the listener in pieces, and their
  first piece sounds before the speaker has finished. The "first audio"
  column therefore goes below zero for Spanish→English and Khmer→English.
- **Streaming routes speak while the speaker is still talking.**
  - Gemini Live Translate starts 1.7–3.5 s after the speaker starts. It
    finishes each sentence 2.9–3.3 s after the speaker does, against
    7.6–9.8 s for Azure + Foundry. It was the fastest route in every
    direction by both measures, and the best graded from Spanish (70%). It graded below the
    Foundry pipeline into Japanese (42% vs 69%), from Khmer (36% vs 45%)
    and from Haitian Creole (31% vs 73%), where it hears French.
  - Azure + Gemini streaming (gemini-3.8-live) starts 2.7–3.8 s after the
    speaker starts and finishes each sentence 4.8–6.1 s after the speaker
    does.
- **Azure + Gemini streaming went silent twice.** In 2 of its 8 runs
  (en→es at 88 s, es→en at 32 s) Gemini stopped answering for the rest of
  the clip. LT's reconnecting wrapper never stepped in: Azure's partials
  keep `busy()` true. Over the runs that did not stall it graded 37–53%,
  below the sentence modes.
- **Haitian Creole:**
  - From Haitian (`ht-exception`), the translation starts 4.4 s after the
    stop (p90 5.8 s). The delay comes from Omnilingual's utterance end,
    plus Foundry at reasoning 'low', plus the voice. It is the best graded
    route for Haitian (73%).
  - Into Haitian, Coqui on omni-stt starts sooner than Gemini read mode
    (3.3 vs 5.1 s for the last words), at the same grade (68% vs 67%). But
    Coqui output runs 218 s (with its pauses) for 144 s of English. A listener
    who hears every sentence falls behind (see `stop_to_first_audio_played_ms`).
- **Played vs arrival:** `stop_to_first_audio_played_ms` adds the wait
  behind the previous sentence's audio. With 1–2 s pauses, Azure's voices
  and Coqui (whose output also carries silence) build a queue: a median of
  14–32 s into Spanish, Japanese and Haitian. The Gemini voices and Gemini
  Live Translate stay near real time. The pauses here are short, so this
  shows a backlog under continuous speech. It does not measure how quickly
  a route responds.

## Caveats

- One location and one afternoon (2026-10-20, about 14:00–17:00 US
  Eastern), on Azure S0 (eastus) and Foundry DataZoneStandard at 50
  requests/min. Two rounds, so n = 40 sentences per route and direction,
  pooled.
- Before LT's reconnecting wrapper was added, a first attempt was discarded.
  It also ran on an F0 Azure key (throttled) and recorded no voicing. In
  that attempt Gemini Live Translate on Haitian Creole replied "I'm just a
  language model…", then went silent until its watchdog. With the wrapper,
  as in the app, it redials.
- Foundry returned 429 even with a single session in one round (5–7
  sentences per run). That round was rerun (`r4`), and every Foundry run
  kept here is free of 429s. Treat a 50 RPM deployment as tight for one
  room.
- Streaming sentence attribution comes from an LLM label. Boundaries are
  fuzzy to within one transcript piece (about 1 s).
- The quality judge is gemini-3.5-flash and may favour Gemini outputs. The
  Haitian→English references are model-made, and English→Haitian has no
  reference. The rubric is strict: speech recognition errors such as
  numbers and names count. Read the scores as a ranking within a
  direction, not as absolute quality.
- Read speech with clean pauses: not preaching, not a room's echo, no
  language switching. LT's per-room settings were used: fixed speaker
  language, and auto for the Haitian exception.
- Open stack not measured, since no pod was running (see Routes).
- Audio outputs were not kept. The per-sentence texts and timings are
  regenerated by `analyze.py` from the run logs, which hold no audio.

