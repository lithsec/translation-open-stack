# MAI-Transcribe-2-Streaming: why it trailed Azure standard streaming, October 2026

In `../2026-10-mai-streaming-pipelines`, MAI-Transcribe-2-Streaming got more characters wrong than Azure
standard real-time recognition on English (6.1% against 3.6%) and Japanese (11.8% against 6.9%). Batch
MAI-Transcribe-2, sent one sentence at a time, was the most accurate system in `../2026-10-whisper-vs-azure`.
This follow-up separates the possible causes: the stream's own sentence cutting, language
auto-detection, how Japanese is written, and recognition itself.

**Answer:**
- **Japanese: language auto-detection.** Pinning the language takes MAI streaming from 11.8% to **4.5%**,
  better than Azure's 6.9%. Left to detect the language, it writes English words into the Japanese
  ("Prideは", "tall"), whether or not it has to cut sentences itself.
- **English: the streaming model's recognition, plus a little sentence cutting.** Pinning changes nothing
  (6.0%). One sentence per session improves words (WER 11.5% → 9.9%) but hardly characters (5.9%). Batch
  MAI on the same sentences gets 3.7%, so the gap is in the streaming model.
- **Pin the language when using it.** Pinned, MAI streaming beats Azure standard streaming on Japanese,
  French and Spanish, and trails it on English and Portuguese.

## How it was run

- **Clips:** the unseen clips of `../2026-10-unseen`, regular pauses, 20 FLEURS read sentences per language
  (en, es, pt, fr, ja). Scored with `../2026-10-whisper-vs-azure/score.py` (one scorer, numbers spelled out)
  against "what was said".
- **Model:** `mai-transcribe-2-streaming` (public preview), Speech SDK 1.52.0, a Speech resource in East US 2,
  streamed in real time in 100 ms chunks (`stream.py`).
- **New runs (`stream.py`):**
  - **C, pinned:** the whole clip with `speech_config.speech_recognition_language` set to the clip's locale.
  - **C2, control:** the English clip pinned to French. The output follows the pin partly: French words appear
    in 6 finals ("Ouais.", "et neutrons.") and WER rises from 11.5% to 14.4%. So the SDK setting does reach the
    model as a strong hint, not a hard switch.
  - **D, one sentence per session:** each gold sentence (its span plus 0.3 s, with 0.5 s of silence either side)
    streamed as its own session, language not given. The model never has to cut a sentence.
- **Reused runs:**
  - A (Azure standard streaming) and B (MAI streaming, auto-detect): from `../2026-10-mai-streaming-pipelines`.
  - E (batch MAI per sentence) and F (Azure fast transcription per sentence): from `../2026-10-whisper-vs-azure`.
- **The Realtime API** documents a `transcription.language` field too, but needs a Foundry model deployment,
  which we don't have; it wasn't tested.
- **Analysis:** `analyze.py` (scores, the Japanese kana pass, the English breakdown) and `ja_spans.py` (the
  Japanese span judge). Scores only are committed (`results.json`); the runs' text stays local.

## Results

Characters wrong / words wrong (%), against what was said:

| | en | es | pt | fr | ja (chars) |
|---|---|---|---|---|---|
| A Azure standard streaming, whole clip | **3.6** / 7.8 | 2.4 / 5.6 | **0.9** / 2.8 | 3.6 / 9.5 | 6.9 |
| B MAI streaming, whole clip, auto-detect | 6.1 / 11.5 | 2.0 / 4.7 | 2.8 / 4.5 | 2.4 / 5.7 | 11.8 |
| C MAI streaming, whole clip, **language pinned** | 6.0 / 11.2 | 1.9 / 4.5 | 1.7 / 3.2 | **1.2** / 3.6 | **4.5** |
| D MAI streaming, one sentence per session, auto | 5.9 / 9.9 | 1.7 / 4.1 | 2.1 / 3.8 | 0.8 / 1.6 | 12.3 |
| E MAI batch, one sentence at a time | 3.7 / 6.7 | 1.7 / 4.1 | 1.6 / 2.8 | 0.6 / 1.6 | 2.5 |
| F Azure fast transcription, one sentence at a time | 3.7 / 7.0 | 1.7 / 4.1 | 3.1 / 5.8 | 1.2 / 3.8 | 4.7 |

No system dropped a sentence on these clips; F lost the start of one Portuguese sentence.

### Japanese: how much is writing, not recognition?

Converting both sides to their kana reading (`pykakasi`) removes kanji-against-kana and numeral-against-reading
differences:

| | CER | CER on kana readings |
|---|---|---|
| A Azure standard streaming | 6.9 | 3.3 |
| B MAI streaming, auto-detect | 11.8 | 8.4 |
| C MAI streaming, pinned | 4.5 | **2.7** |
| D MAI streaming, one sentence per session | 12.3 | 9.3 |
| E MAI batch per sentence | 2.5 | 1.6 |

The kana pass is generous: words that sound alike also collapse. So a judge (`gemini-pro-latest`) labelled a
sample of each system's differing spans blind, with a little context, as "form" (same words, written
differently) or "error":

| | Spans | Sampled | Form | Error |
|---|---|---|---|---|
| A Azure standard streaming | 27 | 25 | 7 | 18 |
| B MAI streaming, auto-detect | 23 | 23 | 4 | 19 |
| C MAI streaming, pinned | 23 | 23 | 2 | 21 |
| E MAI batch per sentence | 13 | 13 | 1 | 12 |

Writing differences inflate every system's Japanese CER, Azure's slightly more than MAI's. They don't explain
the gap: on kana readings, auto-detect MAI is still the worst (8.4) and pinned MAI the best streaming system
(2.7).

### English: where MAI streaming's extra errors fall

Word errors against what was said, placed by where they fall in the recogniser's finals (`analyze.py`):

| | Finals | Text near a final's edge | Near an edge | In a run of 2+ dropped words | Repeats | Inside a final | Total |
|---|---|---|---|---|---|---|---|
| A Azure standard streaming | 22 | 23% | 15 | 2 | 0 | 12 | 29 |
| B MAI streaming, auto-detect | 34 | 30% | 24 | 3 | 0 | 16 | 43 |
| C MAI streaming, pinned | 34 | 30% | 23 | 3 | 0 | 16 | 42 |

MAI streaming makes 14 more word errors than Azure on this clip: 9 near a final's edge, 4 inside finals and
1 dropped. It also cuts the clip into 34 finals instead of 22, so more of its text sits near an edge. Streaming
one sentence per session (D) removes some of the edge errors (WER 11.5% → 9.9%), but batch MAI on the same
sentences (E, 6.7%) shows the streaming model itself mishears more English.

## What this means

- **How much of each gap comes from where:**

  | | Japanese | English |
  |---|---|---|
  | Language guessing | almost all of it | none |
  | Sentence cutting | none | about 40% of the word-error gap, little of the character gap |
  | Writing differences | inflate everyone, don't explain the gap | – |
  | Recognition | – | the rest |

- **Using MAI streaming:** pin the language. Our Azure streaming hub already knows the conversation's
  languages. For a two-language session (table talk) pinning one language isn't possible, so it would need
  one stream per language or auto-detect with its Japanese weakness.
- **English:** stay on Azure standard streaming for now.

## Limits

- One 20-sentence read clip per language, one run of each variant.
- The model is a preview and may change.
- Microsoft reports MAI's accuracy on FLEURS, which these clips come from.
- The Japanese span judge saw a small sample (13–25 spans per system).
