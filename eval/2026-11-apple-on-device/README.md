# Apple on-device (SpeechTranscriber + Translation) against Talk's automatic cloud route, November 2026

For Lithos Talk (a two-way conversation translator): where Apple can hear and translate a language on the device,
is it good enough for the automatic engine to stay on the device instead of going to the cloud? Apple's on-device
path as the Talk app runs it (SpeechTranscriber hearing, Apple Translation one final at a time), and the same
transcript cut into pieces as Talk's cloud routes cut it (FastPhrases phrase or boundary cutter), against the route
the automatic engine runs today, graded blind side by side in one grading round on the clips of
`../2026-11-talk-soniox` (20 directions, n = 40 per direction). Round `apple-on-device-2026-11`.

## Results

Quality: share of the possible 3 per sentence, blind (`gemini-flash-latest`), against the FLEURS English meaning,
mean of sets a and b (20 sentences each, n = 40). Critical: sentences flagged with a critical error, of 40.
**Apple whole**: every Apple final translated whole (the app's on-device path). **Apple pieces**: the same
transcript cut as Talk's cloud routes cut it with fast mode on (the cut column: FastPhrases' phrase cutter with
its min-max words, the boundary cutter, or whole sentences where FastPhrases cuts nothing, in which case pieces is
the same as whole and was not graded separately). **Cloud route**: what the automatic engine runs today for the
direction (lithos-server `src/routes/plan.ts` `autoPlan`, mode talk, Standard, Plus, the Soniox switch on, run
2026-11-25), its translations taken from the Talk eval's rounds on the same clips. Numbers: `results.json`
`directions`.

