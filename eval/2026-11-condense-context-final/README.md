# Condensing with context, the final prompt (2026-11-04)

Re-run of `../2026-11-condense-context` on the prompt that ships in live-translation `feat/condense-context`:
the eval's prompt B **plus one line** (owner's choice, to win back faithfulness): "Never drop a word that changes the
meaning: time, place, possession, negation or emphasis." B is the app's own `condensePrompt(pieces, lang, spoken)`
(imported from the worktree's `src/main/providers/voice-condense.ts`) and its answer is judged as the app judges it
(`judgeRewrite`: markers stripped, the 5% rule, then the "repeats" check).

## Setup
- **Same runs as the first eval:** its translated pieces (`prev/condense_<lang>.json`: 37 runs each, en→pt and en→es,
  Gemma 4 31B on Bedrock), so only the prompt differs. A and final B were both condensed again today.
- **Grading:** as before (Gemini Flash, blind, two rounds with labels swapped, `code/grade.py`). Two gradings:
  A vs final B (`runs/grades_condense.json`) and the first eval's B vs final B, head to head
  (`runs/grades_oldB_vs_final.json`; the old B texts are the first run's).
- `code/run.sh` runs it all; summaries in `runs/summary_*.txt`.

## A (today) vs final B

| | Rewrite used | Speech length overall | Call p50 | Join in | Natural | Faithful | Join out | Repeats / added (of 74) |
|---|---|---|---|---|---|---|---|---|
| pt A | 24/37 | 92% | 393 ms | 4.43 | 4.31 | 4.89 | 4.64 | 5 / 0 |
| pt **final B** | **34/37** | **86%** | 419 ms | 4.62 | 4.66 | **4.89** | 4.65 | 6 / 0 |
| es A | 23/37 | 91% | 396 ms | 4.51 | 4.42 | 4.86 | 4.57 | 2 / 0 |
| es **final B** | **32/37** | **85%** | 402 ms | 4.65 | 4.72 | 4.78 | 4.59 | 1 / 0 |

Where both rewrites were used, final B − A (95% bootstrap), next to the first eval's B − A:

| | Join in | Natural | Faithful | Join out |
|---|---|---|---|---|
| pt final (24 runs) | +0.27 (−0.33 to +0.90) | **+0.52 (+0.02 to +1.04)** | **0.00 (−0.12 to +0.12)** | +0.04 |
| pt first eval (23) | +0.33 | +0.59 | −0.15 | 0.00 |
| es final (22 runs) | +0.25 (−0.07 to +0.66) | **+0.57 (+0.20 to +0.95)** | −0.11 (−0.32 to +0.09) | +0.02 |
| es first eval (23) | +0.43 | +0.83 | −0.22 | +0.04 |

## First eval's B vs final B, head to head (both used: pt 34, es 32)

| | Rewrite used (old → final) | Speech overall | Join in | Natural | Faithful | Join out |
|---|---|---|---|---|---|---|
| pt | 37 → 34 | 84% → 86% | 0.00 | +0.06 (−0.10 to +0.24) | **+0.10 (+0.01 to +0.21)** | +0.04 |
| es | 35 → 32 | 83% → 85% | **−0.19 (−0.38 to −0.03)** | **−0.30 (−0.50 to −0.11)** | +0.08 (−0.02 to +0.19) | 0.00 |

## Reading
- The meaning line did what it was for: final B's faithfulness is **no worse than A** in Portuguese (0.00, was
  −0.15) and closer in Spanish (−0.11, was −0.22); head to head it is more faithful than the first B (pt +0.10,
  significant; es +0.08). Runs where B lost ≥ 1 faithful point: pt 1, es 5 (first eval: 9 over both).
- **It costs Spanish naturalness, plainly:** head to head final B is less natural than the first B in Spanish
  (−0.30, CI excludes 0) and joins in a little worse (−0.19). Gemma now keeps place and wording it used to drop,
  e.g. "…el expresidente de los Estados Unidos | , contra la mayoría democrática del Congreso **de los Estados
  Unidos** y…" (first B dropped the repeated "de los Estados Unidos"). Portuguese naturalness is unchanged (+0.06).
- Against today's prompt final B is still clearly better on naturalness (+0.5 to +0.6, significant in both) and
  joins in better (+0.25, not significant), and its rewrite is used far more (66/74 vs 47/74), saving 14–15% of the
  speech against 8–9% — less than the first B's 16–17% (it condenses a little less hard).
- The "repeats" check never fired here (0 of 74 B answers); the grader's "repeats" flags (B 6 pt, 1 es) are softer
  rephrasings the word check does not catch.
- ~10–25 ms more per call than A here (p50 402–419 vs 393–396 ms).

Model-graded; parliamentary speeches only, not other kinds of live speech; 37 runs per language.
