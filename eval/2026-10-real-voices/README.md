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
speech: real voices and accents, not continuous or spontaneous speech or a
large room's echo.

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

## STT bake-off for Japanese, Khmer and Lao (2026-10-19)

Can anything beat Azure Speech at hearing Japanese, Khmer and Lao (English as
a control)? Same clips (`audio/{en,ja,km,lo}.wav`, 30 FLEURS sentences each),
same grading as `score_transcribe_live.py` (`judge.cer(" ".join(reference), hyp)`),
the language named wherever the API takes it. Everything lives in
`out/stt-bakeoff/`: `batch.mjs` (ElevenLabs, AssemblyAI, OpenAI, Gemini batch),
`live.mjs` (OpenAI Realtime, AssemblyAI streaming), `../../elevenlabs_stt.mjs`
(ElevenLabs Realtime; new `EL_VAD_SILENCE`/`EL_OUT` env), `score.py` ->
`summary.json` / `table.txt`, raw output in `raw/<system>/<lang>.json`.

    set -a; . <env with the four keys>; set +a
    node out/stt-bakeoff/batch.mjs <el-scribe-v2|aai-batch|oai:<model>|gem:<model>> en ja km lo
    node out/stt-bakeoff/live.mjs <oai-live|aai-stream> en ja km lo
    EL_VAD_SILENCE=0.5 EL_OUT=out/stt-bakeoff/raw/el-realtime-vad05 node elevenlabs_stt.mjs en ja km lo
    python3 out/stt-bakeoff/score.py

How: batch "whole clip" = the 6-min file in one request; "per sentence" = each
sentence cut with ffmpeg at its marks and sent alone (Gemini prompt: transcribe
verbatim in <language>, its own script, no translation; Pro on thinking "low",
Flash with no thinking). Live = streamed at real-time pace in 100 ms chunks.
Latency: live systems, median from each sentence's speech end (found from the
audio) to the first final covering it; per-sentence batch, median request
round trip (the wait if each sentence were sent the moment it ended).

CER (lower is better); **bold** = beats Azure. Latency in brackets.

| System | Mode | en | ja | km | lo |
|---|---|---|---|---|---|
| Azure Speech (baseline) | live | 6.4 | 10.2 | 13.3 | 17.9 |
| gemini-3.5-transcribe-live (baseline) | live | 14.2 | **7.3** | **10.8** | 30.2 |
| Omnilingual ASR, open stack (baseline) | live | 27.4 | 35.1 | 30.0 | 24.0 |
| ElevenLabs Scribe v2 Realtime, VAD 1.5 s (default) | live | 6.9 (10.3 s) | **9.9** (2.1 s) | 52.0 | 21.8 |
| ElevenLabs Scribe v2 Realtime, VAD 0.5 s | live | **4.5** (0.9 s) | 13.1 (0.9 s) | 31.0 (1.4 s) | 25.2 (5.6 s) |
| OpenAI gpt-live-transcribe (Realtime) | live | 6.8 (1.0 s) | **9.0** (1.0 s) | 31.2 (1.0 s) | 95.9 (Thai) |
| AssemblyAI Universal-3.6 Pro Streaming | live | 12.1 (0.6 s) | 18.9 (1.4 s) | not offered | not offered |
| ElevenLabs Scribe v2 | batch, whole clip | **4.1** | **6.7** | **9.1** | 95.3 (Thai) |
| AssemblyAI U-3.5 Pro (U-2 for km/lo) | batch, whole clip | 9.0 | 11.5 | 97.9 (Thai) | 98.9 (Thai) |
| OpenAI gpt-transcribe | batch, per sentence | **3.8** (3.2 s) | **6.0** (3.4 s) | 14.4 (3.8 s) | 36.8 |
| OpenAI gpt-4o-transcribe | batch, per sentence | 6.8 (3.4 s) | **5.4** (4.3 s) | 28.7 | 19.0 |
| OpenAI gpt-4o-mini-transcribe | batch, per sentence | **3.5** (3.0 s) | **6.7** (3.2 s) | 34.3 | 97.7 (Thai) |
| Gemini 3.1 Pro preview | batch, per sentence | **4.7** (27 s) | **5.8** (24 s) | **12.2**¹ (32 s) | **8.5** (28 s) |
| Gemini 3.8 Flash | batch, per sentence | **3.8** (8.6 s) | **5.9** (9.3 s) | **11.7**¹ (9.8 s) | **16.9**¹ (9.5 s) |

