# Complete-thought sentence ends (Gemma on Bedrock). October 2026

Whole sentences wait for the recogniser to finalise a segment (about 500 ms of silence, or its forced
cut). That is slow, and with a speaker who leaves short pauses one final often holds two or three
sentences. The streaming policies are quicker but split thoughts: Agree speaks a mid-clause piece in
about 9 of 10 sentences, and for hi→en and tr→en it guesses the English verb too early
(an earlier commit-policy run on Bedrock, `2026-10-llm-commit-policy-bedrock-de-hi-tr`, not yet in this repository).

This run tests a third way of ending a sentence: at each decision point ask Gemma whether the words heard
so far, not yet translated, **begin with a complete thought**. If they do, Gemma translates that part and
it is spoken once. If not, Gemma answers WAIT. Three variants:

- **CT (a)** commits on the first "complete";
- **CT (b)** commits only when two successive checks name the same end word;
- **CT (c)** commits on "complete" plus the boundary cutter's energy dip at the end word.

They are compared with silence-based whole sentences, Agree and Phrase ≤8 in ten directions (en↔es,
en↔de, en↔hi, en↔tr, en↔fr), and with the boundary cutter for es→en and fr→en. en→fr also has sol arms:
sentences with sol, and the best variant with sol deciding and translating, or with Gemma deciding and sol
translating.

## Setup

- **Clips** (`build_clips.py`): 20 unseen FLEURS test sentences (CC BY 4.0) shared by en, es, de, hi, tr and
  fr. No earlier clip used them (every FLEURS id named in the earlier evals' clip and result files was left
  out). They were drawn with seed 2026, and each has 6–25 English words. One recording per sentence,
  alternating male and female readers, with the same two pause patterns as before: *reg* (1.0–1.95 s between
  sentences) and *irr* (0.3–1.2 s). The ids are in `raw/clips/`.
- **Recognition:** MAI-Transcribe-2-Streaming, streamed in real time with every partial and final kept
  (`stream_partials.py`, unchanged).
- **What was said** (`witness.py`, Gemini Flash): 5 English recordings of 20 stop early or misread (graded
  against what was said). Spanish has 1 such recording, German 1, Hindi 0, Turkish 3 and French 5; these are
  left out of the into-English scores.
- **Translator and decider:** `google.gemma-4-31b` on Amazon Bedrock (us-east-2), temperature 0. For the
  en→fr sol arms: gpt-6-sol on Azure AI Foundry (a deployment named by `FOUNDRY_DEPLOYMENT`), `reasoning_effort` low, as in
  the earlier `2026-10-llm-commit-policy-bedrock-fr-ar-sw` run (not yet in this repository).
- **Arms** (`simulate_ct.py`): Sentence, Phrase ≤8 and Agree are the earlier runs' arms, unchanged. The
  boundary cutter is the scored-boundary cutter ported from the Worker, for es→en and fr→en only. In the
  complete-thought arms, words are committed as before (two partials agree, a 300 ms pause, or the final)
  and join a "tail" of words heard but not yet translated. The tail runs across recogniser finals. Gemma gets
  the tail as numbered words, with the last two thoughts as context. It answers `{"end": N, "translation":
  ...}` (words 1..N are a complete thought) or WAIT. As a fallback, the whole tail is translated as a
  sentence when nothing new has been heard for 2 s or more than 30 words are waiting.
- **Voice timing** (`tts_timing.py`): Azure neural TTS (Jenny, Elvira, Katja, Swara, Emel, Denise), time to
  first audio and characters per second, measured on this run's chunks.
- **Cut, grade, contradictions, splits** (`grade_all.py`, `split.py`): the earlier `seg_all.py`, `grade.py`
  and `contradictions.py`, unchanged, with gemini-flash-latest. One blind call per direction and clip
  grades every arm side by side (for en→fr, all nine arms in the same call). `split.py` is new: for each read
  sentence it counts the chunks that stop in the middle of a clause.
- **Two grading rounds.** Round 2 repeats the grading calls under new ids, so the arms are shuffled under
  different letters. It covers the eight directions with a close call. de→en and hi→en were left out: in
  both, every gap between arms is 10 points or more.
