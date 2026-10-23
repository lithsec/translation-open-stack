# Gemma 4 on Azure's transcripts: an addendum to the translator shootout

`../2026-10-translator-shootout` gave seven translators the same sentence text,
mostly Azure speech-to-text transcripts, and graded them blind. This addendum asks
whether Google's open Gemma 4 can stand in for sol as the translator behind Azure
recognition. Gemma 4 led the Haitian Creole/Lao shootout on correct text
(`../2026-10-ht-lo-translators`), and English is the focus here.

**Systems** (eight, one blind round, 25 directions):

| System | How it ran |
|---|---|
| **Gemma 4 31B** (`google/gemma-4-31b-it`, Apache-2.0) | OpenRouter, bf16, zero data retention required, temperature 0, reasoning off |
| **Gemma 4 26B-A4B** (`google/gemma-4-26b-a4b-it`, Apache-2.0) | same; the paid endpoint, not `:free` |
| Hy-MT2 7B NF4, MADLAD-400 7B int8, TranslateGemma 12B, Azure Translator, Gemini 3.5 Flash @medium, GPT-5.6-sol @low | the original shootout's saved outputs, unchanged (not re-translated) |

The Gemma 4 models get the original shootout's LLM prompt, the one Flash and sol
were given: "Translate this {source} sentence, transcribed from live speech (it
may contain recognition errors), into natural {target}. Keep numbers, names and
negation exact. Output only the {target}." This is not the correct-text prompt of
`../2026-10-ht-lo-translators`. The input here is recognition output, and every
LLM in the round should be told the same thing. One sentence per call.

**Inputs and grading** are the original shootout's: its `out/inputs.json`
(the `syn:` and `real:` sets; Azure's transcripts, Omnilingual's for Haitian
Creole), and its grader and rubric (`shootout.grade_one`: Gemini 3.1 Pro preview,
0–3 per sentence against the English meaning, plus a critical flag; all systems
shuffled under letters, one call per direction). **All eight systems were graded
again together in this round**, because grades move 5–10 points between rounds.
Compare the numbers below with each other, never with the original README's.

    # needs the original shootout's out/ (not committed): run ../2026-10-translator-shootout first
    export OPENROUTER_API_KEY=... GEMINI_API_KEY=... SHOOTOUT_OUT=../2026-10-translator-shootout/out
    python3 gemma4.py translate && python3 gemma4.py grade && python3 gemma4.py table

## Results (22 October 2026)

Score (critical errors); best in each row in bold. `results.json` has every number.

| Direction | Hy-MT2 | MADLAD | TGemma 12B | Azure Tr. | Flash @med | sol @low | Gemma 4 31B | Gemma 4 26B |
|---|---|---|---|---|---|---|---|---|
| syn:en-ja | 99% (0) | 94% (2) | 97% (0) | 96% (1) | **100% (0)** | **100% (0)** | **100% (0)** | **100% (0)** |
| syn:en-zh | 99% (0) | 89% (1) | 92% (2) | 99% (0) | **100% (0)** | **100% (0)** | 96% (1) | 99% (0) |
| syn:en-km | **100% (0)** | 65% (1) | 57% (1) | 89% (0) | **100% (0)** | 99% (0) | 97% (0) | **100% (0)** |
| syn:en-lo | n/a | 83% (3) | 61% (1) | 79% (1) | 96% (0) | **99% (0)** | 97% (0) | 94% (0) |
| syn:en-ht | n/a | 79% (6) | 57% (10) | 71% (6) | 99% (0) | **100% (0)** | 90% (3) | 94% (2) |
| syn:en-es | **100% (0)** | 94% (1) | **100% (0)** | **100% (0)** | **100% (0)** | **100% (0)** | **100% (0)** | **100% (0)** |
| syn:en-fr | 93% (0) | 89% (1) | 99% (0) | 93% (1) | **100% (0)** | **100% (0)** | 99% (0) | 97% (0) |
| syn:en-ru | 96% (0) | 93% (2) | 93% (0) | 97% (1) | **100% (0)** | **100% (0)** | **100% (0)** | **100% (0)** |
| syn:en-de | 90% (2) | 89% (1) | 94% (0) | 99% (0) | **100% (0)** | **100% (0)** | **100% (0)** | 99% (0) |
| syn:en-uk | 94% (0) | 58% (9) | 96% (1) | 99% (0) | 99% (0) | **100% (0)** | 97% (0) | 94% (1) |
| syn:ja-en | 82% (6) | 75% (8) | 83% (5) | 75% (6) | 92% (3) | **97% (1)** | 89% (4) | 86% (5) |
| syn:zh-en | 96% (1) | 78% (5) | 89% (2) | 74% (3) | **97% (1)** | **97% (1)** | **97% (1)** | 96% (1) |
| syn:km-en | 42% (8) | 32% (9) | 44% (11) | 18% (10) | **68% (4)** | **68% (5)** | 53% (7) | 46% (8) |
| syn:lo-en | n/a | 29% (16) | 25% (18) | 25% (19) | 43% (16) | **44% (15)** | 35% (17) | 32% (17) |
| syn:ht-en | n/a | 28% (8) | 29% (10) | 17% (6) | 74% (6) | **78% (6)** | 40% (14) | 33% (11) |
| real:en-ja | 71% (3) | 52% (2) | 70% (2) | 59% (3) | **82% (2)** | 80% (3) | 76% (2) | 77% (2) |
| real:en-km | 68% (5) | 50% (7) | 54% (8) | 53% (6) | 81% (4) | **82% (3)** | 74% (3) | 68% (4) |
| real:en-lo | n/a | 56% (9) | 66% (8) | 60% (7) | 78% (5) | **82% (4)** | 72% (5) | 66% (7) |
| real:en-ht | n/a | 49% (13) | 64% (8) | 61% (6) | 74% (6) | **80% (5)** | 69% (5) | 68% (7) |
| real:en-fr | 69% (5) | 60% (6) | 76% (4) | 58% (7) | 76% (3) | **81% (3)** | 78% (3) | 68% (5) |
| real:ja-en | 60% (12) | 62% (14) | 66% (9) | 58% (13) | 81% (4) | **83% (3)** | 68% (9) | 62% (10) |
| real:km-en | 59% (13) | 47% (14) | 51% (14) | 49% (17) | 67% (10) | **69% (9)** | 51% (14) | 51% (13) |
| real:lo-en | n/a | 13% (25) | 21% (24) | 17% (26) | **47% (15)** | 42% (18) | 30% (21) | 23% (23) |
| real:fr-en | 82% (2) | 74% (2) | 86% (2) | 72% (2) | **88% (2)** | **88% (2)** | 84% (2) | 80% (2) |
| real:ht-en | n/a | 38% (22) | 38% (25) | 40% (24) | **93% (4)** | **93% (3)** | 54% (19) | 31% (27) |

