# Catching language switches in table talk, and keeping other people's speech off a phone (October 2026)

Three questions, on the same synthetic audio:

1. **Language switches.** Today table talk relies on Azure's continuous language ID. Can small
   detectors catch a switch sooner and cut it in the right place, including fast back-and-forth?
2. **Phone bleed.** In Live Translation's open-mic mode each phone is pinned to its owner's language
   but also hears a nearby talker and the PA. Which gate keeps the owner and drops the rest?
3. **Azure diarization.** Can Azure's built-in speaker labelling, with or without continuous
   language ID, drive table talk (and a per-speaker voice pool) by itself?

## Audio (local only; not committed)

- **Switch clips** (`build_clips.py`): utterances cut from the unseen FLEURS sets
  ([`../2026-10-unseen`](../2026-10-unseen/) and the full-stack round's second set; Haitian Creole
  from CMU), trimmed and brought to one level, English paired with Spanish, French, Portuguese,
  Japanese and Haitian Creole:
  - **S1** "same voice": the two languages alternate with 0.12 s gaps, readers matched on gender.
    FLEURS has no bilingual (or even identified) speakers, so this is still two people.
  - **S2** two speakers alternating, gaps 0 / 0.1 / 0.2 / 0.3 s.
  - **S3** fast back-and-forth: 16 turns of 1-3 s (utterance starts cut at a quiet point), no text
    reference.
  - **ctl** one language only, 8 utterances: false switches.

  7 switches per S1/S2 clip, 15 per S3 clip; ground-truth switch time = the next speech onset.
- **Bleed clips** (`bleed_clips.py`): FLEURS has no speaker ids, so owners come from LibriSpeech
  test-clean (English, 4 speakers, CC BY 4.0) and CMU Haitian speech (3 speakers). Each owner has a
  separate ~12 s enrolment pool and ~50 s of content, mixed with:
  - a nearby talker in another language (FLEURS) at -6 / -12 / -18 dB relative to the owner, half
    in the owner's pauses, half overlapping;
  - PA playback (Azure TTS of FLEURS sentences, the "translated voice", plus FLEURS speech) through
    a synthetic room response (RT60 about 0.6 s) at -10 / -20 dB, nearly continuous;
  - every condition again with the owner 6 dB quieter (farther from the phone).

  70 clips, about 70 minutes.
- **Returning-speaker clips** (`build_dia_clips.py`, CMU Haitian, three speakers): R1 one speaker
  for 2 minutes, R2 two speakers alternating 4 times each, R3 three in rotation.

## Signals and recognisers

- **On a GPU pod** (`features.py`, `bleed_features.py`, `footprint.py`; one A40, Secure Cloud):
  - Silero VAD
  - VoxLingua107 ECAPA (`speechbrain/lang-id-voxlingua107-ecapa`, Apache-2.0) on 0.5 s and 1 s
    windows every 0.25 s, constrained to the pair
  - Whisper small language ID (faster-whisper, MIT) on 1 s and 2 s windows
  - ECAPA speaker embeddings (`speechbrain/spkrec-ecapa-voxceleb`, Apache-2.0)

  pyannote segmentation-3.0 is gated (terms to accept), so it was not used.
- **From the Mac, streamed in real time** (`recognize.py`, `diarize.py`):
  - Azure continuous language ID set up as Talk's table talk (DetectContinuous, 150 ms
    segmentation, 10 s forced cut)
  - Azure standard real-time pinned to each language, with word timings
  - MAI-Transcribe-2-Streaming pinned to each language
  - Azure ConversationTranscriber (real-time diarization), pinned and with continuous language ID

## 1. Language switches

**Methods.** Everything is simulated causally (`analyze.py`): a window's result is usable only after
it ends (+50 ms compute).
- (a)/(b)/(d)/(e) decide language with VoxLingua107 1 s windows when their trigger fires.
- (c) smooths frame scores (mean of 3) with hysteresis (1.0 log-odds), then cuts back to where the
  scores turned, snapped to a pause.
