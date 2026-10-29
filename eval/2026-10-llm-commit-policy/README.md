# Who decides when to speak: a phrase rule or the translator? October 2026

Phrase mode speaks before the speaker finishes a sentence, but a fixed rule decides where to cut
(4–8 words, at a clause word or comma). [`../2026-10-open-streaming`](../2026-10-open-streaming/) found
that the cut, not speed, is what costs quality: phrase mode scores well below whole sentences and up
to a third of its phrases are contradicted later. Here the translator decides instead. Three
policies let Gemma 4 choose when to speak and are compared with the phrase rule and with whole
sentences, on the same recordings.

## Setup

- **Recordings:** the streaming recognition already recorded on the unseen clips (20 FLEURS sentences
  per language, regular *reg* and irregular *irr* pauses), en↔es and en↔fr:
  - **MAI-Transcribe-2-Streaming**, from [`../2026-10-simultaneous-phrases`](../2026-10-simultaneous-phrases/)
    (`raw/rec/`).
  - **Nemotron 3.5 ASR streaming**, from `../2026-10-open-streaming/raw/rec/`.
- **Commits:** as `../2026-10-open-streaming/simulate_open.py`. A word is committed when two partials
  agree on it, the recogniser marks it stable, a 300 ms pause follows, or the final arrives. Every
  policy sees the same commits. A *decision point* is a commit that added words, taken only once the
  previous call has finished (one call at a time per stream).
- **Translator:** Gemma 4 31B (`gemma-4-31b-it`) on the Gemini API, temperature 0, `thinkingLevel`
  MINIMAL (about 1.1 s a call). Each prompt carries the previous sentences as context, as before.
- **Policies** (`simulate_policy.py`):

  | Policy | When it speaks | Calls per decision |
  |---|---|---|
  | **Sentence** | once per recogniser final | 1 |
  | **Phrase ≤8** | `simulate_open.py`'s rule: 4–8 words at a clause word or comma, or a pause | 1 |
  | **Judge** | Gemma answers SEND or WAIT for the words not yet translated; SEND runs the phrase continuation prompt | 1, or 2 on SEND |
  | **Decide** | Gemma gets the sentence so far and what is already spoken, and returns the next words to speak, or WAIT | 1 |
  | **Agree** | Gemma translates the whole sentence so far; only the words two successive translations agree on, beyond what is already spoken, are spoken (local agreement) | 1 |

  In Judge, Decide and Agree the recogniser's final ends the sentence: one call speaks the rest, given
  what was already spoken. More than 14 untranslated words force a send.
- **Rate limit:** the key allows 30 calls a minute, so calls wait for a slot and 429s are retried. The
  wait is not part of a call's measured time, so the replay's timeline is what an unthrottled
  translator would give.
- **Latency and grading:** `analyze_policy.py` is `../2026-10-open-streaming/analyze_open.py` with these
  policies. The voice is the phrase eval's measured Azure neural TTS time to first audio. Gemini cuts
  each spoken stream into the read sentences at verbatim anchors (`seg_all.py`). gemini-pro-latest then
  grades all of one recogniser's policies blind, side by side, one call per direction and clip
  (`grade.py`), and counts the chunks that the finished sentence contradicts (`contradictions.py`).
  Each recogniser was graded on its own.

## Results

Means over both pause patterns and the two directions in each group (4 graded clips of 20 sentences
per cell). Latencies are medians of the per-direction medians, in seconds (`table.py`).

**Out of English (en→es, en→fr)**

| Recogniser | Policy | Quality, said | Critical | Speech starts → first audio (s) | Speech ends → last audio (s) | Chunks wrong later | Gemma calls per sentence |
|---|---|---|---|---|---|---|---|
| MAI-Transcribe-2-Streaming | Sentence | 68.8 | 5.75 | 9.9 | 4.0 | – | 1.4 |
| MAI-Transcribe-2-Streaming | Phrase ≤8 | 65.0 | 6.25 | 4.2 | 1.9 | 12% | 3.2 |
| MAI-Transcribe-2-Streaming | Judge | 63.8 | 6.5 | 6.7 | 3.1 | 14% | 6.4 |
| MAI-Transcribe-2-Streaming | Decide | 50.4 | 7.5 | 2.7 | 2.3 | 13% | 6.3 |
| MAI-Transcribe-2-Streaming | Agree | 69.2 | 5.5 | 4.9 | 3.7 | 13% | 5.0 |
| Nemotron 3.5 ASR streaming | Sentence | 52.9 | 6.75 | 16.8 | 10.4 | – | 0.6 |
| Nemotron 3.5 ASR streaming | Phrase ≤8 | 41.7 | 6.75 | 4.3 | 2.1 | 25% | 2.6 |
| Nemotron 3.5 ASR streaming | Agree | 51.7 | 6.75 | 7.3 | 7.1 | 28% | 3.8 |

**Into English (es→en, fr→en)**

