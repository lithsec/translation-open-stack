# Phrase-by-phrase translation against whole sentences and Gemini Live, October 2026

Can a pipeline of separate pieces (streaming recognition, a translator, a voice) start
speaking sooner, the way Gemini Live Translate does, by translating each phrase as soon as
its words stop changing instead of waiting for the end of the sentence? And what does it
cost in accuracy? Per-language policy, measured on the unseen clips of
[`../2026-10-unseen`](../2026-10-unseen/) (20 FLEURS sentences per language, regular and
irregular pauses), with every system graded blind in one round per direction.

## Setup

- **Recognisers**, each clip streamed at real time and every partial kept with its arrival
  time (`stream_partials.py`):
  - **MAI-Transcribe-2-Streaming** (public preview; Speech SDK 1.52.0, a resource in East US 2,
    auto language detection).
  - **Azure standard real-time** (East US, the language's locale): "Azure std" below.
- **Committing words** (`simulate.py`): a word is committed when two consecutive partials
  agree on it, when the audio has been quiet for 300 ms (a client-side VAD: everything heard
  so far), or when the final arrives. Committed words are lined up with the latest hypothesis
  by edit distance, because a recogniser rewrites earlier words (MAI's partials do this
  often). Japanese is compared by character.
- **Policy table** (`POLICY` in `simulate.py`): phrase for English with Spanish, Portuguese,
  French and Italian (both ways); clause for German and Mandarin; sentence for Japanese and
  Korean and for anything Omnilingual hears. Here every phrase system is run on every
  direction, so the Japanese rows show what phrase mode would do there.
- **Phrase rule:** send the pending committed words once there are at least 4 and a clause
  word (and, but, because, which, que, porque, parce que, …) or a comma follows, the audio
  pauses 300 ms, or 5 / 8 words are waiting. Japanese source: 8 to 18 characters, or "、".
- **Continuation translation:** each chunk is sent with the source sentence so far, what has
  already been spoken for it, and the two previous sentences as context; the model outputs only
  the continuation and is told never to repeat or contradict what was spoken. Sentence mode
  gets the translator shootout's prompt with the same context. Translators:
  - Gemma 4 26B and Gemma 4 31B on OpenRouter, reasoning off, zero data retention required on
    every request (`"zdr": true`, `"data_collection": "deny"`).
  - GPT-5.6-sol on Foundry at `reasoning_effort: none` (the deployment does not accept
    "minimal").
- **Timing:** one call at a time per stream, since a continuation needs the previous output:
  a chunk's translation starts at max(commit, previous call done) and takes its measured time.
  The voice adds Azure neural text-to-speech's measured time to first audio (`tts.py`, 24
  real chunks per language: 146–207 ms at the median). "Speech starts → first audio" is from
  the start of a read sentence's speech to the first audio of its translation; "speech ends →
  last audio" is to the start of the last chunk carrying that sentence. Gemini Live: the
  arrival of the first and last text of each sentence's translation (its audio arrives with
  the text).
- **Gemini Live Translate:** `gemini-3.5-live-translate-preview` (AI Studio), re-run on both
  English clips with `../2026-10-es-pt-live-compare/live_translate.mjs`, out of English only.
- **Lining output up with sentences** (`seg_all.py`): every system's spoken stream, the
  simulated ones included, is cut into the read sentences at verbatim anchors, the method
  `../2026-10-es-pt-live-compare/segment.py` uses for Gemini Live. All 128 simulated streams
  and 8 Gemini Live runs were located with no anchor missing.
- **Quality:** `../2026-10-es-pt-live-compare/grade.py` (gemini-pro-latest, systems shuffled
  under letters, 0–3 per sentence plus a critical flag, shown as a share of the possible), all
  9 systems in one call per direction, pause pattern and reference: against what was said
  (English sources: the witness; Spanish, Portuguese, French and Japanese sources: only the
  sentences whose recording matches its text) and against the written text.
- **Chunks wrong later** (`contradictions.py`): the same grader, blind, counts for each
  sentence how many of a system's chunks turned out wrong once the whole sentence is known (a
  guess the rest contradicts, a wrong role or order, a repetition, something a later chunk had
  to correct). Mishearings the whole sentence also carries are not counted.