| Direction | Cloud route (hearing + translator) | Apple whole (a / b) | Apple pieces (a / b) | Cloud route (a / b) | Apple whole − cloud | Pieces − whole | Critical, whole / pieces / cloud | Apple cut |
|---|---|---|---|---|---|---|---|---|
| en→es | Soniox + Gemma 4 | **55.0** (55.0 / 55.0) | **37.5** (40.0 / 35.0) | **87.5** (93.3 / 81.7) | -32.5 | -17.5 | 9 / 9 / 3 | phrases 4-8 (121 cut pieces) |
| en→pt | Azure + Gemma 4 | **53.4** (55.0 / 51.7) | **34.2** (31.7 / 36.7) | **77.5** (88.3 / 66.7) | -24.1 | -19.2 | 7 / 9 / 6 | phrases 4-8 (121) |
| en→fr | Soniox + Gemma 4 | **54.1** (53.3 / 55.0) | **32.5** (33.3 / 31.7) | **85.8** (90.0 / 81.7) | -31.7 | -21.6 | 7 / 8 / 4 | phrases 3-7 (129) |
| en→de | Azure + Gemma 4 | **53.3** (58.3 / 48.3) | **32.5** (35.0 / 30.0) | **78.3** (86.7 / 70.0) | -25.0 | -20.8 | 10 / 13 / 6 | phrases 3-7 (129) |
| en→zh | Azure + Gemma 4 | **55.0** (53.3 / 56.7) | **45.8** (43.3 / 48.3) | **80.0** (88.3 / 71.7) | -25.0 | -9.2 | 8 / 8 / 4 | boundary (42) |
| en→vi | Soniox + Gemma 4 | **52.5** (51.7 / 53.3) | **43.4** (40.0 / 46.7) | **86.7** (91.7 / 81.7) | -34.2 | -9.1 | 5 / 7 / 2 | boundary (42) |
| en→ar | Soniox + gpt-6-sol | **52.5** (50.0 / 55.0) | **35.0** (30.0 / 40.0) | **90.0** (96.7 / 83.3) | -37.5 | -17.5 | 5 / 5 / 1 | phrases 4-8 (121) |
| en→uk | Soniox + gpt-6-sol | **40.0** (36.7 / 43.3) | **32.5** (28.3 / 36.7) | **85.8** (91.7 / 80.0) | -45.8 | -7.5 | 5 / 8 / 3 | boundary (42) |
| en→ko | Azure + Gemma 4 | **52.5** (48.3 / 56.7) | **40.0** (35.0 / 45.0) | **80.8** (81.7 / 80.0) | -28.3 | -12.5 | 10 / 10 / 4 | boundary (42) |
| en→ru | Azure + Gemma 4 | **49.2** (51.7 / 46.7) | **40.8** (43.3 / 38.3) | **79.2** (86.7 / 71.7) | -30.0 | -8.4 | 6 / 7 / 4 | boundary (42) |
| en→hi | Soniox + Gemma 4 | **53.3** (53.3 / 53.3) | **41.6** (40.0 / 43.3) | **85.8** (91.7 / 80.0) | -32.5 | -11.7 | 3 / 5 / 1 | boundary (42) |
| en→it | Azure + Gemma 4 | **51.6** (53.3 / 50.0) | **40.0** (41.7 / 38.3) | **72.5** (76.7 / 68.3) | -20.9 | -11.6 | 6 / 7 / 6 | boundary (42) |
| es→en | Soniox + Gemma 4 | **65.8** (70.0 / 61.7) | **49.1** (53.3 / 45.0) | **96.7** (98.3 / 95.0) | -30.9 | -16.7 | 3 / 3 / 1 | boundary (60) |
| pt→en | MAI + gpt-6-sol | **61.6** (60.0 / 63.3) | **51.7** (46.7 / 56.7) | **95.0** (96.7 / 93.3) | -33.4 | -9.9 | 3 / 4 / 2 | boundary (73) |
| fr→en | Soniox + Gemma 4 | **63.4** (55.0 / 71.7) | **44.1** (43.3 / 45.0) | **90.8** (86.7 / 95.0) | -27.4 | -19.3 | 6 / 8 / 2 | boundary (58) |
| de→en | Azure + gpt-6-sol | **59.1** (63.3 / 55.0) | as whole | **85.8** (86.7 / 85.0) | -26.7 | 0 | 11 / 11 / 3 | whole (0) |
| zh→en | MAI + Gemma 4 | **60.8** (68.3 / 53.3) | **57.5** (66.7 / 48.3) | **96.7** (100.0 / 93.3) | -35.9 | -3.3 | 13 / 14 / 1 | boundary (2) |
| ko→en | MAI + gpt-6-sol | **65.0** (70.0 / 60.0) | as whole | **98.3** (100.0 / 96.7) | -33.3 | 0 | 9 / 9 / 0 | whole (0) |
| hi→en | Soniox + gpt-6-sol | **37.5** (43.3 / 31.7) | as whole | **88.3** (86.7 / 90.0) | -50.8 | 0 | 14 / 14 / 4 | whole (0) |
| it→en | Azure + gpt-6-sol | **65.8** (66.7 / 65.0) | **46.7** (46.7 / 46.7) | **100.0** (100.0 / 100.0) | -34.2 | -19.1 | 4 / 8 / 0 | boundary (83) |

No second read was graded: in every direction the top two (the cloud route, then Apple whole) are 20.9 or more
points apart, far outside the 2-3 points a second read moves a score.

## Findings

1. **Apple on-device is far behind the cloud route in all 20 directions**: 20.9 to 50.8 points behind (median
   −32.1), Apple whole 37.5-65.8 against the cloud's 72.5-100.0, with more critical errors in 19 of 20 (level in
   en→it, 6 / 6). Out of English Apple scores 40.0-55.0, into English 37.5-65.8. Apple is below 70 in every
   direction; the cloud route is at or above 72.5 in every one.
2. **Whole sentences beat pieces on the device.** Where FastPhrases cuts (17 directions), Apple pieces score 3.3 to
   21.6 points below Apple whole (median −12.5), never above it. Phrase cutting (en→es, pt, fr, de, ar: 121-129
   pieces over 40 sentences) costs the most, 17.5-21.6; the boundary cutter out of English (42 pieces) 7.5-12.5;
   into English 9.9-19.3, and 3.3 in zh→en where only 2 pieces were cut. Apple Translation has no context, so
   each piece is translated alone.
