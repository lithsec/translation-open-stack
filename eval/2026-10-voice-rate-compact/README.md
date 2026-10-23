# Voice speaking rate and concise translations, October 2026

The phrase-by-phrase round ([`../2026-10-simultaneous-phrases`](../2026-10-simultaneous-phrases/)) found that
the voice, not recognition or translation, now sets the lag. At Azure's default speaking rate the
translated audio of a 2.7-minute read monologue is longer than the monologue, so it falls behind and
never catches up. This round asks how much a faster speaking rate and a concise, interpreter-style
prompt help. It also checks what they cost, measured with grading built for shorter output.

## Setup

- **Input:** the unseen English clips ([`../2026-10-unseen`](../2026-10-unseen/)), regular and irregular
  pauses, 20 FLEURS sentences each (163 s). Recognition is the Azure standard real-time partials recorded
  for the phrase round and replayed through the same commit policy. Nothing was re-streamed.
- **Directions:** English → Spanish, Portuguese and French.
- **Translator:** Gemma 4 31B on OpenRouter, with zero data retention required. It runs in two modes:
  - **phrase mode:** up to 8 words, continuation prompt (`P8`)
  - **whole sentences:** the control (`S`)
- **Variants:**

| | Prompt | Speaking rate |
|---|---|---|
| V0 | current | +0% |
| V1 | current | +10% |
| V2 | current | +20% |
| V3 | concise | +15% |
| V4 | concise | +0% |

- **Concise prompt:** the current prompt, plus: *"Speak like a professional interpreter: keep every fact,
  name, number, negation and qualifier; drop filler, repetition and redundant words; prefer shorter
  phrasing."*
- **Where the translations come from:** the current-prompt translations are the phrase round's own
  (`P8-gemma31-std`, `S-gemma31-std`). The concise ones were made the same way (`translate.py`).
- **The rate doesn't change the words.** V0, V1 and V2 share one text, and V3 and V4 the other, so the
  text measures below are the same within each group.
- **Voice:** every chunk of every variant was synthesised with Azure neural voices (es-ES Elvira,
  pt-BR Francisca, fr-FR Denise) at the variant's SSML `prosody rate` (`tts_rates.py`). Audio lengths
  are measured, not estimated. Time to first audio was 152 ms at the median.
- **Backlog** (`table.py`): one voice, chunks played in order, none skipped. A chunk's audio starts when
  its translation is done plus its measured time to first audio, or when the previous chunk's audio
  ends, whichever is later. Three timings:
  - **last:** when a sentence's last chunk starts playing, after the speaker finishes that sentence.
  - **heard:** when the listener has heard all of that sentence.
  - **end:** when all audio has finished, after the speaker's last word.

## Grading shorter output

A single faithfulness score marks a concise rendering down for dropping words that carried no meaning,
so this round uses four measures (`grading.py`):

1. **Meaning units.**
   - *Fixed list.* Before any translation was seen, the grader listed each English sentence's meaning
     units from the "what was said" reference: facts, names, numbers, dates, negations, qualifiers and
     who-did-what. That gave 76 units for 20 sentences, each marked essential or minor, reused for every
     system.
   - *Labels.* Then, blind and one system per call, each unit was labelled conveyed, missing or
     distorted.
   - *Reported:* **recall** (essential units conveyed) and **distortion** (units made wrong, out of all
     units). Distortion is the number that matters: compaction may drop filler but must never change a
     fact.
2. **Listener questions.** 32 factual questions with reference answers were written from the reference
   at the same time as the units.
   - *Answering:* a separate call answered them from the interpretation alone, never seeing the English.
   - *Scoring:* a third call scored those answers against the reference answers (correct = 1,
     partial = ½).
   - This is what a listener comes away knowing.
3. **The usual 0–100 blind grade**, with critical errors, for comparison with earlier rounds. It used the
   grader of [`../2026-10-es-pt-live-compare`](../2026-10-es-pt-live-compare/) (`gemini-pro-latest`), with
   all four texts side by side in one call per direction, against what was said and against the written
   text.
4. **Compression:** characters and seconds of audio per sentence, relative to V0.

Listening samples (the first three sentences of each direction and variant, phrase mode) were made
for a human check of naturalness. They are not in the repository.

## Results

Averages over the three directions and both pause patterns. Per-direction rows are in `results.json`.

**Phrase mode (P8)**

| | Units recall | Distortion | Questions | 0–100 (said) | Critical | Characters | Audio | Last p50 / p90 | End |
|---|---|---|---|---|---|---|---|---|---|
| V0 current +0% | 84.6 | 11.8% | 84.4 | 55.5 | 30 | 1.00 | 1.00 | 23.6 / 41.6 s | 46.3 s |
| V1 current +10% | 84.6 | 11.8% | 84.4 | 55.5 | 30 | 1.00 | 0.91 | 15.4 / 25.9 s | 28.9 s |
| V2 current +20% | 84.6 | 11.8% | 84.4 | 55.5 | 30 | 1.00 | **0.84** | **10.7 / 15.6 s** | **16.8 s** |
| V3 concise +15% | 84.1 | 12.7% | 85.4 | 59.2 | 31 | 0.99 | 0.87 | 12.2 / 19.1 s | 21.4 s |
| V4 concise +0% | 84.1 | 12.7% | 85.4 | 59.2 | 31 | 0.99 | 1.00 | 23.5 / 41.2 s | 45.7 s |

