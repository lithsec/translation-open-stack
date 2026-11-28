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

## What it means for Talk

- **Keep Transcribe first for Khmer.** Nothing measured here beats it by more than the judge's noise at a speed that
  works live.
- **Tha-ASR is the open model to watch.** At beam 5 it matched Transcribe's characters and scored a little higher, and
  its MIT licence would allow self-hosting at Private. To be live, it would need a GPU (it was 11 s per sentence on
  this Mac), and a test on spontaneous speech: FLEURS is read speech, and FLEURS is in its training data.
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

Spend: under $1. That covers about 7 minutes of Gemini 3.5 Transcribe, 120 sol translations and 48 grading calls. The
open models ran locally.