- `analyze_ct.py` (latency, calls, tokens, grades) and `table.py` make the tables below.

## Results

Each cell is the mean of both pause patterns (2 graded clips of 20 sentences each). Latencies are medians of
the per-clip figures, in seconds. The longest wait is the larger of the two clips. Quality is 0–100 against
what was said. "Critical" is the mean number of critical errors per graded clip. "Longest wait" runs from
when a chunk's first source word was spoken to that chunk's first audio. "Sentences split mid-clause" is the
share of read sentences that have at least one chunk ending inside a clause. "Quality of unsplit sentences"
is the round-1 score over the sentences that were not split. "Calls per sentence" counts Gemma calls, plus
sol calls where marked. "Thoughts by fallback" is the number of
complete-thought chunks per read sentence that came from the 2 s or 30-word fallback, as a percentage.

\* For whole-sentence arms, "wrong later" counts the *reg* clip only. On *irr*, one recogniser final often
covers two or three read sentences. The check then sees the same chunk under each of those sentences and
marks it "repeated" (24–54% per clip). That figure measures the cut, not the translation.

**Per direction**

| Direction | Arm | Quality, said (round 1) | Round 2 | Mean | Critical | Speech starts → first audio (s) | Speech ends → last audio, p50 (s) | p90 (s) | Longest wait (s) | Chunks wrong later | Sentences split mid-clause | Quality of unsplit sentences | Calls per sentence | Thoughts by fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| en→es | Sentence (silence) | 89.2 | 90.0 | **89.6** | 1.0 | 9.3 | 3.9 | 9.4 | 22.7 | 8%* | 12% | 97.1 | 1.0 | – |
| en→es | Phrase ≤8 | 71.7 | 71.7 | **71.7** | 2.5 | 3.4 | 0.9 | 2.7 | 7.8 | 8% | 80% | 91.1 | 3.0 | – |
| en→es | Agree | 81.7 | 82.5 | **82.1** | 1.5 | 2.5 | 2.1 | 7.1 | 21.0 | 6% | 92% | 100.0 | 10.4 | – |
| en→es | CT (a) first complete | 71.7 | 71.7 | **71.7** | 3.5 | 4.5 | 1.1 | 2.1 | 9.8 | 9% | 18% | 74.4 | 13.6 | 0% |
| en→es | CT (b) two checks agree | 85.0 | 84.2 | **84.6** | 1.0 | 7.2 | 2.2 | 4.2 | 11.7 | 5% | 0% | 85.0 | 13.9 | 2% |
| en→es | CT (c) complete + dip | 81.7 | 85.0 | **83.3** | 2.0 | 6.2 | 1.2 | 2.7 | 15.4 | 5% | 18% | 84.5 | 13.2 | 5% |
| es→en | Sentence (silence) | 97.3 | 97.3 | **97.3** | 0.0 | 10.8 | 5.5 | 9.6 | 25.8 | 0%* | 5% | 99.0 | 0.8 | – |
| es→en | Phrase ≤8 | 83.3 | 82.5 | **82.9** | 1.0 | 3.6 | 1.4 | 2.9 | 6.4 | 6% | 87% | 95.8 | 3.3 | – |
| es→en | Agree | 91.2 | 92.1 | **91.7** | 1.0 | 2.6 | 2.3 | 15.1 | 30.2 | 4% | 82% | 100.0 | 10.7 | – |
| es→en | Boundary cutter | 92.1 | 91.2 | **91.7** | 1.0 | 6.4 | 3.2 | 4.9 | 11.4 | 15% | 50% | 93.3 | 1.8 | – |
| es→en | CT (a) first complete | 78.1 | 78.1 | **78.1** | 1.0 | 4.4 | 1.0 | 5.4 | 29.7 | 4% | 37% | 80.9 | 15.2 | 0% |
| es→en | CT (b) two checks agree | 87.8 | 87.8 | **87.8** | 1.5 | 8.0 | 2.1 | 2.8 | 14.1 | 0% | 5% | 89.1 | 16.2 | 5% |
| es→en | CT (c) complete + dip | 81.6 | 82.5 | **82.0** | 1.0 | 5.1 | 1.1 | 2.3 | 13.8 | 2% | 16% | 83.6 | 15.9 | 2% |
| en→de | Sentence (silence) | 90.0 | 88.3 | **89.2** | 1.5 | 9.2 | 3.9 | 9.4 | 22.7 | 4%* | 12% | 97.0 | 1.0 | – |
| en→de | Phrase ≤8 | 63.4 | 58.4 | **60.9** | 2.0 | 3.4 | 0.9 | 2.7 | 7.6 | 5% | 70% | 77.8 | 3.0 | – |
| en→de | Agree | 79.2 | 75.8 | **77.5** | 1.5 | 3.1 | 2.3 | 10.5 | 21.7 | 5% | 88% | 95.8 | 9.8 | – |
| en→de | CT (a) first complete | 70.0 | 67.5 | **68.8** | 2.0 | 4.8 | 1.2 | 4.0 | 11.4 | 3% | 2% | 70.1 | 13.2 | 0% |
| en→de | CT (b) two checks agree | 88.3 | 87.5 | **87.9** | 1.0 | 7.7 | 2.3 | 3.8 | 12.3 | 0% | 0% | 88.3 | 14.1 | 2% |
| en→de | CT (c) complete + dip | 79.2 | 75.0 | **77.1** | 1.0 | 6.4 | 1.2 | 3.2 | 14.8 | 4% | 5% | 80.1 | 13.4 | 5% |
| de→en | Sentence (silence) | 94.7 | – | **94.7** | 0.5 | 11.4 | 2.1 | 7.2 | 21.6 | 5%* | 3% | 95.4 | 0.9 | – |
| de→en | Phrase ≤8 | 67.6 | – | **67.6** | 3.5 | 4.1 | 0.9 | 2.0 | 7.2 | 5% | 66% | 62.5 | 3.0 | – |
| de→en | Agree | 71.9 | – | **71.9** | 2.0 | 2.5 | 1.9 | 9.5 | 23.5 | 5% | 87% | 100.0 | 11.3 | – |
| de→en | CT (a) first complete | 71.9 | – | **71.9** | 4.0 | 5.4 | 1.0 | 2.0 | 10.8 | 4% | 21% | 73.8 | 15.0 | 0% |
| de→en | CT (b) two checks agree | 81.6 | – | **81.6** | 2.5 | 6.8 | 2.3 | 3.8 | 14.9 | 2% | 3% | 82.1 | 16.1 | 2% |
| de→en | CT (c) complete + dip | 69.3 | – | **69.3** | 4.5 | 5.8 | 1.1 | 2.5 | 12.7 | 5% | 11% | 70.4 | 14.9 | 2% |
| en→hi | Sentence (silence) | 90.8 | 91.7 | **91.2** | 1.0 | 9.4 | 3.9 | 9.3 | 23.0 | 8%* | 12% | 98.0 | 1.0 | – |
| en→hi | Phrase ≤8 | 63.4 | 66.7 | **65.0** | 2.5 | 3.5 | 0.9 | 2.7 | 7.2 | 7% | 60% | 72.9 | 3.0 | – |
| en→hi | Agree | 77.5 | 80.0 | **78.8** | 1.5 | 2.9 | 2.6 | 33.3 | 69.1 | 9% | 75% | 94.5 | 8.1 | – |
| en→hi | CT (a) first complete | 70.8 | 70.0 | **70.4** | 2.0 | 4.7 | 1.1 | 3.8 | 11.1 | 1% | 8% | 70.4 | 13.7 | 0% |
| en→hi | CT (b) two checks agree | 88.3 | 91.7 | **90.0** | 0.5 | 7.8 | 2.4 | 5.5 | 12.4 | 2% | 0% | 88.3 | 14.1 | 2% |
| en→hi | CT (c) complete + dip | 79.2 | 77.5 | **78.3** | 1.5 | 6.1 | 1.2 | 4.1 | 12.4 | 4% | 2% | 78.6 | 13.6 | 2% |
| hi→en | Sentence (silence) | 90.8 | – | **90.8** | 0.5 | 11.2 | 3.4 | 7.8 | 21.7 | 5%* | 8% | 92.5 | 0.9 | – |
| hi→en | Phrase ≤8 | 50.9 | – | **50.9** | 5.0 | 4.0 | 0.8 | 3.0 | 7.1 | 9% | 70% | 69.5 | 3.4 | – |
| hi→en | Agree | 66.7 | – | **66.7** | 2.0 | 3.2 | 2.7 | 8.2 | 21.3 | 11% | 90% | 91.7 | 13.2 | – |
| hi→en | CT (a) first complete | 60.0 | – | **60.0** | 4.0 | 6.2 | 1.1 | 4.3 | 14.8 | 8% | 2% | 59.8 | 16.4 | 5% |
| hi→en | CT (b) two checks agree | 70.0 | – | **70.0** | 3.5 | 8.2 | 2.3 | 7.4 | 15.6 | 6% | 5% | 72.0 | 17.3 | 5% |
| hi→en | CT (c) complete + dip | 60.9 | – | **60.9** | 4.5 | 7.8 | 1.1 | 4.8 | 16.4 | 11% | 2% | 60.7 | 16.3 | 8% |
| en→tr | Sentence (silence) | 93.3 | 92.5 | **92.9** | 1.0 | 9.3 | 4.0 | 9.4 | 23.0 | 8%* | 8% | 97.3 | 1.0 | – |
| en→tr | Phrase ≤8 | 66.7 | 66.7 | **66.7** | 2.0 | 3.4 | 0.9 | 2.7 | 7.3 | 10% | 65% | 73.6 | 3.0 | – |
| en→tr | Agree | 85.0 | 81.7 | **83.3** | 1.0 | 2.6 | 2.5 | 8.7 | 20.3 | 11% | 90% | 91.7 | 9.9 | – |
| en→tr | CT (a) first complete | 68.3 | 64.2 | **66.2** | 2.5 | 4.4 | 1.2 | 3.6 | 11.1 | 5% | 8% | 70.3 | 13.7 | 0% |
| en→tr | CT (b) two checks agree | 88.3 | 87.5 | **87.9** | 0.5 | 7.7 | 2.3 | 5.2 | 17.1 | 0% | 2% | 89.7 | 13.6 | 2% |
| en→tr | CT (c) complete + dip | 80.0 | 79.2 | **79.6** | 1.0 | 6.3 | 1.1 | 4.7 | 15.4 | 3% | 8% | 82.2 | 13.6 | 5% |
| tr→en | Sentence (silence) | 90.2 | 90.2 | **90.2** | 0.5 | 10.8 | 1.9 | 7.9 | 22.1 | 0%* | 3% | 90.9 | 0.8 | – |
| tr→en | Phrase ≤8 | 64.7 | 62.8 | **63.7** | 2.0 | 4.6 | 0.9 | 2.8 | 9.2 | 12% | 62% | 77.0 | 2.5 | – |
| tr→en | Agree | 76.5 | 78.4 | **77.4** | 2.0 | 4.1 | 1.9 | 8.0 | 21.9 | 8% | 88% | 100.0 | 10.6 | – |
| tr→en | CT (a) first complete | 76.5 | 74.5 | **75.5** | 0.5 | 6.4 | 1.0 | 1.4 | 11.2 | 6% | 6% | 77.1 | 12.1 | 0% |
| tr→en | CT (b) two checks agree | 85.3 | 84.3 | **84.8** | 1.0 | 7.9 | 2.2 | 3.3 | 14.4 | 2% | 0% | 85.3 | 13.0 | 5% |
| tr→en | CT (c) complete + dip | 81.3 | 80.4 | **80.9** | 1.0 | 7.4 | 1.0 | 1.5 | 14.0 | 4% | 6% | 80.2 | 12.2 | 2% |
| en→fr | Sentence (silence) | 86.7 | 88.3 | **87.5** | 1.0 | 9.2 | 3.9 | 9.3 | 22.7 | 4%* | 12% | 91.5 | 1.0 | – |
| en→fr | Phrase ≤8 | 72.5 | 71.7 | **72.1** | 2.0 | 3.4 | 0.9 | 4.1 | 7.7 | 6% | 70% | 81.5 | 3.0 | – |
| en→fr | Agree | 84.2 | 81.7 | **82.9** | 1.0 | 2.8 | 2.7 | 7.5 | 20.0 | 7% | 90% | 91.7 | 10.0 | – |
| en→fr | CT (a) first complete | 75.0 | 71.7 | **73.3** | 1.5 | 4.8 | 1.1 | 2.9 | 13.1 | 2% | 5% | 75.5 | 13.1 | 0% |
| en→fr | CT (b) two checks agree | 82.5 | 82.5 | **82.5** | 1.0 | 7.6 | 2.2 | 5.7 | 15.7 | 3% | 0% | 82.5 | 13.6 | 5% |
| en→fr | CT (c) complete + dip | 79.2 | 79.2 | **79.2** | 1.0 | 6.4 | 1.1 | 4.8 | 23.0 | 5% | 10% | 79.6 | 13.1 | 8% |
| en→fr | Sentence (silence), sol | 90.8 | 90.0 | **90.4** | 1.0 | 10.0 | 4.5 | 10.8 | 23.5 | 4%* | 10% | 93.7 | 1.0 sol | – |
| en→fr | CT (b), sol decides and translates | 90.8 | 91.7 | **91.2** | 0.5 | 10.2 | 5.2 | 10.4 | 22.0 | 19% | 2% | 90.5 | 4.6 sol | 20% |
| en→fr | CT (b), Gemma decides, sol translates | 89.2 | 91.7 | **90.4** | 0.0 | 8.5 | 3.5 | 6.3 | 16.4 | 0% | 0% | 89.2 | 11.0 + 1.5 sol | 2% |
| fr→en | Sentence (silence) | 97.8 | 98.9 | **98.3** | 0.0 | 8.7 | 1.9 | 8.1 | 21.1 | 5%* | 3% | 97.7 | 0.9 | – |
| fr→en | Phrase ≤8 | 81.1 | 81.2 | **81.1** | 1.0 | 3.1 | 0.8 | 2.9 | 7.0 | 5% | 93% | 100.0 | 3.2 | – |
| fr→en | Agree | 91.1 | 92.2 | **91.7** | 1.0 | 2.2 | 1.8 | 5.0 | 11.9 | 3% | 97% | 100.0 | 10.9 | – |
| fr→en | Boundary cutter | 87.8 | 86.7 | **87.2** | 1.0 | 6.1 | 1.9 | 4.7 | 12.6 | 14% | 33% | 88.3 | 1.6 | – |
| fr→en | CT (a) first complete | 86.7 | 85.6 | **86.1** | 1.0 | 4.7 | 1.1 | 2.3 | 9.8 | 2% | 13% | 89.7 | 13.6 | 0% |
| fr→en | CT (b) two checks agree | 93.3 | 93.3 | **93.3** | 0.5 | 6.7 | 1.9 | 3.0 | 11.7 | 0% | 3% | 93.2 | 14.1 | 2% |
| fr→en | CT (c) complete + dip | 85.6 | 85.6 | **85.6** | 1.5 | 5.0 | 1.1 | 3.9 | 11.1 | 3% | 10% | 87.7 | 13.5 | 5% |