- (b), (c), (d) re-recognise from the cut point using buffered audio; the other pinned stream's
  words from that point stand in for that re-recognition.
- (f) keeps both pinned streams running and uses (c)'s labels to pick between them.
- "Combo" lowers (c)'s hysteresis for 1.5 s after a speaker-change or recogniser-warning trigger.

**Scoring.**
- Delay: true switch → first decision into the new language.
- Cut error: |cut − switch|.
- CER/WER per segment, against FLEURS's written text; S3 has none.
- Wrong-language text: units attributed to a language other than the segment's.

**Coverage.** Recognition text uses the Azure pinned streams. Rows for Azure's own language ID count
28 switches per scenario, because Azure has no Haitian Creole; the others count 35, Haitian Creole
detection included.

| Approach | Delay p50 S1 / S2 / S3 (s) | Missed S1 / S2 / S3 | Cut error p50 (s) | CER / WER S1+S2 | Wrong-language text S1+S2 / S3 | False switches (5 one-language clips) |
|---|---|---|---|---|---|---|
| Today: Azure continuous language ID | 2.62 / 2.49 / 2.15 | 0/28 · 0/28 · 37/60 | 0.88 | 12.4% / 24.9% | 7.4% / 22.8% | 0 |
| Azure diarization + continuous language ID | 2.67 / 2.44 / 2.13 | 0/28 · 0/28 · 30/60 | 0.65 | 11.7% / 21.4% | 5.5% / 29.0% | 0 |
| (a) fixed 2 s check | 2.65 / 2.41 / 2.02 | 0/35 · 0/35 · 36/75 | 2.41 | 25.0% / 52.4% | 25.6% / 58.4% | 0 |
| (b) check 1 s after each pause | 1.29 / 1.33 / 1.23 | 3/35 · 0/35 · 23/75 | 0.44 | 12.5% / 20.1% | 4.2% / 6.0% | 0 |
| (c) frame scores, 0.5 s windows | 0.87 / 0.84 / 0.73 | 0/35 · 2/35 · 8/75 | 0.16 | 10.6% / 21.3% | 5.9% / 7.8% | 22 |
| (c) frame scores, 1 s windows | 1.1 / 1.0 / 0.98 | 0/35 · 2/35 · 9/75 | 0.09 | 8.4% / 15.8% | 2.0% / 2.4% | 2 |
| (c) frame scores, Whisper small 1 s | 1.41 / 1.21 / 1.06 | 7/35 · 7/35 · 26/75 | 0.15 | 8.3% / 14.9% | 2.2% / 2.2% | 18 |
| (d) speaker-change trigger | 1.01 / 0.95 / 0.78 | 3/35 · 1/35 · 9/75 | 0.3 | 8.9% / 17.0% | 3.2% / 11.1% | 23 |
| (e) recogniser warning signs | 2.39 / 2.97 / 1.96 | 22/35 · 18/35 · 66/75 | 2.92 | 30.4% / 67.7% | 34.9% / 47.5% | 1 |
| (f) two pinned recognisers, 1 s frame labels | 1.1 / 1.0 / 0.98 | 0/35 · 2/35 · 9/75 | 0.09 | 8.4% / 15.8% | 2.0% / 2.4% | 2 |
| f + c + d + e | 1.09 / 1.0 / 0.95 | 0/35 · 2/35 · 9/75 | 0.09 | 8.6% / 16.1% | 2.1% / 2.4% | 2 |

**What it shows**

- **Today's continuous language ID** reacts **about 2.5 s** after a switch. It misses **37 of 60**
  fast switches (S3), and 23% of S3 text lands in the wrong language. The 10 s forced cut doesn't help.
  - **Azure diarization with continuous language ID** behaves the same: about 2.5 s, and 30 of 60
    fast switches missed. Running both together works (no errors, per-segment languages), but it
    gives no gain for switching.
