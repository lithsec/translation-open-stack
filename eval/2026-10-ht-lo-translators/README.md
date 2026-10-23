# Haitian Creole and Lao translators on correct text, October 2026

The open stack translates Haitian Creole and Lao with MADLAD-400 7B, because
Hy-MT2 has neither language. Earlier rounds put MADLAD well below the cloud
models in these directions. Can another open model replace it? This round
gives every candidate the **same correct text**, with no speech recognition in
the loop, in four directions: English → Haitian Creole, Haitian Creole →
English, English → Lao and Lao → English. All outputs are graded blind, side
by side, in **one round**, by one grader. Grades move 5–10 points between
rounds, so compare within these tables only. MADLAD's scores here are not
comparable with its scores in `../2026-10-open-stack-e2e`.

## Systems

| System | Licence | How it ran |
|---|---|---|
| MADLAD-400 7B | Apache-2.0 | `google/madlad400-7b-mt` at the stack's revision. **bf16 under transformers**, beam 4, `<2xx>` prompt; the stack runs it as CTranslate2 int8. |
| MADLAD-400 10B | Apache-2.0 | `google/madlad400-10b-mt` (`9f27976`), the same settings |
| NLLB-200 3.3B | **CC-BY-NC-4.0** (non-profit edition only) | `facebook/nllb-200-3.3B` (`1a07f7d`), transformers bf16, beam 4 |
| TranslateGemma 27B | Gemma terms | `google/translategemma-27b-it` (`7d10f0b`), vLLM bf16, the card's chat template, greedy |
| MiLMMT-46 12B | Gemma terms | `xiaomi-research/MiLMMT-46-12B-v0.1` (`7aaf496`; Gemma 3 continued on 46 languages, Lao but **no Haitian Creole**), vLLM bf16, the card's prompt, greedy |
| Gemma 4 31B | Apache-2.0 | `google/gemma-4-31b-it` through OpenRouter, pinned to bf16 hosts (Crusoe, Novita), temperature 0 |
| Qwen3.5-122B-A10B | Apache-2.0 | `qwen/qwen3.5-122b-a10b` through OpenRouter, pinned to bf16 (Novita), thinking off, temperature 0 |
| gpt-oss-120b @low | Apache-2.0 | `openai/gpt-oss-120b` through OpenRouter, pinned to fp4 (its release format; Near AI, CoreWeave, BaseTen and others), reasoning effort low, the card's sampling |
| GPT-5.6-sol @low | closed | Azure AI Foundry (Data Zone), `reasoning_effort: low`: the cloud bar |

The LLMs share one prompt: "Translate this {source} sentence into natural
{target}. Keep numbers, names and negation exact. Output only the {target}."
They get one sentence per call. TranslateGemma and MiLMMT use their own
model-card prompts.

- **OpenRouter** requests set `"provider": {"zdr": true}` (zero data
  retention) and pin the precision. Each sentence's serving provider is kept
  in `out/` (not committed). Hosted precision can differ from what we would
  self-host: here Qwen ran in bf16, but the 80 GB card below holds only its
  GPTQ Int4 build.
- **The pod**: one A100 SXM 80 GB, `vllm/vllm-openai:v0.31.0`
  (`pod_run.py`, `run.sh`). It ran the models OpenRouter doesn't host. For
  Qwen3.5-122B (GPTQ Int4) and Gemma 4 31B (bf16) it ran only the timing
  sample, to measure **our** GPU's speed and memory.
- **MADLAD in bf16, not int8.** CTranslate2's converter ran for 10–17 minutes
  on 13 cores without writing output, for both sizes, so both ran under
  transformers. The stack's int8 build
  is not compared with bf16 here; the two may differ a little. Its speed here
  is transformers' speed, not the stack's: CTranslate2 int8 takes about 0.3 s
  a sentence (`../2026-10-translator-shootout`).

## Sentences

| Set | n | Direction | Source | English meaning (graded against) |
|---|---|---|---|---|
| `sept` | 24 each | en↔ht, en↔lo | September's short sentences built to catch critical errors (times, doses, negation) | the English originals |
| `fleurs` | 60 (40 for en→ht) | en→lo, lo→en, en→ht | FLEURS / FLoRes test sentences (CC BY 4.0): long news-style text, a seeded draw that excludes the 30 the real-voice rounds used | FLoRes's professional English |
| `cmu` | 30 | ht→en | CMU Haitian Creole speech prompts (read text) | Gemini 2.5 Pro's English (`../2026-10-real-voices`) |
| `news` | 33 each | ht→en, en→ht | Five minutes of continuous VOA Kreyòl studio news (`../2026-10-continuous-ht`) | Gemini 3.1 Pro's English. **The text is not committed: only scores.** |

That gives en→ht 97 sentences, ht→en 87, en→lo 84 and lo→en 84.

**Grading** (`htlo.py grade`): `gemini-3.1-pro-preview`, with the translator
shootout's rubric.
- Each sentence scores 0–3 against the English meaning, with "critical"
  marked for a wrong number, time, date, dose, amount, negation or
  who-did-what.
