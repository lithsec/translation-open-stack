# The open stack end to end, and what would improve it (October 2026)

Two questions about the open stack, measured on 2026-10-21/22:

1. How does the stack do end to end (speech in, translated speech out) on
   the languages we care about, in latency and in errors?
2. Where does it lose quality, recognition or translation? Would a bigger
   recogniser, a bigger translator, an LLM that repairs the translation, or a
   hosted model close the gap to the best cloud route?

Grades come from one blind Gemini grader (`gemini-pro-latest`) per round, on
the same 0–3 scale as the earlier rounds, shown as % of the maximum, with
the count of critical errors (score 0) in brackets. Grades move 5–10 points
between rounds, so **compare numbers only inside one table**. The cloud
baseline everywhere is gpt-5.6-sol (reasoning low) on Azure AI Foundry, the
best route in `docs/dev/route-findings-2026-10.md`.

Results (aggregates only: scores, error rates, latencies; no transcripts or
translations) are in `results/`. Scripts are in `scripts/`; paths and hosts
are hard-coded for the run's layout or taken from the environment, as in the
other eval folders.

## Audio

One clip per language: the first 20 sentences of each real-voice set from
`../2026-10-real-voices` (FLEURS read speech, CC BY 4.0, for English,
Spanish, French, Japanese, Khmer and Lao; CMU Haitian Creole speech for
Haitian Creole), joined with pauses of 1.0–1.95 s (the same pause pattern in
every language), 3–4.5 minutes each. Read speech, not spontaneous speech or a
room's echo.

## 1. End to end through the stack

The published image (`2026.10.09.2`, its default `languages.toml`) on one
NVIDIA A40. Each clip streamed at real time (`scripts/e2e/e2e_client.mjs`,
`run_all.sh`), one direction at a time; `sidecar.py` on the pod collected GPU
samples and stage timings; `analyze_e2e.py` aligns what the stack heard to
the read sentences. Recognition is Whisper for en/es/fr/ja and Omnilingual
LLM 300M (the public card) for ht/km/lo; translation is Hy-MT2 7B, or MADLAD
7B where Hy-MT2 has no support (Haitian Creole, Lao).

`results/e2e.json`:

| Direction | Recognition CER | Speaker stops → first translated audio, p50 / p90 (s) | Live | Stack MT on its transcript | Stack MT on the correct text | sol on the stack's transcript |
|---|---|---|---|---|---|---|
| en→es | 11.3 | 2.4 / 3.9 | 50 (8) | 55 (6) | 100 (0) | 68 (4) |
| es→en | 0.4 | 2.8 / 3.4 | 70 (1) | 82 (0) | 90 (0) | 92 (0) |
| en→ja | 11.3 | 2.9 / 4.2 | 53 (4) | 58 (4) | 92 (0) | 75 (3) |
| ja→en | 18.4 | 1.1 / 3.4 | 58 (12) | 63 (11) | 90 (3) | 78 (6) |
| en→fr | 11.3 | 2.8 / 3.8 | 52 (4) | 55 (4) | 92 (0) | 75 (3) |
| fr→en | 4.4 | 2.6 / 3.2 | 75 (5) | 75 (5) | 98 (0) | 88 (2) |
| en→km | 11.3 | **22.5 / 32.5** | 38 (14) | 62 (8) | 97 (1) | 80 (4) |
| km→en | 36.3 | see note / 3.3 | 27 (10) | 30 (10) | 80 (2) | 45 (7) |
| ht→en | 7.5 | see note / 3.4 | 22 (16) | 35 (16) | 72 (6) | 78 (5) |
| en→ht | 11.3 | 1.7 / 2.3 | 38 (10) | 38 (10) | 53 (7) | 80 (3) |
| lo→en | 19.6 | see note / 3.9 | 13 (17) | 33 (15) | 85 (1) | 77 (6) |
| en→lo | 11.3 | **8.6 / 10.6** | 43 (9) | 43 (9) | 63 (7) | 77 (4) |

"Live" grades what the stack said against the reference; the other three
columns re-translate per sentence so the steps can be separated.

- **Latency:** for Whisper languages the first translated audio comes
  2.4–2.9 s after the speaker stops. English→Khmer can't keep up (Hy-MT2 is
  token-heavy into Khmer; it fell 2.1× behind real time and dropped
  sentences), and English→Lao waits 8.6–10.6 s. "See note": for the
  Omnilingual sources half or more of the sentences were already being
  spoken back before the speaker stopped, because the stack cut them
  mid-sentence; the median is negative and means nothing.