3. **Apple's errors are hearing and translation both.** Its transcripts have more character errors than the
   recogniser the cloud route uses in all 8 languages where they compare (next table), and it drops words at sentence
   starts and ends in English ("the less active the star." without "with respect to magnetic reversals"; "you,
   you, you, you" for "Everyone participates in society"). On the translation side the grader's notes include
   literal renderings that are not hearing errors (en→es "caja de primavera" for the Springboks, "mariquitas"
   for mayflies). This round does not separate the two: Apple Translation on the correct text was not run.
4. **Hindi**: Apple's hi-IN recogniser writes Hindi in Latin letters ("yeh Koch pakshiyon mein Pankhon ke vikas
   ki poori jankari..."), not Devanagari, so its character error against the FLEURS text (169%) means nothing.
   Apple Translation then translates the romanised Hindi; hi→en scores 37.5 with 14 critical errors of 40, the
   lowest of the 20 directions.
5. **Apple's text is not sooner** (delay table below). Its last words come 1.5-1.95 s after the speech's marked
   end out of English (p50) and 2.1-2.9 s into English, against 0.7-2.3 s for the cloud reference (Azure
   standard + the same translator, from the Talk eval). Pieces bring the first words of a sentence sooner only
   where phrases are cut (out of English: 3.3-3.9 s after the sentence starts, against 7.0-7.4 s whole).

## Translation alone (correct text)

A second grading run with Apple Translation given the reference sentences instead of what Apple heard
(harness/TextOnly.swift, text_only.py; results/text-only/). One blind read per direction and set, the three systems
side by side, so its heard and cloud scores differ a little from the table above (a different read of the same outputs).

| Direction | Apple Translation, correct text | Apple heard + translated | Cloud route |
|---|---|---|---|
| en→es | 83.3 | 52.5 | 86.7 |
| en→pt | 87.5 | 55.8 | 75.8 |
| en→fr | 83.3 | 53.3 | 85.8 |
| en→de | 79.2 | 51.7 | 75.8 |
| en→zh | 84.2 | 52.5 | 76.7 |
| en→vi | 81.7 | 52.5 | 88.3 |
| en→ar | 76.7 | 50.0 | 89.2 |
| en→uk | 62.5 | 40.8 | 85.8 |
| en→ko | 84.2 | 46.7 | 75.8 |
| en→ru | 68.3 | 45.8 | 80.0 |
| en→hi | 85.8 | 53.3 | 83.3 |
| en→it | 85.0 | 52.5 | 68.3 |
| es→en | 95.0 | 66.7 | 95.8 |
| pt→en | 95.0 | 65.8 | 95.0 |
| fr→en | 95.0 | 60.0 | 91.7 |
| de→en | 93.3 | 58.3 | 86.7 |
| zh→en | 92.5 | 59.2 | 96.7 |
| ko→en | 77.5 | 59.2 | 98.3 |
| hi→en | 80.8 | 34.2 | 85.0 |
| it→en | 87.5 | 66.7 | 99.2 |

- Given correct text, Apple Translation scores within 10 points of the cloud route in 15 of 20 directions, and above
  it in 8 (en→pt, en→de, en→zh, en→ko, en→hi, en→it, fr→en, de→en; pt→en ties). The cloud row is heard
  by its own recogniser, so this compares Apple's translator on perfect text with the full cloud pipeline.
- Most of the on-device loss is hearing: 18 to 47 points between Apple on correct text and Apple on what it heard.
  These read sentences are dense in names and rare words ("El día de ayer, Martelly juró…" heard as "Peshi juró…",
  "efemerópteros" as "enfermermerópteros"), which the grader counts as critical errors. Everyday speech with fewer
  names may hear better; not measured here.
- Weakest translation on correct text: en→uk 62.5, en→ru 68.3, ko→en 77.5.

## Hearing

Characters wrong (CER) against the FLEURS text of the whole clip, mean of sets a and b, and words wrong (WER,
after the same normalisation; not for Chinese). Apple: its finals at real time with the app's settings, pinned to
the locale in the table. The cloud recognisers' transcripts are the Talk eval's on the same clips (Soniox: the
original-language transcript of its translation streams, mean over the streams for English). **Bold**: the
recogniser the cloud route uses for that language's speakers. Numbers: `results.json` `recognition`.

| Language (Apple locale) | Apple CER (a / b) | Soniox | MAI | Azure | Apple WER | Soniox / MAI / Azure WER |
|---|---|---|---|---|---|---|
| en (en-US) | 9.9% (6.7 / 13.1) | 5.8% | 4.1% | 6.9% | 13.4% | 7.8 / 6.2 / 9.8% |
| es (es-MX) | 2.5% (2.1 / 2.8) | **0.9%** | 0.5% | 1.4% | 4.4% | 1.7 / 0.9 / 2.6% |
| pt (pt-BR) | 4.6% (4.7 / 4.6) | 1.3% | **0.8%** | 1.6% | 7.5% | 3.5 / 2.4 / 4.0% |
| fr (fr-FR) | 4.3% (4.1 / 4.6) | **1.9%** | 1.1% | 4.0% | 9.6% | 3.7 / 2.9 / 8.4% |
| de (de-DE) | 4.5% (3.6 / 5.5) | 1.2% | 0.9% | **2.2%** | 10.9% | 4.2 / 3.4 / 6.2% |
| zh (zh-CN) | 5.9% (4.1 / 7.8) | 2.4% | **1.1%** | 3.0% | - | - |
| ko (ko-KR) | 5.3% (3.6 / 6.9) | 4.0% | **3.0%** | 6.1% | 16.9% | 12.2 / 9.8 / 17.1% |
| hi (hi-IN) | not comparable (Latin letters) | **3.6%** | 2.9% | 4.3% | - | 5.2 / 4.2 / 6.7% |
| it (it-IT) | 2.3% (1.8 / 2.8) | 1.4% | 0.3% | **1.1%** | 4.2% | 2.3 / 0.6 / 2.2% |

The cloud route hears English with Soniox (en→es, fr, vi, ar, uk, hi) or Azure (en→pt, de, zh, ko, ru, it).

1. **Apple has the most character errors of the four in 7 of the 8 comparable languages**, 1.4 to 5.8 times the
   cloud route's recogniser (en 9.9% against Soniox's 5.8% and Azure's 6.9%; es 2.5% against Soniox's 0.9%; pt
   4.6% against MAI's 0.8%; zh 5.9% against MAI's 1.1%). In Korean it is ahead of Azure (5.3% against 6.1%) and behind MAI (3.0%), which the route uses.
