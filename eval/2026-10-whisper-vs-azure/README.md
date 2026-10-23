# Whisper against Azure speech-to-text, same clips, one scorer, October 2026

Is Azure's recognition better than the stack's Whisper? Earlier numbers came from
different rounds and different scoring scripts. Here five recognisers (six were
planned) hear the **same** recordings and are scored by **one** script.

## Clips and references

- The unseen clips of `../2026-10-unseen` (PR #44): 20 FLEURS read sentences per
  language (CC BY 4.0) that no tuning round used, several readers per clip, in two
  pause patterns: **reg** (1.0–1.95 s between sentences) and **irr** (0.3–1.2 s,
  irregular). English, Spanish, Portuguese, French and Japanese.
- **Main reference: what the reader actually said** (that folder's `witness.py`: a
  verbatim transcription per recording; seven English recordings stop early or
  misread their text). The written FLEURS text is scored too (`results.json`,
  `text`).

## Systems

| # | System | How |
|---|---|---|
| 1 | **Whisper, per sentence** | The stack's own engine (`server/engines/whisper.py`): large-v3 at the pinned revision, float16, beam 1, Silero VAD filter, the non-speech gates. One read sentence at a time on the gold boundaries, language given. The recogniser's best case (`whisper_sent.py`, on an A40). |
| 2 | **Whisper in the stack, live** | The open stack on main, streamed at real time (the e2e client of `../tools`). English (both patterns) and Spanish (reg) reuse the unseen round's main runs; the other seven were run here on main. |
| 3 | **Azure real-time** | Continuous recognition, streamed at real time in 100 ms chunks, locale given (`azure_stream.py`). English, Spanish and Portuguese (reg) reuse `../2026-10-es-pt-live-compare`. |
| 4 | **Azure fast transcription, per sentence** | `transcriptions:transcribe` (the call Talk's `/v1/hear` makes), one sentence per request, locale given (`azure_fast.py`). |
| 5 | **MAI-Transcribe-2** (preview) | Fast transcription's enhanced mode, `"model": "MAI-Transcribe-2"`, language given (`mai.py`): per sentence on the gold boundaries, and the **whole clip in one request**. |
| 6 | MAI-Transcribe-2-Streaming (preview) | **Not run.** `mai_stream.py` sets `speech_config.model` with Speech SDK 1.52.0; both of our existing East US resources (Speech, and AI Services) close the connection with "speech.context.model routing is not enabled for this request". The model is served from Sweden Central, Central US, East US 2 and Southeast Asia; trying it needs a resource there. |

Neither MAI model lists Haitian Creole, Lao or Khmer (the model's language table on
learn.microsoft.com), so those clips were not run.

## Scoring (`score.py`)

The same for every system and reference: Unicode NFKC; digits spelled out with
`num2words` ("11th" as an ordinal, so "11th" and "eleventh" match); lower case;
punctuation to spaces. **CER** on characters with spaces removed and **WER** (not
for Japanese), both on the whole clip's text joined. Per sentence, from the
alignment: **dropped** (80% or more of its words deleted) and **missing start**
(two or more of its first three words deleted; Japanese, three of its first five
characters).

## Results: against what was said

CER / WER in %. In brackets, (missing starts, dropped sentences) where any.

| Lang | Pauses | 1 Whisper per sentence | 2 Stack live | 3 Azure real-time | 4 Azure fast per sentence | 5 MAI-2 per sentence | 5 MAI-2 whole clip |
|---|---|---|---|---|---|---|---|
| en | reg | 4.3 / 8.6 | 14.1 / 18.4 (3, 1) | 4.1 / 8.0 | 3.7 / 7.0 | **3.7 / 6.7** | 6.5 / 11.5 |
| en | irr | 4.3 / 8.6 | 21.3 / 24.3 (3, 2) | **3.7** / 8.3 | **3.7** / 7.0 | **3.7 / 6.7** | 8.6 / 13.4 |
| es | reg | 1.7 / 4.3 | 1.7 / 3.9 | 2.4 / 5.6 | 1.7 / 4.1 | 1.7 / 4.1 | **0.5 / 2.4** |
| es | irr | 1.7 / 4.3 | 1.7 / 3.6 | 2.4 / 5.6 | 1.7 / 4.1 | 1.7 / 4.1 | **0.5 / 2.6** |
| pt | reg | 2.3 / 4.5 (1, 0) | 2.4 / 4.5 (1, 0) | **0.9 / 2.8** | 3.1 / 5.8 (1, 0) | 1.6 / 2.8 | 1.4 / 2.8 |
| pt | irr | 2.3 / 4.5 (1, 0) | 2.4 / 4.5 (1, 0) | **1.0** / 3.0 | 3.1 / 5.8 (1, 0) | 1.6 / 2.8 | 1.4 / **2.5** |
| fr | reg | 1.6 / 4.1 | 4.8 / 8.4 (2, 0) | 3.3 / 8.6 | 1.2 / 3.8 | **0.6 / 1.6** | 0.8 / 2.3 |
| fr | irr | 1.6 / 4.1 | 5.9 / 9.5 (2, 0) | 2.9 / 7.7 (1, 0) | 1.2 / 3.8 | **0.6 / 1.6** | 0.7 / 2.0 |
| ja | reg | 4.7 | 8.6 (3, 0) | 6.9 | 4.7 | **2.5** | 2.9 |
| ja | irr | 4.7 | 11.3 (4, 1) | 8.0 (1, 0) | 4.7 | **2.5** | 2.6 |

Systems 1, 4 and 5 (per sentence) read the same recordings in both patterns, so
their two rows are one run.

## Latency

| | p50 | p90 |
|---|---|---|
| 3 Azure real-time: end of speech → final result | 0.71 s | 1.17 s |
| 4 Azure fast, per sentence request (round trip) | 0.75 s | 0.98 s |
| 5 MAI-Transcribe-2, per sentence request (round trip) | 0.92 s | 2.31 s |
| 5 MAI-Transcribe-2, whole 2.5-minute clip in one request | 1.74 s | 2.44 s |
| 1 Whisper, per sentence (GPU decode on an A40, no network) | 0.47 s | 1.70 s |

Round trips are from one client to East US with four requests at once.

## Findings

1. **Whisper itself is level with Azure.** Fed whole sentences, Whisper large-v3 and
   Azure's fast transcription are within 0.8 CER points of each other in every
   language: English 4.3 vs 3.7, Spanish 1.7 vs 1.7, Portuguese 2.3 vs 3.1,
   French 1.6 vs 1.2, Japanese 4.7 vs 4.7. Azure real-time (streaming) is a little
   worse than both on Spanish, French and Japanese (2.4, 3.3, 6.9) and the best on
   Portuguese (0.9).
2. **The live stack's English loss is cutting, not Whisper.** Live, English is
   14.1% CER (regular pauses) and 21.3% (irregular) against Whisper's own 4.3% on
   the same recordings. Splitting the word errors by sentence (`breakdown.py`):

   | English, word errors | Whisper per sentence | Stack live |
   |---|---|---|
   | reg: the 1 sentence the stack dropped | 1 | 18 |
   | reg: the 3 sentences whose start it lost | 5 | 23 |
   | reg: the other 16 sentences | 23 | 25 |
   | irr: the 2 dropped | 3 | 35 |
   | irr: the 3 with a lost start | 8 | 35 |
   | irr: the other 15 | 18 | 18 |

   On the sentences the stack heard whole, it makes the same errors as Whisper
   alone. Nearly all of the extra error is whole sentences or sentence starts
   missing: quiet readers who start right after loud ones, before the stack's
   quiet boost has caught up, and with irregular pauses, pieces run together.
   French and Japanese show the same pattern on a smaller scale (2–4 lost starts
   live, none per sentence). Spanish and Portuguese live match Whisper per sentence.
3. **MAI-Transcribe-2 is the most accurate here** on French (0.6%) and Japanese
   (2.5%), about half of Whisper's and Azure fast's errors, and level or better
   elsewhere per sentence. On a whole clip in one request it stays as good for
   Spanish, Portuguese, French and Japanese, but English rises to 6.5–8.6%.
   Caveat: Microsoft reports MAI-Transcribe-2's accuracy **on FLEURS**, the source
   of these clips, so it may have seen FLEURS material. Its scores here could be
   flattering. It has no Haitian Creole, Lao or Khmer.
4. **Numbers matter for scoring.** Before digits were spelled out, every system
   lost 1.8–2.9 CER points in English to "11th" against "eleventh". All figures above
   use the spelled-out form for both sides.

## Limits

- One clip of 20 sentences per language, read speech. The live stack ran once per
  clip.
- The "what was said" references are a model's verbatim transcription.
- Azure's systems were given the language; Talk passes the conversation's two
  languages and lets Azure choose, which can only add errors.
- MAI-Transcribe-2 is a public preview.

## Files

- `whisper_sent.py`, `azure_stream.py`, `azure_fast.py`, `mai.py`, `mai_stream.py`: the systems.
- `score.py`: the scorer (`pip install num2words==0.5.14`); `breakdown.py`: the English split.
- `results.json`: every score (both references), dropped and missing-start sentence
  numbers, latency. Transcripts are not committed.