- **Recognition is the bigger loss in 9 of the 12 directions**: compare
  "Stack MT on the correct text" with "on its transcript".
- **The English loss is segmentation, not Whisper.** English is 11.3% CER
  live, 4.7% fed one sentence at a time (section 3). The stack dropped one
  sentence and cut another.
- **MADLAD is weak into Haitian Creole and Lao** even on correct text (53,
  63).

## 2. Lao and Khmer: Omnilingual 300M against 7B (experiment A)

Omnilingual LLM 300M and 7B (bf16) through omni-stt's own code
(`scripts/gpu/asr_a.py`): per sentence on the 30-sentence real-voice clips,
and on the 20-sentence e2e clip through omni-stt's AudioIn, Silero and
Segmenter at two pause settings (pause ms : maximum s). Each segment goes
through the service's repetition guard (30 characters/s, 6 repeats).
`results/A_cer.json`, `results/A_quality.json`.

Character error (%):

| | Lao 300M | Lao 7B | Khmer 300M | Khmer 7B |
|---|---|---|---|---|
| One sentence at a time | 15.6 | **8.5** | 14.1 | 12.6 |
| Segmented 200 : 10 | 21.3 | 18.3 (46.4 without the guard) | 35.7 | 32.8 |
| Segmented 700 : 15 | 19.3 | **15.7** (29.5 without the guard) | 35.1 | 31.5 |
| Stack live (300M) | 19.6 | | 36.4 | |

Translation into English of those transcripts, Lao→English:

| Transcript | Stack MT | sol |
|---|---|---|
| Correct text | 90 (0) | |
| 300M, one sentence at a time (30) | 32 (12) | 69 (7) |
| 7B, one sentence at a time (30) | **53 (8)** | 84 (3) |
| 300M, segmented 700 : 15 (20) | 28 (16) | 58 (8) |
| 7B, segmented 700 : 15 (20) | **53 (9)** | 83 (2) |
| 7B, segmented 200 : 10 (20) | 33 (12) | 77 (4) |

- **Lao should be heard by 7B, with the repetition guard and 700 ms : 15 s
  pauses**: +21 to +25 points for the stack's translator. At 200 : 10 the
  gain is only +3. Without the guard 7B loops on short fragments (the guard
  caught 2–4 Lao segments per clip here).
- Khmer gains 10–19 points with 7B, but the Khmer clip has very quiet
  sentences that the VAD drops whatever the model (see
  `../2026-10-omni-sizes`), so the segmented numbers stay high.
- 7B needs ~15 GB against 3.5 GB, at about the same speed (0.19 × real time
  on the A40).

## 3. English recognisers (experiment C)

Whole sentences, the 20-sentence e2e clips. `results/C_cer.json`,
`results/C_quality.json`.