- **Frame-level language scores on 1 s windows** catch a switch in **about 1.0 s**. They miss 2 of
  70 normal switches and 9 of 75 fast ones, and cut **within about 0.1 s** of the true point.
  - Wrong-language text falls from 7.4% to **2.0%** (S3: 22.8% → **2.4%**), and WER from 24.9% to
    15.8%.
  - 0.5 s windows react 0.2 s faster but make 22 false switches on single-language clips; 1 s
    windows make 2.
  - Whisper small's language ID is slower and misses more (26/75 fast switches).
- **A fixed 2 s check** reacts as slowly as Azure and garbles the most: no cut-back.
- **Recogniser warning signs alone** react far too rarely.
- **The speaker-change trigger** helps a little as a booster but makes false switches on its own.
  On these clips every utterance is a new reader, so the speaker changes even when the language
  doesn't.
- **(f) vs (c).** In this simulation (f) equals (c) with 1 s windows, because re-recognition is
  stood in by the other pinned stream. In a live system:
  - (c) re-runs recognition on the buffered stretch, so that stretch's text arrives about **delay +
    0.5 s** (Azure fast transcription) later.
  - (f) has it already, at the cost of a second stream.
- **The combination (f + c + d + e)** is level with (f): the triggers shave a few tens of ms.

**MAI streaming, pinned.** Detection doesn't depend on the recogniser. MAI's text could not be
scored per stretch: it gives no word timings, and the arrival-time reconstruction was not reliable
(single-language CER 16-49%, against 1-7% for Azure on the same clips). MAI pinned to one language
also tends to transcribe the other language's speech in its own language rather than garbling it.

## 2. Phone bleed (open-mic Live Translation)

**Methods** (`bleed_analyze.py`):
- (a) level gate: 6-15 dB under the owner's running level.
- (b) owner voice: ECAPA cosine to the owner's enrolment, median of 3 windows.
- (c) a and b.
- (d) VoxLingua107: the phone's language against the rest.
- (e) all three.

**Thresholds** are chosen leave-one-owner-out on the normal-level clips (minimising owner rejected +
bleed accepted), then applied to all clips.

**Scoring.** Words are counted uniformly over each utterance. Owner words include stretches where
the nearby talker overlaps them.

**Hold-back.** A small hold-back matters a lot. Decisions need about 1 s of audio, so a gate that
must decide instantly loses the start of every owner turn. Holding audio back 0.75 s before passing
it on (0.75 s of extra latency) fixes most of that.