**Every direction together** (Gemma arms. Each figure is the mean of the ten directions' rows above;
the boundary cutter ran in two directions only, so it is left out.)

| Arm | Quality, said | Critical | First audio (s) | Last audio p50 / p90 (s) | Longest wait (s) | Wrong later | Split mid-clause | Gemma calls per sentence | Input tokens per hour |
|---|---|---|---|---|---|---|---|---|---|
| Sentence (silence) | 92.2 | 0.7 | 9.9 | 3.4 / 8.7 | 22.6 | 5%* | 8% | 1.0 | 82k |
| Phrase ≤8 | 68.3 | 2.4 | 3.6 | 0.9 / 2.9 | 7.5 | 7% | 72% | 3.0 | 423k |
| Agree | 80.4 | 1.4 | 2.9 | 2.3 / 11.3 | 26.1 | 7% | 88% | 10.5 | 998k |
| CT (a) first complete | 72.2 | 2.2 | 5.0 | 1.1 / 3.2 | 13.3 | 4% | 12% | 14.0 | 1.78M |
| **CT (b) two checks agree** | **85.0** | 1.3 | 7.6 | 2.2 / 4.5 | 14.0 | **2%** | **2%** | 14.7 | 2.10M |
| CT (c) complete + dip | 77.6 | 1.9 | 6.2 | 1.1 / 3.5 | 14.9 | 5% | 9% | 14.1 | 1.90M |

