# sol through OpenRouter (zero data retention) against our Foundry deployment, and gpt-6 / gpt-6.1 sol

**Question.** Can the apps reach sol through OpenRouter, with zero data retention, instead of a separate
Foundry deployment and key, and is a newer sol better on the directions where sol matters most?

**Systems.** All with `reasoning` effort low and the previous two segments as context (the apps' prompt):
- `foundry-gpt-5.6-sol@low`: our Azure AI Foundry deployment (Data Zone Standard, US).
- `or-gpt-5.6-sol@low`, `or-gpt-6.1-sol@low`, `or-gpt-6-sol@low`: OpenRouter with
  `provider: {zdr: true, data_collection: "deny"}`.

**Routing.** OpenRouter's zero-retention endpoint list (`/api/v1/endpoints/zdr`) has exactly one host for each of
the three models: **Azure**. Every OpenRouter request that answered was served by `Azure`.

**Material.** Lao, Khmer and Haitian Creole into English from the full-stack run's own recognition (Omnilingual 7B
for Lao and Khmer, the base card for Haitian Creole; two clip sets), English into Haitian Creole, Khmer, Lao and
Spanish from Azure's transcripts of the unseen English clip, and Spanish into English. Grading:
[`../2026-10-unseen/grade.py`](../2026-10-unseen/grade.py), blind, all four systems in one call per direction.

## Results

**Incomplete.** The OpenRouter account's credit ran out mid-run (HTTP 402) and the account was rate-limited (HTTP
429), so 115 of 245 gpt-5.6-sol requests, 68 of gpt-6.1-sol and 42 of gpt-6-sol failed. Only sentences that
**every** system finished were graded: Lao 18, Khmer 16 and Haitian Creole 14 into English; out of English too
few (English → Khmer none, English → Lao one), so those are not reported. Treat every gap under ~10 points as
noise.

Quality against the written reference (critical errors in brackets):

| Direction (n) | Foundry 5.6 | OpenRouter 5.6 | OpenRouter 6.1 | OpenRouter 6 |
|---|---|---|---|---|
| Lao → English (18) | 72.2 (5) | 74.1 (3) | 74.1 (4) | 79.6 (3) |
| Khmer → English (16) | 87.5 (2) | 85.4 (2) | 87.5 (2) | 91.7 (1) |
| Haitian Creole → English (14) | 69.0 (3) | 76.2 (2) | 81.0 (1) | 71.4 (2) |
| Spanish → English (6) | 77.8 | 77.8 | 77.8 | 77.8 |

Successful requests only (latency includes OpenRouter's retries after rate limiting; list price per hour of speech
for one direction, 392 sentences, from the measured tokens):

| | p50 | p90 | Price / hour |
|---|---|---|---|
| Foundry 5.6 | 2.0 s | 4.3 s | $1.63 |
| OpenRouter 5.6 | 3.0 s | 15.0 s | $1.47 |
| OpenRouter 6.1 | 3.6 s | 16.7 s | $0.56 |
| OpenRouter 6 | 2.2 s | 6.0 s | $0.57 |

## What it shows

- **Routing is as advertised:** zero-retention requests for sol went only to OpenRouter's Azure host.
- **Quality through OpenRouter is the same model:** OpenRouter 5.6 is within noise of Foundry 5.6.
- **gpt-6 / gpt-6.1 sol are at least as good** on these into-English directions and cost about a third (they spend
  fewer output tokens and are listed at half the price). The sample is too small to call one better.
- **Latency and reliability through OpenRouter were worse here** (p90 6–17 s against 4.3 s), mostly rate limiting on
  this account's tier. Re-measure with credit and a higher limit before switching anything live.

## Files

`run.py` (translate, jobs, table), `results.json` (scores, success counts, latency, tokens). Translations and grades
are not committed.
