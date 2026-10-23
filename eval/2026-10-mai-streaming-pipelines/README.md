# MAI-Transcribe-2-Streaming in a live pipeline, October 2026

Microsoft's streaming recogniser (public preview since 2026-10-01) hooked to a translator the way a
live route uses one: the clip streamed in real time, each final translated the moment it arrives,
with the previous two finals as context. Four translators behind it, and today's Talk route
(Azure standard real-time → sol) as the baseline, all graded blind in one round per direction.

## Setup

- **Audio:** the unseen clips of [`../2026-10-unseen`](../2026-10-unseen/) (20 FLEURS read
  sentences per language, CC BY 4.0), regular (1.0–1.95 s) and irregular (0.3–1.2 s) pauses, for
  en, es, pt, fr and ja. Streamed at real time in 100 ms chunks (`pipeline.py`).
- **Recognisers:**
  - **MAI-Transcribe-2-Streaming:** Speech SDK 1.52.0, `speech_config.model =
    "mai-transcribe-2-streaming"`, no language given (it detects it). It is served only from
    swedencentral, centralus, eastus2 and southeastasia; an East US resource refuses it, so it ran on
    an East US 2 Speech resource.
  - **Azure standard real-time** (East US), with the clip's locale given, as
    [`../2026-10-whisper-vs-azure`](../2026-10-whisper-vs-azure/) system 3.
- **Translators,** all given the translator shootout's prompt (it warns about recognition errors)
  plus the previous two finals as context:
  - `sol@low`: GPT-5.6-sol on Azure AI Foundry (Data Zone Standard, US), `reasoning_effort: low`.
  - OpenRouter, every request with `"provider": {"zdr": true, "data_collection": "deny"}`:
    `qwen/qwen3.5-122b-a10b` (reasoning off), `qwen/qwen3.8-2.4t-a95b` (the newest large Qwen with
    zero-retention endpoints; its endpoints refuse reasoning off, so reasoning effort low) and
    `google/gemma-4-31b-it` (reasoning off).
- **Pipelines:** A MAI → sol; B MAI → Qwen 3.5 122B and MAI → Qwen 3.8 2.4T; C Azure → sol (today's
  route); D MAI → Gemma 4 31B. The MAI pipelines share one MAI stream per clip, so their
  translators see identical finals.
- **Recognition scores:** [`../2026-10-whisper-vs-azure/score.py`](../2026-10-whisper-vs-azure/score.py)
  (digits spelled out, the same normalisation for every system), against what the readers said.