Gemma call time on Bedrock, every call: the complete-thought checks p50 about 285 ms (p90 460–560 ms),
Agree 385 ms (631), Sentence 474 ms (765). sol, when it decides, takes 1.5 s per call (p90 2.7 s).

**en→fr against sol** (the sol-vs-Gemma rule: use Gemma if it is at least as good as sol. If it is below
sol, use it only when it is within 5 points **and** scores 80 or more. The rule is applied to the two-round
mean.)

| Style | Gemma | sol | Gap | Rule |
|---|---|---|---|---|
| Whole sentences | 87.5 | 90.4 | −2.9 | passes (within 5, above 80) |
| CT (b), Gemma decides and translates vs sol decides and translates | 82.5 | 91.2 | −8.7 | keep sol |
| CT (b), Gemma decides and translates vs Gemma decides, sol translates | 82.5 | 90.4 | −7.9 | keep sol for the translation |

## Findings

1. **CT (b) is the best variant, in every direction.** Across the ten directions it scores 85.0, against
   72.2 for (a) and 77.6 for (c). It is the best of the three in all ten directions in round 1. In round 2
   it is the best everywhere except en→es, where (c) is 0.8 points higher. Its chunks are almost never contradicted later (2%), and it splits a sentence
   mid-clause in only 2% of sentences, against 88% for Agree and 72% for Phrase ≤8.
