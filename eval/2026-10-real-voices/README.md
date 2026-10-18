# Real voices, October 2026

The October Azure round again, with people instead of synthetic voices:

| Language | Audio | Reference (graded against) |
|---|---|---|
| English, Japanese, Khmer, Lao | **FLEURS** (google/fleurs, CC BY 4.0): native speakers reading the same 30 FLoRes sentences, one recording per sentence, alternating men and women | FLoRes's own professional translations: English for the others, each language's text for English into it |
| Haitian Creole | **CMU Haitian Creole speech** (speech.cs.cmu.edu/haitian; 1997–98, read by native speakers): 30 sentences from 30 speakers | **Model-made**: Gemini 2.5 Pro translated the sentences once (`make_refs.py`); CMU has no English |

Acknowledgement: Haitian Creole speech data © 2010 Language Technologies
Institute, Carnegie Mellon University, used under its COPYING terms.

Each recording's silence at both ends is trimmed (relative to its own loudness)
and the sentences joined with 0.8 s pauses, as in the synthetic rounds. Read
speech, not preaching: real voices and accents, not spontaneous speech or a
church room's echo.

Four systems: Azure alone, Azure STT → Gemini, **Gladia STT → Gemini**
(`gladia_stt.mjs`, Solaria-1 live; it lists Haitian Creole, Khmer and Lao),
and Gemini Live. Directions: English into Japanese, Khmer, Lao, Haitian Creole;
Japanese, Khmer, Lao into English; Haitian Creole into English (Gladia → Gemini
and Gemini Live only: Azure can't hear Haitian Creole).

    .venv/bin/python fetch_audio.py      # ~1.6 GB streamed, ~30 s of audio kept per sentence set
    python3 make_refs.py                 # English meaning files (Gemini for Haitian Creole)
    bash run.sh <env file with AZURE_SPEECH_KEY/REGION> <env file with GLADIA_API_KEY>

Scripts other than these come from `../2026-10-azure-stt-gemini`, with the
grader reading each clip's own sentences and references.

## Google's live speech-to-text: gemini-3.5-transcribe-live (2026-10-18)

`transcribe_live.mjs` streams each clip to `models/gemini-3.5-transcribe-live`
(Gemini Live API, AI Studio key; `responseModalities: ['TEXT']`,
`inputAudioTranscription.languageCodes` = one code or `[]` for auto) at
real-time pace in 100 ms chunks; `azure_stt.py` does the same clips with Azure
Speech (eastus). `score_transcribe_live.py` grades both: CER with `judge.cer`
against the verified text each speaker read (as `text-mt/stt_compare.py`), and
latency (see its header). Raw output: `out/stt-transcribe-live/`, `out/stt/`;
summary: `stt_transcribe_live.json`.

    set -a; . <env with GEMINI_API_KEY>; set +a
    node transcribe_live.mjs ht:auto ht:ht-HT fr:fr-FR fr:auto km:km-KH km:auto lo:auto ja:ja-JP en:en-US
    AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus .venv/bin/python azure_stt.py en fr ja km lo
    python3 score_transcribe_live.py

Sentence latency = from the end of each sentence's speech (found from the audio)
to the first final that covers it, median / p90 in ms. "Turns" = finals; 30
sentences each.

| Clip | System, language setting | CER | Turns | Sentence latency med / p90 |
|---|---|---|---|---|
| ht | transcribe-live, auto | 46.7% | 27 | 1318 / 10082 |
| ht | transcribe-live, `ht-HT` (unlisted, accepted) | **6.3%** | 27 | 1364 / 11804 |
| fr | transcribe-live, auto | 2.5% | 20 | 1494 / 14907 |
| fr | transcribe-live, `fr-FR` | **2.2%** | 21 | 1464 / 8801 |
| fr | Azure, fr-FR | 4.9% | 30 | 903 / 5070 |
| km | transcribe-live, auto | 15.4% | 22 | 1926 / 23543 |
| km | transcribe-live, `km-KH` | **10.8%** | 23 | 1828 / 23594 |
| km | Azure, km-KH | 13.3% | 33 | 980 / 10576 |
| lo | transcribe-live, auto (Lao unlisted) | 30.2% | 38 | 1181 / 1656 |
| lo | Azure, lo-LA | **17.9%** | 45 | 3924 / 12712 |
| ja | transcribe-live, `ja-JP` | **7.3%** | 32 | 1551 / 13267 |
| ja | Azure, ja-JP | 10.2% | 34 | 1162 / 11894 |
| en | transcribe-live, `en-US` | 14.2% | 25 | 1530 / 11911 |
| en | Azure, en-US | **6.4%** | 25 | 1276 / 10504 |

Haitian Creole, the same CMU clip, earlier runs (`text-mt/out/stt_cer.json`):
Gemini 2.5 Pro batch per sentence 3.8%, Meta Omnilingual ASR (open stack, live)
5.7%, Gemini 2.5 Flash batch 7.1%, Gladia live 18.9%, Gemini Live Translate's
input transcript 49.4%. Azure can't hear Haitian Creole.

What it shows:

- **Haitian Creole needs the code.** On auto it writes the speakers down as
  French (46.7%, like Live Translate's 49%), with the odd Haitian turn. Given
  `ht-HT`, which is not in its list, it takes it without complaint and writes
  real Haitian orthography: 6.3%, close to Omnilingual's 5.7% and live, though
  still behind Gemini 2.5 Pro batch (3.8%).
- **Lao comes out partly as Thai.** Auto only (no Lao code): 11 of 38 turns are
  in Thai script, 22% of all letters Thai, and Thai letters leak into Lao words;
  5 sentences effectively lost. Azure's lo-LA does better (17.9%).
- **English drops sentences.** Two whole sentences missing (the Trump statement,
  "Dunlap broadsides") and long multi-sentence turns cut short: 88% of the
  reference length, hence 14.2% against Azure's 6.4%.
- French, Japanese, Khmer (with its code): better than Azure. Naming the
  language helps Khmer (15.4% -> 10.8%) and slightly French.
- No translations: every run transcribed in the spoken language (apart from
  Haitian on auto becoming French).
- **Latency.** Each final arrives 350-520 ms (median) after its turn's speech
  ends by the model's own voice-activity offset, versus 770-890 ms for Azure's
  segments. But it often keeps two or three sentences in one turn across the
  0.8 s pauses (20-23 turns for 30 French/Khmer sentences), so earlier
  sentences wait for the turn: per sentence median ~1.2-1.9 s, p90 9-24 s.
  Interim hypotheses stream throughout (430-650 per clip) for live captions.