¹ Sentences that never came back count as deletions: Pro km #3 (four 180 s
timeouts), Flash km #0 and lo #6, #28 (`promptFeedback.blockReason: OTHER`,
three tries each). On the sentences answered: Pro km 9.7, Flash km 8.2, Flash
lo 10.4.

Live latency detail (median / p90 ms, segment = final minus the vendor's own
speech end; sentence = as above): Azure ~800 segment, 1.0-3.9 s sentence;
ElevenLabs Realtime VAD 0.5 s 820-1140 segment, 0.9-1.4 s sentence (Lao 5.6 s; p90 8-12 s where
turns still merge); default VAD 1.5 s is longer than the clips' 0.8 s pauses,
so sentences merge into long turns (17 turns for 30 English sentences, 10 s
median sentence wait); OpenAI gpt-live-transcribe ~1.0-1.1 s after the commit
(its server refuses turn detection, so a client VAD is simulated: commit
0.5 s after each speech end, i.e. ~0.5 s after the commit); AssemblyAI 65-125
segment, 0.6-1.4 s sentence (p90 10-13 s, merged turns).

What it shows:

- **Lao: Gemini 3.1 Pro per sentence, 8.5% CER, half of Azure's 17.9%** and
  the best number for any language here. Proper Lao script throughout. But it
  is batch and slow today: median 27 s per 10 s sentence, five sentences 54 s
  to 12 min. Flash: 16.9% (10.4% on the 28 it answered) at ~9 s. Nothing live
  beats Azure on Lao: ElevenLabs Realtime 21.8%, OpenAI writes Thai.
- **Thai script for Lao** is the common failure, and it is not the grader:
  ElevenLabs Scribe v2 **batch** (told `lao`, reports `lao` at probability 1)
  writes 93% Thai letters, while its **Realtime** model writes Lao. AssemblyAI
  (Universal-2), gpt-4o-mini-transcribe and gpt-live-transcribe also write
  Thai; gpt-transcribe mixes (23% Thai) and returns 291 U+FFFD characters
  (broken UTF-8) in Lao. AssemblyAI Universal-2 on Khmer writes Thai/Latin too.
  Only Gemini and gpt-4o-transcribe stay in Lao script.
- **Khmer: ElevenLabs Scribe v2 batch 9.1%** (whole clip), Gemini Flash 11.7%
  (8.2% answered), Gemini Pro 12.2% (9.7% answered), vs Azure 13.3% and
  transcribe-live 10.8%. Nothing *live* beats transcribe-live on Khmer:
  ElevenLabs Realtime drops text mid-turn (2316 of 3973 reference letters at
  VAD 1.5 s; 31% at 0.5 s), OpenAI Realtime 31%.
- **Japanese**: every batch system bar AssemblyAI beats Azure (5.4-6.7%:
  gpt-4o-transcribe best). Live: gemini-3.5-transcribe-live 7.3% stays best;
  OpenAI gpt-live-transcribe 9.0% at ~1 s and ElevenLabs Realtime 9.9% edge
  Azure (10.2%).
- **English (control)**: batch 3.5-4.7% across OpenAI, ElevenLabs, Gemini.
  Live: ElevenLabs Realtime with 0.5 s VAD 4.5% at 0.9 s beats Azure (6.4%).
- Grading artefacts (all systems pay them; eyeballed): the references keep
  Latin names in Japanese/Khmer/Lao text ("Angel (2006)", "Arnold
  Schwarzenegger", "Taipei IT Month"), which good transcripts write in native
  script (エンジェル, អាណុល ស្វាតសេនេហ្គា) and lose letters for; Japanese
  numerals as kanji (ElevenLabs batch: 十五メートル, 二千十一年; OpenAI live 十五)
  against the reference's digits; English numbers as words (OpenAI live "two
  thousand six"); Khmer digits ១៥ vs the reference's 15 (Gemini, gpt-transcribe;
  NFKC does not fold them, ~20-30 letters, under 1 point) and Khmer numbers as
  words (Gemini Pro ដប់ប្រាំ = 15). None of these move a ranking; the
  Thai-script outputs are real misses.