**Whole sentences (S, control)**

| | Units recall | Distortion | Questions | 0–100 (said) | Critical | Characters | Audio | Last p50 / p90 | End |
|---|---|---|---|---|---|---|---|---|---|
| V0 current +0% | 89.3 | 10.7% | 91.4 | 75.3 | 27 | 1.00 | 1.00 | 13.0 / 18.8 s | 26.1 s |
| V1 current +10% | 89.3 | 10.7% | 91.4 | 75.3 | 27 | 1.00 | 0.91 | 11.4 / 15.9 s | 21.3 s |
| V2 current +20% | 89.3 | 10.7% | 91.4 | 75.3 | 27 | 1.00 | 0.83 | 10.0 / 14.9 s | 17.4 s |
| V3 concise +15% | 91.2 | 9.4% | 87.5 | 71.4 | 31 | 0.94 | 0.83 | 10.4 / 16.0 s | 16.8 s |
| V4 concise +0% | 91.2 | 9.4% | 87.5 | 71.4 | 31 | 0.94 | 0.96 | 13.0 / 17.5 s | 22.6 s |

In the tables, "Questions" is listener-question accuracy and "Characters" and "Audio" are relative to
V0. "Last" is the time from the end of a sentence to the start of its last chunk's audio, and "End" is
the time from the speaker's last word until all audio has finished.

## Findings

1. **The speaking rate is the lever, and it costs nothing in content.**
   - *Phrase mode:* at +0% the translation's audio runs 192–200 s for a 163 s monologue, so the voice
     can't keep up. All audio finishes 46 s after the speaker stops. At +20% the audio is 162–168 s and
     that falls to 17 s; at +10%, to 29 s.
   - *No content cost:* recall, distortion and the listener questions are identical, because the words
     are identical.
   - *What the rate can't measure:* whether +20% still sounds natural. That is for the listening
     samples, not the grader.
2. **The concise prompt barely shortens read news.** Phrase output was 1% shorter, and whole sentences
   6% shorter (4% less audio at the same rate). FLEURS read news has almost no filler, repetition or repairs, so
   there is little to drop: compaction here can only risk real content.
3. **The concise prompt's quality effect is mixed and within one grading round's noise.**
   - *Phrase mode:* its 0–100 grade was 3.7 points higher, and its questions 1 point better, but its
     distortion was 0.9 points worse (58 distorted units vs 54).
   - *Whole sentences:* the reverse. Its 0–100 grade was 3.9 points lower, and its questions 3.9 worse,
     with distortion 1.3 points better.
   - *Per direction:* the swings run both ways. For example, phrase-mode en→es scored 9.2% distortion
     with regular pauses but 17.1% with irregular pauses.
   - *Verdict:* no consistent gain, so no reason to adopt it on this material.
4. **Even +20% doesn't fully keep up on nonstop fast reading.** Per sentence, the last chunk starts
   about 10–11 s after the sentence ends, in both modes. These readers speak quickly and without
   breaks. In conversation, turn-taking gives the voice time to catch up, which this clip never does.
5. **Distortion of about 10–13% is present in every variant**, V0 included. Unit judging counts
   recognition errors carried into the translation (Azure standard real-time misheard about 3.7% of
   English characters on these clips), and phrase-mode fragments. It is a baseline to compare against,
   not an absolute measure.

## Recommendation

- **Fast mode (Talk):** speaking rate **+15–20%**, if the listening samples sound acceptable; +10% is the
  conservative choice. Keep the **current prompt**.
- **Monologue (Live Translation):** **+20%**, with whole sentences and the current prompt.
  - *Why not more:* a fixed rate still leaves a backlog on fast nonstop speech.
  - *Next step:* make the rate adaptive, speeding up when the audio queue is longer than a few seconds.
- **The concise prompt:** not justified on read news. **Follow-up:** repeat the test on spontaneous,
  conversational speech, where fillers, repetitions and self-repairs give a concise prompt something
  real to remove. The meaning-unit and listener-question grading here carry over unchanged.

## Limits

- **Data:** one 20-sentence read clip per pause pattern, three target languages, one grading round.
  Grades move a few points between rounds; compare only within this round.
- **What the grader judges:** meaning units and questions are written and judged by the same grader
  family. Naturalness at higher rates is not graded at all; it is left to listening.
- **Timing:** queued timing assumes a single voice that never skips or overlaps chunks.

## Files

- `translate.py`: concise translations (reuses `../2026-10-simultaneous-phrases/simulate.py`)
- `tts_rates.py`: Azure TTS for every chunk at each rate (measured lengths), and the listening samples
- `grading.py`: meaning units, listener questions, and jobs for the 0–100 grade
  (`../2026-10-es-pt-live-compare/grade.py`)
- `table.py`: backlog and all measures → `results.json`