| Method | Owner words lost, normal / quiet owner | Bleed words accepted, normal / quiet owner | Owner accepted after (p50, s) | Thresholds chosen |
|---|---|---|---|---|
| **0.75 s hold-back** | | | | |
| (a) level gate | 1.5% / 1.4% | 59.0% / 77.9% | 0.0 | {G: 6} |
| (b) owner voice, 1 s windows, 10 s enrolment | 8.3% / 14.5% | 6.8% / 5.9% | 0.0 | {TAU: 0.2} |
| (b) owner voice, 1.5 s windows, 10 s enrolment | 11.1% / 17.4% | 8.8% / 7.0% | 0.3 | {TAU: 0.3} |
| (b) 1.5 s windows, 5 s enrolment | 12.3% / 18.3% | 8.8% / 8.0% | 0.3 | {TAU: 0.2}, {TAU: 0.3} |
| (b) 1.5 s windows, 3 s enrolment | 11.7% / 17.0% | 9.7% / 9.2% | 0.3 | {TAU: 0.2}, {TAU: 0.3} |
| (c) level + voice, 1 s, 10 s enrolment | 9.1% / 15.2% | 5.5% / 4.9% | 0.0 | {G: 6, TAU: 0.2} |
| (c) level + voice, 1.5 s, 5 s enrolment | 9.0% / 13.8% | 8.6% / 8.0% | 0.2 | {G: 6, TAU: 0.2} |
| (c) level + voice, 1.5 s, 3 s enrolment | 10.0% / 15.1% | 7.1% / 7.9% | 0.2 | {G: 6, TAU: 0.2} |
| (d) language mismatch | 17.3% / 24.1% | 9.3% / 7.1% | 0.0 | {DELTA: -1}, {DELTA: 0} |
| (e) all, 1 s, 10 s enrolment | 15.3% / 22.7% | 2.2% / 1.3% | 0.05 | {DELTA: -2, G: 6, TAU: 0.2} |
| (e) all, 1.5 s, 3 s enrolment | 16.7% / 23.1% | 1.6% / 1.5% | 0.25 | {DELTA: -2, G: 6, TAU: 0.2} |
| **no hold-back** | | | | |
| (a) level gate | 7.3% / 8.1% | 34.0% / 57.0% | 0.05 | {G: 6} |
| (b) owner voice, 1 s windows, 10 s enrolment | 19.4% / 27.0% | 20.7% / 16.3% | 0.9 | {TAU: 0.3} |
| (b) owner voice, 1.5 s windows, 10 s enrolment | 23.2% / 30.5% | 24.0% / 20.4% | 1.25 | {TAU: 0.4} |
| (b) 1.5 s windows, 5 s enrolment | 25.8% / 34.6% | 19.7% / 17.7% | 1.25 | {TAU: 0.4} |
| (b) 1.5 s windows, 3 s enrolment | 20.6% / 27.0% | 26.6% / 22.9% | 1.12 | {TAU: 0.3} |
| (c) level + voice, 1 s, 10 s enrolment | 20.6% / 26.6% | 11.0% / 12.8% | 0.75 | {G: 6, TAU: 0.2} |
| (c) level + voice, 1.5 s, 5 s enrolment | 20.6% / 26.2% | 14.0% / 17.0% | 0.9 | {G: 6, TAU: 0.2} |
| (c) level + voice, 1.5 s, 3 s enrolment | 21.5% / 27.1% | 13.3% / 15.9% | 0.95 | {G: 6, TAU: 0.2} |
| (d) language mismatch | 20.1% / 27.3% | 16.7% / 15.3% | 0.55 | {DELTA: 0} |
| (e) all, 1 s, 10 s enrolment | 25.3% / 32.4% | 7.4% / 7.5% | 0.8 | {DELTA: -2, G: 6, TAU: 0.2} |
| (e) all, 1.5 s, 3 s enrolment | 26.5% / 33.4% | 7.6% / 8.2% | 1.0 | {DELTA: -2, G: 6, TAU: 0.2} |

Per condition, 0.75 s hold-back. Each cell is owner words lost / bleed words accepted:

| Condition (owner normal level) | (a) level | (b) voice 1 s | (c) level + voice | (d) language | (e) all |
|---|---|---|---|---|---|
| nearby talker -6 dB | 1.1% / 98.9% | 13.2% / 4.5% | 13.8% / 4.5% | 24.6% / 5.3% | 23.0% / 0.3% |
| nearby talker -12 dB | 1.5% / 74.9% | 9.8% / 4.6% | 10.5% / 3.7% | 18.9% / 5.2% | 16.9% / 1.2% |
| nearby talker -18 dB | 2.2% / 18.3% | 6.3% / 7.2% | 7.1% / 5.2% | 14.5% / 9.7% | 12.1% / 2.1% |
| PA -10 dB | 0.8% / 69.7% | 7.9% / 9.2% | 8.4% / 8.7% | 16.5% / 13.3% | 14.5% / 5.5% |
| PA -20 dB | 2.0% / 16.8% | 4.2% / 10.5% | 5.5% / 7.0% | 11.7% / 16.8% | 9.8% / 3.5% |

**What it shows**

- **The level gate alone fails** whenever bleed is loud: 59% of bleed accepted, and 78% with a quiet
  owner.
- **The owner-voice check does most of the work.** With 1 s windows, 10 s enrolment and 0.75 s
  hold-back it loses **8%** of owner words and accepts **7%** of bleed.
- **Adding the level gate (c)** gives **9% / 5.5%**.
- **Adding language (e)** cuts bleed to **2%** but loses 15% of owner words. Most of that loss is
  where a loud nearby talker overlaps the owner.
- **Enrolment length.** 3 s, 5 s and 10 s are within about 3 points of each other here. 10 s is
  slightly better.
