# English and Portuguese hearing, rechecked: MAI-Transcribe-2-Streaming against Azure standard, November 2026

Two earlier rounds disagreed on which streaming recogniser hears English and Portuguese (pt-BR) better:

| | Round | English CER, Azure / MAI | Portuguese CER, Azure / MAI |
|---|---|---|---|
| October | `../2026-10-mai-streaming-followup` (clip of `../2026-10-unseen`) | **3.6** / 6.0 | **0.9** / 1.7 |
| November | `../2026-11-talk-soniox`, round `talk-hearing-2026-11` (sets a+b) | 6.9 / **4.2** | 1.6 / **0.8** |

This round streams **both clip sets through both recognisers with one setup**, on one day (2026-11-16), twice, and
scores every arm with one scorer under both rounds' references and normalisations. It also runs each earlier
round's own script once on English.

## Answer

- **The rounds scored against different references, and most of the disagreement is that.** October scored
  against *what was said* (a Gemini verbatim transcription of each recording); November against the *written
  FLEURS text*. October's own results file has written-text figures as well: English Azure 7.0 / MAI 8.3,
  Portuguese Azure 3.0 / MAI 0.9. Azure's English "doubling" (3.6 → 6.9) is the reference, not Azure: on
  October's clip, against the written text, Azure scores 7.0 in October and 7.0 today, and Azure's output was
  identical in all three runs today.
- **Portuguese: MAI, under every reference, on both sets, except one sentence.** On October's clip against what
  was said, Azure leads 0.9 to 1.5. That lead is one sentence: MAI wrote "400 d.C. … 1100 d.C." and the reference
  spelled out "depois de Cristo" (24 characters, a writing difference, not a hearing one). Elsewhere Azure
  mishears names that MAI gets ("árvores. Portugal." for *pohutukawa*, "kolung" for *Kowloon*, "Scott turbby").
- **English: MAI's output on October's clip has changed since October.** The audio, SDK version, region, locale
  and script were the same as October's (`orig` run). Against the written text, a reference that hasn't changed,
  MAI scores 7.1–7.4 today (8.3 in October) and returns 23 finals in every run (34 in October). Azure on the same
  clip is unchanged (7.0, 22 finals). Against what was said MAI scores 3.0–4.0 today (6.0 in October). That
  reference was made again for this round; Azure scores 3.8 against it (3.6 in October), so it moves a score by
  about 0.2. Microsoft documents no update to the model (below), so this is a change in its output, cause unknown.
- **English, which clip set:** with today's MAI, October's clip puts the two level (CER within 0.6 under every
  reference and normalisation). November's sets favour MAI clearly against the written text (CER 3.9 vs 6.4, WER 5.9 vs 9.7) and
  less against what was said (CER 3.05 vs 3.0, level; WER 4.9 vs 6.7).
- **Why the reference matters so much in English:** many FLEURS English recordings stop before the sentence ends
  (Gemini flagged 4–5 per 20-sentence set as cut off). Where a recording is cut off, MAI often writes a complete
  ending, sometimes the written one ("…feathers in birds", "…the far side") and sometimes a different one ("…with
  respect to the Sun", "…were critically ill"). Azure stops where the audio does. The written text rewards MAI's
  endings when they match and the "said" reference penalises them. These data can't tell whether MAI heard the
  quiet tail or guessed it. Away from the sentence ends, Azure makes plain mishearings that MAI doesn't ("Plasmic
  oxygen", "He denies that a figure", "political chatter instilling it").

**Verdict, today:**
- **English: MAI, modestly.** It has fewer word errors in every comparison on November's sets (WER 1.8–4.2
  points fewer). Character errors: ahead by 2.5–2.9 against the written text, level against what was said (−0.05 to +0.3). On
  October's clip it is level with Azure (CER within 0.6 either way, WER 0–0.8 better).
- **Portuguese: MAI.** Fewer errors on both sets under both references (CER 0.5 vs 0.7 said, 0.8 vs 1.0 written,
  October's normalisation; 1.1 vs 3.0 on October's clip against the written text). The one exception, October's
  clip against what was said (1.5 vs 0.9), comes from a single "d.C." sentence.

## Results

Characters wrong / words wrong (%), mean of runs r1 and r2 (November sets: mean of sets a and b, as November).
"oct norm": October's scorer (`../2026-10-whisper-vs-azure/score.py`: digits spelled out, punctuation to spaces);
"nov norm": November's (`../2026-11-talk-soniox/round_hearing.py`: letters and digits only). Earlier figures in
the scoring that round used.

### English