- Each chunk of up to 30 sentences is one call, with all nine systems
  shuffled under letters.
- Score = share of the possible points. Critical errors are in brackets.

## Results (22 October 2026)

| System | Licence | en→ht | ht→en | en→lo | lo→en | A100 p50 / p90 (s) | A100 tok/s | Memory |
|---|---|---|---|---|---|---|---|---|
| GPT-5.6-sol @low (cloud) | closed | **99 (0)** | **98 (2)** | **99 (0)** | **98 (0)** | API 2.3 | - | - |
| **Gemma 4 31B** | Apache-2.0 | **90 (2)** | 86 (13) | **94 (2)** | 95 (1) | 1.03 / 2.48 | 23 | 58 GiB weights (bf16) |
| MiLMMT-46 12B | Gemma terms | n/a | n/a | **94 (2)** | **98 (0)** | 0.44 / 1.08 | 54 | 23 GiB weights (bf16) |
| TranslateGemma 27B | Gemma terms | 85 (10) | 78 (22) | 86 (7) | 92 (4) | 0.95 / 2.44 | 27 | 51 GiB weights (bf16) |
| Qwen3.5-122B-A10B | Apache-2.0 | 77 (14) | **87 (9)** | 62 (24) | 88 (7) | 0.43 / 1.02 (Int4) | 59 | 68 GiB weights (Int4) |
| MADLAD-400 7B (the stack) | Apache-2.0 | 78 (15) | 77 (19) | 80 (10) | 88 (7) | 1.43 / 3.11 (bf16) | 17 | 18 GiB peak (bf16) |
| NLLB-200 3.3B | **non-profit only** | 78 (5) | 81 (15) | 75 (17) | 80 (15) | 0.39 / 0.70 | 60 | 7 GiB peak |
| MADLAD-400 10B | Apache-2.0 | 72 (16) | 69 (26) | 73 (18) | 86 (10) | 0.91 / 1.88 (bf16) | 25 | 21 GiB peak (bf16) |
| gpt-oss-120b @low | Apache-2.0 | 87 (4) | 81 (16) | 16 (46) | 34 (46) | not run on the pod | - | ~65 GB (fp4) |

**How to read the speed and memory columns**
- **Speed:** single-stream, one sentence at a time, measured on the A100 on
  the same 40 sentences (10 per direction) for every model.
- **API figures:** the cloud and OpenRouter round trips from a Mac. They are
  **not** GPU latency: Gemma 4 2.4 s, Qwen 1.3 s, gpt-oss 4.4 s.
- **Memory:** "weights" is vLLM's figure for the loaded model. vLLM then
  fills the card with KV cache up to its limit. "Peak" is nvidia-smi's peak
  for the seq2seq models.

**Qwen3.5-122B on an 80 GB card**
- With the e2e round's settings (MTP speculative decoding, 0.94 of memory)
  its weights took 72.4 GiB and left no room for the KV cache.
- Without MTP, at 0.98 of memory and 2,048 tokens of context, it took
  67.7 GiB with 8 GiB of cache.

Per set (score, critical errors):

| Set | n | sol | Gemma 4 31B | MiLMMT 12B | TGemma 27B | Qwen3.5-122B | MADLAD 7B | NLLB 3.3B | MADLAD 10B | oss-120b |
|---|---|---|---|---|---|---|---|---|---|---|
| sept:en-ht | 24 | 100 (0) | 93 (1) | n/a | 93 (2) | 79 (3) | 82 (5) | 88 (2) | 81 (4) | 93 (0) |
| fleurs:en-ht | 40 | 99 (0) | 82 (1) | n/a | 85 (2) | 68 (6) | 66 (8) | 66 (2) | 58 (8) | 78 (2) |
| news:en-ht | 33 | 98 (0) | 97 (0) | n/a | 80 (6) | 88 (5) | 90 (2) | 86 (1) | 82 (4) | 93 (2) |
| sept:ht-en | 24 | 100 (0) | 89 (3) | n/a | 78 (7) | 85 (3) | 76 (7) | 81 (6) | 65 (10) | 79 (6) |
| cmu:ht-en | 30 | 97 (1) | 84 (5) | n/a | 70 (11) | 88 (3) | 82 (5) | 77 (6) | 69 (8) | 78 (7) |
| news:ht-en | 33 | 97 (1) | 86 (5) | n/a | 87 (4) | 89 (3) | 74 (7) | 85 (3) | 72 (8) | 86 (3) |
| sept:en-lo | 24 | 100 (0) | 99 (0) | 97 (0) | 83 (3) | 64 (8) | 85 (3) | 83 (4) | 82 (4) | 28 (17) |
| fleurs:en-lo | 60 | 98 (0) | 92 (2) | 92 (2) | 88 (4) | 61 (16) | 78 (7) | 71 (13) | 69 (14) | 11 (29) |
| sept:lo-en | 24 | 100 (0) | 100 (0) | 100 (0) | 97 (1) | 92 (3) | 92 (3) | 76 (8) | 85 (5) | 38 (17) |
| fleurs:lo-en | 60 | 97 (0) | 93 (1) | 97 (0) | 89 (3) | 87 (4) | 87 (4) | 81 (7) | 86 (5) | 33 (29) |