2. **English is Apple's weakest comparable language**, 9.9% (set b 13.1%), against 5.8% (Soniox) and 6.9% (Azure)
   for the route. Its set-b misses include whole stretches at a sentence's start or end (", you, sparsely
   populated..." for "Large areas further north are quite sparsely populated"). Some of the count is spelling
   numbers out ("70 kilometers" for "70 km"), which every recogniser was scored the same way on.
3. **The app's bare language code picks a different English.** The app asks for
   `SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: code))` with its bare code; on this Mac
   bare "en" resolved to en-GB. On set a, en-GB had 8.1% CER (13.4% WER) against en-US's 6.7% (12.1%)
   (`results/hear_a_en_bare.json`). This round pinned every language to the region the clips were read in and
   Azure was pinned to (table), so the app as shipped may hear English slightly worse than measured here.
4. **Most non-English finals come from the app's own finalize timer.** In es, pt, fr, de, zh, ko, hi and it, the
   by-hand finalize (the text unchanged for 0.8 s after . ? ! or 1.4 s otherwise) fired 35-43 times per language
   over both sets, for 39-54 finals; in English 5 times for 49 finals. Apple left the end punctuation off 5-22 of
   each of those languages' finals (Hindi 30 of 39), and those waited the longer 1.4 s; 48 of the 49 English
   finals ended in punctuation. This is consistent with the later text into English
   (next section), but the delay was not broken down by cause.