| Clip set | Recogniser | Earlier figure | Said, oct norm | Text, oct norm | Text, nov norm | Said, nov norm | Finals |
|---|---|---|---|---|---|---|---|
| October (20) | Azure | Oct: said 3.6 / 7.8, text 7.0 / 11.8 | 3.78 / 8.58 | 7.00 / 11.78 | 8.15 / 12.94 | 5.10 / 9.92 | 22 (Oct 22) |
| October (20) | MAI | Oct: said 6.0 / 11.2, text 8.3 / 13.6 | **3.43** / **7.91** | 7.22 / **11.39** | 8.73 / 12.94 | **4.63** / **9.09** | 23 (Oct 34) |
| November a+b (40) | Azure | Nov: text 6.86 (a 4.51, b 9.21) | **3.00** / 6.67 | 6.41 / 9.66 | 7.13 / 10.40 | 3.81 / 7.50 | 23, 19 |
| November a+b (40) | MAI | Nov: text 4.15 (a 2.26, b 6.04) | 3.05 / **4.93** | **3.93** / **5.91** | **4.27** / **6.16** | **3.52** / **5.31** | 22, 22 |

### Portuguese

| Clip set | Recogniser | Earlier figure | Said, oct norm | Text, oct norm | Text, nov norm | Said, nov norm | Finals |
|---|---|---|---|---|---|---|---|
| October (20) | Azure | Oct: said 0.9 / 2.8, text 3.0 / 5.6 | **0.91** / **2.75** | 3.01 / 5.84 | 3.84 / 7.01 | **2.08** / 4.35 | 22 (Oct 22) |
| October (20) | MAI | Oct: said 1.7 / 3.2, text 0.9 / 2.5 | 1.47 / 3.00 | **1.09** / **3.05** | **1.49** / **3.64** | 2.29 / **4.09** | 25 (Oct 20) |
| November a+b (40) | Azure | Nov: text 1.57 (a 1.78, b 1.35) | 0.73 / 2.56 | 1.02 / 3.49 | 1.59 / 4.17 | 1.31 / 3.23 | 23, 21 |
| November a+b (40) | MAI | Nov: text 0.77 (a 0.54, b 1.01) | **0.51** / **1.70** | **0.80** / **2.48** | **0.81** / **2.52** | **0.52** / **1.72** | 26, 23 |

Run to run: Azure's output was identical in r1, r2 and the `orig` run. MAI's moved a little: English October
clip, text oct norm 7.33 / 7.11 / 7.39 (orig), said 3.83 / 3.03 / 4.00; set a text nov norm 2.26 / 2.75 / 2.26.

### Each earlier round's own script (English, `orig`)

| | Script | Azure | MAI |
|---|---|---|---|
| October clip, said, oct norm | `../2026-10-whisper-vs-azure/azure_stream.py`, `../2026-10-mai-streaming-followup/stream.py pin` | 3.78 / 8.58 (Oct 3.6 / 7.8) | 4.00 / 8.31 (Oct 6.0 / 11.2) |
| October clip, text, oct norm | same | 7.00 (Oct 7.0) | 7.39 (Oct 8.3) |
| November sets, text, nov norm | `../2026-11-talk-soniox/stt_azure.py` | a 4.57, b 9.70 (Nov 4.51, 9.21) | a 2.26, b 6.04 (Nov 2.26, 6.04) |

The scripts reproduce today what this round's `stream.py` gives (their streaming settings are the same: SDK
1.52.0, 100 ms real-time chunks, locale pinned, Detailed output, 2 s of silence after the clip). Each round's
script, run today, gives today's numbers, not that round's: the October script doesn't bring back MAI's October
score.

## Setup differences between the two earlier rounds

