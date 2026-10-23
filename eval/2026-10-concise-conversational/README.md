# Concise prompt and faster voice on conversational speech, October 2026

The voice-rate round ([`../2026-10-voice-rate-compact`](../2026-10-voice-rate-compact/)) ran on FLEURS read
news, which has almost no filler, so an "interpreter-style" concise prompt had little to drop. This round
repeats it on spontaneous speech full of "I mean", "like", false starts and repairs, to see whether the concise
prompt earns its place there.

**Answer: no. Speaking rate is still the lever; the concise prompt is not.**

- **Whole sentences:** on conversation the concise prompt shortens output by a quarter (26% fewer
  characters out of English, against 6% on read news), but most of what it drops is content, not filler.
  Essential meaning units conveyed fall from 95.8% to 81.9%, listener answers from 94.0 to 81.5, distortion
  doubles (1.9% to 3.8%) and critical errors rise from 3 to 10.
- **Phrase mode (fast mode):** phrases are already short, so the concise prompt only trims 8%. Meaning
  units are unchanged, listener answers drop 4 points out of English, and distortion rises into English
  (2.0% to 5.0%). Not worth it.
- **Speaking rate:** +20% changes no words and cuts the time for all audio to finish by 43% out of English and
  70% into English in phrase mode.

## Audio

| Source | Licence | What |
|---|---|---|
| English | AMI Meeting Corpus (`edinburghcstr/ami`, ihm, test), CC BY 4.0 | 37 consecutive utterances of meeting EN2002a (306–467 s), 3 speakers taking turns; backchannels under 4 words or 1.2 s and overlapping turns left out. 150 s. |
| Spanish | VoxPopuli (`facebook/voxpopuli`, es, test), CC0 1.0 | One continuous European Parliament speech, 10 segments. 148 s. |
| French | VoxPopuli (fr, test), CC0 1.0 | One continuous speech, 14 segments. 160 s. |

Utterance ids and times are in `sources.json`. No audio or transcript text is stored here.

- **Each utterance is levelled** to the same speech RMS (−26 dBFS over its loud frames), and gaps from
  the source are kept, clamped to 0.35–1.2 s. Quiet-speaker effects are therefore not part of this round.
- **The parliament speeches are more formal than the meeting.** They're prepared, partly read, with fewer
  fillers (the verbatim Spanish still has "eh" and "que que"). The English meeting is the real
  conversational test; Spanish and French into English show the effect on semi-prepared speech.
- **No Portuguese source.** I found no spontaneous Portuguese speech under a licence that allows this
  (NURC-SP is CC BY-NC-ND; VoxPopuli has no transcribed Portuguese), so pt→en wasn't run. en→pt was.

## How it was run

- **Source truth:** a verbatim "what was said" transcript per utterance, made with the witness method
  ([`../2026-10-unseen/witness.py`](../2026-10-unseen/witness.py)). For Spanish and French, a Gemini
  English translation of what was said serves as the meaning reference, made once before any system
  output was seen (`grading_conv.py refs`).
- **Recognition:** each clip streamed in real time to Azure standard real-time recognition, recording every
  partial (`../2026-10-simultaneous-phrases/stream_partials.py`). This is the recogniser Talk's fast mode
  uses.
- **Translation:** the phrase round's replay (`run_mt.py`, `../2026-10-simultaneous-phrases/simulate.py`)
  in phrase mode (max 8 words) and whole sentences, with Gemma 4 31B on OpenRouter (zero data retention
  required), current prompt (`cur`) and with the concise instruction of the voice-rate round added (`con`).
- **Voice:** every chunk synthesised by Azure neural voices at the variant's rate (`tts_conv.py`):
  - V0 current +0%
  - V2 current +20%
  - V3 concise +15%
  - V4 concise +0%
- **Grading:** as in the voice-rate round (`grading_conv.py`):
  - meaning units and 1–2 listener questions per utterance fixed from the reference before any output
    was seen (fillers and false starts are not units)
  - blind unit labels (conveyed, missing, distorted)
  - questions answered from the translation alone
  - the 0–100 blind grade with critical errors, all four texts side by side in one round per direction
    (`../2026-10-es-pt-live-compare/grade.py`)
- **Backlog:** one voice, chunks in order, each starting at translation done + time to first audio or when
  the previous chunk ends (`table_conv.py`).

## Results

Columns: essential meaning units conveyed (%); units distorted (% of all, count); listener answers
correct (0–100); 0–100 grade against what was said (critical errors); characters and audio seconds relative
to V0; when each utterance's last chunk starts after the speaker finishes it (p50 / p90); when all audio has
finished after the speaker stops. Rate changes no words, so V0/V2 and V3/V4 share their text measures.

**Out of English (AMI meeting → Spanish, Portuguese, French), phrase mode**

| | Units | Distorted | Questions | Grade | Chars | Audio | Last (p50 / p90) | All done |
|---|---|---|---|---|---|---|---|---|
| V0 current +0% | 93.8 | 5.1% (8) | 94.4 | 75.1 (4) | 1.00 | 1.00 | 39.8 / 71.0 s | 85.0 s |
| V2 current +20% | 93.8 | 5.1% (8) | 94.4 | 75.1 (4) | 1.00 | 0.84 | 21.0 / 38.7 s | 48.5 s |
| V3 concise +15% | 93.8 | 5.1% (8) | 90.3 | 71.2 (5) | 0.92 | 0.84 | 23.7 / 42.2 s | 52.0 s |
| V4 concise +0% | 93.8 | 5.1% (8) | 90.3 | 71.2 (5) | 0.92 | 0.95 | 36.3 / 64.5 s | 77.6 s |

