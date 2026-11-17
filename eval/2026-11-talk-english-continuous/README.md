# English speech styles: MAI against Azure standard as Talk streams them, November 2026

For Lithos Talk: should an English speaker be heard by MAI-Transcribe-2-Streaming instead of Azure's standard model?
October's streaming follow-up had MAI worse for English (6.0% against 3.6% characters wrong), and November's
"which hearing" round (`../2026-11-talk-soniox`) had it better (4.2% against 6.9%) on read speech with regular pauses.
That round ran Azure at the SDK's own segmentation, not Talk's, and only one pause pattern. So this check asks what
German's itseg check (2026-10-26) asked: the same sentences with **paused, irregular and non-stop** speech, streamed
the way Talk streams them. Another session is rerunning en and pt-BR clip for clip on read speech, and this one
doesn't repeat it.

## Setup

- **Audio:** the 40 English FLEURS sentences (CC BY 4.0) of `../2026-11-talk-soniox` (sets a and b, male and female
  readers alternating; `results/ids.json`), cut out of that round's clips at their sentence marks and joined again
  (`build_styles.py`): **paused** 1.0-1.95 s between sentences (the round's own gaps: the same audio as its clips),
  **irregular** 0.3-1.2 s, **non-stop** 0.05-0.2 s (under Talk's 300 ms English silence, so a sentence end is no
  pause to end on). 2 sets × 3 styles, 110-173 s each.
- **Streaming** (`stream.py`): the Speech SDK (1.53.1), real time in 100 ms chunks, en-US pinned, with **Talk's
  English settings** (lithos-translate-app main, `AzureStreamHub.swift`: segmentation silence 300 ms, forced cut
  20 s). MAI is the same SDK with `speech_config.model = "mai-transcribe-2-streaming"` (as `AzureStreamHub.maiModel`).
  Both on the eastus2 resource, three streams at a time. **Control:** both again at the SDK's default segmentation
  (what `../2026-11-talk-soniox` ran).
- **Recognition** (`score.py`): WER and CER on each clip's whole text (every final joined), errors pooled over sets a
  and b; two normalisations: *plain* (NFKC, lower case, punctuation removed) and *spelled* (digits spelled out with
  num2words too, as `../2026-10-whisper-vs-azure/score.py`). Per run: finals, **forced** cuts (≥ 19.5 s),
  **mid-sentence** cuts (a final ending 10+ characters inside a read sentence: the sentence split across two pieces
  Talk translates on their own), **joined** (a final spanning two or more sentences), and the final's lag after its
  audio ends (p50, mean of the two sets).
- **Translation:** the transcripts differed enough to grade. Each arm's finals cut into the read sentences by text
  (`align.py`), translated en→es and en→fr by Gemma 4 31B on Bedrock (Talk's translator for both, the shootout prompt:
  `../2026-11-talk-soniox/mt.py` gemma()), graded blind side by side, one call per set and target
  (`../2026-11-talk-soniox/grade.py`, `gemini-flash-latest`, 0-3 against the FLEURS meaning). Quality is the share of
  the possible 3 over 80 sentences per arm and style (es and fr pooled); critical errors of 80.

## Results

| Recogniser (segmentation) | Style | WER plain | CER plain | WER spelled | CER spelled | Finals | Forced | Mid-sentence | Joined | Final lag p50 (s) | Quality en→es / fr (pooled) | Critical |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Azure standard (Talk: 300 ms) | paused | 14.03 | 10.07 | 13.24 | 9.31 | 63 | 0 | 23 | 1 | 0.21 | 66.7 / 69.2 (**67.9**) | 8 |
| Azure standard (Talk: 300 ms) | irregular | 15.14 | 11.16 | 14.32 | 10.35 | 59 | 0 | 20 | 1 | 0.21 | 70.0 / 66.7 (**68.3**) | 9 |
| Azure standard (Talk: 300 ms) | nonstop | 14.86 | 10.88 | 14.05 | 10.1 | 42 | 1 | 18 | 9 | 0.24 | 72.5 / 73.3 (**72.9**) | 11 |
| MAI (Talk: 300 ms) | paused | 6.39 | 4.31 | 6.14 | 3.99 | 53 | 0 | 15 | 2 | 0.41 | 85.8 / 84.2 (**85.0**) | 6 |
| MAI (Talk: 300 ms) | irregular | 7.09 | 4.6 | 6.82 | 4.27 | 52 | 0 | 16 | 4 | 0.4 | 85.0 / 84.2 (**84.6**) | 4 |
| MAI (Talk: 300 ms) | nonstop | 7.36 | 5.38 | 7.09 | 5.04 | 33 | 1 | 14 | 13 | 0.4 | 87.5 / 85.0 (**86.2**) | 6 |
| Azure standard (SDK default) | paused | 10.42 | 7.03 | 9.69 | 6.34 | 43 | 0 | 4 | 2 | 0.64 | 75.0 / 75.8 (**75.4**) | 9 |
| Azure standard (SDK default) | irregular | 9.86 | 6.57 | 9.14 | 5.89 | 28 | 1 | 3 | 10 | 0.75 | 78.3 / 77.5 (**77.9**) | 6 |
| Azure standard (SDK default) | nonstop | 13.89 | 10.59 | 12.82 | 9.79 | 16 | 5 | 4 | 10 | 0.67 | 72.5 / 74.2 (**73.3**) | 8 |
| MAI (SDK default) | paused | 5.97 | 4.05 | 5.73 | 3.73 | 44 | 0 | 5 | 1 | 0.59 | - | - |
| MAI (SDK default) | irregular | 6.67 | 4.66 | 6.41 | 4.33 | 39 | 1 | 6 | 4 | 0.6 | - | - |
| MAI (SDK default) | nonstop | 6.95 | 5.24 | 6.68 | 4.89 | 23 | 4 | 11 | 11 | 0.57 | - | - |

(MAI at SDK default was not translated: Talk doesn't run it.)

1. **MAI has half Azure's errors in every style at Talk's settings:** WER 6.4 / 7.1 / 7.4% against 14.0 / 15.1 / 14.9%
   (paused / irregular / non-stop), CER 4.3 / 4.6 / 5.4% against 10.1 / 11.2 / 10.9%. Translated, that's 84.6-86.2
   against 67.9-72.9, with fewer critical errors (16 against 28 of 240).
2. **Talk's 300 ms silence is what sinks Azure's English.** At the SDK's default segmentation Azure is at 7.0% CER on
   paused speech, which reproduces `../2026-11-talk-soniox` (6.9%, the same audio). At 300 ms it cuts 18-23 finals
   mid-sentence and **drops the last word or two of the piece** ("evolution of feathers in birds" → "evolution of
   feathers and."; "to succeed", "men" gone). Its finals do come sooner (0.21 s after the audio against 0.64-0.75 s).
   MAI cuts mid-sentence at 300 ms too (14-16), but keeps the words.
3. **Non-stop speech is the hardest for both, not a MAI weakness:** MAI 7.4% WER against its 6.4% paused; Azure at
   default goes 10.4 → 13.9%. Forced cuts: one each at Talk's settings (non-stop set a). MAI joins more sentences into
   one final in non-stop speech (13 against Azure's 9), which a translator can take (both arms' non-stop quality is
   their best or level).
4. **MAI gives partials and they come sooner:** first partial 1.36 / 1.67 s (sets a / b) against Azure's 1.98 / 2.27 s.
   (The Spanish GC bench's "no partials, ~4 s first word" was not this streaming path.)
5. **MAI does not ignore the silence setting** (as `lithos-server docs/test-routes-design.md` says): at default it
   gave 22 finals on paused set a against 30 at 300 ms. Its errors barely move with it (paused 6.0 → 6.4% WER).
6. **MAI's word timings run late and short** (a final holding set a's sentence 13, read at 117.4-125.1 s, says
   127.0-131.0 s), so grouping its finals by audio offset (`../2026-10-translator-shootout/shootout.py group`) puts
   its text in the wrong sentences. Splits, joins and the translated sentences here are aligned by text instead
   (`align.py`, for every arm). Anything in Talk that maps MAI's offsets to audio (echo windows, the boundary
   cutter's clock) would see the same drift. Not checked here.

**Verdict:** on English speech in all three styles, MAI as Talk would run it is clearly better than Azure as Talk runs
it (about 6 CER points fewer in each style, +13 to +17 translation quality), and not worse on non-stop speech. October's
opposite result is not explained here: the other session's clip-for-clip rerun is the place for that. If it doesn't
overturn this, English should move to MAI in Talk. Independent of that, Talk's 300 ms English silence costs Azure about
3 CER points against the SDK default (lost words at cuts), which matters wherever Azure keeps hearing English.

## Caveats

- Read FLEURS speech with artificial pauses, not conversation; 40 sentences, 20 readers. One run per arm and style,
  one grading read (the gaps are 13-17 points, far over a regrade's ~2.5).
- The SDK's segmentation properties (`Speech_SegmentationSilenceTimeoutMs`, `Speech_SegmentationMaximumTimeMs`)
  stand in for the app's raw speech.context `segmentation` (mode Custom); not checked byte for byte.
- Translation was per read sentence (text-aligned), so the cost of a sentence split across two finals isn't in the
  grades, only the lost and wrong words. Talk translates each final as it comes, so splits would cost more there:
  Azure at 300 ms splits more (18-23 against 14-16).
- en-US pinned for both. Talk pins MAI to the speaker's language and runs Azure the same way for English.

## Reproduce

```
python3 -I ../2026-11-talk-soniox/build_clips.py WORK ../2026-10-real-voices .. ../2026-11-talk-soniox/results/ids.json en
python3 -I build_styles.py WORK WORK/styles
for r in azure mai; do AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 RECOGNISER=$r python3 -I stream.py WORK/styles WORK/out; done
for r in azure mai; do SEGMENTATION=default AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 RECOGNISER=$r python3 -I stream.py WORK/styles WORK/out; done
python3 -I score.py WORK/out WORK/styles WORK/scores.json
AWS_PROFILE=lithos-evals python3 -I mt_styles.py WORK/out mt WORK/styles
python3 -I mt_styles.py WORK/out jobs WORK/styles
GEMINI_API_KEY=... GRADER=gemini-flash-latest python3 -I ../2026-11-talk-soniox/grade.py WORK/out/jobs.json WORK/out/grades.json
python3 -I table.py WORK/scores.json WORK/out/grades.json results.json
```
Python 3 with `azure-cognitiveservices-speech`, `numpy`, `boto3`, `num2words`. `results/`: every run's finals
(`runs/<arm>/<set>_<style>.json`), translations (`mt/`), grading jobs and grades, and `scores.json`; no audio.
Spend: about $1 (56 min of streamed audio on Azure Speech, 1,440 Gemma calls, 12 grading calls).
