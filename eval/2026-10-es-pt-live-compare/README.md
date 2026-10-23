# Azure recognition + three translators, and Gemini Live Translate, October 2026

Two questions on held-out speech:

1. Behind Azure speech-to-text, how do an open translator (Hy-MT2 7B), an open
   LLM (Gemma 4 31B) and GPT-5.6-sol compare for Spanish and Portuguese (both
   ways) and out of English?
2. How does all of that compare with Gemini Live Translate, the speech-in,
   speech-out model, on the same English audio?

## Setup

- **Audio:** the held-out clips of `../2026-10-held-out` (its `build_clips.py`,
  regular 1.0–1.95 s pauses): 20 FLEURS sentences per language (CC BY 4.0)
  that no earlier round used, read by FLEURS speakers, 2.5–3 minutes each.
  English, Spanish and Portuguese are used here. In 8 of the 20 English
  recordings the reader stops early or misreads, so English directions are
  graded twice: against the written text, and against what was said (the
  held-out round's `said_en.json`). For Spanish and Portuguese "said" drops the
  sentences whose recording doesn't match (one Spanish sentence).
- **Recognition:** Azure speech-to-text (`stt_azure.py`; en-US, es-ES, pt-BR;
  eastus), fed at real time in 100 ms chunks, finals regrouped into the read
  sentences by audio offset (`../2026-10-translator-shootout/shootout.py`
  `group`).
- **Translation of Azure's text** (`mt.py`), one call per sentence:
  - Hy-MT2 7B on OpenRouter (`tencent/hy-mt2-7b`, served by Tencent), with its
    own instruction (`server/engines/hymt.py`). No Lao or Haitian Creole.
  - Gemma 4 31B on OpenRouter (`google/gemma-4-31b-it`, bf16, served by
    DeepInfra), reasoning off, temperature 0.
  - GPT-5.6-sol on Azure AI Foundry (Data Zone Standard, US), `reasoning_effort: low`.
  - Gemma 4 and sol get the translator shootout's prompt, which says the text
    came from live speech and may contain recognition errors. Every OpenRouter
    request asked for zero data retention (`"provider": {"zdr": true}`).
- **Gemini Live Translate** (`live_translate.mjs`):
  `gemini-3.5-live-translate-preview`, the model in the Talk app's
  configuration, on AI Studio. The English clip streamed at real time
  (100 ms chunks), one session per target language, its output transcription
  kept with arrival times. It does its own recognition from the audio.
  Its answer is one continuous stream; `segment.py` cuts it per sentence: a
  Gemini call names where each sentence's translation starts (words copied
  from the stream) and the cut is made at those anchors, so it can only
  divide the stream, never change it. All anchors were found verbatim; two
  Spanish sentences had no translation of their own.