## Delays

Seconds, over the 40 sentences of both sets (39 where a sentence got no translation: zh→en pieces, hi→en pieces).
**Last words**: when the translation of the sentence's last words was available, after the sentence's marked
speech end in the clip. **First words**: when its first words' translation was available, after the sentence's
marked start. Apple's times include the hearing at real time, the app's finalize timer, Apple Translation one piece
at a time in order (`done = max(piece ready, previous piece done) + its translate time`, measured one call at a
time after a warm-up call) and no voice. **Cloud reference**: the Talk eval's baseline on the same clips and
translator (lithos `../2026-11-talk-soniox` `results.json` `latency_ms`): the sentence's last Azure standard final
arrives, plus the translation call's wall time. It is the cloud route's own recogniser only where the route hears
with Azure (en→pt, de, zh, ko, ru, it, de→en, it→en); Soniox's and MAI's finals in that pipeline were not timed.
Numbers: `results.json` `delay_s`, `pieces`.

| Direction | Apple whole: last words p50 / p90 | Apple pieces: last words p50 / p90 | First words p50, whole / pieces | Apple translate call p50, whole / pieces | Cloud reference: last words p50 / p90 (translator) |
|---|---|---|---|---|---|
| en→es | 1.58 / 2.68 | 1.23 / 2.28 | 7.1 / 3.7 | 0.59 / 0.39 | 1.26 / 2.06 (Gemma 4) |
| en→pt | 1.51 / 2.66 | 1.28 / 2.34 | 7.0 / 3.8 | 0.63 / 0.40 | 1.25 / 2.10 (Gemma 4) |
| en→fr | 1.59 / 2.78 | 1.22 / 2.33 | 7.1 / 3.3 | 0.66 / 0.39 | 1.25 / 2.21 (Gemma 4) |
| en→de | 1.65 / 2.76 | 1.27 / 2.32 | 7.1 / 3.3 | 0.71 / 0.43 | 1.30 / 2.21 (Gemma 4) |
| en→zh | 1.55 / 2.65 | 1.58 / 2.64 | 6.9 / 6.0 | 0.60 / 0.51 | 1.24 / 2.13 (Gemma 4) |
| en→vi | 1.66 / 2.77 | 1.66 / 2.73 | 7.0 / 6.1 | 0.74 / 0.61 | 1.31 / 2.19 (Gemma 4) |
| en→ar | 1.93 / 3.12 | 1.43 / 2.38 | 7.4 / 3.9 | 0.93 / 0.55 | 2.28 / 4.37 (gpt-6-sol) |
| en→uk | 1.95 / 3.03 | 1.82 / 2.82 | 7.4 / 6.2 | 0.91 / 0.74 | 1.99 / 3.44 (gpt-6-sol) |
| en→ko | 1.84 / 2.85 | 1.76 / 2.75 | 7.1 / 6.2 | 0.73 / 0.67 | 1.29 / 2.07 (Gemma 4) |
| en→ru | 1.65 / 2.82 | 1.66 / 2.69 | 7.1 / 6.1 | 0.75 / 0.60 | 1.26 / 2.08 (Gemma 4) |
| en→hi | 1.72 / 2.87 | 1.72 / 2.81 | 7.2 / 6.1 | 0.83 / 0.68 | 1.30 / 2.14 (Gemma 4) |
| en→it | 1.59 / 2.84 | 1.59 / 2.83 | 7.0 / 6.1 | 0.63 / 0.58 | 1.23 / 2.25 (Gemma 4) |
| es→en | 2.42 / 3.53 | 2.31 / 3.11 | 9.7 / 7.3 | 0.62 / 0.45 | 1.04 / 1.41 (Gemma 4) |
| pt→en | 2.49 / 3.18 | 2.23 / 2.91 | 10.4 / 7.3 | 0.56 / 0.40 | 1.51 / 3.16 (gpt-6-sol) |
| fr→en | 2.73 / 3.43 | 2.48 / 3.02 | 9.1 / 7.6 | 0.64 / 0.45 | 0.89 / 1.45 (Gemma 4) |
| de→en | 2.64 / 3.18 | as whole | 9.2 | 0.63 | 1.54 / 2.20 (gpt-6-sol) |
| zh→en | 2.93 / 3.54 | 2.89 / 3.33 | 9.8 / 9.2 | 0.72 / 0.71 | 0.73 / 1.28 (Gemma 4) |
| ko→en | 2.09 / 2.64 | as whole | 8.8 | 0.70 | 1.77 / 3.18 (gpt-6-sol) |
| hi→en | 2.42 / 3.39 | as whole | 11.0 | 0.73 | 1.72 / 2.61 (gpt-6-sol) |
| it→en | 2.59 / 3.05 | 2.36 / 2.85 | 9.8 / 8.2 | 0.56 / 0.39 | 1.54 / 2.42 (gpt-6-sol) |

