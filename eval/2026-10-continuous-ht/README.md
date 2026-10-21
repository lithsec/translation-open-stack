# Continuous speech, Haitian Creole, October 2026

The earlier latency rounds (`../2026-10-latency/`) used read sentences with
clean 1–2 s pauses between them. A news presenter or lecturer does
not pause like that. This test feeds five minutes of continuous Haitian
Creole news speech through Live Translation's Haitian Creole route and asks
two questions: how long is the listener kept waiting, and what decides it?

Date: 2026-10-20 (baseline) and 2026-10-21 (shorter pieces, context). A Mac
in the US Northeast on a wired connection; every endpoint in the US.

## Audio

- One clip: five minutes (01:00–06:00) of a VOA Kreyòl news programme, a
  single male presenter in a studio, continuous speech, no music. VOA
  programmes are US-government works in the public domain. Only metrics are
  kept here: the audio, transcripts, translations, references and run logs
  are not committed.
- Reference: a Haitian transcript and English translation of the clip, both
  made by `gemini-3.1-pro-preview` from the audio, split into 33 sentences
  with approximate times. Nobody checked them by hand, so the references are
  approximate; the scores rank the runs against each other, they are not an
  absolute measure.

## Route and pacing

- Live Translation's solo room with the speaker language fixed to Haitian
  Creole: omni-stt (Omnilingual 300M, privately fine-tuned for Haitian Creole; not in
  the repo) on a Cloud Run L4,
  then GPT-5.6-sol on Azure AI Foundry (reasoning low, one piece per
  request), then the Azure neural English voice. Azure Speech also runs
  beside it, as in the app; its output was not used here.
- The latency round's harness (`../2026-10-latency/harness/`) streams the
  clip at real time in 100 ms chunks of 16 kHz PCM, as a microphone would.
- omni-stt cuts the speech into **pieces** at pauses. Three settings decide
  where: the pause that ends a piece (`ENDPOINT_MS`), the longest a piece can
  get before it is cut anyway (`MAX_UTTERANCE_S`) and the least speech a
  piece must hold (`MIN_SPEECH_MS`). Each run sets them on the service.

| Run | Pause | Cap | Minimum speech | Translation context |
|---|---|---|---|---|
| baseline | 700 ms | 15 s | 0.4 s | none |
| breath | 200 ms | 10 s | 1 s | none |
| breath300 | 300 ms | 10 s | 1 s | none |
| control (no context) | 200 ms | 10 s | 1 s | none |
| context runs 1–3 | 200 ms | 10 s | 1 s | the previous 2 source pieces and the last translation, as context only |

## Metrics

- **First audio:** from the start of speech to the first voiced sound of the
  English translation.
- **Per-piece lag:** for each piece, from the moment its speech *starts* to
  the first voiced sound of its translation, as played (after any earlier
  translation still playing). This is how far behind the speaker the
  listener hears each thought. Median (p50) and 90th percentile (p90).
- **Final lag:** from the speaker's last word to the end of the last
  translated audio.
- **CER:** character error rate of omni-stt's Haitian transcript against the
  reference transcript (lowercased, punctuation removed).
- **Quality:** a Gemini model reads the whole English output and the 33
  numbered reference sentences, and grades each reference sentence 0–3
  (3 correct and natural, 2 minor errors, 1 major meaning errors or mostly
  missing, 0 wrong or missing). **Critical** = a wrong number, name, date or
  negation, or reversed meaning. Temperature 0. The baseline and breath runs
  were graded by `gemini-2.5-pro`, the others by `gemini-pro-latest`;
  re-grading the baseline with `gemini-pro-latest` gave the same 2.52 and 5
  critical errors.
