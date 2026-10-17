# Azure speech-to-text → Gemini voice, October 2026

Does better *hearing* fix Gemini? September's evaluation found Gemini Live's
losses were "mostly mishearings, not mistranslations"
([`docs/dev/model-evaluation.md`](../../docs/dev/model-evaluation.md)). This
round puts Azure's live speech-to-text in front of Gemini — Azure transcribes
the speaker once, each finished sentence goes as text to a Gemini Live session
that says the translation — and runs Gemini Live Translate on the same audio
as the baseline.

| Step | Script |
|---|---|
| Source audio: September's 24 sentences, macOS voices (en, ja, zh) and Meta MMS (km, lo, ht), 0.8 s pauses | `make_audio.py` |
| Azure live speech-to-text, fed in real time (Python SDK; the Node one never connected on Node 26) | `azure_stt.py` |
| Azure's text → Gemini Live (text in, voice out); and Gemini Live Translate on the audio | `gemini_live.mjs pipe` / `live` |
| Blind grading with September's grader and prompt; delay; character error rate of what each one heard | `judge.py` |

Directions: English → Japanese, Mandarin, Khmer, Lao, Haitian Creole, and each
of those → English.

**Delay** is measured per sentence: from the end of the sentence in the clip to
the start of the next translated audio, median over the 24.

Run it all with `bash run.sh <env file with AZURE_SPEECH_KEY and AZURE_SPEECH_REGION>`
(Gemini uses your `gcloud` login and project). Audio, raw outputs and the venv
are not committed; `results.json` is.

## Results (17 October 2026)

Blind-graded by Gemini 2.5 Pro with September's prompt; score = share of the
24 sentences' points (3 each); "crit" = sentences with a wrong number, time,
dose, negation or who-did-what. Delay for the pipeline = from the end of each
sentence to the start of its translated audio (median); Gemini Live speaks
mid-sentence, so it has no comparable per-sentence figure.

| Direction | Azure STT → Gemini | Gemini Live | Azure heard (CER) | Gemini heard (CER) |
|---|---|---|---|---|
| en→ja | **90%** (0 crit), 1.3 s | 74% (4 crit) | 4% | 3% |
| en→zh | **100%** (0 crit), 1.3 s | 74% (6 crit) | 4% | 4% |
| en→km | 83% (0 crit), 1.3 s | 83% (2 crit) | 4% | 4% |
| en→lo | **89%** (0 crit), 1.4 s | 83% (2 crit) | 4% | 4% |
| en→ht | 88% (2 crit), 1.3 s | 88% (0 crit) | 4% | 4% |
| ja→en | **94%** (1 crit), 1.3 s | 50% (5 crit) | 4% | 20% |
| zh→en | **97%** (1 crit), 1.4 s | 58% (8 crit) | 2% | 6% |
| km→en | — (Azure quota exceeded) | 35% (10 crit) | — | 23% |
| lo→en | **56%** (9 crit), 1.3 s | 35% (8 crit) | 22% | (other script) |
| ht→en | — (no Azure Haitian Creole) | 38% (10 crit) | — | 28% |

- **Better hearing is the difference.** Into English from Japanese and
  Mandarin, Azure misheard 2–4% of characters against Gemini Live's 6–20%, and
  the pipeline scored 94–97% against 50–58%.
- **Out of English, Gemini translating from clean text** beat Gemini Live
  interpreting the audio in Japanese and Mandarin, tied in Khmer and Haitian
  Creole, and made almost no critical errors.
- **Delay:** about 1.3 s after each sentence ends (Azure's final ~0.8 s, Gemini's
  first audio ~0.5 s after that), close to the open stack's 0.8 s.
- **Low-resource speakers stay hard.** Azure heard Lao with 22% error and the
  pipeline still scored only 56%; it has no Haitian Creole, and Khmer could not
  be run (the Azure account's quota ran out).
- **Caveats:** synthetic speech only (macOS voices; MMS for km/lo/ht, which may
  be harder to hear than September's VoxCPM2 voices, so the km/lo/ht→en Gemini
  Live scores are well below September's); one run; the grader is Gemini.
- **Harness note:** one long Gemini session per direction re-translated every
  earlier sentence as they piled up; the pipeline uses a fresh session per
  sentence (opened while the previous one speaks). Gemini Live Translate streams
  audio until the session closes, so no "finished speaking" time is reported
  for it.

## Round 2: Azure alone as a third contender (17 October 2026)

`azure_translate.py`: Azure's speech translation on the same clips (one
recogniser per clip, every target at once, as the app runs it), its delay =
when the translated text arrived after the sentence ended + Azure's neural
voice starting (measured on five sentences per language, 200–420 ms). All
three graded side by side again, so the other two columns moved a few points
from round 1 (the grader's run-to-run spread).

| Direction | Azure only | Azure STT → Gemini | Gemini Live |
|---|---|---|---|
| en→ja | **96%** (0 crit), 1.0 s | 86% (0 crit), 1.3 s | 65% (4 crit) |
| en→zh | **99%** (0 crit), 0.9 s | 96% (0 crit), 1.3 s | 74% (5 crit) |
| en→km | **88%** (0 crit), 1.2 s | 81% (0 crit), 1.3 s | 78% (2 crit) |
| en→lo | 79% (0 crit), 1.1 s | **92%** (0 crit), 1.4 s | 81% (2 crit) |
| en→ht | 69%, captions only (no Azure voice) | **89%** (1 crit), 1.3 s | 83% (1 crit) |
| ja→en | 72% (3 crit), 1.0 s | **92%** (1 crit), 1.3 s | 50% (6 crit) |
| zh→en | 82% (2 crit), 1.1 s | **97%** (1 crit), 1.4 s | 64% (7 crit) |
| km→en | 38% (4 crit), 1.0 s | — (Azure quota, round 1) | 39% (9 crit) |
| lo→en | 44% (11 crit), 1.0 s | **61%** (9 crit), 1.3 s | 49% (8 crit) |
| ht→en | — (no Azure Haitian Creole) | — | 36% (9 crit) |

- **Out of English, Azure's own translator wins** Japanese, Mandarin and Khmer,
  and is the quickest (~1 s). Gemini from Azure's text wins Lao and Haitian
  Creole (which Azure can't voice).
- **Into English, Gemini from Azure's text wins every time** (Japanese 92% vs
  72%, Mandarin 97% vs 82%, Lao 61% vs 44%): the same transcript, translated
  better by Gemini.
- Both beat Gemini Live everywhere except Lao/Haitian Creole listeners.
