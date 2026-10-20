# Translator shootout on Azure's transcripts, October 2026

The production route under consideration: Azure speech-to-text and
text-to-speech, with a translator in the middle. Azure Translator is weak into
English (Japanese and Mandarin speakers 72–82% in `../2026-10-azure-stt-gemini`,
against Gemini's 92–97% on the same transcripts). Does the open stack's
translator do better? Seven translators get **identical sentence text**, and
all 25 directions are graded **blind, side by side, in one round** with one
grader. Grades move 5–10 points between rounds, so earlier rounds' numbers are
not compared with these.

| Translator | How it ran |
|---|---|
| **Hy-MT2 7B, 4-bit NF4** | `tencent/Hy-MT2-7B` at the stack's pinned revision, bitsandbytes NF4, the stack's prompt and decoding (`server/engines/hymt.py`). Not run where it lacks the language (Lao, Haitian Creole): **n/a** |
| **MADLAD-400 7B, int8** | `google/madlad400-7b-mt` at the stack's revision → CTranslate2 int8 (int8_float16 on the GPU), beam 4, `<2xx>` prompt (`server/engines/madlad.py`) |
| TranslateGemma 12B | `google/translategemma-12b-it`, bf16, its own chat template rendered by hand (as `../2026-10-real-voices/text-mt/translate_ht.py`) |
| Azure Translator | `api.cognitive.microsofttranslator.com` v3, eastus |
| Gemini 3.5 Flash @medium, and at default thinking | AI Studio, temperature 0 |
| GPT-5.6-sol @low | Azure AI Foundry deployment `gpt-5.6-sol-us`, `reasoning_effort: low`; a 400 (content filter) would score as a blank (none happened) |

The LLMs share `translate_ht.py`'s prompt with the languages filled in
("Translate this {source} sentence, transcribed from live speech (it may
contain recognition errors), into natural {target}. Keep numbers, names and
negation exact. Output only the {target}."). One call per sentence, as a live
pipeline would make them.

**Inputs** (`shootout.py inputs`):

- `syn:` September's 24 sentences (`../2026-09-model-eval/sentences`: times,
  doses, negations) in synthetic voices, from `../2026-10-azure-stt-gemini`:
  Azure's live transcripts of en, ja, zh, lo, and km (re-run here with
  `azure_stt.py` on eastus; the earlier one had hit a quota). English → ja,
  zh, km, lo, ht, es, fr, ru, de, uk all start from Azure's English transcript.
  Haitian Creole speech: Omnilingual's transcript (Azure has no Haitian Creole).
- `real:` real readers from `../2026-10-real-voices` (FLEURS en/ja/km/lo/fr,
  CMU Haitian Creole; 30 sentences, longer news-style text): Azure's live
  transcripts, Omnilingual's for Haitian Creole. French → English is graded
  against FLEURS's English for the same 30 ids (`refs/meaning_fr.json`, rebuilt
  from `fetch_fr.py`'s seeded choice); Haitian Creole against Gemini 2.5 Pro's
  references (as before).
- Azure's finals are regrouped into the read sentences by their audio offsets;
  a final that ran across a pause is cut where the read sentences end.

**Grading** (`shootout.py grade`): Gemini 3.1 Pro (preview) on AI Studio with
run12's rubric — 0–3 per sentence against the English meaning, plus
"critical" for a wrong number, time, date, dose, amount, negation or
who-did-what — one call per direction with every translator shuffled under
letters. Score = share of the points. **Latency**: per sentence, median. For
the pod models it is GPU time measured on the pod (one sentence at a time, no
batching); the APIs' figure is the round trip from a Mac in the US.

    set -a; . <env>; set +a     # GEMINI_API_KEY, AZURE_KEY, FOUNDRY_ENDPOINT, FOUNDRY_KEY, MT_POD, MT_POD_KEY, HF_TOKEN
    python3 shootout.py inputs && python3 shootout.py translate && python3 shootout.py grade && python3 shootout.py table

