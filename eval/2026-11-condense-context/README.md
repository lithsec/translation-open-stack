# Condensing with context: does Gemma's rewrite flow better when it knows what was just spoken? (2026-11-04)

When the voice falls 3 s behind, the app has Gemma rewrite the waiting pieces as one shorter passage
(live-translation `src/main/providers/voice-condense.ts`, `azure.ts maybeCondense`). Today Gemma sees only the
waiting pieces joined with spaces (prompt **A**). Prompt **B** adds what listeners just heard (the last 2 pieces),
the pieces one per line marked `[end]`/`[cut]`, and whether the passage continues a sentence or is followed straight on.

## Setup
- **Text:** 10 continuous English speeches, VoxPopuli en test (CC0 1.0), the longest runs of consecutive segments
  (`fetch_vox.py`), 10,858 characters.
- **Pieces:** sentences; a sentence over 16 words cut at a comma or before a conjunction, nearest the middle (an
  approximation of the boundary cutter's breath cuts; a few cuts landed oddly and left stray letters, the same for
  both arms).
- **Translation:** each piece into Portuguese and Spanish in order with the app's own prompt and context
  (`translateMessages`, previous 2 pieces) and Gemma 4 31B on Bedrock, as a room's voice queue receives them.
- **Runs:** 2–4 waiting pieces and ≥ 80 characters (`CONDENSE_MIN_PIECES`, `CONDENSE_MIN_CHARS`), with ≥ 1 piece
  already spoken; 37 per language. Each condensed by A and B through the app's `condenseCall`; a rewrite not 5%
  shorter (`condenseVerdict`) is spoken as the original, as in the app.
- **Grading:** Gemini Flash, blind A/B, two rounds with labels swapped. The grader hears ALREADY SPOKEN → candidate
  → NEXT and scores 1–5: join in, join out, natural, faithful (to the original pieces), plus repeats/added flags.

## Results

| | Rewrite used (≥ 5% shorter) | Speech length overall | Call p50 | Join in | Natural | Faithful | Join out |
|---|---|---|---|---|---|---|---|
| pt A (today) | 23/37 | 92% | 357 ms | 4.46 | 4.26 | 4.92 | 4.59 |
| pt **B** (context) | **37/37** | **84%** | 415 ms | 4.68 | 4.57 | 4.78 | 4.55 |
| es A (today) | 23/37 | 91% | 373 ms | 4.36 | 4.22 | 4.92 | 4.53 |
| es **B** (context) | **35/37** | **83%** | 405 ms | 4.70 | 4.78 | 4.76 | 4.51 |

Where both rewrites were used (23 runs each), B − A (95% bootstrap):

| | Join in | Natural | Faithful | Join out |
|---|---|---|---|---|
| pt | +0.33 (−0.22 to +0.91) | **+0.59 (+0.04 to +1.15)** | −0.15 (−0.35 to +0.04) | 0.00 |
| es | **+0.43 (+0.07 to +0.87)** | **+0.83 (+0.43 to +1.24)** | −0.22 (−0.43 to +0.02) | +0.04 |

- On runs that continue a sentence already under way (24 per language), B's join in was +0.33 (pt) and +0.50 (es).
- Repeats of already-spoken text: es A 7, B 0; pt A 4, B 5 (of 74 gradings each).
- B's rewrite is used far more often (37/37 and 35/37 against 23/37), so it saves about twice the speech
  (16–17% against 8–9%).
- Faithfulness costs a little: 9 runs lost ≥ 1 point, all small omissions ("também", "um manto de", "nossos",
  "por que") from condensing harder; nothing added or changed (0 "added" flags either arm).
- Join out: no change. Telling Gemma the passage ends mid-sentence did not help.
- B costs ~50 ms more per call (Gemma on Bedrock).

Model-graded; parliamentary speeches only, not other kinds of live speech; 37 runs per language.