- **A quiet or distant owner (-6 dB)** raises owner loss by 5-7 points for (b)/(c), and the level
  gate becomes useless. Thresholds should be per-session, from enrolment, not global.
- **Thresholds at grid edges.** Several landed on the edge of the grid (cosine 0.2, gate 6 dB,
  language -2), so the best settings may lie a little beyond what was tried.

## 3. Azure real-time diarization (ConversationTranscriber)

**Setup** (`diarize.py`, `dia_analyze.py`). Diarization runs pinned to English for labels; the
all-Haitian R clips are pinned to French so Azure keeps returning segments. It also runs with
continuous language ID on the switch clips.
- **With language ID:** the service accepted it and returned per-segment languages, with no errors.
- **Price** (Azure retail prices, East US): S1 Conversation Transcription audio is
  **$1.20/hour**, against $1.00 for standard real-time. A separate "Speech to Text Enhanced Feature
  Audio" meter lists $0.30/hour; which features it covers was not verified.

| | Azure diarization | ECAPA (1 s windows, cosine dip) |
|---|---|---|
| **Returning speakers (R2, R3, 15 changes)** | **0.1%** confusion; **100%** of returning turns keep their label; 3 speakers tracked | not run on these clips |
| One speaker, 2 minutes (R1) | 1 label: no false new speakers | not run |
| Speaker-change delay, S1-S3 (145 changes) | **3.42 s** p50 (labels come with finals), cut error 0.7 s, 4 missed | **0.75 s** p50, cut error 0.28 s, 1 missed |
| False speaker changes | none seen | 7.5-40.8 per minute at cosine 0.15-0.45: too noisy alone |
| Many different voices (S1-S3, 8-16 readers per clip) | at most 6 labels; 42.6% of speech mapped to the wrong reader | n/a |
| Final latency (speech end → final) | **2.07 s** p50 pinned, 1.39 s with language ID, 1.25 s on R clips; plain recognition 0.83 s | n/a (on-device) |
| Bleed mixes (English owner + foreign-language bleed) | owner keeps one label in 99.4% of turns; **16.5%** of bleed labelled as the owner, 71.0% not transcribed at all (the English pin acts as a filter) | see section 2: owner-voice gate 7%, with level 5.5%, all 2% |

- **Distinct, returning speakers.** Azure diarization tracks a few of them very well.
- **Many different voices.** It merges them: at most 6 labels for up to 16 readers.
- **Speed.** It is slow to say who's talking: labels arrive with finals, 3.42 s after a
  change, and finals come about 1.2 s later than plain recognition.
- **Language ID with diarization** works, but switching is no faster than continuous language ID
  alone.

## Compute (could it run on a phone?)

Single core of an Intel Xeon Gold 6342 (2.8 GHz), PyTorch, fp32:

| Model | Parameters | fp16 size | CPU per window (1 s / 1.5 s) | CPU per second of audio, a window every 0.25 s |
|---|---|---|---|---|
| VoxLingua107 ECAPA | 21.2 M | 42.5 MB | 60.4 / 77.2 ms | 0.236 s (1 s windows) |
| ECAPA speaker (VoxCeleb) | 22.2 M | 44.3 MB | 67.4 / 91.5 ms | 0.263 s (1 s), 0.351 s (1.5 s) |
| Silero VAD | 0.46 M | – | – | 0.0132 s |

- **Cost on the phone.** Both ECAPA models together are about half a server core at a 0.25 s hop.
  - On an iPhone through Core ML on the Neural Engine this should be a small fraction of that, but it
    is not measured here.
  - A 0.5 s hop halves it.
  - About 90 MB of models in fp16.
- **Recognition cost** (list prices, East US):
  - Azure standard real-time **$1.00/hour per stream**, so two pinned streams (f) are $2.00.
  - MAI streaming was reported at about $0.54/hour per stream in an earlier round (unverified here),
    so two streams about $1.08.
  - Re-recognising a cut stretch with fast transcription is $0.36/hour of re-sent audio: pennies.