The pod: `mt_pod.py` (header has the start command), one RTX 6000 Ada 48 GB
on RunPod Secure Cloud at $0.99/h, about 40 minutes (~$0.65). Translations
and grades stay in `out/` (not committed); `results.json` has every number.

## Results (19 October 2026)

Score (critical errors); best in each row in bold.

| Direction | Hy-MT2 | MADLAD | TGemma 12B | Azure Tr. | Flash @med | Flash default | sol @low |
|---|---|---|---|---|---|---|---|
| syn:en-ja | 97% (0) | 82% (2) | 97% (1) | 93% (1) | **100% (0)** | **100% (0)** | **100% (0)** |
| syn:en-zh | **100% (0)** | 86% (1) | 97% (0) | 99% (0) | **100% (0)** | **100% (0)** | **100% (0)** |
| syn:en-km | **100% (0)** | 74% (2) | 68% (7) | 90% (2) | **100% (0)** | **100% (0)** | 99% (0) |
| syn:en-lo | n/a | 82% (4) | 60% (5) | 79% (1) | 96% (0) | **99% (0)** | **99% (0)** |
| syn:en-ht | n/a | 83% (6) | 69% (4) | 76% (4) | 97% (0) | **100% (0)** | **100% (0)** |
| syn:en-es | **100% (0)** | 94% (1) | **100% (0)** | **100% (0)** | **100% (0)** | **100% (0)** | **100% (0)** |
| syn:en-fr | 92% (0) | 89% (1) | 99% (0) | 93% (1) | **100% (0)** | **100% (0)** | **100% (0)** |
| syn:en-ru | 96% (0) | 94% (1) | 93% (2) | 97% (1) | **100% (0)** | **100% (0)** | **100% (0)** |
| syn:en-de | 90% (2) | 90% (2) | 93% (0) | 99% (0) | **100% (0)** | 97% (0) | **100% (0)** |
| syn:en-uk | 97% (0) | 62% (9) | 97% (0) | **100% (0)** | **100% (0)** | **100% (0)** | **100% (0)** |
| syn:ja-en | 79% (6) | 71% (8) | 81% (5) | 69% (6) | 92% (3) | 94% (2) | **97% (1)** |
| syn:zh-en | 94% (2) | 78% (6) | 88% (3) | 76% (7) | **97% (1)** | **97% (1)** | **97% (1)** |
| syn:km-en | 42% (17) | 32% (17) | 44% (17) | 14% (22) | 65% (12) | 62% (13) | **69% (10)** |
| syn:lo-en | n/a | 42% (15) | 35% (17) | 38% (17) | **50% (15)** | 47% (15) | **50% (14)** |
| syn:ht-en | n/a | 26% (6) | 29% (8) | 17% (6) | 75% (5) | 71% (7) | **78% (4)** |
| real:en-ja | 69% (6) | 53% (9) | 70% (9) | 58% (11) | **82% (5)** | 81% (5) | 79% (5) |
| real:en-km | 70% (10) | 46% (12) | 43% (12) | 59% (12) | 80% (6) | 77% (6) | **81% (6)** |
| real:en-lo | n/a | 58% (13) | 63% (13) | 63% (11) | 77% (7) | 79% (6) | **81% (6)** |
| real:en-ht | n/a | 44% (12) | 64% (7) | 60% (6) | 78% (5) | 77% (4) | **81% (4)** |
| real:en-fr | 71% (6) | 63% (6) | 73% (4) | 58% (7) | 77% (4) | 74% (3) | **79% (4)** |
| real:ja-en | 61% (10) | 62% (14) | 69% (8) | 57% (10) | 82% (5) | 80% (5) | **84% (4)** |
| real:km-en | 59% (13) | 48% (18) | 47% (18) | 48% (18) | 64% (10) | 63% (10) | **68% (10)** |
| real:lo-en | n/a | 28% (24) | 27% (25) | 26% (25) | 53% (16) | **57% (15)** | 53% (17) |
| real:fr-en | 69% (6) | 63% (8) | 70% (8) | 60% (8) | **79% (6)** | **79% (6)** | **79% (6)** |
| real:ht-en | n/a | 36% (21) | 34% (23) | 34% (22) | 90% (3) | 90% (1) | **93% (3)** |

