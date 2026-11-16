# Soniox speech-to-speech against Talk's automatic engine, November 2026

For Lithos Talk (a two-way conversation translator): should its automatic engine move a direction to Soniox
speech-to-speech (Soniox hears, translates inside its stream and speaks)? Soniox's translation **text** and the
route the automatic engine runs today, graded blind side by side on the same clips in one grading round, for 14
languages both ways with English (28 directions). The rows feed Talk's server
(`soniox-talk-rows.json`): it picks Soniox for a direction only where Soniox scores at least 70 and no more than 3
points behind the baseline.

## Results

Quality: share of the possible 3 per sentence, blind (`gemini-flash-latest`), against the FLEURS English
meaning, mean of sets a and b (20 sentences each, n = 40 per direction). Critical: sentences flagged with a
critical error, of 40 (first read). Recognition CER: characters wrong against the FLEURS text of the whole clip,
mean of sets a and b; Soniox's is the original-language transcript of its translation streams (mean over the 14
streams for English), Azure's is the baseline's recogniser. "Server picks Soniox": Soniox ≥ 70 and Soniox ≥
baseline − 3 (lithos-server `src/routes/sonioxtalk.ts`).

| Direction | Baseline route (recogniser, translator) | Soniox (a / b) | Baseline (a / b) | Soniox − baseline | Critical, Soniox / baseline | Recognition CER, Soniox / Azure | Server picks Soniox |
|---|---|---|---|---|---|---|---|
| en→es | hybrid-gemma (Azure, Gemma 4) | **63.3** (63.3 / 63.3) | **76.7** (81.7 / 71.7) | -13.4 | 5 / 5 | 5.8% / 6.9% | no |
| es→en | mai-gemma (Azure for MAI, Gemma 4) | **75.0** (76.7 / 73.3) | **92.5** (96.7 / 88.3) | -17.5 | 2 / 3 | 0.9% / 1.4% | no |
| en→pt | hybrid-gemma (Azure, Gemma 4) | **69.2** (68.3 / 70.0) | **77.5** (85.0 / 70.0) | -8.3 | 4 / 4 | 5.8% / 6.9% | no |
| pt→en | hybrid-gemma (Azure, gpt-6-sol) | **70.8** (70.0 / 71.7) | **91.7** (88.3 / 95.0) | -20.9 | 6 / 4 | 1.3% / 1.6% | no |
| en→fr | hybrid-gemma (Azure, Gemma 4) | **58.3** (68.3 / 48.3) | **75.0** (85.0 / 65.0) | -16.7 | 5 / 5 | 5.8% / 6.9% | no |
| fr→en | mai-gemma (Azure for MAI, Gemma 4) | **77.9** (80.0 / 75.0; read 2: 80.0 / 76.7) | **78.3** (73.3 / 80.0; read 2: 73.3 / 86.7) | -0.4 | 3 / 5 | 1.9% / 4.0% | **yes** |
| en→de | hybrid-gemma (Azure, Gemma 4) | **50.9** (51.7 / 50.0) | **74.2** (80.0 / 68.3) | -23.3 | 6 / 5 | 5.8% / 6.9% | no |
| de→en | mai-gemma (Azure for MAI, gpt-6-sol) | **69.2** (66.7 / 71.7) | **85.8** (86.7 / 85.0) | -16.6 | 3 / 3 | 1.2% / 2.2% | no |
| en→zh | hybrid-gemma (Azure, Gemma 4) | **57.5** (58.3 / 56.7) | **79.2** (85.0 / 73.3) | -21.7 | 10 / 6 | 5.8% / 6.9% | no |
| zh→en | mai-gemma (Azure for MAI, Gemma 4) | **66.7** (76.7 / 56.7) | **90.0** (88.3 / 91.7) | -23.3 | 12 / 5 | 2.4% / 3.0% | no |
| en→vi | hybrid-gemma (Azure, Gemma 4) | **61.6** (60.0 / 63.3) | **78.3** (83.3 / 73.3) | -16.7 | 9 / 4 | 5.8% / 6.9% | no |
| vi→en | mai-gemma (Azure for MAI, Gemma 4) | **60.0** (56.7 / 63.3) | **80.0** (80.0 / 80.0) | -20.0 | 5 / 4 | 3.4% / 4.6% | no |
| en→ar | hybrid-gemma (Azure, gpt-6-sol) | **66.7** (70.0 / 63.3) | **82.5** (90.0 / 75.0) | -15.8 | 7 / 3 | 5.8% / 6.9% | no |
| ar→en | mai-gemma (Azure for MAI, Gemma 4) | **70.8** (65.0 / 76.7) | **90.8** (85.0 / 96.7) | -20.0 | 10 / 2 | 0.9% / 1.7% | no |
| en→fa | hybrid-gemma (Azure, gpt-6-sol) | **54.1** (58.3 / 50.0) | **81.7** (90.0 / 73.3) | -27.6 | 7 / 3 | 5.8% / 6.9% | no |
| fa→en | mai-gemma (Azure for MAI, Gemma 4) | **65.8** (68.3 / 63.3) | **73.3** (71.7 / 75.0) | -7.5 | 5 / 7 | 2.4% / 4.4% | no |
| en→tl | hybrid-gemma (Azure, Gemma 4) | **71.2** (70.0 / 70.0; read 2: 71.7 / 73.3) | **70.8** (78.3 / 61.7; read 2: 80.0 / 63.3) | +0.4 | 6 / 6 | 5.8% / 6.9% | **yes** |
| tl→en | mai-gemma (Azure for MAI, Gemma 4) | **64.2** (61.7 / 66.7) | **84.2** (83.3 / 85.0) | -20.0 | 2 / 1 | 2.7% / 4.2% | no |
| en→uk | hybrid-gemma (Azure, gpt-6-sol) | **66.7** (61.7 / 71.7) | **81.7** (90.0 / 73.3) | -15.0 | 7 / 4 | 5.8% / 6.9% | no |
| uk→en | mai-gemma (Azure for MAI, gpt-6-sol) | **75.0** (70.0 / 80.0) | **88.3** (80.0 / 96.7) | -13.3 | 3 / 3 | 2.7% / 2.8% | no |
| en→ko | hybrid-gemma (Azure, Gemma 4) | **65.0** (63.3 / 66.7) | **76.7** (80.0 / 73.3) | -11.7 | 4 / 4 | 5.8% / 6.9% | no |
| ko→en | hybrid-gemma (Azure, gpt-6-sol) | **66.7** (63.3 / 70.0) | **90.0** (81.7 / 98.3) | -23.3 | 10 / 2 | 4.0% / 6.1% | no |
| en→ru | hybrid-gemma (Azure, Gemma 4) | **63.4** (61.7 / 65.0) | **77.5** (81.7 / 73.3) | -14.1 | 6 / 5 | 5.8% / 6.9% | no |
| ru→en | hybrid-gemma (Azure, gpt-6-sol) | **70.8** (66.7 / 75.0) | **95.8** (96.7 / 95.0) | -25.0 | 4 / 1 | 1.8% / 2.3% | no |
| en→hi | hybrid-gemma (Azure, Gemma 4) | **64.2** (66.7 / 61.7) | **75.8** (81.7 / 70.0) | -11.6 | 3 / 2 | 5.8% / 6.9% | no |
| hi→en | hybrid-gemma (Azure, gpt-6-sol) | **66.7** (63.3 / 70.0) | **85.0** (83.3 / 86.7) | -18.3 | 10 / 3 | 3.6% / 4.3% | no |
| en→it | hybrid-gemma (Azure, Gemma 4) | **63.4** (66.7 / 60.0) | **73.3** (78.3 / 68.3) | -9.9 | 6 / 5 | 5.8% / 6.9% | no |
| it→en | hybrid-gemma (Azure, gpt-6-sol) | **75.8** (76.7 / 75.0) | **100.0** (100.0 / 100.0) | -24.2 | 3 / 0 | 1.4% / 1.1% | no |

