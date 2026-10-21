# Continuous speech through Azure + Foundry: Spanish, French, Japanese (October 2026)

The Haitian Creole continuous-speech test (`../2026-10-continuous-ht`) asked
how far behind a continuous speaker the listener falls. This asks the same of
Live Translation's (LT) Azure + Foundry route in three languages it serves
through Azure: Azure speech-to-text, then `gpt-5.6-sol` on Azure AI Foundry
(reasoning low, one Azure final per request), then the Azure neural English
voice. Gemini Live Translate ran on the same clips for comparison.

Date: 2026-10-21. A Mac in the US Northeast on a wired connection; every
endpoint in the US. LT's own provider code at `66ae717`, fed at real-time
pace in 100 ms chunks.

## Audio

Five minutes of broadcast news per language, one clip each:

- **Spanish:** a Spanish TV news programme.
- **French:** a French radio news bulletin.
- **Japanese:** a Japanese radio newscast.

The broadcasts are copyrighted, so only metrics are kept here: the audio,
transcripts, translations, references and run logs are not committed.

Pauses in each clip (10 ms frames more than 25 dB below the clip's 90th
percentile level), five minutes:

| Clip | ≥ 150 ms | ≥ 300 ms | ≥ 600 ms | ≥ 1 s |
|---|---|---|---|---|
| Spanish | 30 | 12 | 2 | 0 |
| French | 14 | 5 | 0 | 0 |
| Japanese | 99 | 78 | 45 | 22 |

## Method

- **Chunks:** each Azure final is one chunk, translated and voiced on its own.
  LT ends a segment on 600 ms of silence, and on 150 ms once it sees the
  speaker running sentences together (Spanish after 26 s, French after 48 s;
  Japanese never switched). Azure cuts a chunk anyway at its maximum segment
  length, which LT sets to 20 s, the smallest maximum Azure accepts.
- **Measures:** *first audio*, speech start to the first voiced translated
  sound; *per-chunk lag*, a chunk's speech start to the first sound of its
  translation as played (voice attributed by the speech service's byte
  offsets, so a backlogged voice is counted correctly); *final lag*, the last
  word to the end of the last translated audio.
- **Quality:** `gemini-3.1-pro-preview` reads the whole English output and
  grades each reference sentence 0–3, shown as % of the maximum, flagging
  critical errors (a wrong name, number, date or negation). References are a
  `gemini-3.1-pro-preview` transcript and translation of each clip, not human
  captions, so they are approximate: the scores rank runs against each other.
  Spanish 32, French 39, Japanese 16 reference sentences.
- **Runs:** one run per setting, with one repeat of the default runs for
  Spanish and French (and of the semantic runs).
- `collect.py` writes `results.json` (numbers only) from the run directory.

## Results

| | Spanish | French | Japanese |
|---|---|---|---|
| Chunk length p50 / p90 / max | 4.2 / 8.5 / 19.9 s | 14.6 / 19.8 / 20.1 s | 6.9 / 13.3 / 15.9 s |
| First audio | 9.0 s | 12.0 s | 9.7 s |
| Per-chunk lag p50 / p90 | 10.0 / 13.2 s | 19.7 / 24.7 s | 12.3 / 18.1 s |
| Final lag | 9.1 s | 25.8 s | 9.6 s |
| Quality (critical) | 89% (2); repeat 90% (2) | 97% (3); repeat 94% (1) | 100% (0) |
| Gemini LT: first audio / final lag | 3.3 / 3.4 s | 4.3 / 5.2 s | 3.1 / 4.1 s |
| Gemini LT: quality (critical) | 86% (2) | 86% (6) | 69% (4) |

- **Chunk length follows the audio, not the language.** The French bulletin
  has almost no pauses (14 of 150 ms or more in five minutes), so its chunks
  run into Azure's maximum segment length: 14.6 s median, and the listener
  ends 25.8 s behind. Spanish and Japanese, with more pauses, stay near 9–10 s.
- **Semantic segmentation** (Azure cuts at the end of a meaning, not at a
  pause) made Spanish and French chunks run to 28–30 s (p90) and the final lag
  24.0 s (Spanish) and 34.8–35.8 s (French). Spanish quality rose to 97%, but
  the delay rules it out for live use; it was not adopted. Japanese barely
  changed.
- **Experimental streaming** of the translation into the voice fell 70 s
  (Spanish) and 127 s (French) behind on nonstop speech.
- **Speculative translation** (translating partial results before the final)
  hit 4 of 55, 7 of 25 and 4 of 33 finals, for about 2–4 times the answered
  translation calls (and 79 refused as "too many requests" per run).
- **Translation tokens**, one target language, per hour of speech, at
  $4.40 / $22 per million input / output tokens: Spanish $1.21 (660 calls an
  hour), French $0.78, Japanese $0.72. Nothing was cached (the prompts are
  under the caching minimum).

## Caveats

- One five-minute clip per language, one genre (broadcast news); single runs
  apart from the repeats above.
- Approximate, model-made references and one judge model.
- The earlier Haitian Creole harness (`pipe.py`, `../2026-10-continuous-ht`)
  attributes voice audio to chunks by arrival, which under-counts per-chunk lag
  when the voice is backlogged: on the Spanish default run it reports 2.1 s
  where the byte-offset attribution here gives 5.3 s (chunk end to its
  audio). Its first-audio and final-lag figures are unaffected.