- **Cost:** translation only, list prices from the actual tokens (Gemma 4 26B $0.076 / $0.255,
  Gemma 4 31B $0.20 / $0.40, sol $4.40 / $22 per million input / output tokens), per hour of
  this read speech. Recognition is extra: MAI-Transcribe-2-Streaming was reported at launch at
  about $0.54 per audio hour (not checked against Microsoft's price list); standard real-time is
  listed at about $1. Gemini Live's price was not checked.

## Results

Means over both pause patterns and the directions in each group; latencies are the medians of
the per-direction medians, in seconds. MAI recognition unless marked "Azure std".

| Group | System | Quality, said | Critical | Speech starts → first audio (s) | Speech ends → last audio (s) | Chunks wrong later | Translation $/h |
|---|---|---|---|---|---|---|---|
| Out of English (es, pt, fr) | Phrase ≤5, Gemma 4 26B | 55.0 | 7.5 | 2.9 | 1.8 | 15% | $0.042 |
| Out of English (es, pt, fr) | Phrase ≤8, Gemma 4 26B | 61.9 | 7.3 | 3.4 | 1.6 | 14% | $0.035 |
| Out of English (es, pt, fr) | Phrase ≤8, Gemma 4 31B | 63.3 | 7.2 | 3.7 | 2.2 | 14% | $0.087 |
| Out of English (es, pt, fr) | Phrase ≤8, sol | 62.0 | 7.2 | 3.6 | 2.0 | 13% | $2.081 |
| Out of English (es, pt, fr) | Phrase ≤8, Gemma 4 31B (Azure std) | 64.7 | 6.5 | 4.4 | 2.0 | 14% | $0.089 |
| Out of English (es, pt, fr) | Sentence, Gemma 4 31B | 68.3 | 5.8 | 11.2 | 4.9 | – | $0.026 |
| Out of English (es, pt, fr) | Sentence, sol | 73.3 | 5.2 | 8.6 | 3.2 | – | $0.744 |
| Out of English (es, pt, fr) | Sentence, Gemma 4 31B (Azure std) | 78.3 | 6.0 | 9.7 | 3.4 | – | $0.022 |
| Out of English (es, pt, fr) | Gemini Live Translate | 52.8 | 8.7 | 1.8 | 3.1 | – | – |
| English → Japanese | Phrase ≤5, Gemma 4 26B | 49.1 | 9.5 | 3.0 | 2.0 | 13% | $0.044 |
| English → Japanese | Phrase ≤8, Gemma 4 26B | 51.7 | 8.5 | 3.7 | 1.8 | 14% | $0.036 |
| English → Japanese | Phrase ≤8, Gemma 4 31B | 54.2 | 9.0 | 4.3 | 2.5 | 14% | $0.089 |
| English → Japanese | Phrase ≤8, sol | 59.1 | 8.5 | 4.2 | 3.4 | 14% | $2.392 |
| English → Japanese | Phrase ≤8, Gemma 4 31B (Azure std) | 58.4 | 7.5 | 4.3 | 1.8 | 12% | $0.094 |
| English → Japanese | Sentence, Gemma 4 31B | 75.0 | 6.0 | 11.8 | 7.7 | – | $0.026 |
| English → Japanese | Sentence, sol | 80.8 | 4.5 | 9.0 | 3.6 | – | $0.881 |
| English → Japanese | Sentence, Gemma 4 31B (Azure std) | 80.8 | 6.5 | 9.8 | 3.2 | – | $0.022 |
| English → Japanese | Gemini Live Translate | 55.9 | 11.0 | 1.9 | 1.8 | – | – |
| Into English (es, pt, fr) | Phrase ≤5, Gemma 4 26B | 65.1 | 2.7 | 2.8 | 1.7 | 14% | $0.047 |
| Into English (es, pt, fr) | Phrase ≤8, Gemma 4 26B | 71.3 | 2.7 | 3.6 | 1.6 | 14% | $0.037 |
| Into English (es, pt, fr) | Phrase ≤8, Gemma 4 31B | 73.8 | 2.8 | 3.8 | 2.0 | 11% | $0.093 |
| Into English (es, pt, fr) | Phrase ≤8, sol | 70.9 | 2.2 | 3.8 | 1.8 | 12% | $2.160 |
| Into English (es, pt, fr) | Phrase ≤8, Gemma 4 31B (Azure std) | 62.6 | 3.7 | 4.3 | 1.6 | 12% | $0.087 |
| Into English (es, pt, fr) | Sentence, Gemma 4 31B | 89.6 | 1.3 | 15.0 | 5.8 | – | $0.019 |
| Into English (es, pt, fr) | Sentence, sol | 90.5 | 1.0 | 10.7 | 3.1 | – | $0.539 |
| Into English (es, pt, fr) | Sentence, Gemma 4 31B (Azure std) | 85.7 | 2.3 | 10.1 | 2.7 | – | $0.019 |
| Japanese → English | Phrase ≤5, Gemma 4 26B | 46.2 | 1.5 | 4.5 | 1.1 | 33% | $0.027 |
| Japanese → English | Phrase ≤8, Gemma 4 26B | 47.2 | 2.5 | 3.8 | 1.0 | 33% | $0.027 |
| Japanese → English | Phrase ≤8, Gemma 4 31B | 48.1 | 2.5 | 4.8 | 1.2 | 34% | $0.068 |
| Japanese → English | Phrase ≤8, sol | 54.7 | 2.5 | 4.9 | 1.4 | 34% | $1.706 |
| Japanese → English | Phrase ≤8, Gemma 4 31B (Azure std) | 50.0 | 2.5 | 5.8 | 1.6 | 14% | $0.065 |
| Japanese → English | Sentence, Gemma 4 31B | 63.0 | 1.5 | 10.8 | 2.7 | – | $0.022 |
| Japanese → English | Sentence, sol | 69.5 | 1.5 | 10.1 | 2.5 | – | $0.646 |
| Japanese → English | Sentence, Gemma 4 31B (Azure std) | 72.2 | 1.0 | 10.0 | 2.1 | – | $0.015 |

## Findings

1. **Phrase mode starts speaking about 5–7 s sooner than whole sentences, and finishes each
   sentence about 1–1.5 s sooner.** Out of English, the first translated audio of a sentence
   comes 3.4–3.7 s after the speaker starts it (8-word phrases on MAI; 4.4 s on Azure standard),
   against 8.6–11.2 s for sentence mode, and the last audio 1.6–2.2 s after the speaker stops,
   against 3.2–4.9 s.
2. **It is still about 1.6–1.9 s slower to start than Gemini Live (1.8 s), but finishes
   sooner.** Gemini Live's last words of a sentence come 3.1 s after the speaker stops (out of
   English, Spanish/Portuguese/French), phrase mode's 1.6–2.2 s. Five-word phrases start 0.5 s
   sooner (2.9 s) but lose about 7 points.