fr→en and en→tl were within 3 points on the first read, so both were graded a second time (same jobs, new ids,
so the letters were shuffled again); their quality is the mean of the two reads, and both reads alone give the
same verdict (fr→en: Soniox 77.5 vs 76.7, then 78.3 vs 80.0; en→tl: 70.0 vs 70.0, then 72.5 vs 71.7).

## Findings

1. **The rule picks Soniox in 2 of 28 directions: fr→en (77.9 vs 78.3) and en→tl (71.2 vs 70.8)**, both level
   with the baseline within one round's noise. Everywhere else Soniox is 7.5-27.6 points behind (median −17.1),
   and it is below 70 in 20 of the 28 directions.
2. **Soniox hears better but translates worse.** Its own transcript has fewer character errors than Azure's in
   14 of the 15 languages (not Italian; Ukrainian about level), yet its translations score lower: the grader's notes
   on the low ones are literal or garbled renderings (en→de "Drachenfliegen" for dragonflies, "Undichtigkeit"
   for a leak; it→en "cigarettes" for joints), word order and grammar broken across chunks, and invented or
   dropped details. Soniox translates in chunks while the sentence is still being spoken (translation tokens
   arrive mid-sentence), against the baseline's whole-sentence call to an LLM.
3. **Into English the gap is largest where sol translates** (pt, de, uk, ko, ru, hi, it into English: −13 to −25;
   sol at 85-100), and also large behind Gemma (es, zh, vi, ar, tl into English: −17 to −23). Out of English
   Soniox scores 50.9-71.2 against 70.8-82.5.