Averages over groups of directions (score, total critical errors):

| Group | Hy-MT2 | MADLAD | TGemma 12B | Azure Tr. | Flash @med | Flash default | sol @low |
|---|---|---|---|---|---|---|---|
| Into English: ja, zh, km, fr (6) | 67% (54) | 59% (71) | 66% (59) | 54% (71) | 80% (37) | 79% (37) | **83% (32)** |
| Out of English: ja, zh, km, es, fr, ru, de, uk (11) | 89% (24) | 76% (46) | 85% (35) | 86% (35) | **94% (15)** | 94% (14) | 94% (15) |
| Lao, both ways (4) | n/a | 52% (56) | 46% (60) | 51% (54) | 69% (38) | 70% (36) | **71% (37)** |
| Haitian Creole, both ways (4) | n/a | 47% (45) | 49% (42) | 47% (38) | 85% (13) | 84% (12) | **88% (11)** |

The open stack's own route (Hy-MT2 where it has the language, else MADLAD):
71% over all 25 directions with 179 critical errors, against Azure
Translator 67% (198), Gemini 3.5 Flash 85% (99–103), GPT-5.6-sol 87% (95).

Median latency per sentence, seconds, median over the directions (per
direction in `results.json`):

| Hy-MT2 | MADLAD | TGemma 12B | Azure Tr. | Flash @med | Flash default | sol @low |
|---|---|---|---|---|---|---|
| 1.1 (GPU; English → Khmer 4.8–8.0) | 0.3 (GPU) | 1.2 (GPU) | **0.17** | 4.7 | 4.7 | 2.0 |

- **Hy-MT2 beats Azure Translator into English** in all six directions it can
  run: Mandarin 94% vs 76%, Japanese 79% vs 69% (synthetic) and 61% vs 57%
  (real), Khmer 42% vs 14% and 59% vs 48%, French 69% vs 60%; 67% vs 54% on
  average, 54 critical errors to 71. But it stays well behind the LLMs (80–83%).
- **Out of English it is mixed.** Hy-MT2 wins Khmer (100% vs 90%; real 70% vs
  59%), Japanese (97 vs 93; real 69 vs 58), French on real voices (71 vs 58)
  and Mandarin narrowly; Azure wins German (99 vs 90), Ukrainian, Russian and
  synthetic French by 1–9 points. Average 89% vs 86%, 24 critical errors to 35.
- **MADLAD does not beat Azure** on average (64% vs 67% over 25 directions);
  it leads on synthetic English → Lao and Haitian Creole (82–83% vs 76–79%)
  but loses both on real voices and makes more critical errors.
  It sometimes passes a misheard sentence through untranslated.
- **Lao and Haitian Creole:** no translator except the two LLMs is usable from
  these transcripts. Into English, Haitian Creole is 90–93% for Flash and sol
  on the real speakers against 34–36% for MADLAD, TranslateGemma and Azure;
  Lao speakers are hard for everyone (Azure heard them badly: 26–57%).
  English → Lao and → Haitian Creole: LLMs 77–100%, the rest 44–83%.
- **GPT-5.6-sol @low** is first or tied in 22 of 25 directions, at 2 s per
  sentence, half Gemini Flash's 4.7 s. Flash at medium thinking and at its
  default scored the same and took the same time. TranslateGemma 12B is about
  Hy-MT2's level where both run, and much weaker on Khmer.
- **Speed:** Azure Translator 0.17 s; MADLAD 0.3 s and Hy-MT2 ~1 s of GPU time
  (plus the network to a GPU host); Hy-MT2 into Khmer takes 5–8 s a sentence
  (Khmer script costs it many tokens).

