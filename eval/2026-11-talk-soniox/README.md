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

## Soniox hearing + our translator

A second, fresh round (`talk-soniox-hear-2026-11`): does Soniox's better hearing help when our own translator
translates? A third system, **soniox-hear**: Soniox's own source-language transcript per sentence, taken from the
same streams (`soniox_hear.py`: the original tokens grouped by audio offset as the translations were; each
direction uses its own stream, so en→X uses the en→X stream's English; no new streams, no sentence empty),
translated by the baseline's translator for that direction with the same prompt and host (`mt.py` with
`HEAR=soniox`). All three systems, soniox-hear, the baseline (Azure + the same translator) and Soniox S2S, were
graded blind side by side in one call per direction and set (`round_hear.py`, `grade.py`, `gemini-flash-latest`,
same rubric and FLEURS references, n = 40). Where soniox-hear and the baseline were within about 3 points
(±3.3: pt, de, zh, vi, ar, ru, hi into English and en→uk) the round was graded a second time and the quality is
the mean of both reads (in brackets). Critical: of 40, first read. Recognition CER: as in the first table.
"Qualifies": soniox-hear ≥ 70 and ≥ baseline − 3. Rows: `soniox-hear-rows.json`; numbers: `results.json`
`soniox_hear`.

| Direction | Translator | soniox-hear | Baseline | Soniox S2S | soniox-hear − baseline | Critical, hear / baseline / S2S | CER, Soniox / Azure | Qualifies |
|---|---|---|---|---|---|---|---|---|
| en→es | Gemma 4 | **87.5** | **77.5** | **68.3** | +10.0 | 3 / 4 / 4 | 5.8% / 6.9% | **yes** |
| es→en | Gemma 4 | **95.8** | **91.7** | **75.0** | +4.1 | 2 / 3 / 3 | 0.9% / 1.4% | **yes** |
| en→pt | Gemma 4 | **82.5** | **75.8** | **66.7** | +6.7 | 3 / 3 / 3 | 5.8% / 6.9% | **yes** |
| pt→en | gpt-6-sol | **87.1** (87.5, 86.7) | **91.3** (90.8, 91.7) | **74.6** (73.3, 75.8) | -4.2 | 4 / 2 / 6 | 1.3% / 1.6% | no |
| en→fr | Gemma 4 | **83.3** | **75.8** | **58.4** | +7.5 | 3 / 4 / 6 | 5.8% / 6.9% | **yes** |
| fr→en | Gemma 4 | **90.8** | **79.2** | **77.5** | +11.6 | 3 / 5 / 4 | 1.9% / 4.0% | **yes** |
| en→de | Gemma 4 | **87.5** | **75.8** | **57.5** | +11.7 | 3 / 5 / 8 | 5.8% / 6.9% | **yes** |
| de→en | gpt-6-sol | **90.8** (90.8, 90.8) | **86.7** (87.5, 85.8) | **71.7** (73.3, 70.0) | +4.1 | 4 / 5 / 4 | 1.2% / 2.2% | **yes** |
| en→zh | Gemma 4 | **87.5** | **77.5** | **60.0** | +10.0 | 5 / 6 / 10 | 5.8% / 6.9% | **yes** |
| zh→en | Gemma 4 | **88.8** (89.2, 88.3) | **88.8** (88.3, 89.2) | **65.8** (66.7, 65.0) | +0.0 | 4 / 3 / 9 | 2.4% / 3.0% | **yes** |
| en→vi | Gemma 4 | **87.5** | **78.3** | **66.7** | +9.2 | 4 / 5 / 9 | 5.8% / 6.9% | **yes** |
| vi→en | Gemma 4 | **80.0** (78.3, 81.7) | **77.5** (75.8, 79.2) | **60.4** (59.1, 61.6) | +2.5 | 5 / 6 / 6 | 3.4% / 4.6% | **yes** |
| en→ar | gpt-6-sol | **87.5** | **80.0** | **59.2** | +7.5 | 2 / 2 / 5 | 5.8% / 6.9% | **yes** |
| ar→en | Gemma 4 | **92.5** (92.5, 92.5) | **90.8** (91.7, 90.0) | **71.2** (72.5, 70.0) | +1.7 | 1 / 3 / 9 | 0.9% / 1.7% | **yes** |
| en→fa | gpt-6-sol | **88.3** | **81.7** | **55.9** | +6.6 | 3 / 3 / 7 | 5.8% / 6.9% | **yes** |
| fa→en | Gemma 4 | **88.3** | **76.7** | **68.3** | +11.6 | 2 / 6 / 6 | 2.4% / 4.4% | **yes** |
| en→tl | Gemma 4 | **79.2** | **70.0** | **70.0** | +9.2 | 4 / 7 / 7 | 5.8% / 6.9% | **yes** |
| tl→en | Gemma 4 | **95.0** | **83.3** | **63.4** | +11.7 | 0 / 3 / 4 | 2.7% / 4.2% | **yes** |
| en→uk | gpt-6-sol | **85.8** (85.8, 85.8) | **82.1** (82.5, 81.7) | **62.5** (59.2, 65.8) | +3.7 | 2 / 2 / 5 | 5.8% / 6.9% | **yes** |
| uk→en | gpt-6-sol | **95.8** | **88.3** | **72.5** | +7.5 | 1 / 4 / 5 | 2.7% / 2.8% | **yes** |
| en→ko | Gemma 4 | **87.5** | **77.5** | **64.2** | +10.0 | 3 / 7 / 6 | 5.8% / 6.9% | **yes** |
| ko→en | gpt-6-sol | **95.0** | **90.8** | **68.3** | +4.2 | 1 / 0 / 3 | 4.0% / 6.1% | **yes** |
| en→ru | Gemma 4 | **86.7** | **78.3** | **60.9** | +8.4 | 4 / 7 / 8 | 5.8% / 6.9% | **yes** |
| ru→en | gpt-6-sol | **96.7** (96.7, 96.7) | **96.7** (96.7, 96.7) | **74.2** (75.8, 72.5) | +0.0 | 0 / 1 / 2 | 1.8% / 2.3% | **yes** |
| en→hi | Gemma 4 | **80.8** | **70.0** | **64.2** | +10.8 | 3 / 6 / 4 | 5.8% / 6.9% | **yes** |
| hi→en | gpt-6-sol | **87.9** (87.5, 88.3) | **86.2** (85.0, 87.5) | **64.6** (63.4, 65.8) | +1.7 | 3 / 4 / 11 | 3.6% / 4.3% | **yes** |
| en→it | Gemma 4 | **84.2** | **74.2** | **65.0** | +10.0 | 4 / 7 / 7 | 5.8% / 6.9% | **yes** |
| it→en | gpt-6-sol | **94.2** | **100.0** | **76.7** | -5.8 | 2 / 0 / 2 | 1.4% / 1.1% | no |