2. **Why (a) and (c) lose.** A clause often looks complete before its last words arrive ("…one of the Seven
   Wonders that is still standing" | "today."). (a) commits at the first "complete", so the late words
   become a stray piece joined to the next sentence, and the verb or the object is sometimes placed wrong.
   Checking for an energy dip (c) helps a little but not enough: a short dip often falls inside the
   sentence. (b) waits for a second check after more words have arrived. If Gemma names the same end word
   again, the thought really has ended.
3. **CT (b) stays close to whole sentences out of English.** The gap is −1.2 into Hindi, −1.3 into German,
   −5.0 into Spanish and −5.0 into Turkish. It ends sooner: the slowest tenth of sentences end 3.8–5.5 s after
   the speaker stops, against 9.3–9.4 s for sentences, and the longest wait is 12–17 s against 23 s.
4. **Into English, whole sentences stay ahead.** CT (b) is −5.0 for fr→en, −5.4 for tr→en, −9.5 for es→en,
   −13.1 for de→en and −20.8 for hi→en.
5. **hi→en and tr→en, where Agree failed:**
   - **tr→en:** CT (b) scores 84.8, against 77.4 for Agree and 90.2 for sentences, with 2% of chunks wrong
     later and no split sentences. It is the first streaming policy that comes near sentences in this
     direction.
   - **hi→en:** CT (b) does not rescue it. It scores 70.0, against 66.7 for Agree and 90.8 for sentences, with
     3.5 critical errors per clip. The grader notes are mostly mistranslations and omissions of whole
     phrases, not early guesses. Gemma's Hindi→English is weaker when it works on part of a sentence.
6. **First audio:** CT (b) starts speaking 6.7–8.2 s after the speaker starts. That is about 2 s sooner than
   sentences (8.7–11.4 s) but 4–5 s later than Agree (2.2–4.1 s). Most of the gain is at the end of the
   sentence, not the start. Its last audio comes at the median 1.9–2.4 s after the speaker stops, about
   the same as Agree, and its slowest tenth is much better than Agree's (2.8–7.4 s against 5.0–33 s).
7. **en→fr with sol:**
   - With sol deciding as well, quality is the best (91.2), but sol is slow: 1.5 s per check. It
     starts later than sentences (10.2 s) and falls back to a whole-tail flush 0.2 times per sentence.
   - **With Gemma deciding and sol translating**, quality is the same as sol sentences (90.4). It starts
     sooner (8.5 s against 10.0 s), its slowest tenth ends at 6.3 s against 10.8 s, and none of its chunks
     is contradicted later or split mid-clause. It makes 11 Gemma calls and 1.5 sol calls per sentence.
   - Gemma alone with CT (b) is 82.5, which fails the rule (−8.7).
   - Gemma sentences pass the rule this time (87.5 against 90.4). The earlier fr/ar/sw run found 79.6
     against 83.8, so the two clip sets disagree.
8. **Calls and tokens:** CT (b) makes about 14–17 Gemma calls per sentence: a check at every change of the tail. That is
   about 2.1M input tokens per hour of speech, about twice Agree. A check is short, so the call time is low
   (about 290 ms).

## Recommendation per direction

Phones are fast mode (conversation: the first audio matters most). The PA is where waiting is expected:
quality first, then how far the voice ends behind the speaker. On the PA, CT (b) takes the place of
silence sentences only if it is within 5 points of them.

| Direction | Phones (fast mode) | PA |
|---|---|---|
| en→es | **Agree** (82.1, first audio 2.5 s). CT (b) is 2.5 points better but starts 4.7 s later. | **Sentences** (89.6). CT (b) is a candidate: −5.0, with the slowest tenth ending 4.2 s after the speaker against 9.4 s. |
| es→en | Keep **Agree** or the boundary cutter (91.7 each). CT (b) is lower (87.8). | **Sentences** (97.3). CT (b) is −9.5. |
| en→de | **CT (b)** (87.9, against 77.5 for Agree, with no splits). First audio 7.7 s. | **CT (b)**: −1.3 against sentences, and it ends sooner (p90 3.8 s against 9.4 s). |
| de→en | **CT (b)** (81.6, against 71.9 for Agree). | **Sentences** (94.7). CT (b) is −13. |
| en→hi | **CT (b)** (90.0, against 78.8 for Agree). | **CT (b)**: −1.2 against sentences, p90 5.5 s against 9.3 s. |
| hi→en | **Whole sentences.** Nothing streaming comes within 20 points (CT (b) 70.0, Agree 66.7). | **Sentences.** |
| en→tr | **CT (b)** (87.9, against 83.3 for Agree, with 0% of chunks wrong later against 11%). | **Sentences** (92.9). CT (b) is exactly −5.0, so it is a candidate to confirm on a second clip set. |
| tr→en | **CT (b)** (84.8, against 77.4 for Agree, 2% wrong later, no splits). This replaces whole sentences in fast mode. | **Sentences** (90.2). CT (b) is −5.4. |
| en→fr | **CT (b) with Gemma deciding and sol translating** (90.4, the same as sol sentences, first audio 8.5 s). If first audio matters more than splits, Agree with Gemma (82.9) still fails the rule against sol. | **CT (b) with Gemma deciding and sol translating**: the same quality as sol sentences, and it ends sooner (p90 6.3 s against 10.8 s). Gemma sentences passed the rule here (−2.9) but failed it in the earlier run, so keep sol for the translation. |
| fr→en | **Agree** (91.7, first audio 2.2 s). CT (b) is 93.3 but starts 4.5 s later. | **Sentences** (98.3). CT (b) is −5.0, a candidate. |

Not tested: a decider prompt with few-shot examples. Not tested: cutting the check rate (for example,
checking only when a word ends a clause). Not tested: Gemma deciding and sol translating in any direction
other than en→fr.

## Limits

- One clip set: 20 read FLEURS sentences per language, one reader each, joined with artificial pauses.
  Two grading rounds with Gemini Flash in eight directions, one round in de→en and hi→en. A few points
  either way is noise. Round 2 changed no ranking between arms.
- Quality levels compare within this run only. Each run is graded in its own calls.
- The complete-thought prompt is new and untuned. The prompts are the harness's, not the apps'
  production prompts.
- Latency assumes one call at a time per stream, with Gemma on Bedrock, not on the stack's 4-bit vLLM
  build. Fourteen checks a sentence may be slower on a shared box.
- The boundary cutter ran only for es→en and fr→en.
- Agree's en→hi p90 last audio (33 s) and longest wait (69 s) come from two slow Bedrock calls (19 s and
  47 s) on one clip. Treat them as an outlier.

