# Fourteen more languages, live, November 2026

The 14 languages the stack serves that no round had run live through it: Mandarin, Ukrainian, Vietnamese,
Arabic, Persian, Filipino and Swahili (Gemma 4 configured), and Italian, Korean, Indonesian, Turkish, Bengali,
Urdu and Hindi (Hy-MT2 only). Both directions with English, live at real time, one direction at a time, nonprofit
edition, image `2026.11.04` (main at `26f340a`), Gemma 4 31B 4-bit beside the stack on a 96 GB card. For the
seven Hy-MT2-only languages, a second stack start (`configs/B.toml`) routed them to Gemma 4 as the others are,
graded beside Hy-MT2 in the same call.

## Results: the stack as configured (A)

Quality: share of the possible 3 per sentence, blind (gemini-pro-latest), against the FLEURS text (English
reference meaning), mean of sets a and b (20 sentences each, 40 per direction). Latency: speaker stops → start
of the sentence's last translated audio, p50 and p90 per set a / b, seconds. Drops: sentences without audio /
utterances the pipeline dropped. Recognition: characters wrong against the FLEURS text.

| Direction | Recognition | Translator | Quality (set a / b) | Critical | Recognition error | Last audio p50 | Last audio p90 | Drops |
|---|---|---|---|---|---|---|---|---|
| en→zh | Whisper large-v3 | Gemma 4 | **75.0** (76.7 / 73.3) | 6 | 4.2% | 2.2 / 2.1 | 2.4 / 2.7 | 0 / 0 |
| zh→en | Whisper large-v3 | Gemma 4 | **75.0** (73.3 / 76.7) | 11 | 6.8% | 2.4 / 2.6 | 2.8 / 2.9 | 0 / 0 |
| en→uk | Whisper large-v3 | Gemma 4 | **77.5** (75.0 / 80.0) | 8 | 4.2% | 1.9 / 2.0 | 2.5 / 2.6 | 0 / 0 |
| uk→en | Whisper large-v3 | Hy-MT2 | **81.7** (80.0 / 83.3) | 5 | 2.4% | 2.3 / 2.4 | 2.6 / 2.8 | 0 / 0 |
| en→vi | Whisper large-v3 | Gemma 4 | **81.7** (80.0 / 83.3) | 8 | 4.2% | 1.9 / 1.9 | 2.4 / 2.4 | 0 / 0 |
| vi→en | Whisper large-v3 | Gemma 4 | **55.8** (55.0 / 56.7) | 9 | 7.2% | 2.3 / 2.3 | 2.6 / 2.7 | 0 / 0 |
| en→ar | Whisper large-v3 | Gemma 4 | **78.3** (76.7 / 80.0) | 5 | 4.2% | 2.2 / 2.2 | 2.5 / 2.6 | 0 / 0 |
| ar→en | Whisper large-v3 | Gemma 4 | **80.8** (75.0 / 86.7) | 9 | 2.1% | 2.7 / 2.6 | 3.0 / 3.2 | 0 / 0 |
| en→fa | Whisper large-v3 | Gemma 4 | **77.5** (75.0 / 80.0) | 6 | 4.2% | 2.0 / 2.0 | 2.5 / 2.5 | 0 / 0 |
| fa→en | Omnilingual 300M | Gemma 4 | **65.0** (63.3 / 66.7) | 10 | 12.9% | 2.2 / 3.8 | 5.1 / 5.3 | 0 / 0 |
| en→tl | Whisper large-v3 | Gemma 4 | **80.8** (80.0 / 81.7) | 8 | 4.2% | 2.2 / 2.3 | 3.1 / 3.7 | 0 / 0 |
| tl→en | Whisper large-v3 | Gemma 4 | **62.5** (61.7 / 63.3) | 9 | 2.9% | 1.1 / 1.6 | 2.4 / 2.3 | 0 / 0 |
| en→sw | Whisper large-v3 | Gemma 4 | **70.8** (71.7 / 70.0) | 2 | 4.2% | 2.2 / 2.1 | 2.7 / 2.8 | 0 / 0 |
| sw→en | Omnilingual 300M | Gemma 4 | **36.7** (38.3 / 35.0) | 20 | 8.8% | 3.9 / 3.5 | 6.5 / 5.6 | 0 / 0 |
| en→it | Whisper large-v3 | Hy-MT2 | **76.7** (75.0 / 78.3) | 4 | 4.2% | 2.2 / 2.0 | 2.5 / 2.6 | 0 / 0 |
| it→en | Whisper large-v3 | Hy-MT2 | **84.2** (83.3 / 85.0) | 3 | 0.4% | 2.3 / 2.3 | 2.6 / 2.5 | 0 / 0 |
| en→ko | Whisper large-v3 | Hy-MT2 | **76.7** (78.3 / 75.0) | 7 | 4.2% | 2.5 / 2.5 | 3.2 / 3.2 | 0 / 0 |
| ko→en | Whisper large-v3 | Hy-MT2 | **80.0** (83.3 / 76.7) | 5 | 4.5% | 2.3 / 2.3 | 2.6 / 2.5 | 0 / 0 |
| en→id | Whisper large-v3 | Hy-MT2 | **76.7** (76.7 / 76.7) | 9 | 4.2% | 2.1 / 1.9 | 2.5 / 2.5 | 0 / 0 |
| id→en | Whisper large-v3 | Hy-MT2 | **70.0** (70.0 / 70.0) | 10 | 1.9% | 2.0 / 1.8 | 2.4 / 2.5 | 0 / 0 |
| en→tr | Whisper large-v3 | Hy-MT2 | **76.7** (78.3 / 75.0) | 8 | 4.2% | 2.1 / 2.1 | 2.6 / 2.9 | 0 / 0 |
| tr→en | Whisper large-v3 | Hy-MT2 | **79.2** (81.7 / 76.7) | 7 | 1.4% | 2.3 / 2.3 | 2.7 / 2.6 | 0 / 0 |
| en→bn | Whisper large-v3 | Hy-MT2 | **80.0** (80.0 / 80.0) | 3 | 4.2% | 4.3 / 4.4 | 5.4 / 6.3 | 0 / 0 |
| bn→en | Omnilingual 300M | Hy-MT2 | **60.0** (53.3 / 66.7) | 13 | 5.8% | 4.1 / 4.3 | 5.7 / 5.8 | 0 / 0 |
| en→ur | Whisper large-v3 | Hy-MT2 | **79.2** (73.3 / 85.0) | 7 | 4.2% | 3.6 / 3.9 | 4.9 / 4.7 | 0 / 0 |
| ur→en | Omnilingual 300M | Hy-MT2 | **38.3** (38.3 / 38.3) | 30 | 7.4% | 5.1 / 5.0 | 6.0 / 6.9 | 0 / 0 |
| en→hi | Whisper large-v3 | Hy-MT2 | **70.8** (71.7 / 70.0) | 11 | 4.2% | 4.1 / 4.4 | 5.3 / 5.3 | 0 / 0 |
| hi→en | Omnilingual 300M | Hy-MT2 | **47.5** (48.3 / 46.7) | 20 | 13.5% | 4.2 / 4.4 | 5.1 / 5.8 | 0 / 0 |