**Caveats.** The `syn:` set is synthetic speech (macOS voices; Meta MMS for
km/lo/ht), short sentences built to catch critical errors; the `real:` set is
read news-style text from real speakers, where Azure mishears more, so every
score there is lower. One grading round, one grader (a Gemini model, which
may favour Gemini, and Haitian Creole's English references were written by
Gemini 2.5 Pro); compare within this table only. Lao and Khmer speakers'
scores are bounded by what Azure heard, not by the translators alone. Hy-MT2's
first direction ran while the pod was still converting MADLAD and was re-run
for its timing (same outputs). Round-trip times to the pod are not given
here: requests from the open models queued behind each other on the one GPU.


## Round 2: open-weight reasoning LLMs (19 October 2026)

**A separate grading round.** Grades move between rounds, so compare within
this round's tables only, not with round 1's above. Could the open stack use
an open reasoning LLM as its translator instead of Hy-MT2 and MADLAD? Four
open models ran on round 1's inputs (`out/inputs.json`, same 25 directions,
same text), with the LLM prompt above, one sentence per call; their outputs
were graded blind in one new round beside the **saved** outputs of
GPT-5.6-sol @low, Gemini 3.5 Flash @medium, Hy-MT2 and MADLAD (re-graded,
not re-translated). Same grader (Gemini 3.1 Pro preview), same run12 rubric.

| Model | Revision | How it ran |
|---|---|---|
| `openai/gpt-oss-120b` (MXFP4) | `b5c939de8f754692c1647ca79fbf85e8c1e70f8a` | reasoning effort low, and medium |
| `openai/gpt-oss-20b` (MXFP4) | `6cee5e81ee83917806bbde320786a8fb61efebee` | reasoning effort low |
| `Qwen/Qwen3.8-27B-FP8` (dense, Aug 2026; the newest Qwen that fits one GPU) | `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a` | thinking on, `reasoning_effort: low` (its lowest), MTP speculative decoding (3 tokens) |

- Served by vLLM 0.31.0 (`vllm/vllm-openai:v0.31.0`) on one H100 80 GB SXM
  (RunPod Secure Cloud, $3.99/h), `llm_pod.py`. Each model card's sampling for
  reasoning (gpt-oss: temperature 1, top-p 1; Qwen: temperature 1, top-p 0.95,
  top-k 20). Max 4,096 output tokens; none ran out, no blank answers.
- The reasoning is stripped: vLLM's reasoning parser (`openai_gptoss`,
  `qwen3`) returns it apart from the answer, and only the answer is graded.
- **DeepSeek:** no current DeepSeek model fits one GPU (DeepSeek-V4.1-Flash is
  763B). The distill `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B` loaded, but under
  this vLLM its answers came back as raw byte-level tokens ("ĠThreeĠhundred…"),
  so it was dropped rather than graded.
- `ROUND=2 python3 shootout.py grade` / `table` write
  `out/grades-gemini-3.1-pro-preview-round2.json` and `results-round2.json`;
  round 1's files are untouched.

Score (critical errors); best in each row in bold.