1. **Out of English Apple whole is 0.26-0.55 s later than the cloud reference at p50** in the 10 Gemma 4
   directions, and level or 0.35 s sooner in the two gpt-6-sol ones (en→ar, en→uk), whose calls are slower.
2. **Into English Apple whole is 0.3-2.2 s later at p50** (ko→en +0.3, zh→en +2.2).
3. **Pieces bring the last words up to 0.5 s sooner** than whole: 0.23-0.50 s with phrases and 0.11-0.26 s into
   English (es, pt, fr, it), level (0.03 s later to 0.13 s sooner) with the boundary cutter out of English and in zh→en. With
   phrases the first words come 3.3-3.9 s after the sentence starts (out of English), against 7.0-7.4 s whole. Each Apple Translation call
   takes 0.39-0.93 s at p50 (shorter for pieces), at most one at a time; the warm-up call took
   0.5-1.3 s and is not counted.

## Coverage on this Mac

macOS 27.0.1 (26A434), Apple M2 Pro, 16 GB. Of the Talk eval's 15 languages, SpeechTranscriber hears en, es, pt,
fr, de, zh, ko, hi and it on this Mac (assets installed for each), and Apple Translation translates between English
and every language here except Persian and Filipino. So 20 of the 28 directions run; 8 do not:

| Direction | Not run because |
|---|---|
| vi→en | no Apple speech recognition for Vietnamese |
| ar→en | no Apple speech recognition for Arabic |
| uk→en | no Apple speech recognition for Ukrainian |
| ru→en | no Apple speech recognition for Russian |
| fa→en | no Apple speech recognition or translation for Persian |
| tl→en | no Apple speech recognition or translation for Filipino |
| en→fa | no Apple translation for Persian |
| en→tl | no Apple translation for Filipino |

Vietnamese, Arabic, Ukrainian and Russian run out of English only (Apple hears the English, Apple Translation
translates it).

## Proposed Automatic rule

Use the bar the Soniox rows use for moving a direction off the baseline (`../2026-11-talk-soniox`): **on-device
only where Apple whole scores at least 70 and no more than 3 points behind the cloud route.**

| Direction | Apple whole | Cloud route | Apple − cloud | On-device qualifies |
|---|---|---|---|---|
| en→es | 55.0 | 87.5 | -32.5 | no |
| en→pt | 53.4 | 77.5 | -24.1 | no |
| en→fr | 54.1 | 85.8 | -31.7 | no |
| en→de | 53.3 | 78.3 | -25.0 | no |
| en→zh | 55.0 | 80.0 | -25.0 | no |
| en→vi | 52.5 | 86.7 | -34.2 | no |
| en→ar | 52.5 | 90.0 | -37.5 | no |
| en→uk | 40.0 | 85.8 | -45.8 | no |
| en→ko | 52.5 | 80.8 | -28.3 | no |
| en→ru | 49.2 | 79.2 | -30.0 | no |
| en→hi | 53.3 | 85.8 | -32.5 | no |
| en→it | 51.6 | 72.5 | -20.9 | no |
| es→en | 65.8 | 96.7 | -30.9 | no |
| pt→en | 61.6 | 95.0 | -33.4 | no |
| fr→en | 63.4 | 90.8 | -27.4 | no |
| de→en | 59.1 | 85.8 | -26.7 | no |
| zh→en | 60.8 | 96.7 | -35.9 | no |
| ko→en | 65.0 | 98.3 | -33.3 | no |
| hi→en | 37.5 | 88.3 | -50.8 | no |
| it→en | 65.8 | 100.0 | -34.2 | no |