## Hy-MT2 against Gemma 4 for the seven Hy-MT2-only languages (A against B)

Same clips, same recognition, one grading call per direction and set with both outputs blind side by side.

| Direction | Hy-MT2 (as configured) | Gemma 4 | Gemma − Hy-MT2 | Critical, Hy-MT2 / Gemma | Last audio p50, Hy-MT2 / Gemma¹ |
|---|---|---|---|---|---|
| en→it | 76.7 (75.0 / 78.3) | 80.0 (78.3 / 81.7) | **+3.3** | 4 / 4 | 2.1 / 2.2 s |
| it→en | 84.2 (83.3 / 85.0) | 89.2 (85.0 / 93.3) | **+5.0** | 3 / 1 | 2.3 / 2.5 s |
| en→ko | 76.7 (78.3 / 75.0) | 82.5 (81.7 / 83.3) | **+5.8** | 7 / 4 | 2.5 / 2.2 s |
| ko→en | 80.0 (83.3 / 76.7) | 85.0 (88.3 / 81.7) | **+5.0** | 5 / 5 | 2.3 / 2.5 s |
| en→id | 76.7 (76.7 / 76.7) | 81.7 (78.3 / 85.0) | **+5.0** | 9 / 7 | 2.0 / 1.8 s |
| id→en | 70.0 (70.0 / 70.0) | 76.7 (78.3 / 75.0) | **+6.7** | 10 / 8 | 1.9 / 2.1 s |
| en→tr | 76.7 (78.3 / 75.0) | 77.5 (73.3 / 81.7) | **+0.8** | 8 / 6 | 2.1 / 2.0 s |
| tr→en | 79.2 (81.7 / 76.7) | 84.2 (88.3 / 80.0) | **+5.0** | 7 / 5 | 2.3 / 2.4 s |
| en→bn | 80.0 (80.0 / 80.0) | 82.5 (81.7 / 83.3) | **+2.5** | 3 / 4 | 4.4 / 2.1 s |
| bn→en | 60.0 (53.3 / 66.7) | 61.7 (56.7 / 66.7) | **+1.7** | 13 / 12 | 4.2 / 5.1 s |
| en→ur | 79.2 (73.3 / 85.0) | 80.0 (70.0 / 90.0) | **+0.8** | 7 / 7 | 3.8 / 2.3 s |
| ur→en | 38.3 (38.3 / 38.3) | 45.0 (41.7 / 48.3) | **+6.7** | 30 / 24 | 5.0 / 7.1 s |
| en→hi | 70.8 (71.7 / 70.0) | 77.5 (73.3 / 81.7) | **+6.7** | 11 / 9 | 4.3 / 2.4 s |
| hi→en | 47.5 (48.3 / 46.7) | 57.5 (53.3 / 61.7) | **+10.0** | 20 / 16 | 4.3 / 5.9 s |

