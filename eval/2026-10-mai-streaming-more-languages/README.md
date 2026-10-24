# MAI streaming against Azure streaming, seven more languages

Talk's `mai-gemma` test route sends speakers of Vietnamese, Persian, Arabic, Swahili,
Filipino and Ukrainian (and Mandarin) to MAI-Transcribe-2-Streaming on the strength of
the per-sentence batch results in [`../2026-10-language-short-check`](../2026-10-language-short-check/).
Streaming can behave differently from batch (it did for English and Japanese in
[`../2026-10-mai-streaming-pipelines`](../2026-10-mai-streaming-pipelines/)), so this
checks streaming directly.

**Verdict: pinned MAI streaming is more accurate than Azure's standard streaming model in
all seven, by roughly half the character errors, and shows its first words 0.6–1.2 s
sooner. Its final for each sentence comes about 0.2–0.9 s later at the median. Keep MAI
for all seven.**

## How it was run

- **Clips:** 20 FLEURS test recordings per language (CC BY 4.0; ids in `results.json`),
  joined into one clip per language with 1.0–1.95 s pauses (the regular pattern of
  [`../2026-10-unseen`](../2026-10-unseen/)), 229–331 s each. `fetch.py`, `build_clips.py`.
- **Systems,** both pinned to the language's locale and streamed in real time in 100 ms
  chunks with the Speech SDK 1.52.0 (`stream.py`):
  - MAI-Transcribe-2-Streaming (`speech_config.model`), East US 2
  - Azure's standard real-time model, East US
- **Locales:** vi-VN, fa-IR, zh-CN, ar-EG (FLEURS's Arabic is read by Egyptian speakers),
  sw-KE, fil-PH, uk-UA.
- **Scoring:** [`../2026-10-whisper-vs-azure/score.py`](../2026-10-whisper-vs-azure/)'s
  normalisation and alignment against the FLEURS text (`analyze.py`). Mandarin is scored
  by characters only.
- **Latency:** arrival times from the first audio byte. "First words" is the first partial
  of a new segment after the sentence starts. "Final" is the last final overlapping the
  sentence, measured from the end of its FLEURS recording, which carries trailing
  silence; values below zero mean the final came before that silence ended. Compare the
  two systems, not the absolute numbers.

## Results

Characters wrong / words wrong against the FLEURS text; latency in ms (p50, and p90 for
the final).

| Language | MAI streaming | Azure streaming | First words, MAI / Azure | Final after end, MAI / Azure (p50 · p90) | Finals, MAI / Azure |
|---|---|---|---|---|---|
| Vietnamese | **1.7 / 3.3** | 3.4 / 6.0 | **1120** / 1970 | 137 · 689 / −136 · 382 | 22 / 33 |
| Persian | **1.5 / 5.8** | 5.0 / 17.5 | **2084** / 2869 | −691 · −119 / −949 · −216 | 22 / 26 |
| Mandarin | **4.8** | 7.0 | **1352** / 2570 | −454 · 459 / −1339 · −187 | 20 / 24 |
| Arabic | **0.6 / 10.7** | 2.2 / 15.5 | **964** / 1581 | 427 · 763 / 277 · 775 | 20 / 21 |
| Swahili | **5.9 / 19.2** | 11.8 / 19.5 (1 dropped) | **1495** / 2123 | −29 · 770 / −403 · 331 | 43 / 34 |
| Filipino | **2.7 / 7.9** | 5.9 / 12.4 | **1886** / 2479 | −12 · 701 / −628 · 242 | 21 / 34 |
| Ukrainian | **1.4 / 6.1** | 2.6 / 11.4 | **681** / 1473 | 183 · 743 / −431 · 101 | 34 / 22 |

- **Accuracy:** MAI streaming makes about half Azure's character errors in every
  language. Swahili is the largest gap in absolute terms (5.9 % against 11.8 %, and Azure
  dropped one sentence), though MAI's streaming Swahili is well behind its batch result
  (2.3 % in the short check).
- **Arabic words:** words wrong is far above characters wrong for both (10.7 % and 15.5 %
  against 0.6 % and 2.2 %), so most word errors are small differences inside words rather
  than words lost. They weren't inspected further.
- **Speed:** MAI's first words arrive 0.6–1.2 s sooner, which helps live captions and fast
  mode. Its finals arrive later, by about 0.2–0.9 s at the median (Arabic about the
  same), so a whole-sentence translation starts a little later.
- **Fragmentation:** MAI cut Swahili and Ukrainian into more pieces than Azure (43 / 34
  and 34 / 22), and the other five into fewer.
- **No errors** from either service on any run.

## For Talk's `mai-gemma` route

Keep MAI streaming for vi, fa, zh, ar, sw, fil and uk. None of the seven should move back
to Azure.

## Limits

- One clip per language, read speech, one run.
- Microsoft reports MAI's accuracy on FLEURS, the dataset these clips come from, which may
  flatter it.
- Scored against the written FLEURS text only (no "what was said" witness for these
  languages).

## Files

`fetch.py`, `build_clips.py`, `stream.py`, `analyze.py`, `results.json` (FLEURS ids and
scores only).