4. **Soniox's text comes sooner, as far as this measures.** Last translated text after the sentence's speech
   ends, p50: Soniox 0.1-0.4 s in 23 directions, the baseline 0.7-2.3 s (last Azure final plus the translation
   call; neither includes a voice). Indicative only: the sentence's end is its marked end in the clip, and in
   some recordings (vi, fa, tl, ko, hi into English) speech stops well before it, so some p50s are negative
   (the baseline's too, fa and tl); and Soniox's figure is the last chunk credited to the sentence, so a late
   tail credited to the next sentence makes it read early. Per direction in `results.json` `latency_ms`.

## Caveats

- **MAI not run.** Where the route's recogniser is MAI (`mai-gemma`: es, fr, de, zh, vi, ar, fa, tl, uk into
  English), Azure standard speech-to-text stood in for it. The server's resolver treats Azure and MAI
  transcripts as the same measurement (`resolver.ts` `measures()`), which is why the stand-in is used; a MAI
  run could score differently.
- **The baseline is sentence-at-a-time**, on Azure's finals regrouped into the read sentences, with the
  translator shootout's prompt and no conversation context. Production's routes use their own prompt
  (`standard.ts`) with context, and may cut phrases; this measures the translator behind the same recogniser,
  not the live route end to end. Soniox ran as the app runs it, live at real time.
- **Read speech with regular pauses** (FLEURS, 1.0-1.95 s between sentences), not conversation. Some FLEURS
  English readers stop early or misread (set a sentence 1 ends "allowing the most ambitious and successful."):
  both systems got the same audio, but an LLM that completes the sentence scores better against the written
  reference than Soniox translating what was said.
- **Sentence assignment for Soniox** (see Setup) is by audio offsets; a translation block over two sentences is
  cut by text alignment, which can misplace a few words at a boundary. No Soniox sentence came out empty.
- **One grader, one round** (`gemini-flash-latest`; a second read only for the two close directions). Earlier
  rounds saw grades move 5-10 points between rounds; compare within this table only. Single-direction gaps under
  ~5 points are within noise; the 2 picks are level results, not wins.
- **Soniox's voice was not run or graded**; only its translation text.
- No language was dropped: all 14 were in FLEURS and served by Soniox, Azure, Gemma and sol.

## Setup

- **Clips** (`build_clips.py`, seed 2029): 40 FLEURS test sentences (CC BY 4.0) shared by English and all 14
  languages, none in an earlier round's `ids.json` or the real-voices sentences (`results/ids.json`), split into set a and set b of 20 each. Male and
  female readers alternate, so each set has several FLEURS speakers per language. Regular pauses of 1.0-1.95 s,
  16 kHz mono, about 3 minutes a clip. Texts and offsets in `results/clips_a/`, `results/clips_b/` (audio not
  committed; `build_clips.py` rebuilds it).