## Findings

- **Gemma 4 31B (Apache-2.0) is the best open model in all four directions
  together:** 90 / 86 / 94 / 95, against MADLAD 7B's 78 / 77 / 80 / 88. It
  has far fewer critical errors out of English (2 + 2 against 15 + 10), and
  13 against 19 into English from Haitian Creole. It still trails sol by 4–12
  points.
- **Lao is solved on correct text.** MiLMMT-46 12B (94 / 98, no critical
  errors into English) matches Gemma 4 31B at under half the size and about
  twice the speed: 23 GiB, 0.44 s p50. Gemma 4 31B is level with it. Both are
  within 1–5 points of sol.
- **Haitian Creole → English is the remaining gap.**
  - The best open models score 86–87, against sol's 98, with 9–13 critical
    errors against 2.
  - Clock times recur among the critical errors: Haitian "senkè" (5 o'clock)
    and "twazè edmi" (3:30) come out as other times. Kinship and pronoun
    errors recur in the CMU prompts.
  - Qwen3.5-122B is the best open model into English (87, 9 critical) but the
    weak out of English into Lao (62).
- **MADLAD 10B is worse than 7B** in every direction (−2 to −8 points, more
  critical errors), so it is no upgrade.
- **NLLB-200 3.3B doesn't beat MADLAD 7B** overall (78 / 81 / 75 / 80 against
  78 / 77 / 80 / 88). It is the fastest (0.39 s), but the non-commercial
  licence buys nothing here.
- **gpt-oss-120b can't do Lao** (16 and 34): the grader called most of its
  Lao garbled, as in round 2. It is good out of English into Haitian Creole (87) but has no
  advantage over Gemma 4.
- **TranslateGemma 27B** is second-tier: 85 / 78 / 86 / 92, with 22 critical
  errors into English from Haitian Creole.

## Recommendation

- **Commercial (Talk, the commercial edition):** Gemma 4 31B for Haitian
  Creole both ways and for Lao, under Apache-2.0.
  - Its bf16 weights need an 80 GB card, alone.
  - On the stack's 48 GB card, Google's 4-bit QAT build
    (`google/gemma-4-31B-it-qat-w4a16-ct`) would be the thing to test. It was
    not tested here.
  - For Lao alone, MiLMMT-46 12B is as good and fits beside the stack's other
    models. Its Gemma terms allow commercial use under Google's use policy.
- **Non-profit edition:** the same models. NLLB's non-commercial licence gains
  nothing.
- **Fine-tuning:**
  - **Lao:** no longer needed for translation on correct text. Lao's live
    scores are held back by recognition (`../2026-10-open-stack-e2e`), not
    the translator.
  - **Haitian Creole → English:** still worth it. Fine-tune Gemma 4 31B, or a
    smaller Gemma 4, on Haitian clock times, numbers and kinship terms, and
    on recognition-noisy input.
  - This round is clean text, the ceiling. Round 2 of the translator
    shootout showed open LLMs falling much further than sol on misheard
    Haitian Creole.

## Caveats

- One grading round and one grader. The grader is a Gemini model, and
  Gemma 4 is a Google model.
- The Haitian Creole references (CMU, news) were written by Gemini models and
  not checked by hand.
- Clean text only: no recognition errors.
- gpt-oss used sampled decoding (temperature 1, as its card says); the others
  were greedy, or beam search for the seq2seq models.
- The OpenRouter models ran at the precision noted, on whichever ZDR host
  served each sentence, and Qwen3.5-122B's score is bf16 while its timing is
  GPTQ Int4. The pod's MADLAD and NLLB timings are transformers bf16 with
  beam 4.
- The pod ran about 1 h 40 min. Most of that was model downloads and the two
  CTranslate2 conversions that did not finish.

## Files

- `htlo.py`: builds the inputs, runs sol, grades, and builds the tables.
- `or_run.py`: the OpenRouter models.
- `pod_run.py` and `run.sh`: the pod.
- `systems.json`: labels and licences.
- `results.json`: every score per set and direction, plus speed and memory.
- `out/`: inputs, translations, providers and grades. Not committed: it holds
  the news clip's text.

To reproduce:

    NEWS_DIR=<dir with ref_ht.json, ref_en.json> python3 htlo.py inputs
    # pod: python3 pod_run.py download; ./run.sh   (then copy /root/work/mt -> out/mt, timing-only runs -> out/timing)
    OPENROUTER_API_KEY=... python3 or_run.py && python3 or_run.py fill
    FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=<sol deployment> python3 htlo.py sol
    GEMINI_API_KEY=... python3 htlo.py grade && python3 htlo.py table