1. **Soniox's hearing with our translator qualifies in 26 of 28 directions**, and is ahead of the baseline in 24.
   Out of English it is ahead in all 14 (+3.7 to +11.7); into English -5.8 to
   +11.7, level (within 2.5) in zh, vi, ar, ru, hi into English. It is behind in pt→en (−4.2 over two
   reads) and it→en (−5.8; the baseline scored 100.0), both sol directions.
2. **The gain is larger than the character error rates suggest** (English: 5.8% vs 6.9%). In the 7 en→de
   sentences checked where soniox-hear scored higher, the Azure side had a misplaced sentence break or full stop that the
   translator followed ("the seasonal floods though would spread. Sediment ... were halted"), a clause missing
   from the sentence ("... were now enemies." without "and the Cold War began"), or a misheard word ("vendors"
   as "inventors"); Soniox's transcript of the same audio had none of those. CER counts letters only, not
   punctuation or where a sentence ends.
3. **Soniox S2S in this round** is again far behind both (55.9-77.5), and level with the baseline only in
   fr→en (77.5 vs 79.2) and en→tl (70.0 vs 70.0), as in the first round.
4. Caveats: as above (MAI not run, Azure stands in; sentence-at-a-time translation with the shootout prompt; read
   speech with regular pauses; one grader). soniox-hear's transcripts come from streams that also translated
   (one-way translation on); a Soniox stream without translation was not run. Grades differ between rounds (the
   baseline's en→es is 76.7 in the first round, 77.5 here): compare within one round's table.

## Which hearing: Soniox, MAI or Azure, with our translator

A third, fresh round (`talk-hearing-2026-11`): is Soniox's hearing better than MAI's, not only Azure standard's?
**mai-hear**: MAI-Transcribe-2-Streaming (`stt_azure.py` with `RECOGNISER=mai`: the Speech SDK's
`model = "mai-transcribe-2-streaming"`, as Talk's `AzureStreamHub.maiModel`, pinned to the same locale, on the
eastus2 resource, three streams at a time), finals regrouped per sentence by audio offset as Azure's. Talk hears
es, fr, de, zh, vi, ar, fa, tl and uk with MAI today (lithos-server `testroutes.ts` `MAI_STREAM_LANGS`); MAI was
run on all 15 languages here, English included, and accepted every one, so every direction has all three. Each
arm's transcripts were translated by the direction's baseline translator with the same prompt and host (`mt.py`
`HEAR=mai`; soniox-hear and azure-hear are the second round's translations). The three were graded blind side
by side in one call per direction and set (`round_hearing.py`, `grade.py`, `gemini-flash-latest`, n = 40); 21
directions whose top two were within 3.3 points were graded a second time (quality = mean of both reads, in
brackets). Critical: of 40, first read. "Soniox qualifies": Soniox ≥ 70 and ≥ the better of MAI and Azure − 3.
Rows: `hearing-rows.json`; numbers: `results.json` `hearing`; outputs and grades: `results/hearing/`.

**Audio.** The clips were deleted after the first two rounds and rebuilt for this one from `results/ids.json`
(`build_clips.py ... results/ids.json`). Every rebuilt clip's offsets, files and texts matched the committed
ones except Ukrainian set a, whose last sentence came out 220 ms shorter (199.79 s against 200.01 s). Soniox
(uk→en) and Azure were re-run on the rebuilt uk set-a clip and their translations redone, so all three arms
heard identical audio (`results/hearing/uk_a_rebuilt.json`); every other clip is the one the earlier rounds used.

| Direction | Translator | Soniox | MAI | Azure | Best | Soniox − best other | Soniox qualifies | Critical, Soniox / MAI / Azure |
|---|---|---|---|---|---|---|---|---|
| en→es | Gemma 4 | **85.0** (85.8, 84.2) | **87.5** (87.5, 87.5) | **75.8** (75.8, 75.8) | MAI | -2.5 | **yes** | 3 / 2 / 4 |
| es→en | Gemma 4 | **95.0** (95.0, 95.0) | **95.8** (95.8, 95.8) | **90.8** (90.8, 90.8) | MAI | -0.8 | **yes** | 2 / 1 / 3 |
| en→pt | Gemma 4 | **83.8** (84.2, 83.3) | **87.1** (87.5, 86.7) | **76.7** (76.7, 76.7) | MAI | -3.3 | no | 3 / 2 / 3 |
| pt→en | gpt-6-sol | **87.1** (86.7, 87.5) | **94.2** (93.3, 95.0) | **92.5** (92.5, 92.5) | MAI | -7.1 | no | 5 / 2 / 2 |
| en→fr | Gemma 4 | **84.6** (83.3, 85.8) | **85.8** (84.2, 87.5) | **75.4** (73.3, 77.5) | MAI | -1.2 | **yes** | 4 / 2 / 6 |
| fr→en | Gemma 4 | **91.7** (90.8, 92.5) | **92.9** (91.7, 94.2) | **77.9** (77.5, 78.3) | MAI | -1.2 | **yes** | 2 / 3 / 7 |
| en→de | Gemma 4 | **83.3** (84.2, 82.5) | **85.0** (86.7, 83.3) | **74.6** (75.8, 73.3) | MAI | -1.7 | **yes** | 3 / 2 / 6 |
| de→en | gpt-6-sol | **90.8** | **94.2** | **86.7** | MAI | -3.4 | no | 2 / 2 / 4 |
| en→zh | Gemma 4 | **85.4** (85.8, 85.0) | **87.5** (87.5, 87.5) | **77.1** (78.3, 75.8) | MAI | -2.1 | **yes** | 2 / 2 / 5 |
| zh→en | Gemma 4 | **87.5** | **91.7** | **85.8** | MAI | -4.2 | no | 4 / 2 / 3 |
| en→vi | Gemma 4 | **88.0** (89.2, 86.7) | **89.2** (90.0, 88.3) | **77.5** (78.3, 76.7) | MAI | -1.2 | **yes** | 3 / 2 / 4 |
| vi→en | Gemma 4 | **80.8** (81.7, 80.0) | **83.3** (83.3, 83.3) | **77.1** (77.5, 76.7) | MAI | -2.5 | **yes** | 4 / 5 / 8 |
| en→ar | gpt-6-sol | **87.9** (87.5, 88.3) | **88.8** (87.5, 90.0) | **81.2** (80.8, 81.7) | MAI | -0.9 | **yes** | 3 / 3 / 3 |
| ar→en | Gemma 4 | **90.8** (91.7, 90.0) | **92.5** (93.3, 91.7) | **89.2** (90.0, 88.3) | MAI | -1.7 | **yes** | 1 / 1 / 2 |
| en→fa | gpt-6-sol | **87.9** (87.5, 88.3) | **87.1** (86.7, 87.5) | **82.1** (80.8, 83.3) | Soniox | +0.8 | **yes** | 3 / 4 / 4 |
| fa→en | Gemma 4 | **85.8** | **77.5** | **75.0** | Soniox | +8.3 | **yes** | 1 / 5 / 5 |
| en→tl | Gemma 4 | **80.8** | **84.2** | **71.7** | MAI | -3.4 | no | 5 / 3 / 6 |
| tl→en | Gemma 4 | **92.5** | **87.5** | **81.7** | Soniox | +5.0 | **yes** | 0 / 2 / 3 |
| en→uk | gpt-6-sol | **85.0** (84.2, 85.8) | **84.2** (84.2, 84.2) | **79.6** (79.2, 80.0) | Soniox | +0.8 | **yes** | 4 / 3 / 3 |
| uk→en | gpt-6-sol | **93.8** (95.0, 92.5) | **91.2** (91.7, 90.8) | **90.8** (90.8, 90.8) | Soniox | +2.6 | **yes** | 3 / 4 / 4 |
| en→ko | Gemma 4 | **89.6** (90.0, 89.2) | **91.2** (90.8, 91.7) | **76.2** (76.7, 75.8) | MAI | -1.6 | **yes** | 3 / 2 / 5 |
| ko→en | gpt-6-sol | **95.0** (95.0, 95.0) | **98.3** (98.3, 98.3) | **91.7** (91.7, 91.7) | MAI | -3.3 | no | 1 / 0 / 0 |
| en→ru | Gemma 4 | **83.3** | **89.2** | **76.7** | MAI | -5.9 | no | 4 / 4 / 6 |
| ru→en | gpt-6-sol | **95.4** (95.8, 95.0) | **98.3** (98.3, 98.3) | **95.5** (96.7, 94.2) | MAI | -2.9 | **yes** | 0 / 0 / 1 |
| en→hi | Gemma 4 | **85.4** (85.0, 85.8) | **87.9** (87.5, 88.3) | **75.8** (75.0, 76.7) | MAI | -2.5 | **yes** | 3 / 3 / 6 |
| hi→en | gpt-6-sol | **85.0** (85.8, 84.2) | **86.2** (87.5, 85.0) | **83.8** (85.0, 82.5) | MAI | -1.2 | **yes** | 3 / 2 / 5 |
| en→it | Gemma 4 | **83.3** (85.0, 81.7) | **81.7** (82.5, 80.8) | **72.1** (74.2, 70.0) | Soniox | +1.6 | **yes** | 4 / 4 / 5 |
| it→en | gpt-6-sol | **94.2** | **95.0** | **100.0** | Azure | -5.8 | no | 2 / 1 / 0 |

Recognition, characters wrong against the FLEURS text of the whole clip, mean of sets a and b (Soniox: the
original-language transcript of its translation streams; for Ukrainian set a, the rebuilt clip):

| Language | Soniox | MAI | Azure |
|---|---|---|---|
| en | 5.8% | 4.2% | 6.9% |
| es | 0.9% | 0.5% | 1.4% |
| pt | 1.3% | 0.8% | 1.6% |
| fr | 1.9% | 1.1% | 4.0% |
| de | 1.2% | 0.9% | 2.2% |
| zh | 2.4% | 1.1% | 3.0% |
| vi | 3.4% | 3.3% | 4.6% |
| ar | 0.9% | 0.8% | 1.7% |
| fa | 2.4% | 1.8% | 4.4% |
| tl | 2.7% | 1.9% | 4.2% |
| uk | 2.8% | 1.0% | 2.9% |
| ko | 4.0% | 3.0% | 6.1% |
| ru | 1.8% | 0.7% | 2.3% |
| hi | 3.6% | 2.9% | 4.3% |
| it | 1.4% | 0.3% | 1.1% |

1. **MAI's hearing scores highest in 21 of 28 directions, Soniox's in 6** (en→fa, fa→en, tl→en, en→uk,
   uk→en, en→it), Azure's in 1 (it→en, 100.0). Soniox is within 3 points of the best (and ≥ 70) in 20.
   It is more than 3 behind in en→pt, pt→en, de→en, zh→en, en→tl, ko→en, en→ru and it→en.
2. **MAI has the fewest character errors in all 15 languages**, English included (4.2% against Soniox's 5.8% and
   Azure's 6.9%), and under 60% of Soniox's in fr, zh, uk, ru and it.
3. **Character errors don't decide it.** In fa→en MAI has the fewest (1.8%) but scores 77.5 against Soniox's
   85.8: its misses there were numbers and key words (19 injured heard as 11, 70 km as 700 km, "pencil" as
   "Medal", "all" as "these"), each a whole sentence wrong for one or two characters. Into English from tl and
   uk Soniox is also ahead (+5.0, +2.6) despite more character errors.
4. **Azure standard is last in 25 of 28**: it beats Soniox in pt→en (92.5 against 87.1), ru→en (95.5 against
   95.4) and it→en (100.0 against 94.2), and MAI only in it→en.
5. Caveats: as above (sentence-at-a-time translation with the shootout prompt, read speech with regular pauses,
   one grader). MAI was pinned to the clip's language, as Talk pins it per direction; Soniox ran with language
   identification and no hint, as the app runs it. Grades differ between rounds: compare within one table.

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
# Soniox hearing + our translator
python3 -I soniox_hear.py WORK WORK/out
HEAR=soniox AWS_PROFILE=... FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=gpt-6-sol-us python3 -I mt.py WORK/out
python3 -I round_hear.py jobs WORK WORK/out
GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py WORK/out/hear/jobs.json WORK/out/hear/grades.json
python3 -I round_hear.py jobs2 WORK WORK/out pt-en de-en zh-en vi-en ar-en en-uk ru-en hi-en
GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py WORK/out/hear/jobs_r2.json WORK/out/hear/grades_r2.json
python3 -I round_hear.py table WORK WORK/out
# Which hearing (after rebuilding the audio with build_clips.py WORK ../2026-10-real-voices .. results/ids.json)
RECOGNISER=mai AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 python3 -I stt_azure.py WORK WORK/out
HEAR=mai AWS_PROFILE=... FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=gpt-6-sol-us python3 -I mt.py WORK/out
python3 -I round_hearing.py jobs WORK WORK/out
GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py WORK/out/hearing/jobs.json WORK/out/hearing/grades.json
python3 -I round_hearing.py jobs2 WORK WORK/out <directions whose top two are within ~3>
GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I grade.py WORK/out/hearing/jobs_r2.json WORK/out/hearing/grades_r2.json
python3 -I round_hearing.py table WORK WORK/out
```
(`round_hearing.py restore` puts the earlier rounds' translations back into WORK/out from `results/`.)

Python 3 with `azure-cognitiveservices-speech`, `websockets`, `boto3`, `numpy`; `sox` for the clips.

`results/`: `soniox.json` (per stream: its transcript, its translation per sentence, translation characters),
`stt_azure.json` (Azure finals and per-sentence transcripts), `mt.json` (the baseline translations, wall times,
tokens), `jobs.json` / `grades.json` and `jobs_r2.json` / `grades_r2.json` (what the grader saw and said),
`clips_*` (texts, offsets, FLEURS files and speakers' genders), `ids.json`. `results.json` has the table's numbers;
`soniox-talk-rows.json` is the rows in the shape the server reads (lithos-server `src/routes/soniox-talk.json`).
The second round: `soniox_hear.json` (Soniox's transcript per sentence and its translations), `hear_jobs.json` /
`hear_grades.json`, `hear_jobs_r2.json` / `hear_grades_r2.json`; its rows in `soniox-hear-rows.json`.

Usage, from the runs: Soniox 56 streams, 2.9 hours of stream time, 119,122 translation characters; Azure
speech-to-text 1.8 hours of audio; Gemma 4 on Bedrock 720 calls (67,301 tokens in, 19,122 out); gpt-6-sol 400
calls (28,102 in, 21,662 out); the grader 60 calls (140,462 tokens in, 62,727 out, 173,392 thinking). The second
round: Gemma 4 720 calls (67,440 in, 19,120 out), gpt-6-sol 400 calls (28,305 in, 17,711 out), the grader 72
calls (204,911 in, 107,926 out, 277,377 thinking); no new Soniox or Azure use.
