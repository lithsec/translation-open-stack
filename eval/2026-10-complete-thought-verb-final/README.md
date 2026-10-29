# Complete-thought sentence ends for verb-final languages, and one decider per room. October 2026

[`../2026-10-complete-thought-endpointing`](../2026-10-complete-thought-endpointing/) found CT (b) the best way to end a
sentence early: at each decision point Gemma is asked whether the words heard so far begin with a complete thought, and
a thought is committed only when two checks in a row name the same end word. hi→en failed there (70.0 against 90.8 for
sentences) on mistranslations and omissions, not timing.
[`../2026-10-complete-thought-ht-km-lo`](../2026-10-complete-thought-ht-km-lo/) found that CT gains mainly when the
speaker runs sentences together. This run asks the same question for verb-final languages:

- **Out of English:** en→ja, en→ko, en→fa, en→ur, en→bn, en→ta.
- **Into English:** ja→en, ko→en, fa→en, hi→en, with Gemma deciding and sol translating, to see whether sol fixes hi→en.
- **New: one decider per room.** For a room listening in Japanese, Korean and Urdu, one CT (b) decision stream on the
  English (Gemma, asked only for `COMPLETE N` or `WAIT`, no translation), then one translation call per target per
  committed thought. It is compared with per-language CT (b) on quality, latency (the extra round trip) and calls and
  tokens per room-hour.

## Setup

- **Clips** (`build_clips.py`): 20 unseen FLEURS test sentences (CC BY 4.0) per source language, 6–25 English words,
  drawn with seed 2026. Left out: every FLEURS id named in an earlier eval's json files, and any sentence whose text
  appears in one. Only 18 such ids are shared by all five source languages, so each language draws its own 20 from the
  ids it shares with en_us. The English clip is the source of all six out-of-English directions. ja, ko, fa and hi are
  graded against the English FLEURS text of their own ids. One recording per sentence, alternating male and female
  readers, and the two pause patterns as before: *reg* (1.0–1.95 s between sentences) and *irr* (0.3–1.2 s).
- **What was said** (`witness.py`, Gemini Flash): 6 of the 20 English recordings stop early or are misread, and
  these are graded against what was said. 1 Japanese, 3 Korean, 1 Persian and 4 Hindi recordings are flagged and left out of
  the into-English scores.
- **Hearing** (`stream.py`, every partial and final kept, streamed in real time, locale pinned), as production picks
  it: MAI-Transcribe-2-Streaming for Japanese and Persian, which Live Translation's MAI list holds
  (`src/shared/best-routes.ts`, `TABLE_MAI_LANGS`). Azure's standard real-time recogniser for English, Korean and Hindi,
  which it does not. The earlier runs heard English and Hindi with MAI, so their latencies are not directly
  comparable. Character errors of the finals (*reg* / *irr*): en 4.5 / 4.6%, ko 8.7 / 9.2%, hi 3.9 / 3.9%,
  ja 7.0 / 5.7%, fa 3.6 / 5.0%. On *irr*, Azure gave 14 English finals for 20 sentences (MAI gave 42 Japanese pieces).