- Officially listed: Azure all four; ElevenLabs all four (docs: Japanese
  "excellent", Khmer and Lao "moderate", 25-50% WER); OpenAI takes `ja`/`en`
  codes but refuses `km`/`lo` on every model (the prompt names the language);
  AssemblyAI batch Universal-3.5 Pro has ja not km/lo (Universal-2 has km, lo),
  streaming (3.6 Pro) lists ja, not km/lo; Gemini has no ASR-specific list.
- Cost of the whole bake-off: about $2-3 at list prices (13 passes of 22 min
  incl. retries).

Per language: **Lao** - live stays Azure; Gemini 3.1 Pro per sentence (8.5%)
is the accuracy winner for a delayed/second-pass caption, Flash with a retry
fallback if speed matters. **Khmer** - live stays gemini-3.5-transcribe-live
(`km-KH`, 10.8%); ElevenLabs Scribe v2 batch (9.1%) for batch. **Japanese** -
live stays gemini-3.5-transcribe-live (7.3%), OpenAI gpt-live-transcribe the
next live option (9.0%); batch gpt-4o-transcribe or Gemini (5.4-5.9%).
**English** - ElevenLabs Scribe v2 Realtime at 0.5 s VAD (4.5%, 0.9 s) is the
first live system to beat Azure here.

## Audio degradation (2026-10-19)

How much does audio quality cost speech-to-text? The same clips
(`audio/{en,ja,km,lo,ht}.wav`, 30 read sentences each) degraded on the Mac
with ffmpeg/sox/numpy and streamed at real time (100 ms chunks) to **Azure
Speech** (real time, eastus; en ja km lo) and **Omnilingual ASR** (omni-stt on
Cloud Run; en km lo ht). Graded as the bake-off (`judge.cer(" ".join(reference), hyp)`).
Everything is in `out/stt-degrade/`: `make_conditions.py` (+ `cvsd.c`) builds
the audio (not committed; rebuild it), `azure_run.py` / `omni_run.mjs` run it
(max 3 at once), `score.py` -> `table.md` / `summary.json`, raw output in
`raw/<recogniser>/<condition>/<lang>.json`, IR numbers in `conditions.json`.

    .venv/bin/python out/stt-degrade/make_conditions.py      # RNNOISE_MODEL=<std.rnnn> for the RNNoise row
    AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus .venv/bin/python out/stt-degrade/azure_run.py
    OMNI_URL=... OMNI_TOKEN=... node out/stt-degrade/omni_run.mjs
    .venv/bin/python out/stt-degrade/score.py

Conditions:

- **Reverb**: synthetic hall impulse response, direct sound + 14 early
  reflections (7-90 ms) + exponentially decaying noise tail from 25 ms in three
  bands (RT60 1.6 s below 500 Hz, 1.4 s mid, 0.9 s above 4 kHz); measured
  broadband RT60 1.50 s (T20) / 1.54 s (T30); direct-to-reverberant ratio 0 dB
  (a room mic a few metres from the speaker).
- **Noise**: half HVAC (pink + brown noise) and half babble (the other five
  clips of en/ja/km/lo/ht/fr summed, level-matched, randomly rotated: the same
  FLEURS sentences in other languages); SNR against the speech RMS inside the
  sentence marks. **Room mic** = reverb + noise 10 dB (the noise also through
  the room IR).
- **Bluetooth HFP narrowband**: 300-3400 Hz band-pass, 8 kHz, the Bluetooth
  spec's CVSD coder at 64 kbit/s (`cvsd.c`). **Wideband**: 50-7000 Hz, mSBC
  (ffmpeg `sbc -msbc 1`, 16 kHz). **Opus**: libopus VoIP at 12/24 kbit/s.
- **Cleanup on the room mic**: high-pass 80 Hz + `loudnorm` (single pass,
  -20 LUFS, an AGC-like live normaliser); `afftdn` (nr 12 dB, noise tracking);
  `arnndn` with RNNoise's original `std.rnnn` model (at 48 kHz).
- Mixes that would clip were scaled to peak 0.98 (gains in `conditions.json`).

