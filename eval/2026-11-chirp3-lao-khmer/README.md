# Google Chirp 3 streaming for Lao and Khmer, against Amazon Transcribe and Omnilingual 7B (2026-11-04)

The question: can a managed recogniser hear Lao (which Amazon Transcribe doesn't have) and Khmer as well and as fast
as what we run now, without a GPU? Hearing only: no translation, no voice. No app changes.

## Setup

- **Chirp 3:** Speech-to-Text v2 `StreamingRecognize`, `us-speech.googleapis.com`, recognizer `locations/us`,
  model `chirp_3`, one language named (`lo-LA`, `km-KH`, `en-US`; no auto-detect), LINEAR16 16 kHz mono,
  `interim_results` on, `enable_voice_activity_events` on. Endpointing default (STANDARD) unless stated. Lao and Khmer
  are **Preview** on Chirp 3. Project `linen-cubist-509804-h6` (data logging not enabled: Google keeps no audio by
  default).
- **Amazon Transcribe:** `StartStreamTranscription` through `amazon-transcribe` (Python), us-east-2, `km-KH`, no
  partial-results stabilisation (the app turns it on), key `lithos-evals`.
- **Audio:** sent in 100 ms pieces (3,200 bytes). Our own framing: Google has no frame setting.
- **Pacing:** `oct_stream.py` paces by the clock. `stream.py` and `one_stream.py` sleep 100 ms after each piece,
  which drifts slowly behind real time (about 7 s over 4 minutes; a fraction of a second per FLEURS sentence), so their
  "after the voice stops" times are slightly high. `runs/oct_lo_*_drift.json` keep the drifted run of the October
  clips; its CER matched (6.8 / 11.5%).
- **Scoring:** `score.py` (spaces and punctuation removed; Levenshtein over characters). `oct_score.py` is October's
  `hearing.py` method exactly (NFKC, lowercase, letters and digits only; Levenshtein over the joined finals). Lao vowel
  signs are not alphanumeric, so that method drops them on both sides, for Omnilingual and Chirp alike.

## 1. FLEURS sentences, one stream per sentence (`stream.py`, 25 per language)

FLEURS test (CC BY 4.0), 25 sentences drawn with seed 2026 (`fetch.py`), graded against FLEURS's raw transcription.

| | Characters wrong | Final after the voice stops p50 / p90 | First text p50 |
|---|---|---|---|
| Khmer, Chirp 3 | 20.0% | 2.29 / 2.65 s | 7.09 s |
| Khmer, Transcribe | **17.8%** | **0.73 / 0.92 s** | **2.39 s** |
| Lao, Chirp 3 | 10.2% | 1.76 / 2.08 s | 6.53 s |

Small sets: the first 12 Lao sentences alone scored 4.8% on the same run.

## 2. Endpointing (`CHIRP_ENDPOINT`, first 12 sentences)

| | Characters wrong | Final after voice stops p50 | First text p50 |
|---|---|---|---|
| Khmer default / SHORT / SUPERSHORT | 18.5 / 22.0 / 23.2% | 2.36 / 1.85 / 1.75 s | 7.09 / 5.89 / 5.51 s |
| Lao default / SHORT / SUPERSHORT | **4.8** / 8.9 / 17.2% | 1.76 / 1.70 / 1.31 s | 6.58 / 6.56 / 3.29 s |

Shorter endpointing chops sentences: sooner text, more errors. 0–1 interim results per sentence at every setting.

## 3. Is the slow first text Lao/Khmer, or a warm-up? (`chirp_en.json`, `one_stream_en.json`)

- English (5 FLEURS sentences, one stream each): first text 6.5–6.7 s into every stream, 1–2 interim results per
  sentence. English is GA, so it is not the Preview languages.
- The same 5 in **one** stream (1.5 s pauses): each sentence's first interim came **5.4–5.6 s after Chirp's own
  speech-start event**, the 1st and the 5th alike; a long sentence's next interim 5.4 s later. Not a warm-up: Chirp 3
  streams text in blocks of about 5.5 s of speech. Finals came 0.5–0.7 s after Chirp's speech-end event.
- No public source found a setting for it: Google's Chirp 3 page offers only endpointing sensitivity, and the one
  public benchmark found (AKV85/voice-translator #16, ru/en) measured only time after stop.

## 4. October's Lao clips, one continuous stream (`rebuild_oct.py`, `oct_stream.py`, `oct_score.py`)

The two Lao clips of `../2026-10-complete-thought-ht-km-lo` rebuilt from their stored layout (`raw/clips/clips_*/lo.json`
in the untracked evals: the 20 FLEURS files, the pauses, the 1 s lead) with that eval's own `fetch_audio.to_pcm`:
every sentence edge matched to the millisecond (233.73 s and 217.72 s). One Chirp 3 stream per clip, default
endpointing, paced by the clock.

| Lao | Characters wrong | Final after its piece ends p50 / p90 | Piece p50 | Words while speaking |
|---|---|---|---|---|
| **Chirp 3, reg** | **6.5%** | **0.95 / 1.29 s** (after Chirp's own end) | 9.3 s | first text ~5.4 s after speech start |
| **Chirp 3, irr** | **11.0%** | **1.02 / 1.30 s** | 9.3 s | ~5.4 s |
| Omnilingual 7B, reg (Oct) | 13.4% | 1.3 / 3.0 s | 3.4 s | CTC 3B: ~2.0 s behind, 15.9% wrong |
| Omnilingual 7B, irr (Oct) | 14.3% | 1.5 / 4.3 s | 3.4 s | ~2.0 s behind, 15.5% wrong |

- From each speaker's actual sentence end, Chirp's final came 1.35 s (reg) / 1.46 s (irr) at p50. The p90 there
  (7.6–9.2 s) is about 3 finals whose piece ended mid-sentence, counted from the sentence before; not real delay.
- Omnilingual's times were on an A40 shared by four services; production runs on Cloud Run L4.

## Conclusions

- **Lao:** Chirp 3 hears it better than Omnilingual 7B on the same audio (6.5 / 11.0% against 13.4 / 14.3%), and its
  finals come about 1 s after its own end of speech, steadily (p90 1.3 s against 3.0–4.3 s). No GPU, no cold start,
  billed per minute of audio. It does not show words while someone speaks: text comes in ~5.5 s blocks, so live
  captions lag; Omnilingual's CTC track (~2 s behind) stays better for that.
- **Khmer:** keep Amazon Transcribe (17.8% and 0.7 s against Chirp 3's 20.0% and 2.3 s, one sentence per stream).
- **Haitian Creole:** no Google speech-to-text model has it.
- **Before building:** Google's pre-GA terms for Preview languages (privacy wording), and the per-minute price (not
  verified here; from memory about $0.016/min).
- Clean read speech only (FLEURS); sermon audio will be harder for every recogniser.

`runs/` holds every run's per-sentence (or per-event) output. Audio is not kept; `fetch.py` and `rebuild_oct.py`
rebuild it.

## 5. Lao into English: Chirp 3 or Omnilingual, into sol or Gemma (`translate.mts`, `grade.py`)

Each recogniser's finished pieces on October's two Lao clips (Chirp 3: section 4's one-stream run; Omnilingual 7B:
October's recording `raw/rec/o7_*_lo.json`), translated in order as a live room would, with the app's own code and
prompt: `translateMessages` (correct-then-translate, previous 2 pieces and the last translation as context),
`foundryStream` (sol, `gpt-6-sol-us` on Lithos-foundry) and `gemmaStream` (Gemma 4 31B on Bedrock, SigV4, key
`lithos-evals`). 155 pieces per translator; no errors. Graded blind side by side per read sentence (each arm's pieces
by their midpoint), 4 arms per call under shuffled labels, `gemini-flash-latest`, two rounds, against FLEURS's human
English; 40 sentences. "Ready" = when the sentence's last English text was done, after its speech ended (the voice is
not included).

| Arm | Quality | Round 1 / 2 | Critical (round 1) | Ready after speech ends p50 / p90 | Call p50 |
|---|---|---|---|---|---|
| **Chirp 3 → sol** | **81.2** | 80.8 / 81.7 | 1 | 2.27 / 4.91 s | 0.9 s |
| **Chirp 3 → Gemma (Bedrock)** | **76.2** | 76.7 / 75.8 | 2 | **1.69 / 2.03 s** | **0.3 s** |
| Omnilingual → sol | 64.6 | 65.0 / 64.2 | 7 | 3.23 / 6.72 s | 0.9 s |
| Omnilingual → Gemma (Bedrock) | 47.9 | 49.2 / 46.7 | 11 | 1.50 / 5.86 s | 0.3 s |

Paired differences (bootstrap over sentences, 95%):
- Chirp → Gemma minus Omnilingual → Gemma: **+28.3** (+17.5 to +39.6)
- Chirp → sol minus Omnilingual → sol: **+16.7** (+6.7 to +27.5)
- Chirp → sol minus Chirp → Gemma: +5.0 (−0.0 to +10.8)
- Chirp → Gemma minus Omnilingual → sol (today's route): **+11.7** (+1.2 to +22.5)

- Omnilingual → sol (64.6) matches October's "Sentences (pieces), sol" (63.0) on the same audio: the harness agrees.
- Better hearing helps Gemma most: it closes most of the gap to sol (−5, not significant at 95%), at a third of
  sol's call time and a much tighter tail (p90 2.0 s against 4.9 s).
- Model-made grades on clean read speech; 40 sentences.

## 6. Chirp 2 on the same Lao clips (`oct_stream2.py MODEL=chirp_2 LOC=us-central1`, `oct_score2.py _chirp_2`)

Chirp 2's docs list 16 streaming languages, without Lao, and call its regions "Private GA"; a streaming request for
`lo-LA` in `us-central1` works anyway (`chirp2_probe.py`). Same clips, one stream each, paced by the clock.

| Lao | Characters wrong reg / irr | Final after its own end p50 / p90 | After the speaker's sentence end p50 | First text after speech start p50 |
|---|---|---|---|---|
| Chirp 3 (`us`) | **6.5 / 11.0%** | **0.95–1.02 / 1.3 s** | **1.35–1.46 s** | 5.4 s |
| Chirp 2 (`us-central1`) | 8.7 / 11.0% | 1.48–1.50 / 2.1–2.3 s | 1.9–2.0 s | 5.5 s |

Chirp 2 is a little less accurate and about 0.5 s slower, streams in the same ~5.5 s blocks, and costs the same.

## Price and terms (checked 2026-11-04)

- **Price** (Cloud Billing catalog, service "Cloud Speech API", SKU "Cloud Speech-to-Text Recognition"): $0.016/min for
  the first 500,000 min a month, then $0.010, $0.008 and $0.004 per min. Data logging: $0.012/min (Google may use the
  audio). Chirp 2 and Chirp 3 are billed as standard recognition.
- **Data use:** "By default, Cloud Speech-to-Text does not log customer audio data or transcripts" (data-logging
  page; logging is opt-in per project). Service Specific Terms §18: "Google will not use Customer Data to train or
  fine-tune any AI/ML models without Customer's prior permission or instruction."
- **Preview (Chirp 3's Lao and Khmer):** General Service Terms §5(d): "no data processing terms (including the Cloud
  Data Processing Addendum) apply to Pre-GA Offerings and Customer should not use Pre-GA Offerings to process personal
  data or other data subject to legal or regulatory compliance requirements"; §5(b): no data-location commitment, no
  SLA, may change or end without notice.

## 7. Japanese, Vietnamese, Mandarin, Korean, Hindi: Chirp 3 against today's hearing (`run_asia.sh`)

One live-style clip per language (`build_clips.py`: 20 FLEURS test sentences shared with en_us, seed 2026, the "reg"
pauses), one stream each, paced by the clock. Today's hearing as the app sets it up (`azure_stream.mts`: best-routes
`hear`, the app's segmentation): **MAI** streaming (eastus2) for ja, vi, zh; **Azure standard** (eastus) for ko, hi.
Both arms' pieces translated by Gemma 4 on Bedrock with the app's prompt (`asia_translate.mts`), graded blind side by
side per sentence against FLEURS's human English, two rounds (`asia_grade.py`).

| | Chirp 3 CER | Today CER | Chirp 3 final after sentence end p50 | Today | → Gemma quality: Chirp 3 / today | Difference (95%) |
|---|---|---|---|---|---|---|
| ja (MAI) | 3.8% | **2.7%** | 1.50 s | **0.69 s** | 85.8 / **91.7** | −5.8 (−20.8 to +9.2) |
| vi (MAI) | 3.8% | **3.1%** | 1.16 s | **0.65 s** | 76.7 / **88.3** | −11.7 (−23.3 to 0.0) |
| zh (MAI) | 10.0% | **8.4%** | 1.42 s | **0.67 s** | 86.7 / **88.3** | −1.7 (−13.3 to +11.7) |
| ko (Azure) | **4.0%** | 5.9% | 1.44 s | **0.50 s** | **93.3** / 90.0 | +3.3 (−5.0 to +11.7) |
| hi (Azure) | **8.0%** | 9.7% | 1.47 s | **0.41 s** | **80.0** / 71.7 | +8.3 (−0.8 to +17.5) |

- **MAI beats Chirp 3** for ja, vi and zh: as accurate or better, and its finals come ~0.1 s after its own end of
  speech (Chirp ~0.8 s), so ~0.7 s sooner after each sentence. Keep MAI.
- **Korean and Hindi:** Chirp 3 hears a little better than Azure standard and Gemma's English scores higher (+3, +8,
  neither significant at 20 sentences), but ~1 s later per sentence. Worth a second look against MAI for ko/hi, if
  MAI serves them, before changing anything.
- 20 sentences per language: differences under ~10 points are within noise.

### 7b. Korean and Hindi through MAI too (`azure_stream.mts ko|hi mai`, `asia_grade3.py`)

MAI streaming accepted `ko-KR` and `hi-IN`. Same clips; all three arms into Gemma, graded blind three at a time.

| | CER Chirp 3 / Azure / **MAI** | Final after sentence end p50: Chirp 3 / Azure / MAI | → Gemma quality: Chirp 3 / Azure / **MAI** |
|---|---|---|---|
| ko | 4.0 / 5.9 / **3.7%** | 1.44 / **0.50** / 0.66 s | 90.0 / 89.2 / **95.0** |
| hi | 8.0 / 9.7 / **4.7%** | 1.47 / **0.41** / 0.67 s | 80.0 / 71.7 / **85.0** |

- MAI − Azure standard: ko **+5.8** (−1.7 to +15.8), hi **+13.3** (+4.2 to +24.2).
- MAI − Chirp 3: ko +5.0 (−7.5 to +17.5), hi +5.0 (−5.8 to +18.3).
- **Hindi should move to MAI** (best-routes `hear`); Korean likely too. Chirp 3 is not the best ear for any of the five.