3. **Phrase mode beats Gemini Live on accuracy out of English, by 9–12 points** (62–65 against
   53 against what was said, Spanish, Portuguese and French; fewer critical errors, 6.5–7.3
   against 8.7).
4. **But it costs about 10–15 points against the best whole-sentence systems out of English,
   and 12–28 into English.** Sentence mode scores 68–78 out of English and 86–91 into English;
   phrase mode 62–65 and 63–74. One chunk in seven to nine (11–14%) turns out wrong once the
   sentence is known, out of English and into English alike.
5. **Japanese confirms the policy: whole sentences.** English → Japanese in phrase mode scores
   49–59 against 75–81 for sentence mode (and 56 for Gemini Live), and Japanese → English 46–55
   against 63–72, with a third of chunks wrong later on MAI's partials. The verb-final order
   leaves early chunks guessing.
6. **The translator matters less than the policy in phrase mode.** Gemma 4 31B, Gemma 4 26B
   and sol are within about 3 points of each other out of English; sol phrase mode costs
   about $2 an hour of translation (many calls with long prompts) against $0.035–0.09 for
   Gemma 4. In sentence mode sol leads Gemma 4 31B on MAI's text by 5 points.
7. **Recognisers:** MAI's streaming text had more errors than Azure standard on English (6.1–6.9%
   of characters wrong against what was said, against 3.6–3.7%) and Japanese (11.8–16.1%
   against 6.9–8.0%), slightly fewer on French and Spanish (`results.json` → `recognition`).
   With irregular pauses MAI returned few, long finals (12 for the Spanish clip), so sentence
   mode on MAI spoke a median of 14–20 s after a sentence started (into English), against
   10 s on Azure standard, which finalised more often.
   Phrase mode does not depend on where the recogniser cuts.
8. **The voice is the next bottleneck for every system.** At the default speaking rate the
   Azure voices are slower than these readers, so a continuous 2.7-minute reading builds a
   backlog: waiting for the previous chunk's audio to finish ("queued" in `results.json`), the
   last audio of a sentence comes 8–33 s after the speaker stops out of English into Spanish,
   Portuguese and French, and 24–57 s into Japanese, for sentence and phrase mode alike. A real
   conversation has turns and gaps; a monologue needs a faster speaking rate or shorter
   output. The latencies above are without that queue, as asked.

### Recommended policy

| Language pair | Policy | Why |
|---|---|---|
| English ↔ Spanish, Portuguese, French (Italian by the same rule, not measured) | **Phrase, up to 8 words, as an opt-in fast mode**; whole sentences stay the default | Starts about 5–7 s sooner and beats Gemini Live by 9–12 points out of English, but loses 10–15 points against whole sentences (12–28 into English) |
| English ↔ Japanese (and Korean by the same rule) | **Sentence** | Phrase mode loses 20+ points; a third of chunks wrong into English |
| German, Mandarin | Clause (not measured here) | |
| Anything Omnilingual hears (Haitian Creole, Lao, Khmer) | Sentence | Recognition is the weak link; MAI does not cover them |

Translator for phrase mode: Gemma 4 26B or 31B (zero data retention on OpenRouter); sol adds
nothing there and costs 20–60 times more.

## Limits

- One 20-sentence clip per language and pause pattern, read news sentences joined with
  artificial pauses: not a conversation. One grading round.
- The voice is simulated from measured time to first audio; no audio was played.
- The translation calls were made from one machine with up to 24 streams in parallel (5 for
  sol, which hit Foundry's rate limit; waits for rate limits are not counted in a call's time).
- Chunk-to-audio placement for the phrase-start latency uses the final's audio span shared out
  by characters (MAI returns no word timings).
- Gemini Live text arrives with its audio; its "first audio" is its first text.

## Per direction


### Per direction, regular pauses

