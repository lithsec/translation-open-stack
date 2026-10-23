# The full open stack, every direction, October 2026

The stack as it is now on main (the quiet-talker fix #46, the abbreviation fix #39, the
per-language turn rules #38, Omnilingual 7B for Lao and Khmer, and the `llmmt` translator
from #47), plus translation context for `llmmt` (#48). 14 directions, live at real time,
**one direction at a time**, on two clip sets nobody tuned on, every system for a direction
graded blind in one call. Three questions:

1. What is the best live accuracy in each direction?
2. Out of English (and Japanese into English), Hy-MT2 or Gemma 4?
3. Keep or revert #38's turn rules for Japanese, Haitian Creole, Khmer and Lao?

## Setup

- **Clips.** Set **a**: `../2026-10-unseen`, regular pauses. Set **b**: 20 more FLEURS test
  sentences (CC BY 4.0) shared by en, es, fr, ja, km, lo, pt that no earlier clip used, and 20
  more CMU Haitian Creole utterances, built the same way (`build_clips_b.py`: the unseen
  builder, excluding every earlier clip set's sentences, seed 2027, regular pauses only). Each
  clip is 20 read sentences, several readers, 1.0-1.95 s between sentences.
- **What was said.** Every recording was checked against its text with the unseen round's
  witness (`../2026-10-unseen/witness.py`). Set b: 4 of 20 English recordings, 2 French,
  2 Haitian Creole and 1 each of Japanese, Khmer and Lao differ from their text.
- **Stack.** One 80 GB NVIDIA A100. `STACK_PROFILE=cuda-80gb` (Omnilingual 7B for Lao and
  Khmer). Whisper large-v3 hears en, es, fr, ja, pt; Omnilingual 300M hears Haitian Creole.
  MADLAD 3B was loaded as the fallback translator (`MADLAD=3b`) instead of the 7B to leave
  room for the LLM; no `llmmt` request in a measured run failed over to it.
- **LLM translators** under vLLM 0.31 beside the stack (`llmmt`, with `?context=1`):
  Gemma 4 31B, Google's 4-bit QAT build (`google/gemma-4-31B-it-qat-w4a16-ct`, Apache-2.0),
  and, for Lao, MiLMMT-46 12B (Gemma terms). The two were swapped on the same card for the
  Lao phase, not run together.
- **Client.** The e2e client of `../2026-10-open-stack-e2e`, with `?context=1` on every
  connection, so Hy-MT2 and the LLMs both got the previous pieces as context.
- **Configurations** (`configs/`, the `languages.toml` each phase ran):
  - `A`: Hy-MT2 out of English and into English from es, pt, fr, ja, km; Gemma 4 both ways for
    Haitian Creole.
  - `B`: Gemma 4 for es, pt, fr, ja, km (run only for the directions out of English and ja→en).
  - `L`: MiLMMT for Lao.
  - `PA` / `PL`: A and L with the turn values from before #38 (Lao/Khmer 700 ms : 15 s at any
    length; Japanese and Haitian Creole on the flags' defaults).
- **Grading** (`round.py`, then `../2026-10-unseen/grade.py`): gemini-pro-latest, 0-3 per
  sentence with a critical flag, all systems for a (set, direction) shuffled under letters in
  one call, against the written text and against what was said (English sources: the
  witnessed English; other sources: the sentences whose recording matches its text).
  Quality is the share of the possible 3. Rounds move 5-10 points between calls, so compare
  systems within a direction, and read single-set differences under 5 points as noise.

## 1. Best live accuracy per direction

Quality against what was said, mean of sets a and b (written text in brackets), critical
errors over both sets, recognition error (characters wrong against what was said), and the
time from the speaker stopping to the start of the last translated audio (p50, set a / b).

| Direction | Best translator | Quality, said (written) | Critical | Recognition | Stop → last audio |
|---|---|---|---|---|---|
| es→en | Hy-MT2 | **84.6** (83.3) | 3 | 0.8% | 2.5 / 2.5 s |
| ja→en | Gemma 4 | **80.9** (80.0) | 8 | 3.8% | 2.4 / 2.5 s |
| fr→en | Hy-MT2 | 76.8 (76.7) | 8 | 2.2% | 2.5 / 2.6 s |
| pt→en | Hy-MT2 | 73.3 (73.3) | 10 | 1.2% | 2.4 / 2.5 s |
| en→es | Gemma 4 / Hy-MT2 (tie) | 72.5 (62.5 / 64.2) | 9 / 9 | 5.0% | 1.7 / 1.6 s (Gemma 4) |
| en→lo | MiLMMT | 71.7 (58.4) | 9 | 5.0% | 2.1 / 1.8 s |
| en→fr | Gemma 4 | 70.8 (61.7) | 8 | 5.0% | 1.9 / 1.8 s |
| en→ja | Gemma 4 / Hy-MT2 (tie) | 70.0 (61.6 / 62.5) | 11 / 8 | 5.0% | 1.7 / 1.7 s (Gemma 4) |
| en→ht | Gemma 4 | 69.2 (57.5) | 9 | 5.0% | 1.7 / 1.5 s |
| en→pt | Gemma 4 / Hy-MT2 (tie) | 65.8 (65.8 / 65.0) | 7 / 7 | 5.0% | 1.7 / 1.5 s (Gemma 4) |
| en→km | Gemma 4 | 63.4 (48.4) | 6 | 5.0% | 1.8 / 1.7 s |
| km→en | Hy-MT2 | 61.3 (57.5) | 11 | 8.9% | 3.9 / 3.7 s |
| lo→en | MiLMMT | 50.9 (50.0) | 21 | 15.8% | 2.7 / 2.9 s |
| ht→en | Gemma 4 | 49.6 (47.5) | 20 | 3.0% | 3.1 / 2.6 s |

Per set (said): es→en 84.2 / 85.0, ja→en 74.1 / 87.7, fr→en 85.0 / 68.5, pt→en 78.3 / 68.3,
en→lo 75.0 / 68.3, en→ht 76.7 / 61.7, km→en 64.8 / 57.9, lo→en 43.9 / 57.9, ht→en
54.9 / 44.4. Every number is in `results.json`.

- **English recognition** is 5.0% characters wrong against what was said (6.3% set a, 3.6%
  set b): the quiet-talker fix holds on a second set. It was 16-19% before #46 on set a.
- **No sentences were dropped** except Hy-MT2 into Khmer (below) and one Lao sentence on set a.
- **Into English from Lao and Haitian Creole** is still the weakest: Lao is held back by
  recognition (15.8% wrong even on the 7B); Haitian Creole is heard well (3.0%) and lost in
  translation (20 critical errors).

## 2. Hy-MT2 or Gemma 4

Same recognition, same clips, same grading call (said; written in brackets):

| Direction | Set | Hy-MT2 | Gemma 4 | Hy-MT2 latency | Gemma 4 latency |
|---|---|---|---|---|---|
| en→es | a / b | 73.3 / 71.7 (61.7 / 66.7) | 75.0 / 70.0 (61.7 / 63.3) | 2.5 / 2.2 s | 1.7 / 1.6 s |
| en→pt | a / b | 65.0 / 66.7 (66.7 / 63.3) | 66.7 / 65.0 (66.7 / 65.0) | 2.6 / 2.3 s | 1.7 / 1.5 s |
| en→fr | a / b | 71.7 / 61.7 (63.3 / 60.0) | 75.0 / 66.7 (61.7 / 61.7) | 2.7 / 2.6 s | 1.9 / 1.8 s |
| en→ja | a / b | 75.0 / 65.0 (63.3 / 61.7) | 73.3 / 66.7 (63.3 / 60.0) | 3.0 / 2.8 s | 1.7 / 1.7 s |
| en→km | a / b | 63.3 / 63.3 (50.0 / 50.0), **7 sentences without audio** | 70.0 / 56.7 (56.7 / 40.0), none dropped | 25.0 / 25.7 s | 1.8 / 1.7 s |
| ja→en | a / b | 70.4 / 80.7 (70.0 / 80.0) | **74.1 / 87.7** (75.0 / 85.0) | 2.8 / 3.1 s | 2.4 / 2.5 s |

- **Quality out of English is a tie.** Over both sets the two are within 0-4 points against
  what was said, and the per-set differences go both ways, inside one round's noise.
- **Gemma 4 is 0.7-1.3 s faster** to the last audio out of English (Hy-MT2 is a 4-bit
  transformers model in the stack's process; Gemma 4 runs under vLLM).
- **English → Khmer is where it matters.** Hy-MT2 falls behind real time into Khmer and drops
  sentences (7 without audio over the two sets, the last audio 25 s after the speaker
  stops). Gemma 4 keeps up (1.7-1.8 s, nothing dropped). Its graded quality is level overall
  (63.4 vs 63.3), better on set a and worse on set b, with fewer critical errors (6 vs 11).
- **Japanese → English: Gemma 4 is ahead on both sets** (+3.7 and +7.0), 0.4-0.6 s faster.
- **Load.** Three directions at once (en→es, en→pt, en→fr on set a), Gemma 4 serving all of
  them and the stack hearing all three: the last audio came 2.5-2.7 s after the speaker
  stopped instead of 1.7-1.9 s alone, nothing dropped.

## 3. #38's turn rules: keep

The pre-#38 values against today's, same translator, same grading call (said):

| Direction | Set | Pre-#38 | Today (#38) |
|---|---|---|---|
| ja→en (Hy-MT2) | a / b | 66.7 / 75.4 | 70.4 / 80.7 |
| ht→en (Gemma 4) | a / b | 54.9 / 38.9 | 54.9 / 44.4 |
| km→en (Hy-MT2) | a / b | 64.8 / 54.4 | 64.8 / 57.9 |
| lo→en (MiLMMT) | a / b | 43.9 / 54.4 | 43.9 / 57.9 |

Today's rules are level or ahead in all eight comparisons (+0 to +5.5), and recognition is the
same or better (Khmer set b 12.3% → 9.5%). The pre-#38 rules cut Haitian Creole and Lao into
more pieces (31 and 27-33 utterances for 20 sentences, against 21-23 and 26-27) and answer up
to 0.8 s sooner at the median. One clip per set, so each difference alone is small; together
they don't support reverting.

## Recommendations

- **Translators:**

  | Direction | Translator |
  |---|---|
  | en→es, en→pt, en→fr, en→ja | Gemma 4 (`llmmt`): same quality, about 1 s faster; Hy-MT2 is a fine fallback |
  | en→km | Gemma 4: Hy-MT2 can't keep up live |
  | ja→en | Gemma 4 |
  | es→en, pt→en, fr→en, km→en | Hy-MT2 (not A/B tested here) |
  | en→ht, ht→en | Gemma 4 |
  | en→lo, lo→en | MiLMMT |

  `llmmt` routes a pair by its non-English side, so `[es] translator = "llmmt"` with a
  Gemma `llmmt =` line sends es→en to Gemma 4 too. That direction wasn't measured here;
  until `llmmt` can route by direction, Japanese and Khmer are the safe switches (ja→en
  measured, km→en close enough to take the speed), and es, pt, fr can wait.
- **Card:** one 80 GB card holds the stack with the 7B, VoxCPM2 and Gemma 4 4-bit at 68 GB.
  MiLMMT needs the same room again, so Lao on the same card means Gemma 4 for Lao (not
  measured live here) or a second card.
- **#38:** keep.

## Limits

- One 20-sentence read clip per language per set, one grading call per (set, direction).
- Both sets are FLEURS read speech (CMU for Haitian Creole), not conversation or room audio.
- The Haitian Creole English references are model-made (`../2026-10-unseen/README.md`).
- Gemma 4 and MiLMMT ran one at a time; their GPU memory figures are each with
  `--gpu-memory-utilization 0.36`.

## Files

- `README.md`, `results.json`: per set, direction and system: quality (written and said),
  critical errors, recognition CER, latency, sentences without audio; the load test; GPU memory.
- `round.py`: grading jobs and the table.
- `build_clips_b.py`: set b.
- `configs/`: the `languages.toml` of each phase.