| | October | November | Explains |
|---|---|---|---|
| Reference | what was said (Gemini verbatim, `../2026-10-unseen/witness.py`) | the written FLEURS text | Azure's English 3.6 → 6.9, and all of Portuguese's flip |
| Clips | one clip, 20 sentences (`../2026-10-unseen`, seed 2026) | two clips of 20 (seed 2029), mean of the two | part of English: level on October's clip, MAI ahead on November's |
| MAI's output | 34 finals on October's English clip | (today) 23 finals on the same audio | the rest of English: MAI 1.1 better (text) on identical audio |
| Normalisation | digits spelled out (num2words), punctuation to spaces | letters and digits only, digits left as digits | shifts both recognisers; changes no ranking (tables above) |
| Azure resource | "East US" (the README doesn't name it) | Lithos-Speech, eastus | can't tell; Azure today reproduces October's 7.0 exactly |
| MAI resource | East US 2 | Lithos-Speech-eus2, eastus2 | none found |
| Locales | en-US, pt-BR | en-US, pt-BR | none |
| SDK | 1.52.0 | not recorded (today's run: 1.52.0) | none found |
| End of stream | MAI: 2 s silence, wait up to 15 s for the session to stop; Azure: 2 s silence, 2.5 + 3 s | 2 s silence, 2.5 + 3 s | none: the `orig` runs match today's |
| Whole clip vs per sentence | whole clip | whole clip (finals also regrouped per sentence for translation) | none: CER is on the whole clip in both |
| Segmentation / silence settings | SDK defaults | SDK defaults | none |

Two levels are similar in every clip: 13 of October's 20 English recordings and 14 of each November set's are
quieter than −50 dBFS, so loudness doesn't separate the sets.

## Did Microsoft change MAI (2026-10-15 to 2026-11-16)?

No source found states that it did:

- [Speech service release notes](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/releasenotes),
  Speech to text: the October 2026 entries are real-time multichannel GA, multilingual post-stream refinement GA,
  wider post-stream refinement locales, the `en-Latn-IN` model and an Indic model; November 2026 has the
  LLM-based Live Interpreter. None names MAI-Transcribe-2-Streaming, or a real-time `en-US` or `pt-BR` model.
  The Speech SDK 1.53 (October 2026) notes list IPv6, packaging and keyword-recognition changes, nothing about MAI.
- [MAI-Transcribe-2-Streaming overview](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe-2-streaming)
  and [its Speech SDK guide](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe-2-streaming-speech-sdk):
  last updated 2026-10-07 (`updated_at`), still public preview, no version or changelog.
- [MAI-Transcribe-2 (batch)](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe):
  updated 2026-11-06. It lists MAI-Transcribe-2, 1.5 and 1 (deprecated Aug 20, 2026), no streaming version.
- Web search (2026-11-16) found only October 1 launch coverage, for example
  [MarkTechPost, 2026-10-02](https://www.marktechpost.com/2026/10/02/microsoft-ai-releases-mai-transcribe-2-streaming-1-real-time-speech-to-text-model-on-artificial-analysis/).
- **What the service returns:** MAI's results carry no model or version field. Azure standard's carry
  `SRModel: "base"`, the same in every run, with no version.

So MAI's output on identical audio changed (finals 34 → 23, written-text CER 8.3 → 7.2 on October's English
clip), but Microsoft has published no update to MAI or to Azure's real-time English model in the period.
The cause is unknown. Azure standard's English and Portuguese output reproduces October's figures exactly.

## How it was run

- **Clips:** October's rebuilt with `../2026-10-open-streaming/build_unseen_subset.py` from the committed FLEURS
  ids (offsets, texts and per-sentence loudness match the committed files); November's with
  `../2026-11-talk-soniox/build_clips.py ... results/ids.json en pt` (offsets and texts match `results/clips_*`).
- **Streaming (`stream.py`):** the clip fed at real time in 100 ms chunks, the locale pinned, Speech SDK 1.52.0.
  Azure on Lithos-Speech (eastus), MAI (`model = "mai-transcribe-2-streaming"`) on Lithos-Speech-eus2 (eastus2).
  Three streams at a time per recogniser. Runs r1 and r2: 6 clips × 2 recognisers each. `orig`: each earlier
  round's script, English, once.
- **What was said (`witness.py`):** October's `witness.py` (gemini-pro-latest, served as gemini-3.1-pro-preview),
  made again for all six clips, three calls at a time. It adds two things: a one-item JSON list answer is
  unwrapped, and `REDO=1` re-asks only failed sentences. One sentence (October English 3) failed every time and
  takes October's committed "said" text (`../2026-10-unseen/results.json` `english_said`). Gemini flagged 6 of
  October's 20 English sentences (October flagged 8; this run's flags are 6 of those 8) and none of the Portuguese.
- **Scoring (`score.py`):** every final in audio order, joined, against each reference, under both
  normalisations, CER and WER.
- **Not committed:** audio, transcripts and the "said" texts (FLEURS text and model outputs). The scripts
  regenerate them. `results.json` has every score per run, recogniser and clip.

```
python3 -I ../2026-10-open-streaming/build_unseen_subset.py WORK/oct ../2026-10-real-voices ../2026-10-unseen/results.json en pt
python3 -I ../2026-11-talk-soniox/build_clips.py WORK/nov ../2026-10-real-voices .. ../2026-11-talk-soniox/results/ids.json en pt
REC=azure AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus  python3 -I stream.py WORK/jobs.json WORK/out r1
REC=mai   AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 python3 -I stream.py WORK/jobs.json WORK/out r1
GEMINI_API_KEY=... python3 -I witness.py WORK/oct/clips_reg en WORK/said/oct-en.json   # and the other five clips
python3 -I score.py WORK results.json
```

## Spend

- Azure standard: 0.75 h of audio streamed (15 streams), about 0.75 USD at the 1.00 USD/hour list price.
- MAI-Transcribe-2-Streaming: 0.75 h, about 0.40 USD at the 0.54 USD/hour introductory price.
- Gemini (gemini-pro-latest, eval key): about 150 short calls for the "said" references (120, plus re-asks and
  retries). Token counts weren't recorded; at list price this is a few dollars at most. No translation was graded.

## Limits

- 60 sentences per language (one 20-sentence clip plus two), read FLEURS speech, one reader per sentence.
- Two runs (three for English). MAI varies run to run by up to 1.0 CER point on a clip; Azure didn't vary.
- The "said" reference is a model's transcription, made again for this round. It is close to October's (Azure moves
  0.2) but not identical. Gemini was shown the written text, which may pull its transcription toward it.
- Whether MAI's complete endings on cut-off recordings are heard or guessed can't be told from these data.
- MAI-Transcribe-2-Streaming is a preview and may change again without notice, as it seems to have done here.