- **Soniox** (`soniox_s2s.py`): one real-time stream per direction and set, `stt-rt-v6` with one-way translation
  into the listener's language and the start message the Talk app sends (language identification and speaker
  labels on, endpoint detection, `max_endpoint_delay_ms` 1500, no language hints), the clip streamed at real time
  in 100 ms chunks. Final translation tokens are assigned to sentences by the audio offsets of the original tokens
  they follow; a translation block covering several sentences is cut where they end
  (`../2026-10-translator-shootout/shootout.py` `split_like`, against the FLEURS text in the target language).
  Three streams at a time. Soniox's voice was not called: only its text is graded.
- **Baseline** (what the automatic engine runs today, from the server's planner):
  - recognition (`stt_azure.py`): Azure standard speech-to-text (Talk's locales: es-MX, pt-BR, fr-FR, de-DE,
    zh-CN, vi-VN, ar-SA, fa-IR, fil-PH, uk-UA, ko-KR, ru-RU, hi-IN, it-IT, en-US; eastus), fed at real time in
    100 ms chunks, finals regrouped into the read sentences by audio offset (`shootout.py` `group`).
    **Where the route's recogniser is MAI (`mai-gemma`), Azure standard speech-to-text stands in for it**: the
    server's resolver treats Azure and MAI transcripts as the same measurement (`resolver.ts` `measures()`), and
    this round did not run MAI.
  - translation (`mt.py`), one call per sentence: Gemma 4 31B on Amazon Bedrock (`google.gemma-4-31b`,
    bedrock-mantle us-east-2, temperature 0), or gpt-6-sol on Azure AI Foundry (`gpt-6-sol-us`,
    `reasoning_effort` low), as the table says. Both get the translator shootout's prompt (as
    `../2026-10-es-pt-live-compare/mt.py`). At most 3 calls at a time per host.
- **Grading** (`round.py`, `grade.py`: `../2026-10-es-pt-live-compare/grade.py`'s rubric and prompt):
  `gemini-flash-latest`, temperature 0, blind (the two systems shuffled under letters), one call per direction and
  set with both systems side by side, 0-3 per sentence against the FLEURS English text as the reference meaning,
  plus a critical-error flag (number, negation, who-did-what...). Quality is the share of the possible score,
  mean of sets a and b (n = 40 per direction). One round.

## Reproduce

```
python3 -I build_clips.py WORK ../2026-10-real-voices ..
SONIOX_API_KEY=... python3 -I soniox_s2s.py WORK WORK/out
AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I stt_azure.py WORK WORK/out
AWS_PROFILE=... FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=gpt-6-sol-us python3 -I mt.py WORK/out
python3 -I round.py jobs WORK WORK/out
GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py WORK/out/jobs.json WORK/out/grades.json
python3 -I round.py jobs2 WORK WORK/out fr-en en-tl
GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py WORK/out/jobs_r2.json WORK/out/grades_r2.json
python3 -I round.py table WORK WORK/out
```

Python 3 with `azure-cognitiveservices-speech`, `websockets`, `boto3`, `numpy`; `sox` for the clips.

`results/`: `soniox.json` (per stream: its transcript, its translation per sentence, translation characters),
`stt_azure.json` (Azure finals and per-sentence transcripts), `mt.json` (the baseline translations, wall times,
tokens), `jobs.json` / `grades.json` and `jobs_r2.json` / `grades_r2.json` (what the grader saw and said),
`clips_*` (texts, offsets, FLEURS files and speakers' genders), `ids.json`. `results.json` has the table's numbers;
`soniox-talk-rows.json` is the rows in the shape the server reads (lithos-server `src/routes/soniox-talk.json`).

Usage, from the runs: Soniox 56 streams, 2.9 hours of stream time, 119,122 translation characters; Azure
speech-to-text 1.8 hours of audio; Gemma 4 on Bedrock 720 calls (67,301 tokens in, 19,122 out); gpt-6-sol 400
calls (28,102 in, 21,662 out); the grader 60 calls (140,462 tokens in, 62,727 out, 173,392 thinking).