¹ B ran sets a and b at the same time (two rooms on one stack), so its latencies are under twice the load of
A's; they are an upper bound, not a like-for-like comparison.

## Findings

1. **All 14 keep up live.** 56 runs as configured, no sentence without audio, no utterance dropped, no Gemma
   request failed over (`stack_A.log`). The last translated audio starts 1.3-2.7 s after the speaker stops at
   the median for the Whisper languages and out of English, except where Hy-MT2 writes Bengali, Urdu and Hindi
   (3.8-4.4 s) and where Omnilingual 300M hears Persian, Swahili, Bengali, Urdu or Hindi (3.0-5.0 s).
2. **Out of English, every language scores 70.8-81.7** (A): level with or above the earlier rounds' directions
   out of English (Spanish 69.2, French 71.7, German 71.7 in November; different grading calls).
3. **Into English splits on recognition.** Languages Whisper hears score 75-84 (Italian 84.2, Ukrainian 81.7,
   Arabic 80.8, Korean 80.0, Turkish 79.2, Mandarin 75.0), Indonesian 70.0; Vietnamese (55.8) and Filipino
   (62.5) are low despite few character errors (misheard names, numbers and terms). The languages Omnilingual
   300M hears are the weakest: Swahili 36.7, Urdu 38.3, Hindi 47.5, Bengali 60.0, Persian 65.0, with the most
   critical errors (20-30 in 40 for Swahili and Urdu).
4. **Gemma 4 beats Hy-MT2 in all 14 directions of the seven Hy-MT2-only languages:** +3.6 out of English (+0.8
   to +6.7) and +5.7 into English (+1.7 to +10.0), with fewer or equal critical errors in 13 of 14. Out of
   English into Bengali, Urdu and Hindi it is also 1.5-2.3 s sooner to the last audio, even with two rooms at
   once. Single-direction gaps under ~5 points are within one round's noise; the direction of the result is
   consistent across all 14.