| Direction | oss-120b @low | oss-120b @med | oss-20b @low | Qwen3.8-27B @low | Hy-MT2 | MADLAD | Flash @med | sol @low |
|---|---|---|---|---|---|---|---|---|
| syn:en-ja | 92% (0) | 93% (1) | 90% (1) | 94% (1) | 99% (0) | 81% (1) | **100% (0)** | **100% (0)** |
| syn:en-zh | 94% (0) | 94% (1) | 93% (0) | **100% (0)** | 99% (0) | 83% (1) | **100% (0)** | **100% (0)** |
| syn:en-km | 72% (2) | 76% (1) | 57% (4) | 65% (0) | **100% (0)** | 82% (1) | **100% (0)** | **100% (0)** |
| syn:en-lo | 39% (9) | 43% (8) | 4% (11) | 29% (8) | n/a | 85% (3) | 96% (0) | **99% (0)** |
| syn:en-ht | 97% (0) | 93% (1) | 69% (3) | 56% (6) | n/a | 76% (6) | 99% (0) | **100% (0)** |
| syn:en-es | **100% (0)** | 97% (1) | 94% (0) | 97% (0) | **100% (0)** | 92% (1) | **100% (0)** | **100% (0)** |
| syn:en-fr | 96% (0) | 93% (1) | 86% (2) | 97% (0) | 93% (0) | 86% (1) | **100% (0)** | **100% (0)** |
| syn:en-ru | 96% (0) | 97% (0) | 90% (1) | 94% (1) | 96% (0) | 92% (2) | **100% (0)** | **100% (0)** |
| syn:en-de | 93% (1) | 90% (2) | 92% (1) | 93% (2) | 89% (3) | 89% (2) | **100% (0)** | **100% (0)** |
| syn:en-uk | 93% (0) | 85% (1) | 75% (1) | 90% (0) | 94% (0) | 60% (1) | 99% (0) | **100% (0)** |
| syn:ja-en | 88% (4) | 86% (5) | 88% (4) | 90% (3) | 82% (6) | 78% (7) | 93% (2) | **97% (1)** |
| syn:zh-en | 90% (3) | 88% (3) | 88% (3) | 93% (2) | 93% (2) | 76% (6) | **97% (1)** | **97% (1)** |
| syn:km-en | 31% (18) | 26% (18) | 22% (17) | 32% (19) | 40% (14) | 26% (17) | **65% (10)** | **65% (9)** |
| syn:lo-en | 17% (6) | 15% (6) | 6% (2) | 35% (5) | n/a | 39% (2) | 49% (9) | **50% (8)** |
| syn:ht-en | 26% (13) | 33% (13) | 25% (15) | 38% (12) | n/a | 26% (13) | 76% (5) | **81% (5)** |
| real:en-ja | 68% (3) | 72% (3) | 61% (5) | 77% (4) | 73% (3) | 58% (4) | **84% (1)** | 81% (3) |
| real:en-km | 34% (9) | 51% (9) | 22% (5) | 39% (10) | 70% (10) | 46% (12) | **81% (5)** | 80% (7) |
| real:en-lo | 31% (6) | 24% (4) | 1% (1) | 19% (5) | n/a | 58% (9) | 78% (5) | **83% (4)** |
| real:en-ht | 60% (6) | 60% (8) | 56% (7) | 49% (6) | n/a | 41% (11) | 74% (6) | **80% (4)** |
| real:en-fr | 52% (5) | 60% (5) | 53% (5) | 71% (4) | 66% (5) | 57% (5) | 74% (3) | **77% (3)** |
| real:ja-en | 61% (4) | 59% (4) | 61% (3) | 73% (2) | 66% (3) | 60% (5) | 84% (3) | **87% (2)** |
| real:km-en | 32% (18) | 34% (20) | 29% (20) | 34% (20) | 53% (15) | 38% (18) | 64% (13) | **66% (13)** |
| real:lo-en | 9% (30) | 12% (29) | 2% (30) | 28% (26) | n/a | 34% (23) | **63% (14)** | **63% (15)** |
| real:fr-en | 61% (12) | 63% (11) | 60% (12) | 73% (9) | 71% (9) | 66% (10) | **81% (6)** | **81% (7)** |
| real:ht-en | 30% (22) | 40% (20) | 23% (24) | 41% (20) | n/a | 33% (23) | 87% (3) | **91% (3)** |

Averages over groups of directions (mean of the directions' scores, total
critical errors):

| Group | oss-120b @low | oss-120b @med | oss-20b @low | Qwen3.8-27B @low | Hy-MT2 | MADLAD | Flash @med | sol @low |
|---|---|---|---|---|---|---|---|---|
| Into English: ja, zh, km, fr (6) | 60% (59) | 59% (61) | 58% (59) | 66% (55) | 68% (49) | 57% (63) | 81% (35) | **82% (33)** |
| Out of English: ja, zh, km, es, fr, ru, de, uk (11) | 81% (20) | 83% (25) | 74% (25) | 84% (22) | 89% (21) | 75% (31) | **94% (9)** | 94% (13) |
| Lao, both ways (4) | 24% (51) | 24% (47) | 3% (44) | 28% (44) | n/a | 54% (37) | 71% (28) | **74% (27)** |
| Haitian Creole, both ways (4) | 53% (41) | 57% (42) | 43% (49) | 46% (44) | n/a | 44% (53) | 84% (14) | **88% (12)** |
| All 25 directions | 62% (171) | 64% (175) | 54% (177) | 64% (165) | n/a | 62% (184) | 86% (86) | **87% (85)** |