- **Pause lengths** (`pauses.py`): Silero VAD speech probability per 32 ms
  window (omni-stt's VAD, streamed the same way), a gap being the windows
  under the threshold.
- **Simulated settings** (`sim.py`): omni-stt's own `Segmenter` class
  (`services/omni-stt/server.py`, main `9351de9`), fed the clip's audio and
  VAD probabilities, for several settings. No recognition, network or GPU:
  it shows only where the pieces would be cut.

All numbers are in `results.json`.

## Results

| Run | Pieces | Piece length p50 | First audio | Per-piece lag p50 / p90 | Final lag | CER | Quality (0–3) | Critical |
|---|---|---|---|---|---|---|---|---|
| baseline | 27 | 12.7 s | 19.5 s | 18.2 / 23.1 s | 15.9 s | 9.0% | 2.52 | 5 |
| breath | 69 | 3.8 s | 8.4 s | 9.1 / 13.5 s | 10.6 s | 10.2% | 2.21 | 7 |
| breath300 | 53 | 5.4 s | 8.4 s | 10.7 / 15.6 s | 14.2 s | 9.9% | 2.21 | 7 |
| control (no context) | 69 | 3.8 s | 8.2 s | 8.4 / 13.3 s | 11.7 s | 10.2% | 2.15 | 7 |
| context, run 1 | 69 | 3.8 s | 8.2 s | 7.4 / 12.6 s | 11.0 s | 10.2% | 2.52 | 3 |
| context, run 2 | 69 | 3.8 s | 8.1 s | 8.0 / 12.4 s | 10.3 s | 10.2% | 2.67 | 2 |
| context, run 3 | 69 | 3.8 s | 8.0 s | 8.2 / 12.2 s | 11.2 s | 10.2% | 2.21 | 4 |

Gemini Live Translate on the same clip, for scale: first audio 3.2 s, final
lag 4.8 s, quality 1.82 with 14 critical errors (graded by
`gemini-3.1-pro-preview`, which gave the baseline 2.55 with 3).

## What it shows

- **Piece length was set by omni-stt's pause settings, not by the speaker.**
  With a 700 ms pause and a 15 s cap, a presenter who only takes short
  breaths fills the 15 s: pieces were 12.7 s long (median), and the listener
  waited 19.5 s for the first audio and was 18.2 s behind on each piece.
- **Cutting at 200 ms breaths with a 10 s cap** gave 3.8 s pieces, first
  audio at 8.4 s and a per-piece lag of 9.1 s, about half.
- **Quality fell from 2.52 to 2.21** (critical errors 5 to 7): a short piece
  gives the translator less to work out a misheard name or phrase from.
  Recognition barely changed (CER 9.0% to 10.2%).
- **Context restores it.** Sending the previous 2 source pieces and the last
  translation as context only gave 2.52, 2.67 and 2.21 (3, 2 and 4 critical
  errors), against 2.15–2.21 with 7 critical errors without context. Lag was
  the same or better (per-piece p50 7.4–8.2 s, final 10.3–11.2 s).
- **Run 3 was rate-limited** by the translation service: 18 requests were
  refused as "too many requests" and retried, and 9 pieces were never
  translated, which counts against its score. Run 1 had 4 such refusals and
  4 untranslated pieces.
- One piece was refused by the provider's content filter only when sent with
  context; it is now retried without context.

## Pauses in the clip

At the default threshold (0.5), the five minutes hold 105 gaps of 200 ms or
more (21 a minute) but only 29 of 500 ms or more (6 a minute). Speech between
gaps of at least 200 ms runs 2.2 s (median), 4.5 s (p90), 9.5 s at most;
between gaps of at least 500 ms it already runs 6.6 s, 16.3 s and 31.3 s, so
a 700 ms pause rule leaves the 15 s cap to do most of the cutting.

## Caveats

- The per-piece lag figures are likely low. The harness attributes voice
  audio to pieces by arrival, which under-counts the lag when the voice is
  backlogged: on a Spanish run measured both ways
  (`../2026-10-continuous-azure`) it gave 2.1 s where attributing by the
  speech service's byte offsets gives 5.3 s. First audio and final lag are
  unaffected.
- One five-minute clip, one speaker, one genre (studio news), one language.
- One run per setting, apart from the three context runs. Differences of a
  few tenths on the 0–3 scale are within run-to-run noise: the context runs
  alone spread from 2.21 to 2.67.
- One judge per run (a Gemini model), grading against model-made
  references.
- The settings table is a simulation of the segmenter alone; the live
  runs' piece counts are close to it (69 live against 70 simulated for the
  200 ms setting).
