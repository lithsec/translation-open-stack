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

## Text translation of Haitian Creole (`text-mt/translate_ht.py`)

Text translators on the read text (`gold`) and on transcripts, graded blind
side by side with Gemini 2.5 Pro against the model-made references (`out/` is
not committed; `text-mt/run*.log` keep each run's grades).

**Kreyòl-MT** (`jhu-clsp/kreyol-mt`, JHU, MIT licence, open weights: mBART-50
fine-tuned on Creole data, 611 M parameters, 2.4 GB in float32) added
2026-10-18, run locally on a Mac's CPU (about 1 s a sentence, batches of 4,
beam 4). Haitian into English only: this eval has no Haitian references for
English into Haitian, so that direction is not run.

| Translator | gold: fully correct / mean | Omnilingual transcript: mean |
|---|---|---|
| Gemini 3.5 Flash | 70% / 88% | 87% |
| Google Translate | 47% / 76% | 37% |
| Azure Translator | 27% / 57% | 32% |
| Kreyòl-MT | 3% / 40% | 26% (32% on a re-grade) |

Kreyòl-MT gets the gist but drifts into King James register ("the LORD", "your
fathers"), drops or translates names (Ti Bèf → "the Cow"), omits clauses and
sometimes loops ("a sickness of fever, and bowels; and he had a sickness…").
Not a fallback for live use. A re-grade (`run9.log`) moved the other systems by
up to 7 points; Kreyòl-MT's gold score did not move.

## Haitian Creole exception, "Option A": Omnilingual's text straight to the Live voice (2026-10-18)

Today the app's exception sends Omnilingual's Haitian transcript to Gemini 3.5
Flash (REST) and a Gemini Live voice reads the English ('read'). Option A skips
Flash: the Haitian text goes to the Live voice in its 'interpret' mode, as
Azure's sentences do. `text-mt/live_voice_ht.mjs` reproduces the app's
`GeminiVoice` (exception-hardening, `src/main/providers/azure.ts`): interpret
instruction with from = Haitian Creole, a fresh pre-opened session per
sentence, 2 in flight, one `clientContent` turn per sentence, output
transcription settled after `turnComplete`; `MODE=read` times today's read step.
`text-mt/flash_timing_ht.mjs` times Flash with the app's prompt, one call at a
time (no hedge). `text-mt/grade_live.py` grades with `translate_ht.py`'s own
prompt and system list, side by side with every translator of that input; it
adds only `<input>__live:<model>` rows. Models: the app's default voice
`gemini-2.5-flash-native-audio-preview-09-2025` and `gemini-3.8-live`.

Omnilingual transcripts (30 sentences). Scores are from the same grading call
for every row (grader in brackets: 2.5 Pro on Vertex = grades.json, 3.1 Pro on
AI Studio); first audio = send to first audio chunk, today's route = Flash +
the voice's read step, summed per sentence (median / p90).

| route | mean [2.5 Pro] | fully correct | critical | mean [3.1 Pro] | fully correct | critical | first audio |
|---|---|---|---|---|---|---|---|
| Flash (default thinking) → read, 3.8-live | 84.4% | 67% | 2 | 93.3% | 87% | 2 | 6.7 s / 10.1 s |
| Flash (default thinking) → read, 2.5 native audio | (same text) | | | | | | 8.2 s / 11.8 s |
| Flash @low → read, 3.8-live | — | | | 85.6% | 67% | 1 | 2.8 s / 5.5 s |
| **Option A, gemini-3.8-live** | 63.3% | 30% | 3 | 70.0% | 43% | 5 | **1.0 s / 1.1 s** |
| **Option A, 2.5 native audio (app default)** | 56.7% | 23% | 4 | 60.0% | 30% | 7 | 1.5 s / 2.7 s |

On the read text (gold) Option A with 3.8-live is as good as Flash (3.1 Pro:
96.7% / 93% / 1 vs Flash 96.7% / 90% / 0; 2.5 Pro: 86.7% / 63% / 0 vs 85.6% /
67% / 1); the 2.5 native-audio voice is weaker (85.6% / 73% / 3 and 70.0% /
43% / 0) and twice said nothing at all (turnComplete with no audio). The gap
is the recognition errors: thinking Flash repairs Omnilingual's misheard names
and words (Halah/Habor, Hepher, "Lord … my lord the king", Marie Laurence),
the Live voices translate them as heard or swap in a familiar Haitian name
(Artibonite, Gros-Morne, Port-au-Prince). Flash's default thinking took 6.2 s
median, 9.6 s p90, 16 of 30 over the app's 6 s hedge; @low 2.3 s / 5.0 s.
Interpret first audio is the voice alone; Option A's turnComplete median is
6.6 s (3.8-live), 7.7 s (2.5): it speaks while generating.
Raw output and timings: `text-mt/out/*live*`, `*.timing.json`,
`live-grade-run-<grader>.json` (per-sentence notes).
