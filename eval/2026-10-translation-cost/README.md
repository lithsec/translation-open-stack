# Foundry translation: tokens, cost and reasoning per language, October 2026

What the translation step of Live Translation's Azure + Foundry routes costs
per hour, per listener language, and whether its reasoning setting and
prompt caching change that. Date: 2026-10-21.

## Method

- **Model:** GPT-5.6-sol on Azure AI Foundry (Data Zone Standard
  deployment), called with the app's own translation prompt: a system
  message (fix obvious recognition errors, translate what the speaker
  meant, keep numbers, names and negation exact) and the sentence in a user
  message. One sentence per request, no context. Requests were sent four at
  a time, not paced like live speech; the two reasoning settings were
  interleaved so that load hit both alike.
- **Reasoning:** `reasoning_effort` `low` (the app's setting until now)
  against `none`.
- **Two sentence sets:**
  - *short*: the 24 short, clean sentences of the September evaluation
    (`../2026-09-model-eval/sentences`), typed text. Directions en→fr, en→pt,
    en→es, en→ht, fr→en, es→en.
  - *news*: 33 long spoken sentences, the reference transcript and English
    translation of the five-minute news clip in `../2026-10-continuous-ht`.
    Directions en→fr, en→pt, en→es, en→ht, ht→en. These are clean texts,
    not raw recognition output.
- **Cost:** tokens from each response's usage, at the billed rates of
  $4.40 per million input tokens and $22 per million output tokens
  (reasoning tokens are billed as output). Per hour = cost per request ×
  392, the number of sentences an hour of continuous speech gives per
  listener language.
- **Quality:** `gemini-pro-latest`, blind and side by side (each direction's
  outputs at both settings shuffled under letters and graded in one
  request), 0–3 per sentence against the English meaning with a critical
  flag, as in the translator shootout. Shown as the share of the possible
  points; two grading rounds, averaged.
- **Latency:** median wall time of a request, from a client in the US.

Per-request token counts, cost, latency and both rounds' grades are in
`results.json`. Outputs and grader notes are not committed.

## Results (news set: long spoken sentences)

| Direction | Cost per hour, low → none | Quality, low → none | Reasoning tokens per request at low | Latency p50, low → none |
|---|---|---|---|---|
| en→fr | $0.92 → $0.63 | 96.0 → 100 | 31 | 1.72 → 1.51 s |
| en→pt | $0.90 → $0.60 | 96.0 → 98.0 | 31 | 1.76 → 1.40 s |
| en→es | $0.92 → $0.60 | 93.9 → 98.0 | 34 | 1.53 → 1.31 s |
| en→ht | $0.88 → $0.65 | 95.5 → 95.5 | 23 | 2.19 → 1.76 s |
| ht→en | $0.88 → $0.58 | 96.5 → 95.5 | 32 | 1.55 → 1.30 s |

On the **short set**, the model used no reasoning tokens at either setting:
$0.44–0.49 per hour and the same quality (97–100%) at both.

## What it shows

- At `low`, hidden reasoning made up about half of the output tokens on long
  sentences, and output is billed at five times the input rate.
- For French, Portuguese and Spanish, `none` cut the cost by about a third
  (to about $0.60 per hour per language), was 0.2–0.4 s quicker and graded
  as well or better.
- Haitian Creole is priced at `low` (about $0.88 per hour), the cautious
  choice for a low-resource language. In this test `none` graded the same
  into Haitian and one point lower out of it, at $0.58–0.65; the difference
  is within the noise of two rounds.
- **Prompt caching does not apply.** The prompt is about 160–190 tokens,
  below the 1,024-token minimum for caching, so nothing was cached. Padding
  the system prompt past the minimum did get it cached, but saved only about
  1.5% per request, and a miss is billed as a cache write at 1.25× the input
  rate. Not worth it. (From the caching probe's console output, 8 requests
  per mode; not saved as a file.)

## Caveats

- Clean reference text, not raw speech recognition output; real input has
  mishearings, which may make the model reason more.
- French and Spanish into English were measured only on the short set.
- One judge model, two rounds; 24 and 33 sentences per direction.
- The news set's references are model-made (see `../2026-10-continuous-ht`).
- 392 sentences per hour is an assumption for continuous speech; fewer
  sentences (more pauses, shorter sessions) cost proportionally less.