CER; in brackets the change from the same-day clean run in points. The clean
run reproduced the earlier baselines (Azure en 6.4 / ja 9.8 / km 13.1 / lo
17.9 vs 6.4 / 10.2 / 13.3 / 17.9; Omnilingual en/km/lo identical), so
run-to-run noise is about half a point.

| condition | azure en | azure ja | azure km | azure lo | omni en | omni km | omni lo | omni ht | Azure mean Δ | Omni mean Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| clean (same-day baseline) | 6.4% | 9.8% | 13.1% | 17.9% | 27.4% | 30.3% | 24.0% | 7.4% |  |  |
| hall reverb, RT60 1.5 s, DRR 0 dB | 37.5% (+31.1) | 26.6% (+16.8) | 32.7% (+19.6) | 30.9% (+13.0) | 75.1% (+47.7) | 49.9% (+19.6) | 40.5% (+16.5) | 21.5% (+14.1) | +20.1 | +24.5 |
| crowd/HVAC noise, SNR 10 dB | 77.3% (+70.9) | 25.5% (+15.7) | 39.0% (+25.9) | 25.5% (+7.6) | 67.9% (+40.5) | 48.2% (+17.9) | 34.1% (+10.1) | 17.4% (+10.0) | +30.0 | +19.6 |
| crowd/HVAC noise, SNR 5 dB | 77.3% (+70.9) | 27.0% (+17.2) | 56.1% (+43.0) | 39.1% (+21.2) | 66.1% (+38.7) | 63.7% (+33.4) | 52.8% (+28.8) | 34.3% (+26.9) | +38.1 | +31.9 |
| reverb + noise 10 dB (room mic) | 74.1% (+67.7) | 33.5% (+23.7) | 65.3% (+52.2) | 50.6% (+32.7) | 93.6% (+66.2) | 92.5% (+62.2) | 72.9% (+48.9) | 46.0% (+38.6) | +44.1 | +54.0 |
| Bluetooth HFP narrowband (8 kHz CVSD) | 33.1% (+26.7) | 19.1% (+9.3) | 15.7% (+2.6) | 18.9% (+1.0) | 38.8% (+11.4) | 34.4% (+4.1) | 31.7% (+7.7) | 10.2% (+2.8) | +9.9 | +6.5 |
| Bluetooth HFP wideband (16 kHz mSBC) | 9.9% (+3.5) | 10.7% (+0.9) | 12.9% (-0.2) | 18.5% (+0.6) | 26.0% (-1.4) | 29.8% (-0.5) | 24.9% (+0.9) | 6.9% (-0.5) | +1.2 | -0.4 |
| Opus 12 kbit/s | 7.8% (+1.4) | 10.6% (+0.8) | 15.2% (+2.1) | 19.5% (+1.6) | 28.4% (+1.0) | 32.7% (+2.4) | 29.3% (+5.3) | 9.8% (+2.4) | +1.5 | +2.8 |
| Opus 24 kbit/s | 8.2% (+1.8) | 9.2% (-0.6) | 13.1% (+0.0) | 18.3% (+0.4) | 25.4% (-2.0) | 30.1% (-0.2) | 26.6% (+2.6) | 7.8% (+0.4) | +0.4 | +0.2 |
| room mic + HPF 80 Hz + loudnorm | 68.7% (+62.3) | 33.4% (+23.6) | 59.4% (+46.3) | 45.1% (+27.2) | 89.3% (+61.9) | 89.4% (+59.1) | 65.0% (+41.0) | 43.7% (+36.3) | +39.9 | +49.6 |
| room mic + afftdn denoise | 75.5% (+69.1) | 34.5% (+24.7) | 65.2% (+52.1) | 53.4% (+35.5) | 70.8% (+43.4) | 76.1% (+45.8) | 59.5% (+35.5) | 38.7% (+31.3) | +45.4 | +39.0 |
| room mic + RNNoise (arnndn) | 77.7% (+71.3) | 49.3% (+39.5) | 70.7% (+57.6) | 64.6% (+46.7) | 71.1% (+43.7) | 81.1% (+50.8) | 68.0% (+44.0) | 55.4% (+48.0) | +53.8 | +46.6 |