## Files

- `build_clips.py`: the unseen clips. `stream_partials.py`: MAI streaming recognition. `witness.py`: what
  was said.
- `simulate_ct.py`: the replay, with the complete-thought arms, the boundary cutter and the sol arms.
- `tts_timing.py`: voice timing. `grade_all.py`: cut, grade, contradictions. `split.py`: mid-clause splits.
- `analyze_ct.py`: latency, calls, tokens, grades. It writes `results.json` (round 1) and, with
  `GRADES=grades_r2.json RESULTS=results_r2.json`, `results_r2.json`. `table.py`: the per-direction table.
- `raw/tts.json`: the voice timing.

**Not included:**
- the clip audio and the clip metadata (`raw/clips/`, with the FLEURS ids and texts): `build_clips.py` rebuilds them
  from FLEURS with seed 2026;
- the recognisers' partials and finals (`raw/rec/`), each replay's chunks and calls (`raw/sim/`) and the cut
  (`raw/seg/`): about 11 MB of raw dumps that carry the transcripts and translations;
- the grading inputs and outputs (`jobs*.json`, `grades*.json`, `contra*.json`, `split*.json`) and `witness/`: raw
  dumps (up to 0.6 MB each) with the sentence texts. Their figures are in `results.json` and `results_r2.json`.