5. **Persian recognition invents text.** Omnilingual 300M appended phrases that were never said to some Persian
   utterances, mostly Arabic ("المراجعات والتقارير", "reviews and reports"; "نهاية الدرس", "end of lesson") and once
   Hebrew-looking letters; Gemma translated them, and once answered with a note ("The provided text is not in
   Persian ... Please provide the correct Persian text") in place of a translation (set a, sentences 0, 5, 7, 17).

## Setup

- **Pod:** RunPod secure cloud, one RTX PRO 6000 Blackwell Server Edition 96 GB (host CUDA 13.2, 32 vCPUs),
  template `dftcc24b6q` with the image `ghcr.io/lithsec/translation-open-stack:2026.11.04`, start command
  `/start.sh`; `v1b4iqda8t3tjs`, 11:09-16:02 UTC, ~$12.20. The repository's tracked files plus this folder were
  copied to `/workspace/tos`.
- **`setup.sh`:** Gemma 4 via `scripts/start-llmmt.sh` (`LLMMT=gemma`, profile `cuda-80gb`: vLLM share 0.38),
  Node 22, the 15 languages' voices, `prepare-mt.sh` with `MADLAD=3b` (MADLAD is only Swahili's fallback),
  `prepare-voices.sh`, the clips, the two configs. GPU memory in use during the runs: about 63 GB of 97.9.
- **Routes** (`configs/check-A.txt`, `check-B.txt`): A is `languages.toml` as it is. B is the same with it, ko,
  id, tr, bn, ur, hi set to `translator = ["llmmt", "hymt"]`, Gemma's `llmmt` line and
  `translator_to_en = ["llmmt", "hymt"]` (`make_config.py`). Recognition: Whisper large-v3, except Omnilingual
  300M for fa, sw, bn, ur, hi.
- **Clips** (`build_clips.py`, seed 2028): 40 FLEURS test sentences (CC BY 4.0) shared by English and all 14
  languages, sets a and b of 20, male and female readers alternating, regular pauses (1.0-1.95 s). Only 21
  shared ids were unused by earlier rounds; those come first, the other 19 are ids earlier rounds used in other
  languages (none of these 14 was run live before). Ids in `results/ids.json`, texts in `results/clips_*/`.
- **Runs** (`run.sh`, `live.sh`): one stack start for A (15 languages), each direction alone, set a then set b;
  one for B, sets a and b at once (`PAR=1`). Client `../2026-10-de-ru-ro/e2e_client.mjs` (`?context=1`).
  Analysis `analyze.sh` (`../2026-10-unseen/analyze_e2e.py` with this round's directions). Grading `round.py`
  and `grade.py` (`../2026-10-de-ru-ro/grade.py`'s rubric and prompt); one call (vi→en set b) was retried.
  B's `live.sh` waited on the stack as well as its two loops and hung after the last run; the stack was
  stopped by hand at 15:59 and the round went on to the analysis (no run affected; fixed in `live.sh`).

## Limits

- One 20-sentence read clip per language and set, FLEURS read speech, one grading call per direction and set;
  differences under ~5 points are noise. Graded against the FLEURS text, not a transcript of what was said
  (the de-ru-ro method), so a reader's own slips count against the system.
- Not comparable with earlier rounds' numbers (other grading calls, other clips); the earlier directions are
  context only.
- B's latencies are under two rooms at once (¹). Its quality is not affected by load.
- Recognition error for Mandarin is in characters; Whisper's punctuation and number style count as errors.

## Files

- `README.md`, `results.json` (`round.py table`): per direction and system, quality, critical errors,
  recognition error, latency, drops.
- `build_clips.py`, `make_config.py`, `setup.sh`, `live.sh`, `run.sh`, `analyze.sh`: the pod side.
- `round.py`, `grade.py`: grading jobs, grading, table (local).
- `configs/`: A and B and their `stack_config.py check` output.
- `results/`: clip texts and metadata (no audio), `e2e_{A,B}_{a,b}/out/` (runs, latency, sentences), stack, vLLM
  and setup logs, grading jobs and grades.