1. **Automatic goes to the cloud in all 20 directions** when it can reach the server: on-device qualifies in none
   (it fails both halves of the bar everywhere). A looser bar changes nothing: the smallest gap is 20.9 points
   (en→it) and Apple's best score is 65.8.
2. **When the device has to translate on its own** (no network, or "On-device only"), **translate whole finals,
   not pieces**: pieces scored lower in all 17 directions where they differ.
3. The 8 directions above with no Apple hearing or translation are cloud only.
4. Weakest on the device: hi→en (37.5, romanised Hindi) and en→uk (40.0). If on-device is offered there at all,
   these are the directions where it is least usable.

## Caveats

- **Read speech with regular pauses** (FLEURS, 1.0-1.95 s between sentences), not conversation. Apple's finalize
  timer and the cutters may behave differently on run-on speech.
- **One grader, one read** (`gemini-flash-latest`). Grades move a few points between rounds; the gaps here are
  20.9-50.8 points, so the verdicts do not hang on that. Compare scores within this table only: the cloud route's
  scores here are this round's grades of the Talk eval's outputs, not that eval's numbers.
- **The cloud route's outputs are the Talk eval's**: its recognisers on the same clips and the route's translator
  one sentence at a time with the translator shootout's prompt and no context (as described there), not the live
  app end to end. Apple ran as the app runs it, live at real time, on this Mac only (no iPhone was measured).
- **Sentence grouping.** Apple's finals do not line up with the read sentences (39-54 finals for 40 sentences per
  language: it split some sentences and joined others); finals and pieces were assigned to sentences by audio range, and a final over two
  sentences was cut by text alignment (`../2026-10-translator-shootout/shootout.py` `split_like`), which can move
  a few words across a boundary. The grader is told a live system can carry a neighbour's words.
- **Audio.** The clips were rebuilt from `../2026-11-talk-soniox/results/ids.json` with its `build_clips.py`.
  Every rebuilt clip's texts matched; the offsets matched except Ukrainian set a (its last sentence 220 ms
  shorter, as that eval found; Ukrainian is only a target here) and **German set a, whose sentence 16 came out
  1.22 s shorter** (164.86 s end against 166.08 s; later sentences shifted by the same amount;
  `results/de_a_rebuilt.json`). So in de→en Apple may have heard a different recording of one of the 40 sentences
  than the cloud recognisers did. The 1.22 s shift does not touch Apple's own timing (it uses the rebuilt clip's
  offsets).
- **Locales**: pinned per language (en-US, es-MX, pt-BR, fr-FR, de-DE, zh-CN, ko-KR, hi-IN, it-IT); the app's bare
  codes may resolve elsewhere (bare "en" gave en-GB here, see Hearing).
- **Delays are indicative**: measured on the clip's clock against marked sentence ends; the cloud reference is
  Azure standard's finals for every direction, not Soniox's or MAI's where the route uses them; no voice in
  either.

## Setup

- **Clips**: sets a and b of `../2026-11-talk-soniox` (40 FLEURS test sentences shared by all languages, CC BY 4.0,
  male and female readers alternating, regular pauses, 16 kHz mono, about 3 minutes a clip), rebuilt with its
  `build_clips.py` from `results/ids.json`. No audio committed.
- **Stage 1, hearing** (`harness/Hear.swift`, `applehear hear`): as the Talk app's on-device engine
  (`LocalTranslateSession`, OnDevice.swift): `SpeechTranscriber(locale: supportedLocale(equivalentTo:),
  transcriptionOptions: [], reportingOptions: [.volatileResults, .fastResults], attributeOptions: [])`, the clip's
  PCM16 fed at real time in 100 ms chunks (converted to `bestAvailableAudioFormat`), and the app's force-finalize
  rule (`analyzer.finalize(through: nil)` once the text stops changing: 0.8 s after . ? ! or 。？！, else 1.4 s).
  Every volatile and final result is logged with its arrival time and audio range (`results/hear/`). Three clips
  at a time.