## Recommended design

**Table talk (both people at one phone)**
- **Phone:**
  - Silero VAD plus VoxLingua107 ECAPA on 1 s windows every 0.25 s, constrained to the
    conversation's two languages.
  - Mean of 3, hysteresis 1.0.
  - On a switch, cut back to where the scores turned, snapped to a pause. This decides in about 1 s
    and cuts within about 0.1 s.
  - Keep a 25 s audio ring (build 23 already does).
- **Server, either:**
  - **(c) one pinned stream:** restart it in the new language and re-recognise the cut stretch from
    the ring with fast transcription. One stream; the switched stretch arrives about 1.5 s after the
    switch.
  - **(f) two pinned streams:** both always on, with the phone's labels picking the text. No restart
    and no wait for that stretch, at twice the recognition cost. MAI pinned streams could bring this
    to about the cost of one Azure stream; MAI's per-stretch accuracy is not measured here.
- **Speaker change** (ECAPA dips) and **recogniser warnings** only as hints that lower the
  hysteresis. Neither is reliable alone.
- **Azure continuous language ID** stays only as a fallback when the phone can't run the detector.

**Per-speaker voice pool**
- **Azure diarization can drive it** in a normal 2-3 person conversation: speakers kept apart,
  labels stable when people come back.
- **What it costs:** about 1.2 s extra latency on finals, and $1.20/hour instead of $1.00.
- **It won't handle switching:** it can't replace on-device language ID for language switches.
- **When on-device ECAPA is needed instead:**
  - the voice must be chosen before the final arrives
  - there are many speakers
  - the phone must gate its owner (open mic)

**Open-mic phones (Live Translation)**
- **On the phone:** owner enrolment, with a 10 s read prompt ("read this sentence aloud") at session
  start; 5 s is nearly as good.
- **On each 1 s window:** ECAPA cosine to the enrolment plus a level gate relative to the owner's
  running level.
- **Hold audio back 0.75 s** so the decision covers the start of each turn.
- **Starting thresholds:** cosine about 0.2-0.3, level 6 dB under the owner. Re-tune per session
  from the enrolment, because a quiet owner shifts them.
- **Add the language-mismatch check (e)** where bleed must almost never get through, such as a PA
  playing the translation back. It cuts bleed to about 2% but costs owner words during overlaps.
- **Only accepted audio goes to the server.**

## Limits

- **Synthetic mixes.** FLEURS readers, not people who switch languages mid-thought: S1 is two
  matched voices, not one bilingual person. The room response is synthetic, and the PA TTS is one
  voice.
- **Single round.** One run per clip and one setting per approach. Thresholds were set by hand for
  the switch detectors, and leave-one-owner-out for bleed.
- **Text scoring.** Against FLEURS's written text, so recordings that differ from their text count
  against every approach alike.
- **Simulated re-recognition.** Stood in by the other pinned stream's words. That stream had heard
  the whole stretch from its start, so (b)/(c)/(d) may be slightly flattered.
- **MAI text** couldn't be scored per stretch (no word timings).
- **Haitian Creole** has detection numbers only (no Azure recogniser).
- **Diarization on returning speakers** comes from two short CMU clips.

## Files

| File | Purpose |
|---|---|
| `build_clips.py` | Switch clips |
| `bleed_clips.py` | Bleed mixes (pod) |
| `build_dia_clips.py` | Returning-speaker clips |
| `features.py` | Language, VAD and speaker signals (pod) |
| `bleed_features.py`, `bleed_energy.py` | Bleed signals (pod) |
| `footprint.py` | Model sizes and CPU time |
| `recognize.py` | Azure and MAI streams |
| `diarize.py` | Azure ConversationTranscriber |
| `analyze.py`, `table.py` | Switch simulation and table |
| `bleed_analyze.py` | Bleed gates (`BUF=0.75` for the hold-back) |
| `dia_analyze.py` | Diarization metrics |
| `results.json` | Every number above |

Audio, transcripts and per-clip outputs stay local.
