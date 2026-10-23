# LLM translators for Haitian Creole and Lao, live, October 2026

On correct text (`../2026-10-ht-lo-translators`), Gemma 4 31B and MiLMMT-46 12B beat MADLAD-400 7B,
the stack's translator for Haitian Creole and Lao, by 10–14 points. This round puts them in the
stack (`server/engines/llmmt.py`: an OpenAI-compatible client for a model served beside the stack by
vLLM) and runs the unseen clips through it, against main, live.

## Setup

- **This branch** (`L`): `translator = "llmmt"` for `ht`, `lo` and `en` in `languages.toml`, with
  - `[ht] llmmt = "chat http://127.0.0.1:8101/v1 google/gemma-4-31B-it-qat-w4a16-ct"`: Gemma 4 31B,
    Google's official 4-bit build (W4A16, compressed-tensors; Apache-2.0), vLLM 0.31.0;
  - `[lo] llmmt = "milmmt http://127.0.0.1:8102/v1 xiaomi-research/MiLMMT-46-12B-v0.1"`: MiLMMT-46 12B
    in bf16 (Gemma terms; Lao, no Haitian Creole), the model card's prompt.
  - English sources still go to Hy-MT2: a pair goes to the server its non-English side names.
- **main** (`M`): MADLAD-400 7B. On this pod it ran in **bf16 under transformers**, not the stack's
  CTranslate2 int8 (the int8 conversion ran over an hour without finishing), so main's translation
  latency here is slower than a normal deployment's.
- Clips, client and grading as the quiet-talker round (PR #46): the unseen round's regular-pause clips,
  real-time streaming, one blind call per direction (gemini-pro-latest), against the written text and
  against what was said. Lao is heard by Omnilingual 7B, Haitian Creole by Omnilingual 300M, in both.
- One A100 80 GB. The Haitian Creole runs used a stack serving `en,ht` beside Gemma; the Lao runs one
  serving `en,lo` (with the 7B) beside MiLMMT.

## Results

Quality against the written text / against what was said (critical errors), and speaker stops → last
piece's audio starts (p50 / p90, s):

| Direction | main (MADLAD 7B) | this branch | Latency main | Latency branch |
|---|---|---|---|---|
| en→ht (Gemma 4) | 35.0 (11) / 46.7 (8) | **63.3 (6) / 68.3 (6)** | 4.2 / 6.1 | 1.6 / 2.1 |
| ht→en (Gemma 4) | 48.3 (12) / 47.1 (10) | **66.7 (9) / 64.7 (8)** | 7.5 / 9.4 | 3.0 / 4.0 |
| en→lo (MiLMMT) | 38.3 (13) / 46.7 (10) | **48.3 (12) / 63.3 (8)** | 13.7 / 20.7 | 2.1 / 2.8 |
| lo→en (MiLMMT) | 35.0 (11) / 35.1 (10) | **41.7 (11) / 42.1 (10)** | 5.0 / 6.2 | 2.9 / 5.0 |

- **Haitian Creole gains 18–28 points both ways**, with fewer critical errors. Recognition is the same
  in both (5.2% of characters wrong), so this is the translator.
- **Lao gains 7–17 points.** lo→en is still held back by recognition (18.7% characters wrong on the
  7B), as on correct text MiLMMT scored 98.
- Latency is lower on this branch, but part of that is main's bf16 MADLAD on this pod; the int8 build
  takes about 0.3 s a sentence.

## Does it fit on one 80 GB card?

Measured (GB of GPU memory):

| | |
|---|---|
| Stack, all 8 test languages, Omnilingual 7B, MADLAD bf16 | 52.5 |
| Stack serving en, lo (7B) | 50.1 |
| Stack serving en, ht (no 7B) | 34.8 |
| Gemma 4 31B W4A16 under vLLM (weights 18.7, `--gpu-memory-utilization 0.34`) | 27.7 |
| MiLMMT-46 12B bf16 under vLLM (`0.36`) | 27.7 |

Everything at once (stack + Gemma + MiLMMT) is about 108 GB: it does **not** fit one 80 GB card. The
two that would: stack + Gemma alone, with Gemma also translating Lao (it scored en→lo 94 / lo→en 95 on
correct text), about 80 GB with MADLAD bf16 and about 75 GB with the int8 build; or stack + MiLMMT for
Lao only. Each server's share can be trimmed with a shorter `--max-model-len`.

## 4-bit or full precision? The same inputs, again in bf16

`or_bf16.py` sent the live run's exact translator inputs to `google/gemma-4-31b-it` on OpenRouter,
pinned to bf16 hosts (Novita, Crusoe), zero data retention, temperature 0, one request per sentence. The
stack didn't log llmmt's requests, so they are rebuilt with llmmt's own code from the logged utterances:
`split_sentences` of what the stack heard, then `llmmt.request("chat", ...)` per sentence (no context:
llmmt takes none). The Lao utterances MiLMMT translated went to Gemma bf16 the same way, which gives a
first live-text data point for Gemma on Lao. Each pair was graded blind, side by side, in one new round
(same grader and rubric); compare within this table only. The 4-bit scores differ from the table above
because it is another grading round.

Quality against the written text / against what was said (critical errors):

| Direction | Gemma 4-bit (stack) | Gemma bf16 (OpenRouter) | Same output |
|---|---|---|---|
| en→ht | 51.7 (10) / 61.7 (6) | 55.0 (10) / 66.7 (6) | 3 of 22 identical, 17 near (≥ 0.9 similar) |
| ht→en | **66.7 (8) / 64.7 (8)** | 60.0 (10) / 58.8 (9) | 7 of 21 identical, 16 near |

| Direction | MiLMMT 12B (stack) | Gemma 4 bf16 (OpenRouter) |
|---|---|---|
| en→lo | 48.3 (12) / 56.7 (11) | 48.3 (12) / 61.7 (9) |
| lo→en | **46.7 (9) / 47.4 (9)** | 40.0 (9) / 40.4 (9) |

- **Full precision doesn't beat 4-bit.** Most outputs are the same or nearly so. bf16 is ahead by
  3–5 points into Haitian Creole and behind by 6–7 out of it, with critical errors level or worse:
  differences inside one grading call's noise. Google's 4-bit build is not what's holding Haitian
  Creole back, so a bigger card for bf16 (~62 GB of weights) or 8-bit (~31 GB) buys nothing measurable.
- **For Lao, Gemma bf16 is no better than MiLMMT on live text**: level out of English, 7 points behind
  into English. MiLMMT stays the Lao choice; Gemma for Lao would only be for fitting one model on the card.

## What isn't measured

- One clip per direction, one grading call each.
- Gemma 4 for Lao inside the live stack (only replayed on OpenRouter from MiLMMT's run, above).
- The stack's int8 MADLAD as the baseline (bf16 here).