- **Stage 2, translation** (`harness/Cut.swift`, `applehear cut`), one direction at a time, from the same stage-1
  log for both arms:
  - **whole**: every final with a letter or digit, translated whole (the app's `OnDevice.swift` enqueue).
  - **pieces**: the stream cut as Talk's cloud routes cut it with fast mode on (`StandardTranslateSession`, the
    server's boundary cutter on, `fastCuts = FastPhrases.latestLevel` = 4): the boundary cutter where
    `FastPhrases.cutsAtBoundaries` says so, else the phrase `Cutter` where `FastPhrases.policy` says phrases,
    else whole sentences. Volatile results are the partials, finals the sentences (Apple has no forced cut), and
    the app streaming hub's mic gate (`AzureStreamHub.gate`: 100 ms chunks, loud = rms > max(0.012, 2.5 x noise
    floor), 300 ms quiet = a pause, its 10 ms energy track for the boundary cutter's dip) runs on the clip's audio
    on the same clock. FastPhrases.swift is compiled in from the Talk app's checkout (`harness/build.sh`).
  - Apple Translation: `TranslationSession(installedSource:target:)`, one piece per call, no context, in order,
    after one warm-up call; codes en, es, pt-BR, fr, de, zh-Hans, vi, ar, uk, ko, ru, hi, it.
  Output per piece: text, ready and done times, translate time, translation (`results/cut/`).
- **Grouping** (`run.py jobs`): finals and pieces assigned to the read sentences by audio range (as
  `shootout.py group` does for Azure's finals); pieces over several sentences go to the sentence most of their
  words were heard in; a piece Apple capitalised mid-sentence starts lower-case when joined.
- **Cloud route**: `run.py` `AUTO` (from `autoPlan`), its translations from `../2026-11-talk-soniox/results/`:
  `soniox_hear.json` (Soniox hearing), `hearing/mt_mai.json` (MAI), `mt.json` (Azure).
- **Grading** (`../2026-11-talk-soniox/grade.py`): `gemini-flash-latest`, temperature 0, blind (the systems shuffled
  under letters), one call per direction and set with all systems side by side, 0-3 per sentence against the
  FLEURS English text, plus a critical-error flag. At most 3 calls at a time. Pieces were not sent where they
  equal whole (de→en, ko→en, hi→en).

## Reproduce

```
python3 -I ../2026-11-talk-soniox/build_clips.py CLIPS ../2026-10-real-voices .. ../2026-11-talk-soniox/results/ids.json
FASTPHRASES=<Talk app checkout>/LithosSpike/FastPhrases.swift bash harness/build.sh WORK/applehear
python3 -I run.py hear  CLIPS WORK
python3 -I run.py cut   CLIPS WORK
python3 -I run.py jobs  CLIPS WORK
GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I ../2026-11-talk-soniox/grade.py WORK/jobs.json WORK/grades.json
python3 -I run.py table CLIPS WORK
```
(`run.py show CLIPS WORK <set> <direction>` prints one direction's sentences for both arms.) macOS 26 or later with
the Speech and Translation assets installed for each language; Xcode command-line tools; Python 3.

`results/`: `hear/` (stage 1 logs per set and language), `cut/` (stage 2 per set and direction: both arms' pieces
and translations, times), `jobs.json` / `grades.json` (what the grader saw and said), `hear_a_en_bare.json` (set a
English heard with the bare code "en", resolved to en-GB), `de_a_rebuilt.json` (the rebuilt German set-a offsets).
`results.json` has the tables' numbers.

Usage: Apple on-device only (no cloud recognition or translation calls in this round); the grader 40 calls
(110,437 tokens in, 62,780 out, 143,459 thinking).