Group averages (mean of the directions' scores; total critical errors):

| Group | Hy-MT2 | MADLAD | TGemma 12B | Azure Tr. | Flash @med | sol @low | Gemma 4 31B | Gemma 4 26B |
|---|---|---|---|---|---|---|---|---|
| Into English: ja, zh, km, fr (6) | 70% (42) | 61% (52) | 70% (43) | 58% (51) | 82% (24) | **84% (21)** | 74% (37) | 70% (39) |
| Out of English: ja, zh, km, es, fr, ru, de, uk (11) | 89% (15) | 76% (33) | 84% (18) | 86% (19) | 94% (9) | **95% (9)** | 92% (9) | 91% (12) |
| Lao, both ways (4) | n/a | 45% (53) | 43% (51) | 45% (53) | 66% (36) | **67% (37)** | 58% (43) | 54% (47) |
| Haitian Creole, both ways (4) | n/a | 48% (49) | 47% (53) | 47% (42) | 85% (16) | **88% (14)** | 64% (41) | 57% (47) |
| All 25 directions | n/a | 63% (187) | 68% (165) | 66% (165) | 85% (85) | **86% (81)** | 78% (130) | 75% (145) |

**OpenRouter figures** (hosted, not the stack's GPU; round trip from a Mac in the US):

| | Gemma 4 31B | Gemma 4 26B-A4B |
|---|---|---|
| Providers that served it (bf16, ZDR) | Novita 558, Crusoe 102 | DekaLLM 199, NextBit 152, Io Net 103, CoreWeave 83, Venice 55, Parasail 50, Novita 18 |
| Round trip p50 / p90 | 1.39 / 2.59 s | 0.73 / 1.68 s |
| Mean tokens per sentence, prompt / completion | 74.5 / 25.8 | 74.5 / 26.2 |
| List price per hour of speech (392 sentences, from the usage OpenRouter reported) | $0.008 | $0.006 |
| Blank answers | 0 of 660 | 0 of 660 |

## What it shows

- **Out of English, Gemma 4 31B is close to sol and ahead of Hy-MT2.** It scores
  92% with 9 critical errors over the 11 out-of-English directions, against sol's 95% (9)
  and Hy-MT2's 89% (15). On the typed (`syn:`) sentences it ties sol in most
  directions. On real readers it trails sol by 2–10 points:

  | Direction | Gemma 4 31B | sol | Hy-MT2 |
  |---|---|---|---|
  | en→ja | 76 | 80 | 71 |
  | en→km | 74 | 82 | 68 |
  | en→fr | 78 | 81 | 69 |
  | en→lo | 72 | 82 | – |
  | en→ht | 69 | 80 | – |

- **Into English it is not a stand-in.** It scores 74% (37 critical) against sol's
  84% (21), only a little above Hy-MT2's 70%. The gap is largest where the
  transcript is poor. Haitian Creole into English on Omnilingual's transcripts is
  54% and 40%, against sol's 93% and 78%, and Lao and Khmer into English trail by
  12–17 points. On correct text Gemma 4 scored 86 for Haitian Creole into English
  (`../2026-10-ht-lo-translators`). The loss here is in recovering meaning from
  recognition errors, which sol and Flash do far better.
- **The 26B-A4B is faster and slightly weaker** (75% overall vs 78%), with most of
  the difference into English and in Haitian Creole.
- **For an Azure-recognition route out of English**, Gemma 4 31B costs under a
  cent per hour of speech on OpenRouter, a few points below sol. Into English, and
  for Haitian Creole, Lao and Khmer sources, sol (or Flash) stays well ahead.

Caveats: one round, one grader, 24–30 sentences per direction. Hosted bf16 on
OpenRouter's providers, not a self-hosted build. The `real:` English references
are FLEURS's text, so a reader who departs from it costs every system alike.