- **Grading** (`analyze.py jobs`, then `../2026-10-es-pt-live-compare/grade.py`):
  `gemini-pro-latest`, all five pipelines side by side and shuffled, one call per direction and
  pattern, against the written text and, for English sources, against what was said. A final is
  given to every sentence whose speech it overlaps by 0.3 s or more, so a final that runs two
  sentences together counts for both (the grader treats a neighbour's words as harmless).
- **Latency** is measured from each sentence's speech, found from the clip's energy, so every
  recogniser is timed from the same instant: speech start → the sentence's first partial; end of
  speech → its last final; end of speech → its last translation complete. No voice is included.
- **Translations that failed live** (`fill.py`): Qwen 3.8's zero-retention providers answered
  HTTP 429 to many requests during the runs. Those translations were made again afterwards, so the
  grades compare translators, not rate limits, and are left out of the latency figures. 6 of 2,150
  translations stayed blank and score as missing.
- **Cost per hour of speech,** one listener language: translation from the runs' actual tokens
  (OpenRouter's reported cost; sol at the list 4.40 / 22 USD per million input / output tokens);
  recognition at list prices from the Azure Retail Prices API (2026-10-23): "S1 Speech To Text"
  1.00 USD/hour and "MAI-Transcribe-2" 0.54 USD/hour. No separate streaming meter is listed, so the
  MAI figure is an assumption.

## Results

### Recognition, characters / words wrong against what was said

| Pauses | Recogniser | en | es | pt | fr | ja (chars) |
|---|---|---|---|---|---|---|
| regular | MAI streaming | 6.1 / 11.5 | **2.0 / 4.7** | 2.8 / 4.5 | **2.4 / 5.7** | 11.8 |
| regular | Azure standard | **3.6 / 7.8** | 2.4 / 5.6 | **0.9 / 2.8** | 3.6 / 9.5 | **6.9** |
| irregular | MAI streaming | 7.2 / 12.8 | **1.8 / 4.3** | 2.2 / 3.5 | **2.8 / 5.9** | 16.4 |
| irregular | Azure standard | **3.7 / 8.3** | 2.6 / 6.0 | **1.0 / 3.0** | 2.9 / 7.7 | **8.0** |

- MAI streaming splits speech into more, smaller finals (English 34 against Azure's 22, Japanese 48
  against 25), some of them one or two words ("Prideは", "1から", "3との"…), and once wrote a stray
  "Right." at a quiet reader. With irregular pauses it does the opposite and runs sentences
  together: 8 of Spanish's 12 finals span two or more sentences, against 2 of Azure's 18.
- Unlike MAI-Transcribe-2 sent whole sentences (`../2026-10-whisper-vs-azure`: English 3.7, Japanese
  2.5), the streaming model is worse than Azure standard on English and Japanese here.
- **Language:** the results carry no detected language (`AutoDetectSourceLanguageResult` and the JSON
  are empty of it). A rough check of the text (script and common words) flagged 0–7 finals per clip as another
  language, most in the French clip; it can misjudge short fragments.

### Translation quality, regular pauses

Score out of 100 against what was said (against the written text), critical errors in brackets.

| Direction | A MAI → sol | B MAI → Qwen 3.5 122B | B MAI → Qwen 3.8 2.4T | D MAI → Gemma 4 | **C Azure → sol** (today) |
|---|---|---|---|---|---|
| en→es | 70.0 (63.3) (9) | 61.7 (55.0) (11) | 58.3 (55.0) (11) | 65.0 (58.3) (10) | **80.0 (70.0) (7)** |
| en→pt | 76.7 (68.3) (7) | 65.0 (55.0) (9) | 70.0 (65.0) (7) | 70.0 (61.7) (8) | **85.0 (70.0) (7)** |
| en→fr | 70.0 (68.3) (5) | 65.0 (58.3) (6) | 55.0 (53.3) (5) | 65.0 (60.0) (5) | **76.7 (73.3) (5)** |
| en→ja | 81.7 (70.0) (8) | 63.3 (51.7) (11) | 71.7 (65.0) (9) | 65.0 (60.0) (9) | **86.7 (75.0) (7)** |
| es→en | 89.5 (86.7) (2) | 77.2 (75.0) (2) | 87.7 (85.0) (2) | 84.2 (81.7) (2) | **94.7 (91.7) (1)** |
| pt→en | 88.3 (3) | **91.7 (2)** | **91.7 (2)** | 85.0 (3) | 86.7 (3) |
| fr→en | 85.0 (0) | 80.0 (0) | 83.3 (0) | 83.3 (0) | **86.7 (2)** |
| ja→en | 74.1 (71.7) (3) | 63.0 (61.7) (4) | 68.5 (66.7) (3) | 63.0 (60.0) (4) | **92.6 (91.7) (1)** |
| **Out of English, mean** | 74.6 | 63.8 | 63.8 | 66.2 | **82.1** |
| **Into English, mean** | 84.2 | 78.0 | 82.8 | 78.9 | **90.2** |

With irregular pauses every pipeline drops out of English; the order is the same but closer (means
out of English: A 71.2, B 65.4 / 70.0, D 71.2, C 75.0; into English: A 86.3, B 83.6 / 78.8, D 84.4,
C 88.8). The full table is in `results.json`.

### Latency, regular pauses, p50 / p90 in seconds

| | MAI streaming | Azure standard |
|---|---|---|
| Speech start → first partial | **0.25–0.35 / 0.3–2.5** | 1.0–1.7 / 1.0–3.4 |
| End of speech → last final | 1.2–1.3 / 1.4–4.3 | **0.8–0.9 / 1.0–1.6** |

End of speech → translation complete (median over the four directions of each group):

| | A MAI → sol | B MAI → Qwen 3.5 122B | B MAI → Qwen 3.8 2.4T | D MAI → Gemma 4 | C Azure → sol |
|---|---|---|---|---|---|
| Out of English | 3.7 / 5.4 | 2.9 / 5.6 | 19.3 / 31.9 | **2.3** / 9.6 | 2.9 / 6.1 |
| Into English | 2.7 / 4.0 | 2.6 / 3.7 | 8.7 / 24.5 | 2.3 / 4.2 | **2.2 / 3.5** |
| Translation call alone, p50 | 1.1–2.0 | 1.2–1.5 | 4.7–20.7 | **0.5–1.2** | 1.1–2.2 |

- MAI's first partials come within about 0.3 s of speech, three to five times sooner than Azure
  standard's. Its finals come about 0.4 s later than Azure's, and that is what a translator waits for.
- Qwen 3.8 2.4T is not usable live through zero-retention providers today: 55–85% of its
  calls out of English failed with HTTP 429 during the runs, and the calls that succeeded took 5–21 s
  at the median.
- Gemma 4's calls are the fastest (0.5–1.2 s) but its providers had occasional slow answers (p90
  out of English 9.6 s).
- With irregular pauses, finals that run sentences together push every pipeline's p90 to 14–25 s.

### Cost per hour of speech, one listener language (regular pauses, list prices)

| | Recognition | Translation, out of English | Translation, into English |
|---|---|---|---|
| A MAI → sol | 0.54 | 1.79 | 1.15 |
| B MAI → Qwen 3.5 122B | 0.54 | 0.056 | 0.041 |
| B MAI → Qwen 3.8 2.4T | 0.54 | 1.98 | 1.42 |
| D MAI → Gemma 4 | 0.54 | 0.014 | 0.011 |
| C Azure → sol | 1.00 | 1.54 | 0.87 |

sol costs more per hour here than in `../2026-10-es-pt-live-compare` because each request carries
two finals of context, and MAI's smaller finals mean more requests.

## Conclusions

1. **Today's route, Azure standard → sol, is the most accurate**: 82.1 out of English and 90.2 into
   English, 6–18 points above every MAI pipeline, with the shortest wait for the translation.
2. **MAI-Transcribe-2-Streaming starts showing text sooner** (first partial in about 0.3 s against
   1.0–1.7 s), and it is cheaper (0.54 against 1.00 USD an hour, list), but its finals arrive about
   0.4 s later and are less accurate on English and Japanese. Its many small finals and, with
   irregular pauses, its run-together finals both cost the translator.
3. **Behind MAI, sol is still the best translator**; Qwen 3.5 122B and Gemma 4 are 8–11 points
   behind out of English and 5–6 into English, at about 1–3% of sol's cost.
4. **Qwen 3.8 2.4T** comes within 1.4 points of sol into English when it answers, but its zero-retention
   providers rate-limited it heavily: not usable live today.

## Limits

One 20-sentence read clip per language and pattern, one run per pipeline, one grading round. The
"what was said" references are a model's verbatim transcription. MAI-Transcribe-2-Streaming is a
preview and served from four regions. Microsoft reports MAI-Transcribe-2 results on FLEURS, the
dataset these clips come from.

## Files

- `pipeline.py`: one clip streamed in real time; each final translated by every translator as it
  arrives.
- `fill.py`: re-makes translations that failed live, marked `filled_offline`.
- `analyze.py`: grading jobs, recognition manifest, latency, cost and `results.json`.
- `results.json`: every number above, per direction and pattern.

Transcripts, translations and grades are not committed (they hold FLEURS text in other languages
and the model outputs); the scripts regenerate them.