| Recogniser | Policy | Quality, said | Critical | Speech starts → first audio (s) | Speech ends → last audio (s) | Chunks wrong later | Gemma calls per sentence |
|---|---|---|---|---|---|---|---|
| MAI-Transcribe-2-Streaming | Sentence | 89.0 | 2 | 11.0 | 3.5 | – | 1.1 |
| MAI-Transcribe-2-Streaming | Phrase ≤8 | 71.1 | 3 | 3.8 | 1.9 | 15% | 3.7 |
| MAI-Transcribe-2-Streaming | Judge | 71.5 | 2.75 | 6.3 | 2.6 | 18% | 8.2 |
| MAI-Transcribe-2-Streaming | Decide | 52.7 | 3.75 | 2.8 | 2.3 | 14% | 7.8 |
| MAI-Transcribe-2-Streaming | Agree | 82.2 | 2.75 | 4.4 | 3.1 | 11% | 6.2 |
| Nemotron 3.5 ASR streaming | Sentence | 81.5 | 1.5 | 9.1 | 2.6 | – | 1.1 |
| Nemotron 3.5 ASR streaming | Phrase ≤8 | 44.7 | 2.5 | 4.1 | 2.4 | 29% | 3.9 |
| Nemotron 3.5 ASR streaming | Agree | 65.2 | 1.75 | 4.5 | 3.1 | 21% | 5.9 |

Quality is the phrase eval's score (0–100, against what was said); "Critical" is the mean count of
critical errors per graded clip.

## Findings

1. **Agree is the only policy that beats the phrase rule, and on MAI it nearly matches whole
   sentences.** Out of English it scores 69.2 against 68.8 for sentences and 65.0 for the phrase rule.
   Into English it scores 82.2 against 89.0 and 71.1. It led the phrase rule on all 8 MAI clips, by
   2–19 points. It starts speaking 0.6–0.7 s after the phrase rule and 5–7 s before whole sentences,
   and no more of its chunks are contradicted (13% and 11%, against 12% and 15%).
2. **On Nemotron, Agree lifts the phrase rule by 10–20 points but stays below sentences.** Into
   English it scores 65.2 against 44.7 (phrase rule) and 81.5 (sentences), at the same 4.1–4.5 s to first
   audio as the phrase rule. Out of English it gains less and waits longer (7.3 s), because Nemotron's
   English finals merge sentences (12 finals for 20 sentences) and Agree, like sentence mode, finishes
   on the final. A recogniser's quality still sets the ceiling.
3. **Judge does not help.** Asked zero-shot whether to send, Gemma mostly answers WAIT. It speaks
   fewer, later chunks than the phrase rule, at the same quality and twice the calls.
4. **Decide is the fastest and the worst.** It speaks within 2.7–2.8 s but commits to word order
   before the meaning is clear: 15–18 points below the phrase rule, with more critical errors.
5. **Cost:** Agree makes 1.5–1.7 times as many Gemma calls as the phrase rule (5–6 a sentence), about
   455k input tokens an hour of speech on MAI. That is fine on our own GPU, but it is close to a
   30-call-a-minute API limit for one stream.
6. **Weak spot:** with irregular pauses, on three of the four MAI clips the slowest tenth of Agree's
   sentences finished 13–17 s after the speaker stopped. Whole sentences share the problem there,
   since both wait for the final. A cap on untranslated words below 14, or speaking the latest
   translation at a long pause, should bound it.

**Recommendation:** if phrase mode ships, use Agree rather than the fixed phrase rule, with a lower
pending cap, and test it live on the stack's own Gemma before switching. Judge and Decide are not
worth pursuing without few-shot examples or fine-tuning.

## Limits

- One grading call per direction and clip; a few points either way is noise.
- Read FLEURS sentences, one reader each, joined with artificial pauses; Nemotron's card lists FLEURS
  among its training data.
- The prompts are zero-shot and were not tuned. Judge in particular might send more with examples.
- Gemma ran on the Gemini API, not the stack's 4-bit vLLM build; the call times (about 1.1 s) are the
  API's.
- Latency assumes one call at a time per stream and an unthrottled translator.

## Files

- `simulate_policy.py`: the replay (the five policies).
- `analyze_policy.py`: grading jobs, latency, calls per sentence and tokens; writes `results.json`,
  merged by system.
- `table.py`: the tables above.
- `results.json`: every row, per pattern and direction.
- `raw/`:
  - `rec/`: the MAI recordings.
  - `sim/<system>/`: each replay's chunks and calls (prompt and output tokens, wall time).
  - `seg/`, `mai/` and `nemo/` (`jobs.json`, `grades.json`, `contra_jobs.json`, `contra.json`): the
    Gemini cut, grading jobs and grades for each recogniser.

## Reproduce

With `CLIPS_ROOT` holding the unseen `clips_reg/` and `clips_irr/` (`../2026-10-open-streaming/build_unseen_subset.py`)
and `UO` that eval's unseen output folder, `WORK/rec/` the recordings and `WORK/tts.json` the
phrase eval's TTS timings:

```
export GEMINI_API_KEY=... CLIPS_ROOT=...
RECS=mai THREADS=6 python3 -I simulate_policy.py WORK
python3 -I ../2026-10-simultaneous-phrases/seg_all.py $CLIPS_ROOT WORK
RECS=mai python3 -I analyze_policy.py jobs $CLIPS_ROOT UO WORK
python3 -I ../2026-10-es-pt-live-compare/grade.py WORK/jobs.json WORK/grades.json
python3 -I ../2026-10-simultaneous-phrases/contradictions.py WORK/contra_jobs.json WORK/contra.json
RECS=mai python3 -I analyze_policy.py table $CLIPS_ROOT UO WORK
python3 -I table.py
```

For Nemotron: `RECS=nemo python3 -I simulate_policy.py WORK S-nemo P8-nemo agree-nemo`, then the same
steps in a second WORK that holds only those three systems, with `RECS=nemo POLICIES=S,P8,agree`.