| Direction | System | Quality said / written | Critical | Start → first audio p50/p90 | End → last audio p50/p90 | Chunks wrong later | Sentences with no output |
|---|---|---|---|---|---|---|---|
| en-es | Phrase ≤5, Gemma 4 26B | 63.3 / 50.0 | 4 | 3.0 / 9.5 | 2.5 / 10.9 | 8/86 | 0 |
| en-es | Phrase ≤8, Gemma 4 26B | 68.3 / 53.3 | 4 | 3.9 / 7.5 | 1.9 / 4.9 | 4/69 | 0 |
| en-es | Phrase ≤8, Gemma 4 31B | 73.3 / 51.7 | 4 | 3.8 / 5.9 | 2.1 / 3.6 | 5/69 | 0 |
| en-es | Phrase ≤8, sol | 65.0 / 53.3 | 4 | 3.6 / 5.4 | 2.2 / 4.4 | 2/69 | 0 |
| en-es | Phrase ≤8, Gemma 4 31B (Azure std) | 71.7 / 55.0 | 3 | 4.4 / 5.6 | 1.9 / 2.5 | 3/62 | 0 |
| en-es | Sentence, Gemma 4 31B | 68.3 / 60.0 | 3 | 8.1 / 17.7 | 3.0 / 13.5 | – | 0 |
| en-es | Sentence, sol | 80.0 / 70.0 | 3 | 6.7 / 13.7 | 2.8 / 5.5 | – | 0 |
| en-es | Sentence, Gemma 4 31B (Azure std) | 83.3 / 70.0 | 3 | 8.0 / 11.5 | 2.6 / 4.6 | – | 0 |
| en-es | Gemini Live Translate | 48.3 / 35.0 | 3 | 1.7 / 3.1 | 3.5 / 9.6 | – | 2 |
| en-pt | Phrase ≤5, Gemma 4 26B | 53.3 / 41.7 | 11 | 2.6 / 5.2 | 1.8 / 3.7 | 15/85 | 0 |
| en-pt | Phrase ≤8, Gemma 4 26B | 58.3 / 51.7 | 10 | 3.8 / 8.2 | 1.7 / 5.1 | 10/69 | 0 |
| en-pt | Phrase ≤8, Gemma 4 31B | 60.0 / 53.3 | 9 | 3.7 / 7.0 | 2.3 / 5.0 | 12/69 | 0 |
| en-pt | Phrase ≤8, sol | 60.0 / 56.7 | 8 | 4.0 / 5.6 | 2.2 / 3.2 | 12/69 | 0 |
| en-pt | Phrase ≤8, Gemma 4 31B (Azure std) | 61.7 / 53.3 | 10 | 4.4 / 6.2 | 1.7 / 2.5 | 8/62 | 0 |
| en-pt | Sentence, Gemma 4 31B | 65.0 / 60.0 | 8 | 9.7 / 17.9 | 3.6 / 13.5 | – | 0 |
| en-pt | Sentence, sol | 75.0 / 68.3 | 5 | 6.8 / 13.4 | 2.6 / 5.4 | – | 0 |
| en-pt | Sentence, Gemma 4 31B (Azure std) | 75.0 / 61.7 | 8 | 8.0 / 14.3 | 2.7 / 8.8 | – | 0 |
| en-pt | Gemini Live Translate | 48.3 / 43.3 | 12 | 1.8 / 3.2 | 3.7 / 5.1 | – | 0 |
| en-fr | Phrase ≤5, Gemma 4 26B | 56.7 / 46.7 | 6 | 2.8 / 6.7 | 2.1 / 5.3 | 13/86 | 0 |
| en-fr | Phrase ≤8, Gemma 4 26B | 65.0 / 55.0 | 6 | 3.4 / 9.3 | 1.9 / 5.9 | 11/70 | 0 |
| en-fr | Phrase ≤8, Gemma 4 31B | 66.7 / 53.3 | 6 | 4.7 / 23.3 | 2.3 / 17.8 | 8/69 | 0 |
| en-fr | Phrase ≤8, sol | 66.7 / 56.7 | 7 | 4.0 / 5.4 | 2.3 / 3.1 | 7/69 | 0 |
| en-fr | Phrase ≤8, Gemma 4 31B (Azure std) | 68.3 / 53.3 | 4 | 4.7 / 7.0 | 2.3 / 3.6 | 6/62 | 0 |
| en-fr | Sentence, Gemma 4 31B | 68.3 / 63.3 | 5 | 8.5 / 17.4 | 3.2 / 13.3 | – | 0 |
| en-fr | Sentence, sol | 76.7 / 70.0 | 4 | 6.8 / 13.9 | 2.6 / 5.3 | – | 0 |
| en-fr | Sentence, Gemma 4 31B (Azure std) | 78.3 / 66.7 | 4 | 7.9 / 12.4 | 3.0 / 4.6 | – | 0 |
| en-fr | Gemini Live Translate | 53.3 / 48.3 | 9 | 1.5 / 3.1 | 3.2 / 5.1 | – | 0 |
| en-ja | Phrase ≤5, Gemma 4 26B | 55.0 / 45.0 | 7 | 3.3 / 5.8 | 2.0 / 5.4 | 7/85 | 0 |
| en-ja | Phrase ≤8, Gemma 4 26B | 56.7 / 46.7 | 7 | 3.9 / 7.0 | 1.8 / 7.4 | 7/69 | 0 |
| en-ja | Phrase ≤8, Gemma 4 31B | 56.7 / 50.0 | 7 | 3.5 / 5.2 | 1.9 / 3.2 | 9/69 | 0 |
| en-ja | Phrase ≤8, sol | 63.3 / 53.3 | 6 | 3.8 / 5.5 | 2.4 / 2.8 | 7/69 | 0 |
| en-ja | Phrase ≤8, Gemma 4 31B (Azure std) | 61.7 / 53.3 | 5 | 4.3 / 6.0 | 1.8 / 2.5 | 7/62 | 0 |
| en-ja | Sentence, Gemma 4 31B | 73.3 / 66.7 | 6 | 8.5 / 17.2 | 3.2 / 12.6 | – | 0 |
| en-ja | Sentence, sol | 85.0 / 75.0 | 3 | 7.3 / 13.6 | 2.9 / 5.4 | – | 0 |
| en-ja | Sentence, Gemma 4 31B (Azure std) | 85.0 / 71.7 | 5 | 8.3 / 11.8 | 2.8 / 4.5 | – | 0 |
| en-ja | Gemini Live Translate | 61.7 / 45.0 | 9 | 1.9 / 3.2 | 2.0 / 3.2 | – | 0 |
| es-en | Phrase ≤5, Gemma 4 26B | 75.4 / 73.3 | 1 | 2.8 / 4.0 | 1.8 / 3.4 | 8/101 | 0 |
| es-en | Phrase ≤8, Gemma 4 26B | 80.7 / 78.3 | 1 | 3.7 / 5.2 | 1.9 / 5.3 | 3/76 | 0 |
| es-en | Phrase ≤8, Gemma 4 31B | 82.5 / 80.0 | 1 | 3.9 / 6.5 | 2.1 / 5.8 | 3/76 | 0 |
| es-en | Phrase ≤8, sol | 73.7 / 71.7 | 1 | 3.9 / 4.7 | 2.3 / 2.7 | 3/76 | 0 |
| es-en | Phrase ≤8, Gemma 4 31B (Azure std) | 77.2 / 75.0 | 2 | 4.3 / 5.5 | 1.5 / 1.9 | 4/76 | 0 |
| es-en | Sentence, Gemma 4 31B | 93.0 / 90.0 | 2 | 12.0 / 17.3 | 3.0 / 7.8 | – | 0 |
| es-en | Sentence, sol | 94.7 / 91.7 | 2 | 10.3 / 16.3 | 2.6 / 3.0 | – | 0 |
| es-en | Sentence, Gemma 4 31B (Azure std) | 91.2 / 88.3 | 2 | 10.4 / 18.6 | 2.9 / 8.9 | – | 0 |
| pt-en | Phrase ≤5, Gemma 4 26B | 68.3 / 68.3 | 4 | 3.1 / 4.2 | 1.7 / 5.5 | 10/87 | 0 |
| pt-en | Phrase ≤8, Gemma 4 26B | 80.0 / 80.0 | 4 | 3.9 / 6.8 | 1.7 / 8.4 | 5/67 | 0 |
| pt-en | Phrase ≤8, Gemma 4 31B | 81.7 / 81.7 | 4 | 4.0 / 5.1 | 1.9 / 2.9 | 4/67 | 0 |
| pt-en | Phrase ≤8, sol | 83.3 / 83.3 | 3 | 4.4 / 11.9 | 1.9 / 12.4 | 2/67 | 0 |
| pt-en | Phrase ≤8, Gemma 4 31B (Azure std) | 68.3 / 68.3 | 5 | 4.5 / 6.0 | 1.5 / 2.4 | 9/72 | 0 |
| pt-en | Sentence, Gemma 4 31B | 93.3 / 93.3 | 1 | 11.2 / 16.2 | 2.7 / 4.3 | – | 0 |
| pt-en | Sentence, sol | 91.7 / 91.7 | 1 | 10.5 / 16.1 | 2.5 / 2.8 | – | 0 |
| pt-en | Sentence, Gemma 4 31B (Azure std) | 90.0 / 90.0 | 2 | 10.8 / 15.9 | 2.7 / 9.7 | – | 0 |
| fr-en | Phrase ≤5, Gemma 4 26B | 61.7 / 61.7 | 3 | 2.8 / 8.8 | 1.7 / 10.0 | 12/98 | 0 |
| fr-en | Phrase ≤8, Gemma 4 26B | 58.3 / 58.3 | 2 | 3.5 / 8.2 | 1.6 / 8.7 | 16/76 | 0 |
| fr-en | Phrase ≤8, Gemma 4 31B | 61.7 / 61.7 | 2 | 3.7 / 5.0 | 1.8 / 2.9 | 11/76 | 0 |
| fr-en | Phrase ≤8, sol | 58.3 / 58.3 | 2 | 3.7 / 4.5 | 2.2 / 2.5 | 17/76 | 0 |
| fr-en | Phrase ≤8, Gemma 4 31B (Azure std) | 48.3 / 48.3 | 4 | 3.8 / 5.1 | 1.5 / 1.9 | 2/69 | 0 |
| fr-en | Sentence, Gemma 4 31B | 85.0 / 85.0 | 0 | 8.5 / 13.6 | 2.4 / 3.0 | – | 0 |
| fr-en | Sentence, sol | 85.0 / 85.0 | 0 | 8.7 / 13.7 | 2.4 / 3.0 | – | 0 |
| fr-en | Sentence, Gemma 4 31B (Azure std) | 78.3 / 78.3 | 3 | 9.2 / 14.7 | 2.2 / 7.8 | – | 0 |
| ja-en | Phrase ≤5, Gemma 4 26B | 44.4 / 41.7 | 2 | 4.5 / 10.2 | 1.0 / 4.9 | 18/83 | 0 |
| ja-en | Phrase ≤8, Gemma 4 26B | 44.4 / 41.7 | 3 | 3.7 / 6.3 | 1.0 / 3.5 | 22/85 | 0 |
| ja-en | Phrase ≤8, Gemma 4 31B | 48.1 / 45.0 | 2 | 5.1 / 7.4 | 1.3 / 3.8 | 19/84 | 0 |
| ja-en | Phrase ≤8, sol | 53.7 / 50.0 | 3 | 5.1 / 6.5 | 1.5 / 2.7 | 19/82 | 0 |
| ja-en | Phrase ≤8, Gemma 4 31B (Azure std) | 51.9 / 53.3 | 4 | 6.0 / 7.8 | 1.5 / 2.9 | 8/74 | 0 |
| ja-en | Sentence, Gemma 4 31B | 64.8 / 63.3 | 1 | 10.8 / 18.4 | 2.4 / 8.2 | – | 0 |
| ja-en | Sentence, sol | 68.5 / 66.7 | 1 | 10.0 / 13.0 | 2.4 / 2.8 | – | 0 |
| ja-en | Sentence, Gemma 4 31B (Azure std) | 74.1 / 75.0 | 1 | 10.1 / 12.9 | 2.1 / 3.1 | – | 0 |