| Recogniser | en CER | es CER | fr CER | Decode p50 (s) |
|---|---|---|---|---|
| Whisper (the stack's) | **4.7** | 0.4 | **2.2** | 0.15–0.20 |
| Canary-Qwen 2.5B | 7.3 (writes numbers as words) | | | 0.27 |
| Parakeet TDT 0.6B v3 | 9.3 | 0.6 | 5.2 | 0.05–0.07 |
| Whisper live in the stack | 11.3 | 0.4 | 4.4 | |

Translated by the stack's Hy-MT2 (out of English):

| | en→es | en→fr | en→ja |
|---|---|---|---|
| Stack, live transcript | 66.7 | 55.0 | 63.3 |
| Whisper, whole sentences | 80.0 | 66.7 | 75.0 |
| Canary-Qwen, whole sentences | 78.3 | 73.3 | 78.3 |
| sol, live transcript | 75.0 | 76.7 | 76.7 |

Whole sentences recover 12–15 points. A different recogniser does not:
the fix is how the stack cuts English speech.

## 4. A bigger translator, a repair step, or a quality pick (experiment B)

On one 96 GB GPU (RTX PRO 6000): **Qwen3.5-122B-A10B** (GPTQ Int4, vLLM,
`gptq_marlin` with MTP speculative decoding, `scripts/gpu/serve_q2.sh`) and
**Hy-MT2-30B-A3B** (`serve_h.sh`), on the stack's own transcripts: the 12
e2e directions plus 10 real-voice directions (540 sentences). Qwen modes:
*direct*; *ctx* (with the previous sentences); *repair* (given the source and
the stack's translation, return a corrected translation). *QE pick* chooses,
per sentence, among stack / Qwen direct / Qwen ctx by MetricX-24 QE
(`metricx_qe.py`). `results/B_results.json`.

| Group | Stack | Qwen direct | Qwen ctx | Qwen repair | QE pick | Hy-MT2-30B | sol |
|---|---|---|---|---|---|---|---|
| All 22 directions | 57.0 (210) | 57.3 (205) | 58.3 (206) | 60.0 (201) | 61.2 (201) | 52.9 (216) | **79.0 (103)** |
| Out of English (ja km fr es) | 67.3 (35) | 63.3 (42) | 62.0 (44) | 68.0 (38) | 69.4 (39) | **72.2 (33)** | 80.0 (21) |
| Into English (ja km fr es) | 62.9 (64) | 62.7 (67) | 63.3 (69) | 64.9 (63) | 64.9 (64) | 65.1 (66) | 77.8 (39) |
| Haitian Creole (both ways) | 40.3 (55) | 53.7 (41) | **54.7 (42)** | 52.0 (44) | 52.0 (47) | 38.7 (57) | 83.0 (16) |
| Lao (both ways) | 46.0 (56) | 41.3 (55) | 47.0 (51) | 46.0 (56) | 50.0 (51) | 13.7 (60) | 75.0 (27) |

Single-stream latency per sentence, p50 / p90: Qwen 0.31 / 0.91 s with
marlin + MTP (0.98 / 2.94 s without), Hy-MT2-30B 0.25 / 1.33 s.

- **No overall gain worth a 96 GB GPU.** Repair adds 3 points, QE pick 4;
  sol is still 18 points ahead.
- **Haitian Creole is the exception**: Qwen with context is +14 over MADLAD
  with fewer critical errors, at acceptable speed. sol is still ~28 points
  better.
- **Hy-MT2-30B is the best open model out of English** (+5), but has no Lao
  or Haitian Creole.

## 5. DeepSeek V4-Flash (round D)

DeepSeek V4-Flash through OpenRouter, with experiment B's prompts
(`scripts/analysis/ds.py`, reasoning disabled, temperature 0), graded blind
with the stack and sol on the 7 hardest real-voice directions.
`results/D_deepseek.json`.

| Direction | Stack | V4-Flash direct | V4-Flash ctx | sol |
|---|---|---|---|---|
| en→ja | 70.0 | 72.2 | 70.0 | 77.8 |
| en→km | 68.9 | 63.3 | 63.3 | 80.0 |
| en→lo | 58.9 | 70.0 | 72.2 | 83.3 |
| en→ht | 47.8 | 64.4 | 72.2 | 82.2 |
| km→en | 51.1 | 44.4 | 43.3 | 63.3 |
| lo→en | 36.7 | 36.7 | 38.9 | 66.7 |
| ht→en | 40.0 | 47.8 | 62.2 | 92.2 |
| **All 7** | 53.3 (68) | 57.0 (59) | **60.3 (53)** | **77.9 (37)** |

API round trip p50 / p90: V4-Flash 1.7 / 4.8 s (2.2 / 5.8 s with context);
V4.1-Flash 0.65 / 1.66 s (translated, not graded); V4-Pro 1.9 / 6.4 s (not
graded). Even with reasoning disabled, V4-Flash still spent reasoning tokens
on some requests.

+7 with context: a little ahead of Qwen-122B on the same directions in
round B, about 18 points behind sol.

## Conclusions

1. **Hear Lao (and try Khmer) with Omnilingual 7B**, with the repetition
   guard and 700 ms : 15 s pauses. The clearest win: +21 to +25 points into
   English.
2. **Fix how the stack cuts speech before recognition.** It costs 12–15
   points for English and more on the Omnilingual languages, more than any
   model swap here gains.
3. **No open translator is close to sol.** Bigger LLMs, a repair pass, a QE
   pick and DeepSeek V4-Flash each add 3–7 points overall.
4. **Haitian Creole:** Qwen3.5-122B with context is a real upgrade over
   MADLAD (+14) if a 96 GB GPU is acceptable; a smaller model fine-tuned for
   Haitian Creole may get there more cheaply.
5. **Out of English:** Hy-MT2-30B is +5 over the stack, without Lao or
   Haitian Creole.
