# Khmer hearing: open Khmer recognisers and Gemini 3.5 Transcribe (2026-11)

**Question.** Is there a Khmer recogniser that hears Khmer better than Amazon Transcribe, which Talk uses first for
Khmer today? The test is the same as [eval/2026-11-khmer-table-talk](https://github.com/lithsec/translation-open-stack/pull/105)
(PR #105): its 24 Khmer FLEURS test sentences, the same character scoring, gpt-6-sol translating into English, and
the Flash judge. Spaces and punctuation are removed before scoring, since Khmer doesn't put spaces between words.

**Answer.** No recogniser is clearly better than Transcribe.
- **Tha-ASR** (Whisper-small, MIT) at beam 5 got as many characters right as Transcribe (18.3% wrong against 18.2%) and
  scored 80.6 against Transcribe's 77.1. That gap is inside the judge's noise of about 5 points. It is also too slow for
  live use on a Mac CPU or GPU: 11 s per sentence.
- **Tha-ASR greedy** (beam 1) runs at 1.6 s per sentence but scores 76.4.
- **Gemini 3.5 Transcribe** tied Transcribe on translation quality (77.1) with more characters wrong (21.2%) and more
  critical errors. It can be used at Standard only, because Private never uses Gemini.
- **PsarAI** and **Qwen3-ASR-Khmer** scored lower.
- The two live (streaming) NeMo models couldn't be tested: their Hugging Face pages refuse anonymous access.
- **Added 2026-11-28: OpenRouter's recognisers and ElevenLabs Scribe** (section below). Base Whisper can't hear Khmer
  at all. ElevenLabs Scribe v2 had fewer characters wrong than Transcribe (15.3% against 18.2%) and scored 81.9 against
  78.5 in one shared grading, again inside the judge's noise. Its live models were much worse on Khmer.

## Results

24 sentences, one sentence per call, as a phone's utterance would be. Each score is out of 100: the mean of the
judge's 0-3 grades divided by 3, over both rounds. "Critical" counts the translations the judge flagged as stating
something false, per round.

All candidates, including the baselines, were graded together in one blind side-by-side, eight answers per sentence.
The baselines are PR #105's stored transcripts and sol translations; they were graded again, not heard or translated
again. In that eval, four translators were graded side by side and Transcribe scored 79.9 and Azure 69.4, so this
grading runs a few points lower.

| Recogniser | Characters wrong | sol into English | Critical / round | s per sentence (p50) | Where it ran | Licence | Streams |
|---|---:|---:|---:|---:|---|---|---|
| FLEURS text (perfect hearing) | 0 | 94.4 | 0 | | | | |
| Tha-ASR, beam 5 | 18.3% | **80.6** | 2 | 11.2 | M2 Pro, MPS | MIT | no (30 s windows) |
| Amazon Transcribe km-KH (baseline) | 18.2% | 77.1 | 2.5 | (final ~0.7 s after the audio) | AWS | service | yes |
| Gemini 3.5 Transcribe | 21.2% | 77.1 | 4.5 | 1.65 (with network) | Google, Standard only | service | live model exists, not tested |
| Tha-ASR, greedy | 19.4% | 76.4 | 2.5 | 1.6 | M2 Pro, MPS | MIT | no |
| PsarAI-ASR-1B, greedy | 22.7% | 75.7 | 4.5 | 0.54 | M2 Pro, MPS | **CC-BY-NC-4.0** | no (CTC; streamable in principle) |
| Qwen3-ASR-0.6B-Khmer | 26.4% | 70.1 | 2 | 4.7 (10.6 on CPU) | M2 Pro, MPS | Apache-2.0 | no |
| Azure km-KH, streaming (baseline) | 19.9% | 64.6 | 3 | (final ~0.45 s after the audio) | Azure | service | yes |

The judge's two rounds agreed within about 4 points for every recogniser (`results/results.json`: `r1`, `r2`).

Notes per recogniser:
- **Tha-ASR** (Thareah/Tha-ASR, Whisper-small, 242M parameters) ran with beam 5 and the language set to km, as its card
  measured it. Its card reports 12.57% characters wrong on the full FLEURS km_kh test set, with spaces and punctuation
  removed. On these 24 sentences it got 18.3%. FLEURS is among its training data; its card says no training sentence
  shares text with a test sentence. It spends about 0.73 s of computing per second of audio at beam 5, so it can't keep
  up live; greedy is 0.11 s per second of audio.
- **Gemini 3.5 Transcribe** was called through the Interactions API (v1beta) with `language_codes: ["km-KH"]`, the
  audio sent inline as WAV. Google's list marks Khmer as "Central Khmer km-KH"; its Vertex page calls it experimental.
  It often adds a Latin spelling in brackets after a transliterated name, which counts against its character score but
  not its translations. Its critical errors (4.5 a round) were the most of any recogniser here, tied with PsarAI. The
  price is about $0.005 a minute.
- **PsarAI-ASR-1B** (MMS-1b-all Khmer adapter) was decoded greedily: its card's Khmer language model isn't published.
  It is the fastest by far (0.04 s of computing per second of audio), but its licence is non-commercial, so it could
  only serve the non-profit side.
- **Qwen3-ASR-0.6B-Khmer** ran through `qwen-asr` 0.0.6 in float32, with the same result on MPS and CPU. It failed
  badly on one sentence with English names and numbers (92% of characters wrong). Its card says it is weaker outside
  its training data, which is read speech.

Not tested:
- **actableai/fastconformer-rnnt-bpe-streaming-khmer** and **manhp/asr-khmer-telephony** (NeMo, streaming): the Hugging
  Face API answers 401 to anonymous requests, so these models are private or gated. Their licences are unknown.
  Nothing was accepted or requested.
- **gemini-3.5-transcribe-live**: only the file model was tested. Its live service would need its own WebSocket test.

## OpenRouter recognisers and ElevenLabs Scribe (added 2026-11-28)

Same 24 sentences and scoring. Each sentence was sent once as a WAV file (16 kHz mono), one request at a time:
OpenRouter's `/api/v1/audio/transcriptions` (`code/or_transcribe.py`, `language=km`, or no language with `NOLANG=1`)
and ElevenLabs' own `POST /v1/speech-to-text` (`code/el_batch.py`, `language_code=km`, three requests at once).

| Recogniser | Characters wrong | Seconds per sentence (p50, with network) | Notes |
|---|---:|---:|---|
| ElevenLabs Scribe v3, direct | **14.6%** | 1.85 | `scribe_v3` |
| ElevenLabs Scribe v2, OpenRouter | 15.3% | 1.78 | `elevenlabs/scribe-v2` |
| ElevenLabs Scribe v2, direct | 17.3% | 1.57 | the same model in a second run: about 2 points of run-to-run spread |
| Amazon Transcribe (PR #105, baseline) | 18.2% | final ~0.7 s after the audio | streaming |
| OpenAI gpt-transcribe, OpenRouter | 23.7% | 1.14 | rejects `language=km` (400 "Language code 'km' is not recognized"); run with no language |
| OpenAI gpt-4o-transcribe, OpenRouter | 30.0% | 1.79 | same 400; run with no language |
| Whisper large-v3-turbo, OpenRouter, `km` | 97.5% | 1.98 | 19 of 24 empty; the rest broken Khmer with stray English words |
| Whisper large-v3, OpenRouter, `km` | 100% | 5.1 | all 24 empty |
| Whisper large-v3, OpenRouter, no language | 98.1% | 1.40 | 21 of 24 in another script: invented English, Thai or Vietnamese sentences |

**Why Whisper failed.** `km` is Whisper's own code for Khmer, and the same files gave Scribe its 15%, so neither the
language code nor the audio is at fault. Base Whisper doesn't hear Khmer: told the language, it returns nothing or
garbled Khmer; left to detect it, it decides on English, Thai or Vietnamese and writes a fluent invented sentence. The
Khmer Whisper models that do work are fine-tunes (Tha-ASR above, 18.3%).

**Translation quality** (sol into English, Flash judge, two blind rounds; `runs/mt_scribe.json`,
`runs/grades_scribe.json`). All eight arms were graded again in one shared set of rounds, so the baselines' numbers
moved a little from the table above: Transcribe 77.1 → 78.5, Tha-ASR 80.6 → 82.6, Gemini 77.1 → 77.8, Azure the same.

| Recogniser | sol score | Round 1 / 2 | Critical errors per round |
|---|---:|---:|---:|
| Perfect text | 94.4 | 94.4 / 94.4 | 0 |
| Tha-ASR, beam 5 | 82.6 | 81.9 / 83.3 | 2 |
| **Scribe v2 (OpenRouter)** | **81.9** | 81.9 / 81.9 | 2.5 |
| **Transcribe** | **78.5** | 77.8 / 79.2 | 1 |
| Gemini 3.5 Transcribe | 77.8 | 77.8 / 77.8 | 4 |
| Scribe v3 (direct) | 75.7 | 75.0 / 76.4 | 2 |
| Azure | 64.6 | 65.3 / 63.9 | 3 |
| gpt-transcribe | 52.8 | 54.2 / 51.4 | 6.5 |

Paired differences (bootstrap over sentences, 95%): Scribe v2 minus Transcribe +3.5 (−5.6 to +12.5); Scribe v3 minus
Transcribe −2.8 (−14.6 to +8.3). Scribe v3's fewer characters wrong did not turn into better English here. None of the
three is clearly better than Transcribe.

**Live hearing** (`code/el_realtime.mjs`): ElevenLabs' docs list Khmer for every Scribe model, its live ones
(`scribe_v2_realtime`, `scribe_v3_live`) included ("90+ languages", the same list), and put Khmer in their "Moderate"
band (25-50% word error). The first 5 sentences, one WebSocket session each, streamed in 100 ms chunks at real-time
pace, `language_code=km`, then 1.5 s of silence and a commit. Two commit settings: VAD (commits at 0.6 s pauses) and
manual (one commit after the audio, like a turn the phone cuts).

| On the same 5 sentences | Characters wrong | First partial after the audio starts (p50) | Final after the audio ends (p50) |
|---|---:|---:|---:|
| Scribe v3 Live, VAD | 31.5% | 2.73 s | 0.15 s |
| Scribe v3 Live, manual | 38.7% | 2.68 s | 0.57 s |
| Scribe v2 Realtime, VAD | 48.4% | 3.10 s | 0.10 s |
| Scribe v2 Realtime, manual | 57.8% | 2.94 s | 0.41 s |
| Scribe v3 / v2 batch (same 5) | 18.2% / 19.1% | – | – |
| Transcribe streaming (stored run of eval/2026-11-chirp3-lao-khmer, as PR #105 used; same 5) | 21.5% | 2.79 s | – |

Both live models return Khmer script and answer quickly, but hear Khmer far worse than the batch models. Talk doesn't
need live captions for Khmer: lithos-server's Khmer path (talktranscribe.ts) already sends each finished turn in one
piece, which is where a batch model fits.

**Privacy** (facts only, 2026-11-28):
- OpenRouter lists `elevenlabs/scribe-v2` on its zero-retention endpoint list (`GET /api/v1/endpoints/zdr`, with
  `"safety_retention": false`). Its ZDR page: "Zero Data Retention (ZDR) means no routine storage of prompts or
  responses after processing", apart from in-flight screening for child sexual abuse material, where flagged content may
  be kept ([docs](https://openrouter.ai/docs/guides/features/zdr)). Its speech-to-text guide: with `provider.zdr: true`
  "the request only routes to Zero Data Retention endpoints"; a test request to Scribe v2 with `zdr: true` succeeded
  ([STT guide](https://openrouter.ai/docs/guides/overview/multimodal/stt)).
- Direct ElevenLabs: retention is off only with `enable_logging=false`, and "Zero retention mode may only be used by
  enterprise customers" (batch: [API reference](https://elevenlabs.io/docs/api-reference/speech-to-text/convert); the
  realtime WebSocket has the same parameter and wording). Scribe v3 is not on OpenRouter.
- OpenRouter's speech-to-text endpoint is file-based; no realtime route through OpenRouter was found. The live models
  are only available direct, under the enterprise-only rule above.

**Cost per hour of audio:** Transcribe streaming $0.60, billed with a 15 s minimum per stream (Talk opens one per
Khmer turn, so a 3 s reply bills as 15 s); Scribe v2 on OpenRouter $0.22 (`0.0000611` per second, billed to the second
in these runs); Whisper large-v3 on OpenRouter $0.03. Scribe v3's direct price was not checked.

## What it means for Talk

- **Keep Transcribe first for Khmer.** Nothing measured here beats it by more than the judge's noise at a speed that
  works live.
- **Tha-ASR is the open model to watch.** At beam 5 it matched Transcribe's characters and scored a little higher, and
  its MIT licence would allow self-hosting at Private. To be live, it would need a GPU (it was 11 s per sentence on
  this Mac), and a test on spontaneous speech: FLEURS is read speech, and FLEURS is in its training data.
- **ElevenLabs Scribe v2 is the one managed alternative worth a live trial** (2026-11-28 section): on par with
  Transcribe on translation (81.9 against 78.5, inside the noise), 15.3% of characters wrong against 18.2%, about 1.8 s
  per finished turn, $0.22/h with no per-stream minimum, and on OpenRouter's zero-retention list. Its live models are
  much worse on Khmer, so it would replace Transcribe only on the finished-turn path. It needs a test on spontaneous
  table speech before any switch.
- **Base Whisper can't be used for Khmer**, through OpenRouter or otherwise; only Khmer fine-tunes of it work.
- **Gemini 3.5 Transcribe adds nothing for Khmer.** It matches Transcribe's translation score with more critical errors,
  and could only run at Standard.
- **Accuracy is still capped near 80 into English** by hearing: perfect text scores 94.4. The open items from PR #105
  remain: fine-tuning on the October Khmer data, and letting the translator see two recognisers' text. Tha-ASR and
  Transcribe make errors in different places, which makes them a natural pair for that untested idea.

## How it was run

- Open models ran on an Apple M2 Pro (16 GB), on PyTorch 2.15 MPS (CPU where noted), one sentence at a time, timed
  after one warm-up call. Each model was downloaded to its own directory, run, and deleted.
- Translation is gpt-6-sol on our Foundry with reasoning "low", the production prompt (lithos-server `speechPrompt`),
  and the previous two sentences as context: PR #105's `translate.ts`, sol only.
- Grading is `gemini-flash-latest` on the eval key, with PR #105's prompt and scale. Every candidate's English appears
  under a shuffled letter, in two rounds with different shuffles, three requests at once.

## Files

- `code/`: `asr_run.py` (the open models), `gemini_transcribe.py`, `cer.py` (PR #105's character scoring),
  `translate.ts` (bundled with esbuild from a lithos-server checkout), `grade.py`, `analyze.py`.
- `runs/`: `set.json` (FLEURS text, CC BY 4.0), each recogniser's transcripts with times (`tha.json`,
  `tha_greedy.json`, `psar.json`, `qwen.json`, `qwen_cpu.json`, `gemini.json`), `mt.json` (sol's translations, the
  baselines' stored ones included), and `grades.json`.
- `results/results.json`: the table above.
- 2026-11-28 additions: `code/or_transcribe.py` (OpenRouter), `code/el_batch.py` and `code/el_realtime.mjs`
  (ElevenLabs batch and realtime), `code/analyze_scribe.py`; `runs/openrouter/*.json`, `runs/elevenlabs/*.json`,
  `runs/mt_scribe.json`, `runs/grades_scribe.json`; `results/results_scribe.json`.

Spend: under $1 for the first part (about 7 minutes of Gemini 3.5 Transcribe, 120 sol translations and 48 grading
calls; the open models ran locally). Under $2 more for the 2026-11-28 additions: OpenRouter hearing (under $0.20),
ElevenLabs batch and realtime (about 15 minutes of audio on Lithos's ElevenLabs plan), 72 sol translations and 48
grading calls.