### Per direction, irregular pauses

| Direction | System | Quality said / written | Critical | Start → first audio p50/p90 | End → last audio p50/p90 | Chunks wrong later | Sentences with no output |
|---|---|---|---|---|---|---|---|
| en-es | Phrase ≤5, Gemma 4 26B | 53.3 / 41.7 | 9 | 3.0 / 12.3 | 1.8 / 12.4 | 9/81 | 0 |
| en-es | Phrase ≤8, Gemma 4 26B | 58.3 / 48.3 | 9 | 3.5 / 9.6 | 1.3 / 4.7 | 6/65 | 0 |
| en-es | Phrase ≤8, Gemma 4 31B | 56.7 / 48.3 | 9 | 3.2 / 5.7 | 1.9 / 4.4 | 7/65 | 0 |
| en-es | Phrase ≤8, sol | 58.3 / 48.3 | 9 | 3.5 / 5.4 | 1.8 / 4.5 | 5/68 | 0 |
| en-es | Phrase ≤8, Gemma 4 31B (Azure std) | 58.3 / 46.7 | 8 | 4.3 / 6.4 | 2.2 / 4.8 | 11/64 | 0 |
| en-es | Sentence, Gemma 4 31B | 68.3 / 58.3 | 7 | 12.9 / 20.9 | 6.2 / 21.3 | – | 0 |
| en-es | Sentence, sol | 71.7 / 63.3 | 7 | 10.5 / 19.7 | 3.9 / 18.9 | – | 0 |
| en-es | Sentence, Gemma 4 31B (Azure std) | 78.3 / 58.3 | 8 | 11.4 / 26.2 | 4.9 / 21.9 | – | 0 |
| en-es | Gemini Live Translate | 51.7 / 45.0 | 11 | 2.0 / 2.9 | 2.9 / 3.6 | – | 0 |
| en-pt | Phrase ≤5, Gemma 4 26B | 50.0 / 45.0 | 10 | 3.0 / 5.0 | 1.8 / 4.6 | 13/80 | 0 |
| en-pt | Phrase ≤8, Gemma 4 26B | 60.0 / 51.7 | 10 | 3.2 / 5.0 | 1.5 / 4.6 | 12/66 | 0 |
| en-pt | Phrase ≤8, Gemma 4 31B | 63.3 / 53.3 | 10 | 3.3 / 5.4 | 1.8 / 4.2 | 13/65 | 0 |
| en-pt | Phrase ≤8, sol | 60.0 / 60.0 | 10 | 3.5 / 5.3 | 1.8 / 4.4 | 13/65 | 0 |
| en-pt | Phrase ≤8, Gemma 4 31B (Azure std) | 63.3 / 50.0 | 10 | 4.2 / 5.9 | 1.9 / 4.5 | 13/63 | 0 |
| en-pt | Sentence, Gemma 4 31B | 70.0 / 65.0 | 8 | 12.9 / 22.0 | 8.9 / 21.9 | – | 0 |
| en-pt | Sentence, sol | 70.0 / 65.0 | 8 | 10.5 / 19.7 | 3.6 / 18.6 | – | 0 |
| en-pt | Sentence, Gemma 4 31B (Azure std) | 76.7 / 63.3 | 9 | 11.4 / 25.8 | 3.8 / 22.0 | – | 0 |
| en-pt | Gemini Live Translate | 55.0 / 51.7 | 11 | 1.9 / 3.2 | 3.0 / 3.9 | – | 0 |
| en-fr | Phrase ≤5, Gemma 4 26B | 53.3 / 48.3 | 5 | 2.7 / 4.5 | 1.6 / 3.4 | 15/81 | 0 |
| en-fr | Phrase ≤8, Gemma 4 26B | 61.7 / 53.3 | 5 | 3.4 / 7.2 | 1.4 / 4.7 | 13/65 | 0 |
| en-fr | Phrase ≤8, Gemma 4 31B | 60.0 / 51.7 | 5 | 4.3 / 13.1 | 2.4 / 11.7 | 11/65 | 0 |
| en-fr | Phrase ≤8, sol | 61.7 / 58.3 | 5 | 3.5 / 5.6 | 1.6 / 4.5 | 13/65 | 0 |
| en-fr | Phrase ≤8, Gemma 4 31B (Azure std) | 65.0 / 51.7 | 4 | 4.1 / 6.0 | 2.2 / 4.6 | 11/63 | 0 |
| en-fr | Sentence, Gemma 4 31B | 70.0 / 65.0 | 4 | 12.8 / 22.2 | 9.1 / 22.1 | – | 0 |
| en-fr | Sentence, sol | 66.7 / 65.0 | 4 | 10.4 / 19.7 | 3.8 / 18.4 | – | 0 |
| en-fr | Sentence, Gemma 4 31B (Azure std) | 78.3 / 65.0 | 4 | 12.1 / 25.4 | 4.9 / 21.5 | – | 0 |
| en-fr | Gemini Live Translate | 60.0 / 51.7 | 6 | 1.8 / 2.7 | 2.5 / 3.4 | – | 0 |
| en-ja | Phrase ≤5, Gemma 4 26B | 43.3 / 38.3 | 12 | 2.8 / 5.1 | 2.0 / 4.9 | 15/82 | 0 |
| en-ja | Phrase ≤8, Gemma 4 26B | 46.7 / 40.0 | 10 | 3.6 / 4.9 | 1.7 / 4.9 | 12/66 | 0 |
| en-ja | Phrase ≤8, Gemma 4 31B | 51.7 / 40.0 | 11 | 5.1 / 17.8 | 3.2 / 18.4 | 10/66 | 0 |
| en-ja | Phrase ≤8, sol | 55.0 / 41.7 | 11 | 4.5 / 30.2 | 4.4 / 23.6 | 11/65 | 0 |
| en-ja | Phrase ≤8, Gemma 4 31B (Azure std) | 55.0 / 41.7 | 10 | 4.2 / 6.7 | 1.9 / 4.7 | 8/63 | 0 |
| en-ja | Sentence, Gemma 4 31B | 76.7 / 61.7 | 6 | 15.0 / 32.3 | 12.2 / 32.7 | – | 0 |
| en-ja | Sentence, sol | 76.7 / 63.3 | 6 | 10.7 / 20.2 | 4.2 / 18.9 | – | 0 |
| en-ja | Sentence, Gemma 4 31B (Azure std) | 76.7 / 66.7 | 8 | 11.2 / 26.3 | 3.7 / 22.5 | – | 0 |
| en-ja | Gemini Live Translate | 50.0 / 43.3 | 13 | 1.9 / 3.3 | 1.6 / 2.9 | – | 0 |
| es-en | Phrase ≤5, Gemma 4 26B | 71.9 / 70.0 | 3 | 2.6 / 3.8 | 1.4 / 3.4 | 14/103 | 0 |
| es-en | Phrase ≤8, Gemma 4 26B | 75.4 / 73.3 | 4 | 3.3 / 4.0 | 1.2 / 4.0 | 15/77 | 0 |
| es-en | Phrase ≤8, Gemma 4 31B | 75.4 / 73.3 | 5 | 3.7 / 4.4 | 2.2 / 4.8 | 13/77 | 0 |
| es-en | Phrase ≤8, sol | 71.9 / 70.0 | 3 | 3.7 / 4.4 | 1.7 / 4.6 | 11/77 | 0 |
| es-en | Phrase ≤8, Gemma 4 31B (Azure std) | 66.7 / 63.3 | 3 | 4.3 / 5.9 | 1.7 / 3.9 | 18/76 | 0 |
| es-en | Sentence, Gemma 4 31B | 89.5 / 86.7 | 2 | 19.8 / 29.5 | 12.3 / 26.0 | – | 0 |
| es-en | Sentence, sol | 93.0 / 93.3 | 1 | 15.5 / 21.6 | 5.2 / 16.7 | – | 0 |
| es-en | Sentence, Gemma 4 31B (Azure std) | 89.5 / 86.7 | 2 | 10.4 / 18.0 | 2.8 / 14.4 | – | 0 |
| pt-en | Phrase ≤5, Gemma 4 26B | 65.0 / 65.0 | 3 | 2.9 / 3.9 | 1.6 / 3.3 | 16/89 | 0 |
| pt-en | Phrase ≤8, Gemma 4 26B | 76.7 / 76.7 | 3 | 3.7 / 4.8 | 1.1 / 4.8 | 7/68 | 0 |
| pt-en | Phrase ≤8, Gemma 4 31B | 81.7 / 81.7 | 3 | 4.2 / 12.5 | 2.1 / 8.2 | 6/68 | 0 |
| pt-en | Phrase ≤8, sol | 80.0 / 80.0 | 2 | 3.9 / 5.0 | 1.6 / 3.8 | 7/68 | 0 |
| pt-en | Phrase ≤8, Gemma 4 31B (Azure std) | 63.3 / 63.3 | 5 | 4.2 / 5.7 | 1.6 / 2.1 | 13/72 | 0 |
| pt-en | Sentence, Gemma 4 31B | 90.0 / 90.0 | 2 | 18.3 / 31.6 | 8.7 / 28.1 | – | 0 |
| pt-en | Sentence, sol | 90.0 / 90.0 | 2 | 13.9 / 21.1 | 3.9 / 15.2 | – | 0 |
| pt-en | Sentence, Gemma 4 31B (Azure std) | 88.3 / 88.3 | 2 | 9.7 / 13.3 | 2.2 / 3.7 | – | 0 |
| fr-en | Phrase ≤5, Gemma 4 26B | 48.3 / 48.3 | 2 | 2.4 / 3.6 | 2.0 / 3.1 | 19/98 | 0 |
| fr-en | Phrase ≤8, Gemma 4 26B | 56.7 / 56.7 | 2 | 3.3 / 6.3 | 2.2 / 6.4 | 18/74 | 0 |
| fr-en | Phrase ≤8, Gemma 4 31B | 60.0 / 60.0 | 2 | 3.5 / 4.4 | 1.5 / 3.9 | 13/74 | 0 |
| fr-en | Phrase ≤8, sol | 58.3 / 58.3 | 2 | 3.5 / 5.1 | 1.7 / 8.7 | 14/74 | 0 |
| fr-en | Phrase ≤8, Gemma 4 31B (Azure std) | 51.7 / 51.7 | 3 | 3.8 / 5.5 | 1.9 / 4.3 | 8/72 | 0 |
| fr-en | Sentence, Gemma 4 31B | 86.7 / 86.7 | 1 | 18.1 / 25.1 | 11.6 / 20.0 | – | 0 |
| fr-en | Sentence, sol | 88.3 / 88.3 | 0 | 10.9 / 20.4 | 3.6 / 15.0 | – | 0 |
| fr-en | Sentence, Gemma 4 31B (Azure std) | 76.7 / 76.7 | 3 | 9.8 / 20.6 | 3.0 / 15.0 | – | 0 |
| ja-en | Phrase ≤5, Gemma 4 26B | 48.1 / 45.0 | 1 | 4.5 / 5.8 | 1.1 / 3.0 | 39/89 | 0 |
| ja-en | Phrase ≤8, Gemma 4 26B | 50.0 / 46.7 | 2 | 3.9 / 5.6 | 0.9 / 1.9 | 36/89 | 0 |
| ja-en | Phrase ≤8, Gemma 4 31B | 48.1 / 45.0 | 3 | 4.4 / 7.0 | 1.0 / 2.2 | 40/90 | 0 |
| ja-en | Phrase ≤8, sol | 55.6 / 51.7 | 2 | 4.7 / 6.9 | 1.3 / 1.6 | 39/86 | 0 |
| ja-en | Phrase ≤8, Gemma 4 31B (Azure std) | 48.1 / 50.0 | 1 | 5.6 / 8.4 | 1.6 / 2.9 | 12/69 | 0 |
| ja-en | Sentence, Gemma 4 31B | 61.1 / 60.0 | 2 | 10.7 / 16.5 | 3.0 / 13.0 | – | 0 |
| ja-en | Sentence, sol | 70.4 / 68.3 | 2 | 10.2 / 12.9 | 2.5 / 10.4 | – | 0 |
| ja-en | Sentence, Gemma 4 31B (Azure std) | 70.4 / 71.7 | 1 | 9.9 / 13.5 | 2.1 / 3.7 | – | 0 |


## Files

- `stream_partials.py`: real-time streaming to MAI or Azure standard, keeping every partial.
- `simulate.py`: the commit rule, the policy table, continuation and sentence prompts, the
  translation calls and the timing.
- `tts.py`: Azure neural voice time to first audio and speaking rate.
- `seg_live.py`, `seg_all.py`: cutting Gemini Live's and every simulated system's output into
  the read sentences.
- `analyze.py`: grading jobs, latency, cost, the table; `contradictions.py`: chunks wrong later.
- `results.json`: every direction, pattern and system.

The recordings, translations and grades stay outside the repository (FLEURS audio is fetched
by `../2026-10-unseen/build_clips.py`).