- the earlier commit-policy run's scripts. `simulate_ct.py` loads `simulate_policy.py` (the Sentence, Phrase ≤8 and
  Agree arms, and the Bedrock call) from `../2026-10-llm-commit-policy-bedrock-de-hi-tr/`, which is not yet in this
  repository, so rerunning the replay needs that folder beside this one. The other scripts are copies or load
  folders already here.

## Reproduce

```
python3 -I build_clips.py CLIPS ../2026-10-real-voices USED_IDS.json
AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 MODEL=mai-transcribe-2-streaming \
  <venv with azure-cognitiveservices-speech==1.52.0>/bin/python -I stream_partials.py CLIPS/clips_reg WORK/rec mai_reg en es de hi tr fr
#   (and the same for clips_irr with tag mai_irr)
GEMINI_API_KEY=... python3 -I witness.py CLIPS/clips_reg <lang> UO/witness/<lang>.json    # each language; UO/said_en.json from the flagged English
CLIPS_ROOT=CLIPS RECS=mai THREADS=10 <venv with boto3, numpy>/bin/python simulate_ct.py WORK S-mai P8-mai agree-mai cta-mai ctb-mai ctc-mai B8-mai
CLIPS_ROOT=CLIPS RECS=mai DIRS=en-fr CT_SOL_VARIANT=b FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=... \
  <venv with boto3, numpy>/bin/python simulate_ct.py WORK S-sol-mai ctb-sol-mai ctb-gs-mai
AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I tts_timing.py WORK
GEMINI_API_KEY=... python3 -I grade_all.py seg CLIPS WORK
python3 -I analyze_ct.py jobs CLIPS UO WORK
GEMINI_API_KEY=... python3 -I grade_all.py grade WORK/jobs.json WORK/grades.json
GEMINI_API_KEY=... python3 -I grade_all.py contra WORK/contra_jobs.json WORK/contra.json
GEMINI_API_KEY=... python3 -I split.py WORK/split_jobs.json WORK/split.json
# round 2: jobs.json without de-en and hi-en, each id + ":r2"
GEMINI_API_KEY=... python3 -I grade_all.py grade WORK/jobs_r2.json WORK/grades_r2.json
python3 -I analyze_ct.py table CLIPS UO WORK
GRADES=grades_r2.json RESULTS=results_r2.json python3 -I analyze_ct.py table CLIPS UO WORK
python3 -I table.py
```