CER; in brackets the change from the same-day clean run, in percentage points. Mean Δ = average of the four languages' changes.

How it fails: mostly **whole sentences vanish**, silently (no error), rather
than words getting garbled. Sentences with no final at all, of 30:
Azure English 5 (reverb), 23 (noise 10 dB), 20 (room mic), 7 (HFP
narrowband); Omnilingual English/Khmer 25-26 of 30 on the room mic, Lao 10.
Azure English is the most fragile case: a check with each noise alone at
10 dB (`diag_noise_split.py`) gave 74.3% CER / 21 sentences dropped with the
steady HVAC noise only and 68.4% / 13 with babble only; a 200 Hz high-pass on
the HVAC version changed nothing (74.4%, 22 dropped). Azure's ja/km/lo models
degrade far more gracefully in the same noise.

What it shows:

- **The room hurts most, the codec least.** Mean change from clean: room mic
  (reverb + 10 dB noise) +44 points Azure / +54 Omnilingual; noise 5 dB
  +38 / +32; noise 10 dB +30 / +20; hall reverb alone +20 / +25. Against
  that, Opus 24 kbit/s +0.4 / +0.2, Opus 12 kbit/s +1.5 / +2.8, Bluetooth
  wideband (mSBC) +1.2 / -0.4. Bluetooth **narrowband** (CVSD, 8 kHz) is the
  one codec that matters: +9.9 / +6.5 on average, +26.7 for English on Azure
  (sentence drops), only +1 to +4 for Khmer, Lao and Haitian.
- **Cleanup does not rescue a room mic.** High-pass + loudness normalisation
  helps a little and hurts nothing (Azure +44 -> +40, Omnilingual +54 -> +50):
  gain/AGC is safe. **Denoisers split by recogniser**: for Azure they hurt
  (afftdn +45, RNNoise +54 vs +44 untreated; RNNoise costs Japanese 16 more
  points); for Omnilingual they help (afftdn +39, RNNoise +47 vs +54), mainly
  by giving its segmenter back the pauses so sentences stop vanishing
  (English 25 -> 9 dropped with afftdn). Even the best treated room mic is
  33-76% CER, i.e. not usable for live translation.
- **A hall's PA**: take the **sound-board / aux feed** (or a lavalier/lectern
  mic close to the mouth). A room mic in a 1.5 s hall with an audience is
  the difference between 6-18% CER and 34-74% (Azure) - a usable feed turned
  into an unusable one, and no ffmpeg cleanup closes the gap. If a board feed
  is impossible, the mic has to be close (high direct-to-reverberant ratio);
  don't add a denoiser in front of Azure, and test one before using it in
  front of Omnilingual. Opus at 24 kbit/s (or even 12) to the relay costs
  nothing measurable.
- **AirPods HFP in Lithos Talk** (`.allowBluetoothHFP`, no
  high-quality-recording option): a wideband (16 kHz mSBC-class) HFP link
  costs about 1 point - no reason to change for accuracy. A link that falls
  back to **narrowband** (8 kHz CVSD: older or third-party headsets, some car
  kits, possibly a congested radio link) costs ~10 points and can drop English
  sentences outright on Azure. Worth logging the input sample rate in the app
  (16 kHz vs 8 kHz) and testing the high-quality AirPods recording mode when
  available. The headset's close mic is worth far more than the codec costs:
  compared with a phone lying in a reverberant room, it is the room that hurts.
  Apple's voice processing (`.voiceChat`) is itself a denoiser; given the
  denoiser result for Azure, an A/B of voice processing on vs off
  (with gain/normalisation instead) on the AirPods mic is worth doing.
- Caveats: one synthetic IR and one noise mix (seeded), read speech, a single
  run per cell; the noise conditions are severe by design (10 dB SNR of mixed
  HVAC and babble). Absolute numbers will differ in a real hall, the ranking
  (room >> narrowband > low-bitrate Opus ~ wideband BT) should not.
- Cost: Azure 12 conditions x 22.4 min + 12 min diagnostics = ~281 min of
  real-time STT at $1/h = **~$4.70**; Omnilingual ~95 min on the Cloud Run L4
  service (max 1 instance) = roughly $1.5-2. Total ~$6-7.