- **Translators.** `google.gemma-4-31b` on Amazon Bedrock (us-east-2), temperature 0, and gpt-6-sol on Azure AI
  Foundry (`FOUNDRY_DEPLOYMENT`, `reasoning_effort` low). The sentence arm uses production's translator for each direction
  (the Live Translation Worker's `testroutes.ts` `gemmaTranslates`, with `routes/table.json` and `overlay.json`): sol out of English
  into ja and fa, sol into English from ja, ko and hi, and Gemma otherwise (en→ko, ur, bn, ta and fa→en). Where
  production uses sol, Gemma sentences ran as well, for the sol-vs-Gemma rule.
- **Arms** (`simulate.py`, wrapping `../2026-10-complete-thought-endpointing/simulate_ct.py`, unchanged):
  1. **Sentences** (silence): one call per recogniser final.
  2. **CT (b), Gemma:** Gemma decides and translates in one call.
  3. **CT (b), Gemma decides, sol translates.**
  4. **Agree** (Gemma), except into Japanese: Agree compares translations word by word on spaces, and Japanese has none.
  5. **Room CT (b)** (en→ja, ko and ur only): one Gemma decision stream, then a translation per target per thought with
     production's translator (sol into ja, Gemma into ko and ur), using the CT arms' thought prompt. The decider does
     not wait for the translations, and each target's translations run one at a time. Also run with Gemma
     translating Japanese. The 2 s quiet / 30 words fallback is the same as in CT (b).
  - Japanese words for the numbered tail are ICU word breaks (`words.py`, as for Khmer and Lao before).
  - The prompts, the fallback and one call at a time per stream are unchanged from the earlier runs. Foundry refused
    no request.
- **Voice timing** (`tts_timing.py`): Azure Jenny (en), Nanami (ja), SunHi (ko), Dilara (fa), Uzma (ur), Tanishaa (bn)
  and Pallavi (ta). Their time to first audio (p50) was 178, 226, 205, 384, 499, 282 and 398 ms.
- **Grading** (`grade_all.py`, `split.py`, `analyze.py`): the earlier cut, grade, contradiction and split checks,
  with gemini-flash-latest. All arms of a direction and clip are graded side by side in one blind call. Every
  direction had a close call, so round 2 (under new ids, which shuffles the arms differently) ran in all of them.
  `table.py`, `patterns.py` and `room.py` make the tables.

## Results

Each cell is the mean of both pause patterns and both rounds. Latencies are medians of the two clips, in seconds, and
the longest wait is the larger of the two. Columns as in the earlier runs. "(prod)" marks production's sentence
translator. "Calls per sentence" counts Gemma calls, plus sol calls where marked. For the room arm, each direction
counts a third of the shared decisions. "Thoughts by fallback" is the share of a CT arm's thoughts that came from the
2 s or 30-word fallback. \* For sentence arms, "wrong later" counts the *reg* clip only, as before.

| Direction | Arm | Quality, said (round 1) | Round 2 | Mean | Critical | Speech starts → first audio (s) | Speech ends → last audio, p50 (s) | p90 (s) | Longest wait (s) | Chunks wrong later | Sentences split mid-clause | Quality of unsplit sentences | Calls per sentence | Thoughts by fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| en→ja | Sentences, sol (prod) | 79.2 | 79.2 | **79.2** | 2.5 | 11.0 | 2.6 | 10.5 | 24.9 | 20%* | 0% | 79.2 | 0.8 sol | – |
| en→ja | Sentences, Gemma | 78.3 | 76.7 | **77.5** | 3.0 | 10.5 | 1.9 | 9.2 | 24.5 | 20%* | 0% | 78.3 | 0.8 | – |
| en→ja | CT (b), Gemma | 71.7 | 73.3 | **72.5** | 4.0 | 9.7 | 3.3 | 21.4 | 49.4 | 17% | 0% | 71.7 | 11.2 | 29% |
| en→ja | CT (b), Gemma decides, sol translates | 78.3 | 78.3 | **78.3** | 2.5 | 10.9 | 4.4 | 11.9 | 21.1 | 15% | 0% | 78.3 | 10.6 + 1.2 sol | 26% |
| en→ja | Room CT (b): one decider, production translator | 76.7 | 76.7 | **76.7** | 3.0 | 11.5 | 5.1 | 11.2 | 24.5 | 24% | 2% | 78.0 | 4.4 + 1.0 sol | 45% |
| en→ja | Room CT (b): one decider, Gemma translates | 79.2 | 77.5 | **78.3** | 3.0 | 10.6 | 3.9 | 9.9 | 23.4 | 24% | 0% | 79.2 | 5.4 | 45% |
| en→ko | Sentences, Gemma (prod) | 82.2 | 82.5 | **82.3** | 2.5 | 10.4 | 1.9 | 9.2 | 24.6 | 10%* | 0% | 82.2 | 0.8 | – |
| en→ko | CT (b), Gemma | 77.5 | 77.5 | **77.5** | 3.5 | 9.7 | 3.5 | 8.6 | 19.9 | 6% | 0% | 77.5 | 12.8 | 26% |
| en→ko | CT (b), Gemma decides, sol translates | 83.3 | 84.2 | **83.7** | 2.0 | 10.6 | 5.0 | 7.8 | 21.2 | 2% | 0% | 83.3 | 10.5 + 1.3 sol | 25% |
| en→ko | Agree, Gemma | 77.5 | 79.2 | **78.3** | 3.0 | 3.5 | 1.9 | 9.6 | 23.9 | 6% | 78% | 77.8 | 9.9 | 0% |
| en→ko | Room CT (b): one decider, production translator | 81.7 | 79.2 | **80.4** | 2.5 | 10.7 | 4.0 | 9.9 | 23.6 | 18% | 0% | 81.7 | 5.4 | 45% |
| en→fa | Sentences, sol (prod) | 80.0 | 78.3 | **79.2** | 3.5 | 11.1 | 2.9 | 10.5 | 25.3 | 10%* | 0% | 80.0 | 0.8 sol | – |
| en→fa | Sentences, Gemma | 72.5 | 68.3 | **70.4** | 3.5 | 10.7 | 2.2 | 9.4 | 24.9 | 10%* | 0% | 72.5 | 0.8 | – |
| en→fa | CT (b), Gemma | 68.3 | 65.0 | **66.7** | 4.0 | 8.9 | 3.2 | 6.9 | 20.1 | 6% | 2% | 69.0 | 12.8 | 28% |
| en→fa | CT (b), Gemma decides, sol translates | 77.5 | 72.5 | **75.0** | 4.0 | 10.8 | 5.5 | 11.5 | 21.1 | 18% | 2% | 77.7 | 10.2 + 1.1 sol | 33% |
| en→fa | Agree, Gemma | 68.3 | 64.2 | **66.2** | 4.0 | 3.6 | 2.3 | 8.0 | 19.2 | 5% | 88% | 66.7 | 9.4 | 0% |
| en→ur | Sentences, Gemma (prod) | 76.7 | 75.8 | **76.3** | 3.0 | 10.8 | 2.4 | 9.8 | 25.2 | 10%* | 0% | 76.7 | 0.8 | – |
| en→ur | CT (b), Gemma | 67.5 | 70.8 | **69.2** | 3.5 | 10.1 | 3.9 | 9.5 | 30.4 | 15% | 0% | 67.5 | 12.3 | 32% |
| en→ur | CT (b), Gemma decides, sol translates | 79.2 | 78.3 | **78.8** | 3.0 | 11.6 | 5.0 | 10.7 | 21.8 | 12% | 0% | 79.2 | 10.7 + 1.1 sol | 27% |
| en→ur | Agree, Gemma | 73.3 | 73.3 | **73.3** | 3.5 | 3.6 | 2.6 | 7.3 | 18.8 | 5% | 88% | 91.7 | 9.0 | 0% |
| en→ur | Room CT (b): one decider, production translator | 77.5 | 75.0 | **76.2** | 3.0 | 11.3 | 4.3 | 10.6 | 22.9 | 18% | 2% | 78.8 | 5.4 | 45% |
| en→bn | Sentences, Gemma (prod) | 78.3 | 79.2 | **78.8** | 4.0 | 10.5 | 2.0 | 9.3 | 24.5 | 10%* | 0% | 78.3 | 0.8 | – |
| en→bn | CT (b), Gemma | 70.8 | 72.5 | **71.7** | 4.0 | 9.9 | 3.3 | 10.8 | 20.0 | 16% | 2% | 71.6 | 12.7 | 27% |
| en→bn | CT (b), Gemma decides, sol translates | 77.5 | 80.0 | **78.8** | 3.5 | 10.9 | 4.7 | 11.5 | 30.0 | 18% | 0% | 77.5 | 10.5 + 1.1 sol | 33% |
| en→bn | Agree, Gemma | 67.5 | 66.7 | **67.1** | 4.5 | 3.4 | 2.0 | 6.9 | 18.3 | 6% | 88% | 83.3 | 9.4 | 0% |
| en→ta | Sentences, Gemma (prod) | 81.7 | 80.0 | **80.8** | 2.5 | 10.7 | 2.3 | 9.6 | 25.0 | 10%* | 0% | 81.7 | 0.8 | – |
| en→ta | CT (b), Gemma | 78.3 | 76.7 | **77.5** | 2.5 | 10.1 | 3.3 | 7.4 | 20.1 | 11% | 0% | 78.3 | 12.8 | 28% |
| en→ta | CT (b), Gemma decides, sol translates | 84.2 | 81.7 | **82.9** | 2.0 | 11.2 | 4.8 | 9.4 | 21.3 | 12% | 0% | 84.2 | 10.6 + 1.1 sol | 30% |
| en→ta | Agree, Gemma | 73.3 | 75.8 | **74.5** | 2.5 | 3.9 | 2.2 | 9.7 | 19.0 | 5% | 80% | 75.0 | 8.8 | 0% |
| ja→en | Sentences, sol (prod) | 88.6 | 89.5 | **89.0** | 1.0 | 10.1 | 2.2 | 8.7 | 15.2 | 14%* | 11% | 98.0 | 2.1 sol | – |
| ja→en | Sentences, Gemma | 79.8 | 80.7 | **80.3** | 1.5 | 9.6 | 1.0 | 2.1 | 14.4 | 21%* | 11% | 88.2 | 2.1 | – |
| ja→en | CT (b), Gemma | 75.5 | 73.7 | **74.6** | 2.5 | 10.0 | 2.1 | 3.5 | 15.3 | 0% | 3% | 76.6 | 15.6 | 44% |
| ja→en | CT (b), Gemma decides, sol translates | 92.1 | 93.0 | **92.5** | 1.5 | 10.7 | 3.2 | 5.0 | 19.0 | 0% | 3% | 92.8 | 14.6 + 1.1 sol | 47% |
| ja→en | Agree, Gemma | 69.3 | 70.2 | **69.7** | 1.5 | 2.5 | 1.5 | 2.3 | 11.6 | 15% | 97% | 100.0 | 12.5 | 0% |
| ko→en | Sentences, sol (prod) | 92.2 | 91.2 | **91.7** | 1.5 | 8.6 | 1.6 | 5.4 | 23.8 | 0%* | 0% | 92.2 | 1.0 sol | – |
| ko→en | Sentences, Gemma | 85.3 | 85.3 | **85.3** | 3.0 | 8.0 | 1.1 | 4.7 | 23.7 | 0%* | 0% | 85.3 | 1.0 | – |
| ko→en | CT (b), Gemma | 82.3 | 82.3 | **82.3** | 2.5 | 9.7 | 2.0 | 5.6 | 18.1 | 0% | 0% | 82.3 | 11.6 | 56% |
| ko→en | CT (b), Gemma decides, sol translates | 92.2 | 92.2 | **92.2** | 1.5 | 11.0 | 3.4 | 10.0 | 22.6 | 0% | 0% | 92.2 | 10.8 + 1.1 sol | 45% |
| ko→en | Agree, Gemma | 70.6 | 68.7 | **69.6** | 3.5 | 3.2 | 1.2 | 4.7 | 22.4 | 5% | 94% | 100.0 | 10.1 | 0% |
| fa→en | Sentences, Gemma (prod) | 80.7 | 84.2 | **82.5** | 2.5 | 11.8 | 0.3 | 6.2 | 22.2 | 28%* | 26% | 91.7 | 1.6 | – |
| fa→en | CT (b), Gemma | 63.2 | 61.4 | **62.3** | 5.0 | 10.5 | 1.1 | 3.9 | 22.2 | 6% | 8% | 62.8 | 18.3 | 34% |
| fa→en | CT (b), Gemma decides, sol translates | 87.7 | 91.2 | **89.5** | 2.0 | 11.6 | 2.5 | 4.9 | 23.6 | 3% | 3% | 88.3 | 16.5 + 1.6 sol | 37% |
| fa→en | Agree, Gemma | 68.4 | 71.9 | **70.2** | 3.5 | 4.3 | 0.2 | 8.2 | 18.7 | 14% | 92% | 100.0 | 15.3 | 0% |
| hi→en | Sentences, sol (prod) | 94.8 | 96.8 | **95.8** | 0.0 | 10.0 | 1.8 | 2.8 | 20.8 | 5%* | 6% | 96.7 | 1.1 sol | – |
| hi→en | Sentences, Gemma | 89.6 | 91.7 | **90.6** | 0.0 | 9.5 | 1.1 | 1.6 | 20.6 | 5%* | 6% | 91.1 | 1.1 | – |
| hi→en | CT (b), Gemma | 85.4 | 87.5 | **86.5** | 1.0 | 9.8 | 2.3 | 5.0 | 20.4 | 0% | 9% | 89.6 | 16.6 | 52% |
| hi→en | CT (b), Gemma decides, sol translates | 94.8 | 95.8 | **95.3** | 1.0 | 10.7 | 3.6 | 5.3 | 21.8 | 4% | 0% | 94.8 | 15.1 + 1.3 sol | 50% |
| hi→en | Agree, Gemma | 65.6 | 76.0 | **70.8** | 1.0 | 3.8 | 1.3 | 6.7 | 28.9 | 6% | 94% | 100.0 | 12.7 | 0% |

**One decider per room** (`room.py`, `raw/room.json`): the three listeners' languages together, per hour of speech.
Per-language means three CT (b) streams: en→ja with Gemma deciding and sol translating, and en→ko and en→ur on Gemma
alone (production's translators). Room means one decision stream plus a translation per target per thought.

| Pauses | Design | Calls per hour | Input tokens per hour | Output tokens per hour |
|---|---|---|---|---|
| reg | per-language | 14,479 | 5.24 M | 237 k |
| reg | room | 6,629 | 2.05 M | 71 k |
| irr | per-language | 15,933 | 5.92 M | 263 k |
| irr | room | 6,813 | 2.19 M | 76 k |

Call times (p50 / p90, all directions):
- **Gemma:** a CT check takes 0.29 / 0.64 s. A room decision (a few output tokens) takes 0.27 / 0.35 s. A room
  thought translation takes 0.60 / 0.90 s, and a sentence 0.48 / 0.86 s.
- **sol:** a thought takes 1.08 / 1.86 s, and a sentence 1.16 / 2.00 s.
- **Outliers:** one Gemma check on en→ja *reg* took 42.8 s. It is behind that arm's 32 s p90 and 49 s longest wait, so
  treat those as an outlier, like the earlier en→hi Agree.

**By pause pattern** (`patterns.py`). Quality is the mean of the two rounds. "Wait p90" is the p90 of the per-chunk wait.

| Direction | Pauses | Arm | Quality | Critical | First audio | Last audio p50 / p90 | Wait p90 | Longest wait |
|---|---|---|---|---|---|---|---|---|
| en→ja | reg | Sentences, sol | 78.3 | 3 | 9.4 | 2.1 / 7.0 | 19.0 | 24.9 |
| en→ja | reg | Sentences, Gemma | 80.0 | 3 | 8.8 | 1.7 / 5.3 | 18.6 | 24.5 |
| en→ja | reg | CT (b), Gemma | 71.7 | 5 | 10.1 | 3.2 / 32.2 | 42.3 | 49.4 |
| en→ja | reg | CT (b), Gemma-sol | 78.3 | 3 | 11.4 | 4.4 / 9.9 | 15.6 | 21.1 |
| en→ja | reg | Room CT (b), production translator | 80.8 | 3 | 11.0 | 4.2 / 9.4 | 15.5 | 21.1 |
| en→ja | reg | Room CT (b), Gemma | 80.0 | 3 | 10.2 | 3.5 / 7.7 | 13.9 | 20.4 |
| en→ja | irr | Sentences, sol | 80.0 | 2 | 12.7 | 3.1 / 13.9 | 19.6 | 24.2 |
| en→ja | irr | Sentences, Gemma | 75.0 | 3 | 12.1 | 2.1 / 13.0 | 18.7 | 23.9 |
| en→ja | irr | CT (b), Gemma | 73.3 | 3 | 9.2 | 3.4 / 10.7 | 13.2 | 19.1 |
| en→ja | irr | CT (b), Gemma-sol | 78.3 | 2 | 10.3 | 4.4 / 13.9 | 17.1 | 20.0 |
| en→ja | irr | Room CT (b), production translator | 72.5 | 3 | 11.9 | 6.0 / 13.0 | 16.6 | 24.5 |
| en→ja | irr | Room CT (b), Gemma | 76.7 | 3 | 11.0 | 4.2 / 12.1 | 16.0 | 23.4 |
| en→ko | reg | Sentences, Gemma | 85.8 | 2 | 8.7 | 1.7 / 5.5 | 18.7 | 24.6 |
| en→ko | reg | CT (b), Gemma | 80.8 | 3 | 9.5 | 3.4 / 6.6 | 13.8 | 19.9 |
| en→ko | reg | CT (b), Gemma-sol | 89.2 | 2 | 9.9 | 4.6 / 5.8 | 15.6 | 21.2 |
| en→ko | reg | Agree, Gemma | 79.2 | 3 | 3.3 | 1.6 / 6.0 | 6.8 | 23.9 |
| en→ko | reg | Room CT (b), production translator | 81.7 | 2 | 10.2 | 3.6 / 7.6 | 14.1 | 20.5 |
| en→ko | irr | Sentences, Gemma | 78.8 | 3 | 12.1 | 2.2 / 13.0 | 18.7 | 23.9 |
| en→ko | irr | CT (b), Gemma | 74.2 | 4 | 10.0 | 3.5 / 10.6 | 15.7 | 18.4 |
| en→ko | irr | CT (b), Gemma-sol | 78.3 | 2 | 11.3 | 5.4 / 9.8 | 15.1 | 20.2 |
| en→ko | irr | Agree, Gemma | 77.5 | 3 | 3.8 | 2.2 / 13.1 | 13.7 | 23.7 |
| en→ko | irr | Room CT (b), production translator | 79.2 | 3 | 11.2 | 4.5 / 12.2 | 16.5 | 23.6 |
| en→fa | reg | Sentences, sol | 81.7 | 3 | 9.5 | 2.5 / 7.4 | 19.4 | 25.3 |
| en→fa | reg | Sentences, Gemma | 66.7 | 4 | 8.9 | 2.0 / 5.7 | 19.0 | 24.9 |
| en→fa | reg | CT (b), Gemma | 60.0 | 4 | 8.7 | 3.4 / 6.1 | 14.0 | 20.1 |
| en→fa | reg | CT (b), Gemma-sol | 79.2 | 3 | 10.3 | 5.0 / 8.4 | 15.6 | 21.1 |
| en→fa | reg | Agree, Gemma | 64.2 | 3 | 3.4 | 1.8 / 5.2 | 6.3 | 15.0 |
| en→fa | irr | Sentences, sol | 76.7 | 4 | 12.8 | 3.3 / 13.6 | 19.3 | 24.5 |
| en→fa | irr | Sentences, Gemma | 74.2 | 3 | 12.5 | 2.4 / 13.2 | 18.8 | 24.2 |
| en→fa | irr | CT (b), Gemma | 73.3 | 4 | 9.2 | 3.0 / 7.6 | 13.5 | 19.3 |
| en→fa | irr | CT (b), Gemma-sol | 70.8 | 5 | 11.4 | 5.9 / 14.6 | 19.3 | 20.2 |
| en→fa | irr | Agree, Gemma | 68.3 | 5 | 3.8 | 2.9 / 10.9 | 10.4 | 19.2 |
| en→ur | reg | Sentences, Gemma | 81.7 | 3 | 9.1 | 2.1 / 6.0 | 19.3 | 25.2 |
| en→ur | reg | CT (b), Gemma | 75.0 | 3 | 10.4 | 3.8 / 10.2 | 15.8 | 30.4 |
| en→ur | reg | CT (b), Gemma-sol | 81.7 | 3 | 11.7 | 4.9 / 8.9 | 15.4 | 21.8 |
| en→ur | reg | Agree, Gemma | 80.0 | 3 | 3.5 | 2.3 / 4.0 | 7.2 | 18.8 |
| en→ur | reg | Room CT (b), production translator | 79.2 | 3 | 10.6 | 3.9 / 8.0 | 14.5 | 21.1 |
| en→ur | irr | Sentences, Gemma | 70.8 | 3 | 12.6 | 2.7 / 13.5 | 19.2 | 24.5 |
| en→ur | irr | CT (b), Gemma | 63.4 | 4 | 9.7 | 3.9 / 8.8 | 16.1 | 20.3 |
| en→ur | irr | CT (b), Gemma-sol | 75.8 | 3 | 11.6 | 5.1 / 12.6 | 17.4 | 20.8 |
| en→ur | irr | Agree, Gemma | 66.7 | 4 | 3.6 | 2.9 / 10.6 | 12.7 | 17.4 |
| en→ur | irr | Room CT (b), production translator | 73.3 | 3 | 12.0 | 4.7 / 13.1 | 16.6 | 22.9 |
| en→bn | reg | Sentences, Gemma | 80.8 | 4 | 8.9 | 1.8 / 5.5 | 18.5 | 24.3 |
| en→bn | reg | CT (b), Gemma | 78.3 | 3 | 9.7 | 3.3 / 8.8 | 14.9 | 20.0 |
| en→bn | reg | CT (b), Gemma-sol | 83.3 | 4 | 10.5 | 4.4 / 9.1 | 15.9 | 21.1 |
| en→bn | reg | Agree, Gemma | 72.5 | 5 | 3.4 | 1.8 / 3.8 | 7.7 | 17.8 |
| en→bn | irr | Sentences, Gemma | 76.7 | 4 | 12.1 | 2.3 / 13.1 | 19.1 | 24.5 |
| en→bn | irr | CT (b), Gemma | 65.0 | 5 | 10.2 | 3.4 / 12.8 | 16.3 | 19.1 |
| en→bn | irr | CT (b), Gemma-sol | 74.2 | 3 | 11.4 | 4.9 / 13.8 | 18.4 | 30.0 |
| en→bn | irr | Agree, Gemma | 61.6 | 4 | 3.4 | 2.3 / 10.0 | 10.3 | 18.3 |
| en→ta | reg | Sentences, Gemma | 84.2 | 3 | 8.9 | 2.1 / 5.7 | 19.1 | 25.0 |
| en→ta | reg | CT (b), Gemma | 76.7 | 3 | 9.8 | 3.4 / 6.2 | 14.1 | 20.1 |
| en→ta | reg | CT (b), Gemma-sol | 82.5 | 3 | 10.8 | 4.7 / 8.2 | 15.8 | 21.3 |
| en→ta | reg | Agree, Gemma | 73.3 | 3 | 3.9 | 2.1 / 9.2 | 10.5 | 19.0 |
| en→ta | irr | Sentences, Gemma | 77.5 | 2 | 12.5 | 2.6 / 13.4 | 19.1 | 24.2 |
| en→ta | irr | CT (b), Gemma | 78.3 | 2 | 10.3 | 3.3 / 8.6 | 15.8 | 19.7 |
| en→ta | irr | CT (b), Gemma-sol | 83.3 | 1 | 11.6 | 5.0 / 10.6 | 17.9 | 20.9 |
| en→ta | irr | Agree, Gemma | 75.8 | 2 | 3.9 | 2.4 / 10.2 | 11.7 | 17.3 |
| ja→en | reg | Sentences, sol | 87.7 | 1 | 9.9 | 2.2 / 7.6 | 13.5 | 14.8 |
| ja→en | reg | Sentences, Gemma | 79.0 | 2 | 9.5 | 1.0 / 2.0 | 12.7 | 14.3 |
| ja→en | reg | CT (b), Gemma | 72.8 | 4 | 10.1 | 2.1 / 3.6 | 14.5 | 15.1 |
| ja→en | reg | CT (b), Gemma-sol | 92.1 | 2 | 10.8 | 3.4 / 5.1 | 16.4 | 19.0 |
| ja→en | reg | Agree, Gemma | 69.3 | 2 | 2.6 | 1.7 / 2.0 | 7.9 | 11.6 |
| ja→en | irr | Sentences, sol | 90.3 | 1 | 10.2 | 2.3 / 9.8 | 13.6 | 15.2 |
| ja→en | irr | Sentences, Gemma | 81.6 | 1 | 9.7 | 1.1 / 2.1 | 12.7 | 14.4 |
| ja→en | irr | CT (b), Gemma | 76.3 | 1 | 9.8 | 2.1 / 3.4 | 15.1 | 15.3 |
| ja→en | irr | CT (b), Gemma-sol | 93.0 | 1 | 10.6 | 3.1 / 4.9 | 16.4 | 17.9 |
| ja→en | irr | Agree, Gemma | 70.2 | 1 | 2.3 | 1.2 / 2.7 | 8.0 | 11.6 |
| ko→en | reg | Sentences, sol | 98.0 | 0 | 8.7 | 1.7 / 2.5 | 11.5 | 14.8 |
| ko→en | reg | Sentences, Gemma | 91.2 | 2 | 8.1 | 1.1 / 1.4 | 10.4 | 13.5 |
| ko→en | reg | CT (b), Gemma | 90.2 | 1 | 9.8 | 1.8 / 3.0 | 11.7 | 15.0 |
| ko→en | reg | CT (b), Gemma-sol | 98.0 | 0 | 10.7 | 3.1 / 13.8 | 16.6 | 22.6 |
| ko→en | reg | Agree, Gemma | 76.5 | 2 | 3.2 | 1.2 / 1.5 | 6.5 | 13.1 |
| ko→en | irr | Sentences, sol | 85.3 | 3 | 8.4 | 1.5 / 8.3 | 14.8 | 23.8 |
| ko→en | irr | Sentences, Gemma | 79.4 | 4 | 8.0 | 1.0 / 8.0 | 14.7 | 23.7 |
| ko→en | irr | CT (b), Gemma | 74.5 | 4 | 9.7 | 2.3 / 8.1 | 14.5 | 18.1 |
| ko→en | irr | CT (b), Gemma-sol | 86.3 | 3 | 11.3 | 3.6 / 6.3 | 12.9 | 19.1 |
| ko→en | irr | Agree, Gemma | 62.8 | 5 | 3.1 | 1.2 / 7.9 | 7.2 | 22.4 |
| fa→en | reg | Sentences, Gemma | 83.3 | 3 | 11.8 | 0.3 / 2.0 | 15.4 | 20.1 |
| fa→en | reg | CT (b), Gemma | 66.7 | 5 | 10.4 | 1.1 / 2.4 | 16.4 | 22.2 |
| fa→en | reg | CT (b), Gemma-sol | 90.3 | 2 | 11.7 | 2.5 / 3.6 | 19.5 | 22.8 |
| fa→en | reg | Agree, Gemma | 73.7 | 3 | 4.2 | 0.3 / 5.6 | 8.3 | 13.2 |
| fa→en | irr | Sentences, Gemma | 81.6 | 2 | 11.8 | 0.3 / 10.3 | 19.6 | 22.2 |
| fa→en | irr | CT (b), Gemma | 57.9 | 5 | 10.6 | 1.0 / 5.4 | 16.2 | 22.2 |
| fa→en | irr | CT (b), Gemma-sol | 88.6 | 2 | 11.6 | 2.4 / 6.3 | 17.6 | 23.6 |
| fa→en | irr | Agree, Gemma | 66.7 | 4 | 4.4 | 0.2 / 10.9 | 11.0 | 18.7 |
| hi→en | reg | Sentences, sol | 94.8 | 0 | 10.0 | 1.7 / 2.3 | 13.6 | 19.1 |
| hi→en | reg | Sentences, Gemma | 88.5 | 0 | 9.3 | 1.1 / 1.6 | 13.2 | 18.7 |
| hi→en | reg | CT (b), Gemma | 84.3 | 1 | 9.6 | 1.9 / 3.2 | 14.0 | 20.2 |
| hi→en | reg | CT (b), Gemma-sol | 96.8 | 1 | 10.4 | 3.4 / 4.8 | 17.1 | 21.8 |
| hi→en | reg | Agree, Gemma | 70.8 | 1 | 3.9 | 1.3 / 11.9 | 7.6 | 28.9 |
| hi→en | irr | Sentences, sol | 96.8 | 0 | 9.9 | 1.9 / 3.4 | 14.4 | 20.8 |
| hi→en | irr | Sentences, Gemma | 92.8 | 0 | 9.8 | 1.1 / 1.6 | 14.1 | 20.6 |
| hi→en | irr | CT (b), Gemma | 88.5 | 1 | 10.0 | 2.7 / 6.8 | 17.7 | 20.4 |
| hi→en | irr | CT (b), Gemma-sol | 93.8 | 1 | 11.1 | 3.8 / 5.7 | 21.3 | 21.7 |
| hi→en | irr | Agree, Gemma | 70.8 | 1 | 3.8 | 1.2 / 1.5 | 6.5 | 19.4 |

## Findings

1. **sol fixes hi→en.** With Gemma deciding and sol translating, CT (b) scores 95.3, against 95.8 for sol sentences
   and 86.5 for Gemma-only CT (b). The earlier 70.0 was Gemma's translation, not the endpointing. Into English, sol
   translating beats Gemma alone by 8.8 to 27 points in all four directions, and Gemma-sol CT (b) is level with sol
   sentences or ahead: ja→en +3.5, ko→en +0.5, hi→en −0.5. For fa→en it is +7.0 against production's Gemma
   sentences.
2. **Out of English, CT (b) needs sol translating too.** Gemma-only CT (b) is 3.3 to 12.5 points below sentences in
   every direction. With sol translating, CT (b) is +1.4 (ko), +2.5 (ur), 0.0 (bn) and +2.1 (ta) against
   production's Gemma sentences, and −0.9 (ja) and −4.2 (fa) against production's sol sentences.
3. **Pauses decide the speed, as before.**
   - **Run-on speech (*irr*):** Azure's English finals cover several sentences. Gemma-sol CT (b) cuts the p90 last
     audio from 13.0 to 9.8 s (ko), 13.5 to 12.6 s (ur) and 13.4 to 10.6 s (ta). For ja it is level (13.9 s).
     For fa (14.6 against 13.6 s) and bn (13.8 against 13.1 s) it is slower.
   - **Regular pauses (*reg*):** sentences end sooner (p90 5.5–7.4 s against 5.8–9.9 s).
   - **First audio** with CT is 0.8–2.6 s later on *reg* and 0.7–2.4 s sooner on *irr*.
   - **Into English** the recognisers already cut short pieces (MAI cut 20 Japanese sentences into 42 finals).
     CT adds up to 2.4 s to first audio (fa→en is level) and 1.0–2.2 s to the p50 last audio. It *shortens* the p90 for ja→en (5.0 against
     8.7 s) and fa→en (4.9 against 6.2 s), where today's pieces are split mid-clause (11% and 26% of sentences) and
     often turn out wrong later (14% and 28%).
4. **Agree** starts soonest (first audio 2.5–4.3 s) but is 3 to 25 points below sentences, with 78–97% of sentences
   split mid-clause.
5. **One decider per room is viable and halves the calls, but it falls back more often.**
   - **Calls and tokens:** against three per-language CT (b) streams, the room makes 54–57% fewer calls, with 61–63%
     fewer input tokens and about 70% fewer output tokens per room-hour.
   - **Quality:** within 1.6–3.3 points of per-language Gemma-sol CT (b) (ja 76.7 against 78.3, ko 80.4 against 83.7,
     ur 76.2 against 78.8). It is well above per-language Gemma-only CT (b) (ko +2.9, ur +7.0, and ja +5.8 with Gemma
     translating). Asking Gemma to decide and translate in one call costs Gemma quality, and splitting the two calls
     recovers most of it.
   - **The extra round trip is small.** A decision is quicker than a CT check, and the decider does not wait for
     translations. First audio is within 1.2 s of the per-language arms. The p90 last audio is within 1.3 s of the per-language arm
     with the same translator, but 2.1 s behind en→ko Gemma-sol.
   - **Fallbacks:** the room decider agrees with itself less. 45% of its thoughts come from the 2 s or 30-word fallback,
     against 25–32% for per-language CT (b). Its fallback chunks often span two read sentences, which the
     contradiction check counts as "repeated". That is why its "wrong later" is 18–24%, the same effect as for
     whole-sentence arms on *irr*. Its prompt asks for the largest complete N, and it sometimes ran a thought across a
     sentence end and left a short fragment for the next chunk.

## The sol-vs-Gemma rule

The rule: Gemma if it scores at least as well as sol. If it scores lower, Gemma only when it is within 5 points and
scores at least 80. Otherwise sol.
- **Sentences:** sol stays for en→ja (Gemma 77.5 against 79.2: within 5 points but under 80), en→fa (−8.8), ja→en
  (−8.7), ko→en (−6.4) and hi→en (−5.2). sol sentences were not run where production is Gemma (en→ko, ur, bn, ta and
  fa→en).
- **CT (b):** sol translates in every direction. Gemma-only CT is 5.4–27 points behind, and below 80 in eight of ten
  directions.

## Recommendation per direction

Phones run fast mode: first audio matters most. The PA puts quality first, and CT replaces sentences only if it is
within 5 points of them. "Sentences" means production's: an Azure final (en, ko, hi) or an MAI final (ja, fa), with
production's translator.

| Direction | Phones | PA |
|---|---|---|
| en→ja | **Sentences (sol).** CT (b) Gemma-sol is −0.9 and no faster on either pattern. | **Sentences (sol).** CT passes the rule but gains nothing. |
| en→ko | **CT (b) Gemma-sol** (83.7 against 82.3). It is as fast as sentences on *reg* (p90 5.8 against 5.5 s) and faster on *irr* (9.8 against 13.0 s). | **CT (b) Gemma-sol** (+1.4). |
| en→fa | **Sentences (sol).** CT is −4.2 and slower on run-on speech. | **Sentences (sol).** CT passes the rule (−4.2) but is worse on *irr* (70.8 against 76.7). |
| en→ur | **CT (b) Gemma-sol for run-on speakers** (+2.5, *irr* p90 12.6 against 13.5 s). Otherwise sentences. | **CT (b) Gemma-sol for run-on speakers** (+2.5). Keep sentences with regular pauses (p90 8.9 against 6.0 s). |
| en→bn | **Sentences (Gemma).** CT ties (78.8) and is no faster. | **Sentences.** |
| en→ta | **CT (b) Gemma-sol for run-on speakers** (+2.1, *irr* p90 10.6 against 13.4 s). Otherwise sentences. | **CT (b) Gemma-sol for run-on speakers.** Sentences otherwise. |
| ja→en | **CT (b) Gemma-sol** (92.5 against 89.0, p90 5.0 against 8.7 s, first audio +0.6 s). | **CT (b) Gemma-sol** (+3.5). |
| ko→en | **Sentences (sol).** CT ties (+0.5) and starts 2.4 s later. | **Sentences (sol).** No gain. |
| fa→en | **CT (b) Gemma-sol** (89.5 against 82.5 for Gemma sentences, p90 4.9 against 6.2 s, first audio level). | **CT (b) Gemma-sol** (+7.0). It also means sol translating into English from Persian, which the rule does not otherwise choose. |
| hi→en | **Sentences (sol).** CT ties (−0.5) and ends later (p50 3.6 against 1.8 s). | **Sentences (sol).** sol fixes the CT arm, but there is nothing to gain. |

**Deciding once per room:** worth building for rooms with two or more listeners' languages. It halves the calls,
cuts the tokens by 60–70%, adds no meaningful latency, and costs 1.6–3.3 points against per-language Gemma-sol CT (b).
Two things are worth trying before it ships:
- a decider prompt that prefers the first complete sentence over the largest N;
- keeping the agreement across a final that does not move the end word, which would lower the 45% fallback.
  Where a room translates with Gemma, it is better than per-language Gemma-only CT (b).

Not tested here: sol sentences where production is Gemma (en→ko, ur, bn, ta and fa→en), Agree into Japanese, and the
room decider for other target sets or with the prompt changes above.

## Limits

- One clip set per language: 20 read FLEURS sentences, one reader each, joined with artificial pauses. The source
  sentences differ between languages, so quality levels compare only within a direction. Two grading rounds with
  Gemini Flash. A few points either way is noise: rounds differ by up to 10.4 points (hi→en Agree) and by up to
  5 points for the other arms.
- The room arm was run for one set of targets (ja, ko, ur). Its decider prompt is new and untuned.
- The latency model is the earlier runs': one call at a time per stream, and the voice's time to first audio added to
  each chunk. The room's translations are modelled as parallel per target.
- English is heard by Azure's standard recogniser here, as in production, and by MAI in the earlier runs.

## Files

- `build_clips.py`: the clips. `stream.py`: recognition (wraps `stream_partials.py`). `witness.py`: what was said.
  `words.py`: Japanese words.
- `simulate.py`: the arms and the room decider. `tts_timing.py`: voice timing.
- `grade_all.py`, `split.py`: the cut, grade, contradiction and split checks.
- `analyze.py`: writes `results.json` (round 1) and `results_r2.json`. `table.py`, `patterns.py`: the tables
  (`table.md`, `patterns.md`). `room.py`: room totals (`raw/room.json`).
- `raw/room.json` (room totals) and `raw/tts.json` (voice timing).

**Not included:**
- the clip audio and the clip metadata (`raw/clips/`: FLEURS ids, texts and English references): `build_clips.py`
  rebuilds them;
- the recognisers' partials and finals (`raw/rec/`), each replay's chunks and calls (`raw/sim/`) and the cut
  (`raw/seg/`): about 9 MB of raw dumps that carry the transcripts and translations;
- the grading inputs and outputs (`jobs*.json`, `grades*.json`, `contra*.json`, `split*.json`, up to 0.6 MB each) and
  `witness/`: raw dumps with the sentence texts. Their figures are in `results.json`, `results_r2.json`, `table.md`
  and `patterns.md`.
- `simulate.py` wraps `../2026-10-complete-thought-endpointing/simulate_ct.py`, which needs the earlier commit-policy
  run's `simulate_policy.py` (not yet in this repository; see that folder's README).

## Reproduce

```
python3 -I build_clips.py CLIPS ../2026-10-real-voices USED_IDS.json ../ <other earlier eval roots>
AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 MODEL=mai-transcribe-2-streaming \
  <venv with azure-cognitiveservices-speech==1.52.0>/bin/python -I stream.py CLIPS/clips_reg WORK/rec mai_reg ja fa
AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus \
  <same venv>/bin/python -I stream.py CLIPS/clips_reg WORK/rec az_reg en ko hi
#   (and the same for clips_irr with tags mai_irr, az_irr)
GEMINI_API_KEY=... python3 -I witness.py CLIPS/clips_reg <en|ja|ko|fa|hi> UO/witness/<lang>.json   # UO/said_en.json from the flagged English
CLIPS_ROOT=CLIPS FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=... THREADS=10 RPM=600 <venv with boto3, numpy>/bin/python simulate.py WORK
AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I tts_timing.py WORK
GEMINI_API_KEY=... python3 -I grade_all.py seg CLIPS WORK
python3 -I analyze.py jobs CLIPS UO WORK                   # jobs_r2.json: jobs.json with each id + ":r2"
GEMINI_API_KEY=... python3 -I grade_all.py grade WORK/jobs.json WORK/grades.json
GEMINI_API_KEY=... python3 -I grade_all.py grade WORK/jobs_r2.json WORK/grades_r2.json
GEMINI_API_KEY=... python3 -I grade_all.py contra WORK/contra_jobs.json WORK/contra.json
GEMINI_API_KEY=... python3 -I split.py WORK/split_jobs.json WORK/split.json
python3 -I analyze.py table CLIPS UO WORK && GRADES=grades_r2.json RESULTS=results_r2.json python3 -I analyze.py table CLIPS UO WORK
python3 -I table.py > table.md && python3 -I patterns.py > patterns.md && python3 -I room.py WORK > raw/room.json   # room.py reads ../clips beside WORK
```
