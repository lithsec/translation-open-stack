# Khmer at the table: where the time and the accuracy go (2026-11-27)

A Table talk test between English and Khmer (one phone, Automatic, Standard) on 2026-11-26 felt slow. The Khmer
speaker said the translation was off. The app reported its first translated audio after 12.8 s on one side and 7.4 s on
the other.

This eval asks where the time goes and where the accuracy goes. It checks each part of the chain on its own: the
translator on correct text, the recogniser, and the voice. It builds no new app behaviour.

**What the route does today** (lithos-server `routes/plan.ts` `autoPlan`, run with production's settings):
- **Khmer speaker:** Omnilingual 7B hears them, and gpt-6-sol on our Foundry translates into English.
- **English speaker:** Azure hears them, and gpt-6-sol translates into Khmer, whole sentences.
- **Voice:** Azure's `en-US-AvaMultilingualNeural` speaks Khmer at Standard. Azure's own Khmer voice, Sreymom, is used
  only at Private.
- **At the table** (the app's `HybridHearHub`):
  - Azure streams English only. Khmer isn't among its languages because it is an "exception" language on this route.
  - Every utterance also goes to Omnilingual, which is asked to choose between Khmer and English.
  - An Azure final waits up to 2.5 s after the utterance ends for Omnilingual's ruling.
  - Amazon Transcribe, which hears a Khmer speaker's own direction first since 2026-11-25, isn't used here: it can't
    tell the two languages apart.
- **When Omnilingual is slow:** if a request has been out more than 6 s (a cold start takes about 45 s), Azure's
  finals pass without waiting. For a Khmer speaker, that is Azure's English reading of Khmer speech.

The test session's meters agree: 17 Omnilingual 7B requests (30.4 s of GPU time, about 1.8 s each), 20 sol
translations, no Transcribe, no Gemma.

## Data and method

- **Sentences:** the 25 Khmer FLEURS test sentences (CC BY 4.0) of
  [`../2026-11-chirp3-lao-khmer`](../2026-11-chirp3-lao-khmer/), with the same sentences' English. FLEURS shares sentence
  ids across languages. `code/fetch.py` gets them. One sentence is left out of the published data and every table
  (its topic trips this repository's private-term rules), so the tables are on 24.
- **Hearing:**
  - Amazon Transcribe km-KH: that eval's stored stream (`runs/tr_km.json` there), not run again.
  - Azure standard streaming (`code/azure_stream.mts`), one sentence a stream at real time plus 5 s of silence. App
    settings: Time segmentation, 300 ms sentence silence, 20 s forced cut. Two setups:
    - pinned to `km-KH`
    - continuous language ID between `en-US` and `km-KH`, on the Khmer recordings and on English recordings of the
      same sentences
  - Omnilingual 7B was not run again: no GPU. Its numbers are cited below.
- **Translators** (`code/translate.ts`): production's prompt (`standard.ts` `speechPrompt`, bundled in), with the
  previous two sentences as context.
  - **sol:** gpt-6-sol-us on Foundry, `reasoning_effort` low.
  - **Flash:** gemini-3.5-flash, thinking medium. This is what Listen uses into Khmer at Standard. Never at Private.
  - **Gemma:** Gemma 4 31B on OpenRouter, production's zero-retention body.
  - **Azure Translator.**
  - Three requests at once per translator.
- **Grading** (`code/grade.py`):
  - gemini-flash-latest, blind side by side, four candidates per sentence, 0–3 plus a critical-error flag, two
    rounds with different shuffles.
  - Quality is a % of the maximum; critical errors are per round.
  - Grades move about 5 points between rounds and judges, and 24 sentences is a small set. Compare within a table.
- **Voice** (`code/voice.ts`): production's SSML (`testroutes.ts` `azureSsml`) for five of sol's Khmer sentences, with
  Ava and with Sreymom. Each clip was then heard by Azure's km-KH recogniser as an objective check of whether it is
  Khmer. The wavs are in `results/voice/`, not committed: they are generated locally by `voice.ts`.

## 1. The translator is not the problem on correct text

| Direction, on FLEURS text | sol | Flash | Gemma 4 | Azure Translator |
|---|---|---|---|---|
| English → Khmer | 96.5 (0) | **100.0** (0) | 91.7 (0) | 64.6 (3.5) |
| Khmer → English | 94.4 (0) | **96.5** (0) | 84.7 (1) | 54.9 (4) |

Critical errors per round are in brackets.

Translation time, p50 / p90 per sentence:

| Translator | English → Khmer | Khmer → English |
|---|---|---|
| sol | **4.1 / 5.0 s** | 3.3 / 4.9 s |
| Flash (thinking medium) | 13.1 / 14.7 s | 12.2 / 15.3 s |
| Gemma 4 | 4.7 / 6.6 s | 2.7 / 4.8 s |
| Azure Translator | 0.4 s | 0.4 s |

- On what was actually said, sol and Flash are both in the 90s each way. So what the English speaker said reached the
  Khmer speaker well translated, provided Azure heard the English right.
  - Azure on these English recordings: 5.6% of characters wrong.
- Flash is no better than sol by more than the judge's noise, and is about three times slower at this thinking level.
- Azure Translator is fast but far behind, with critical errors.
- **sol is slow on Khmer:** 3–4 s a sentence. gpt-6-sol's p50 across pairs was 1.1 s in the Talk host comparison
  (`foundry-effort.ts`). Khmer is token-heavy, and Khmer pairs keep `low` effort.

## 2. Hearing is where Khmer → English loses

Khmer → English, by what the translator was given:

| Translator given | Characters wrong | sol | Flash | Gemma 4 | Azure Translator |
|---|---|---|---|---|---|
| FLEURS text (perfect hearing) | 0 | 94.4 | 96.5 | 84.7 | 54.9 |
| Amazon Transcribe km-KH | 18.2% | 79.9 (1) | 81.2 (2) | 64.6 (2.5) | 34.7 (5) |
| Azure streaming, pinned km-KH | 19.9% | 69.4 (2) | 73.6 (2) | 43.1 (6.5) | 29.2 (6) |

- Mishearing costs sol 15 points on Transcribe's text and 25 on Azure's.
- **Omnilingual 7B** (not run here), on the same kind of sentences:
  - 12.6% of characters wrong one sentence at a time ([`docs/dev/route-findings-2026-10.md`](../../docs/dev/route-findings-2026-10.md) §10).
  - Live with the stack's turn cutting, on a 20-sentence clip: 32% wrong and first audio about 15 s after the speech
    started ([`../2026-10-lao-khmer-7b`](../2026-10-lao-khmer-7b/)).
  - sol on the 7B's live transcripts scored 75.8–77.5 ([`../2026-10-lao-khmer-cloud-and-data`](../2026-10-lao-khmer-cloud-and-data/)).
  - So hearing every Khmer sentence well enough is the cap, whichever recogniser.
- **What the misheard sentences look like** (sol on Transcribe's text):
  - "the photographer later took the place of an elderly woman he had just photographed" for "took the place of an aged
    lady as she needed the lavatory"
  - "showed off his ping-pong skills" for "presented the chhappan bhog bhajan"
  - "is measured in kilometers on the far side" for "100 km thick on the far side"
  - Each reads fluently and is wrong, which matches what the Khmer speaker reported.

**How long hearing takes**, from the end of the speech to the final text:

| Recogniser | Time to final text |
|---|---|
| Azure streaming | **0.44 s p50 / 0.68 s p90** after the end of each final's audio |
| Transcribe | 0.73 s p50 ([`../2026-11-chirp3-lao-khmer`](../2026-11-chirp3-lao-khmer/)) |
| Omnilingual at the table | A ruling about 1–2 s after the utterance ends, the words a little later, up to the app's 2.5 s wait. Plus about 45 s when the GPU is cold |

## 3. Could Azure tell English from Khmer at the table?

Azure's language ID lists km-KH, per Microsoft Learn's language-support table (language identification), checked
2026-11-27. With `en-US` and `km-KH` in continuous language ID:

| Recordings | Segments labelled right | Characters labelled right | Sentences all right | Characters wrong |
|---|---|---|---|---|
| English (24) | 35 / 35 | 100% | 24 / 24 | 5.6% |
| Khmer (24) | 49 / 57 | 94.9% | 17 / 24 | 23.2% (pinned: 19.9%) |

Every English segment came back English. Khmer was labelled English in 8 of 57 segments, mostly a short first
segment of the sentence. Language ID costs Khmer about 3 points of characters against the pinned stream.

**A two-stream design for the table** (not built):
- **How it would work:** Azure streaming with `en-US` + `km-KH` labels each segment within about 0.5 s. Khmer segments
  would then be heard again, or in parallel, by a better Khmer recogniser: Transcribe, 18.2%, or Omnilingual 7B.
- **What it would need:**
  1. A rule for Khmer segments that Azure labels English. Here those are 8 of 57 segments, about 5% of the
     characters, and never the other way round.
  2. Transcribe on a stream that only receives the Khmer-labelled audio, or a per-utterance Transcribe request.
  3. A live test at the table. These are read sentences, one speaker at a time.
- **What it would remove:** the wait for Omnilingual's ruling, and the cold GPU, from every turn.
- **What it would leave:** hearing accuracy roughly where it is (Transcribe 18.2% against the 7B's 12.6% one sentence
  at a time). The Khmer → English cap from section 2 stays.

## 4. The voice: Ava does speak Khmer

| Voice (production SSML) | Audio for 5 sentences | Characters wrong when Azure km-KH hears it back |
|---|---|---|
| en-US-AvaMultilingualNeural, `<lang xml:lang='km-KH'>` | 35.8 s | 13.2% |
| km-KH-SreymomNeural | 41.8 s | **7.9%** |

- Ava speaks every sentence in full: no silence like Azure's as-IN / or-IN case. Azure's Khmer recogniser understands it.
- Ava comes out about 15% faster, and the recogniser makes about 5 more characters of errors in 100 on it than on
  Sreymom, the voice the owner rated best by ear (2026-11-07).
- The wavs are in `results/voice/` (`N_AvaMultilingualNeural.wav`, `N_SreymomNeural.wav`) for listening.

## What it shows

1. **The translator isn't what went wrong.** sol into Khmer scores 96.5 on what was said.
2. **Khmer → English is capped by hearing.** sol drops from 94.4 on correct text to 69–80 on Azure's or Transcribe's
   transcripts, and the October 7B runs scored 76–78. Fluent wrong sentences are what the Khmer speaker heard
   about.
3. **The slowness is in the chain:**
   - **At the table, every Khmer turn waits on Omnilingual:** the ruling, then the words, up to 2.5 s after the
     utterance, on a GPU that can be cold.
   - **sol takes 3–4 s per Khmer sentence.**
   - Azure would give a labelled final in about 0.5 s.
4. **When Omnilingual is slow:** while a request is out more than 6 s, the table passes Azure's English-only reading of
   Khmer speech. That is bound to be badly heard. The test session's meters can't show whether that happened.
5. **Into Khmer at Standard:** Ava speaks it intelligibly, but less clearly than Sreymom.

## Possible changes, each needing the owner's decision

- **Voice:** Sreymom for Khmer at every level in Talk, as managed rooms already do. Azure Khmer STT heard it back
  with 7.9% of characters wrong, against Ava's 13.2%.
- **Table talk Khmer hearing:** build the two-stream design of section 3 behind a test flag, and measure it live at the
  table against today's Omnilingual arbiter. This would be for speed. It doesn't fix accuracy.
- **Khmer accuracy:** no recogniser measured here clears about 80 into English. The open items are the October
  fine-tune data ([`../2026-10-khmer-finetune-public`](../2026-10-khmer-finetune-public/)) and hearing the same audio
  twice and letting the translator see both, which is untested.
- **Not Flash:** it is no better than sol here beyond the judge's noise, and is three times slower at thinking medium.

## Files

- `code/`: `fetch.py`, `azure_stream.mts` (run from a Live Translation checkout for its Speech SDK, with
  `NODE_OPTIONS=--no-experimental-websocket` on Node 26), `translate.ts` and `voice.ts` (bundled with esbuild from a
  lithos-server checkout), `grade.py`, `analyze.py`.
- `runs/`: `set.json` (FLEURS text), `az_km_pin.json`, `az_km_lid.json`, `az_en_lid.json`, `mt.json` (every
  translation with its time), `grades.json`.
- `results/`: `results.json` (every table above), `voice.json`, `heard.tsv` (what Azure heard of each voice clip).

Spend: about $2 (Azure Speech about 25 minutes of audio, about 400 translations, 200 grading calls, 10 voice clips).