- **Grading** (`grade.py`, the held-out round's grader): `gemini-pro-latest`,
  blind, every system for a direction side by side in one call, 0–3 per
  sentence against the English meaning plus a critical-error flag. Shown as
  the share of the possible score, critical errors in brackets. One round for
  everything here; grades move 5–10 points between rounds, so compare within
  this table only.

## Quality

Against what was said (against the written text in the second column group):

| Direction | Hy-MT2 7B | Gemma 4 31B | sol @low | Gemini Live | | Hy-MT2 7B | Gemma 4 31B | sol @low | Gemini Live |
|---|---|---|---|---|---|---|---|---|---|
| en→es | 71.7 (6) | **78.3 (5)** | 75.0 (6) | 50.0 (11) | | **70.0** | 65.0 | **70.0** | 35.0 |
| en→pt | 73.3 (3) | **80.0 (3)** | **80.0 (3)** | 56.7 (8) | | 66.7 | 65.0 | **71.7** | 46.7 |
| en→fr | 76.7 (3) | 80.0 (3) | **83.3 (4)** | 48.3 (10) | | 60.0 | 63.3 | **65.0** | 43.3 |
| en→ja | 71.7 (5) | **78.3 (3)** | **78.3 (4)** | 40.0 (7) | | 58.3 | 63.3 | **71.7** | 33.3 |
| en→km | 73.3 (1) | 76.7 (1) | **85.0 (1)** | 40.0 (1) | | 66.7 | 66.7 | **73.3** | 36.7 |
| en→lo | n/a | **90.0 (2)** | 86.7 (3) | 53.3 (7) | | n/a | **73.3** | 71.7 | 51.7 |
| en→ht | n/a | 78.3 (3) | **83.3 (3)** | 46.7 (10) | | n/a | 63.3 | **68.3** | 41.7 |
| es→en | 91.2 (1) | 89.5 (2) | **93.0 (1)** | – | | 88.3 | 88.3 | **90.0** | – |
| pt→en | 78.3 (2) | 80.0 (1) | **86.7 (0)** | – | | 78.3 | 80.0 | **86.7** | – |

Azure recognition, characters wrong against what was said: English 5.4%,
Spanish 3.5%, Portuguese 3.0% (against the written text 8.7%, 3.8%, 3.8%).

For reference only, from a **different grading round** (`../2026-10-held-out`,
not comparable point for point): the open stack live on the same clips, against
what was said, en→es 65.0, en→pt 56.7, en→fr 61.7, en→ja 56.7, en→km 55.0,
en→lo 53.3, en→ht 38.3, es→en 84.2, pt→en 80.0.

- **Out of English, Gemma 4 31B and sol are level** (Gemma 4 ahead on Spanish
  and Lao, sol on French, Khmer and Haitian Creole), both 3–12 points above
  Hy-MT2. Against the written text, where the misread recordings cost every
  system, sol leads by 5–8 points on Japanese and Portuguese.
- **Into English from Spanish and Portuguese all three are high**; sol leads
  Portuguese → English by 7–8 points.
- **Gemini Live Translate trails every Azure route by 20–45 points.** It
  interprets simultaneously from its own hearing of the audio, and the grader's
  notes are mostly misheard words carried into the translation ("occupants" as
  "Egyptians", "fission bomb" as "vision board"), garbled or merged sentences,
  and two Spanish sentences dropped. Its own recognition, not the cut, is the
  loss: the anchors were all found and sentences it did translate cleanly
  scored 3.

## Latency

Milliseconds after the sentence's speech ends, p50 / p90. Azure routes: the
sentence's last Azure final arrives (English p50 838 / p90 1533) plus one
translation call (wall time, OpenRouter- or Foundry-hosted); no voice. Gemini
Live: arrival of the last text of its translation of the sentence (its audio
arrives with it); its first words come 3–4.5 s **before** the speaker stops,
because it interprets while the sentence is still being spoken.

| Direction | Hy-MT2 7B | Gemma 4 31B | sol @low | Gemini Live (last text) |
|---|---|---|---|---|
| en→es | 2206 / 3133 | 2416 / 3715 | 2905 / 6253 | 3458 / 9693 |
| en→pt | 1886 / 2760 | 2423 / 3417 | 3005 / 8652 | 3606 / 4925 |
| en→fr | 1849 / 2681 | 2507 / 4713 | 3180 / 4765 | 2998 / 4932 |
| en→ja | 1910 / 2888 | 2711 / 4147 | 3367 / 5324 | 1768 / 2601 |
| en→km | 2896 / 3937 | 4266 / 5973 | 4020 / 6856 | 1824 / 2260 |
| en→lo | n/a | 3378 / 5707 | 5975 / 7676 | 1778 / 2814 |
| en→ht | n/a | 2550 / 6632 | 3785 / 5836 | 3024 / 4973 |
| es→en | 1585 / 1876 | 2329 / 7473 | 2454 / 3045 | – |
| pt→en | 1472 / 1774 | 2958 / 4927 | 1751 / 3348 | – |

## Translation cost per hour of speech

One listener language, 392 sentences an hour (`../2026-10-translation-cost`),
from this run's mean tokens per sentence at list prices: OpenRouter's listed
rates on 2026-10-22 (Hy-MT2 7B $0.074 / $0.295, Gemma 4 31B $0.20 / $0.40 per
million input / output tokens), and sol at $4.40 / $22 (reasoning billed as
output).

| | Hy-MT2 7B | Gemma 4 31B | sol @low |
|---|---|---|---|
| Out of English (es, pt, fr, ja) | $0.005–0.006 | $0.010 | $1.04–1.24 |
| en→km / en→lo / en→ht | $0.023 / n/a / n/a | $0.014 / $0.015 / $0.011 | $1.69 / $2.90 / $1.06 |
| es→en / pt→en | $0.005 / $0.005 | $0.011 / $0.010 | $0.80 / $0.70 |

Recognition (Azure speech-to-text) and voices are not included.

## Limits

- One clip per language (20 sentences), one grading round.
- Gemini Live was run once per target; it is a preview model.
- The Azure-route latencies leave out the voice; Gemini Live's include it.
- Latencies of hosted models are the providers' at the time of the run.

## Files

`stt_azure.py`, `mt.py`, `live_translate.mjs`, `segment.py`, `round.py`
(jobs and table), `grade.py` (copy of the held-out round's grader), and
`results.json` (scores, recognition, latency, cost, providers). Transcripts,
translations and grades stay outside the repository.