**Out of English, whole sentences**

| | Units | Distorted | Questions | Grade | Chars | Audio | Last (p50 / p90) | All done |
|---|---|---|---|---|---|---|---|---|
| V0 current +0% | 95.8 | 1.9% (3) | 94.0 | 89.2 (3) | 1.00 | 1.00 | 14.3 / 27.1 s | 38.5 s |
| V2 current +20% | 95.8 | 1.9% (3) | 94.0 | 89.2 (3) | 1.00 | 0.83 | 13.0 / 24.2 s | 33.4 s |
| V3 concise +15% | 81.9 | 3.8% (6) | 81.5 | 60.7 (10) | 0.74 | 0.66 | 12.7 / 22.7 s | 26.7 s |
| V4 concise +0% | 81.9 | 3.8% (6) | 81.5 | 60.7 (10) | 0.74 | 0.75 | 12.8 / 22.7 s | 29.9 s |

**Into English (parliament speeches, Spanish and French), phrase mode**

| | Units | Distorted | Questions | Grade | Chars | Audio | Last (p50 / p90) | All done |
|---|---|---|---|---|---|---|---|---|
| V0 current +0% | 89.9 | 2.0% (2) | 92.5 | 63.4 (2) | 1.00 | 1.00 | 22.0 / 37.7 s | 41.6 s |
| V2 current +20% | 89.9 | 2.0% (2) | 92.5 | 63.4 (2) | 1.00 | 0.83 | 7.2 / 11.1 s | 12.7 s |
| V3 concise +15% | 86.2 | 5.0% (5) | 94.9 | 65.7 (2) | 0.99 | 0.87 | 9.0 / 15.2 s | 17.9 s |
| V4 concise +0% | 86.2 | 5.0% (5) | 94.9 | 65.7 (2) | 0.99 | 0.99 | 20.8 / 36.7 s | 40.7 s |

**Into English, whole sentences**

| | Units | Distorted | Questions | Grade | Chars | Audio | Last (p50 / p90) | All done |
|---|---|---|---|---|---|---|---|---|
| V0 current +0% | 90.5 | 8.0% (8) | 89.5 | 84.2 (2) | 1.00 | 1.00 | 14.4 / 23.4 s | 30.4 s |
| V2 current +20% | 90.5 | 8.0% (8) | 89.5 | 84.2 (2) | 1.00 | 0.83 | 11.8 / 22.3 s | 23.7 s |
| V3 concise +15% | 82.0 | 8.0% (8) | 86.8 | 62.4 (2) | 0.88 | 0.79 | 10.3 / 21.7 s | 20.7 s |
| V4 concise +0% | 82.0 | 8.0% (8) | 86.8 | 62.4 (2) | 0.88 | 0.91 | 13.3 / 22.2 s | 25.4 s |

Per direction, `results.json` has every measure. The concise prompt's whole-sentence loss holds in each
direction: the grade falls 24–33 points out of English and 20–24 into English. Into English, whole-sentence
distortion is high for both prompts (16% on Spanish); that comes from the Spanish clip and reference, not the
prompt.

## What it shows

1. **The concise prompt cuts content, not just filler.** Given a whole utterance, Gemma 4 told to be concise
   summarises: "I mean, I guess maybe we could have that as another thing of like…" becomes a tidy
   paraphrase, and smaller points go with the filler. Distortion is never below V0; it's equal or higher in
   every group.
2. **In phrase mode there's little to compress.** An 8-word phrase has little filler to drop, so the output
   is 0–9% shorter and the quality effect is small and mixed.
3. **Rate is free.** +20% changes no words. In phrase mode it brings the end of the audio from 85 s to
   48 s after the meeting excerpt ends (out of English) and from 42 s to 13 s (into English).
4. **Out of English still falls behind** on this 2.5-minute excerpt even at +20%. Spanish, Portuguese and
   French translations of English run longer than the source, and this excerpt is near-continuous talk.
   Real turn-taking leaves gaps, and an adaptive rate (faster when the queue grows) is the next step for
   long turns.

## Recommendation

- **Fast mode (Talk):** current prompt; speaking rate +15–20% if it sounds natural to listeners (samples
  below), +10% to be conservative.
- **Live Translation (monologue):** current prompt, +20%, then an adaptive rate.
- **Concise prompt:** don't use it, on read or conversational speech.

## Limits

- One excerpt per source language, one run, one grading round.
- The English reference for the Spanish and French sources is model-made, and the parliament speeches are
  only semi-spontaneous.
- Gemini is the grader throughout, and also wrote the verbatim transcripts and the meaning units.

## Files

- `ami_rows.py`, `ami_pick.py`: AMI row metadata from the dataset viewer and the filler-rich window.
- `vox_meta.py`, `vox_pick.py`, `vox_audio.py`: VoxPopuli metadata, one continuous speech, and only its rows'
  audio (HTTP range reads of the parquet).
- `build_clip.py`: the levelled clips.
- `run_mt.py`: phrase and sentence translation, current and concise prompts.
- `tts_conv.py`: Azure voices at each rate.
- `grading_conv.py`: references, meaning units, unit labels, listener questions, grade jobs.
- `table_conv.py`: the tables and `results.json`.
- `sources.json`: utterance ids and times.