The open stack's own route (Hy-MT2 where it has the language, else MADLAD):
71% (160) in this round.

Latency per sentence, seconds, on the pod (APIs: round trip from the Mac, as
in round 1). The full passes ran 4–6 sentences in flight to save GPU time, so
"median over directions" is a little slow; the **single stream** rows are a
second pass of 50 sentences (two per direction) one at a time. Per direction
in `results-round2.json`.

| | oss-120b @low | oss-120b @med | oss-20b @low | Qwen3.8-27B @low | Hy-MT2 | MADLAD | Flash @med | sol @low |
|---|---|---|---|---|---|---|---|---|
| median over directions | 1.05 | 2.18 | 0.52 | 3.20 | 1.13 | 0.31 | 4.70 | 2.02 |
| single stream, median (50) | 0.62 | 1.38 | 0.41 | 2.77 | - | - | - | - |
| single stream, p90 (50) | 1.48 | 4.27 | 0.73 | 6.92 | - | - | - | - |
| completion tokens, median (50) | 127.0 | 299.0 | 112.0 | 506.0 | - | - | - | - |

- **No open reasoning LLM comes close to sol or Flash.** Overall 54–64%
  against 86–87%, with about twice the critical errors (165–177 against
  85–86). The best, Qwen3.8-27B and gpt-oss-120b @medium, tie with MADLAD
  (62–64%) and stay under the stack's own route (71%).
- **Into English they do not beat Hy-MT2:** 58–60% for gpt-oss, 66% for
  Qwen3.8-27B, against Hy-MT2 68% and sol / Flash 81–82%. They do not repair
  recognition errors the way sol does: on misheard Khmer and Haitian Creole
  they translate the garble or guess, and on Khmer speech they get doses
  and times wrong ("more than five tablets" for six).
- **Out of English** they are close to Hy-MT2 on the big languages (Spanish,
  French, Russian, German, Chinese, Japanese 85–100% on the synthetic set
  for gpt-oss-120b and Qwen) but weaker on Khmer and on the real readers:
  74–84% against Hy-MT2 89%, sol / Flash 94%.
- **Lao is not usable** (3–28% over the four Lao directions; gpt-oss-20b
  4% and 1% out of English); English → Lao sometimes comes out in Thai.
  MADLAD 54%, sol 74%.
- **Haitian Creole:** gpt-oss-120b writes it well from clean English
  (synthetic en → ht 93–97%, as good as sol) but cannot read Omnilingual's
  transcripts (ht → en 26–40% against sol's 81–91%). Over the four
  directions 43–57%, against MADLAD 44% and sol 88%.
- **Medium effort does not help gpt-oss-120b** (64% vs 62%, more critical
  errors) and doubles its time.
- **Speed:** gpt-oss-20b 0.4 s and gpt-oss-120b @low 0.6 s per sentence
  (single stream, H100), about MADLAD/Hy-MT2 speed; gpt-oss-120b @medium
  1.4 s; Qwen3.8-27B thinks ~500 tokens a sentence, 2.8 s (p90 6.9 s) even
  with MTP. **Memory:** gpt-oss-120b needs ~65 GB of weights, so it does not
  fit the stack's 24–48 GB card; gpt-oss-20b (~13 GB) and Qwen3.8-27B FP8
  (~31 GB, or ~15 GB in 4-bit) would fit, but they are the weaker ones here.

**Caveats.** One round, one grader (a Gemini model; Gemini Flash is in the
round). Sampled decoding (temperature 1, as the model cards recommend), one
sample per sentence. Qwen3.8-27B was run thinking at its lowest effort, not
non-thinking. The H100 is faster than the stack's GPU, so the latencies are a
lower bound for a 24–48 GB card. The pod ran about 50 minutes (~$3.30).
