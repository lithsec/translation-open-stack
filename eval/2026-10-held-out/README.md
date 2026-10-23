# Held-out check, October 2026

The pause and sentence work of October (#36–#39) was tuned on one 20-sentence clip per language. This
round runs the stack on sentences none of that work saw, to see what holds.

## Method

- **Clips** (`build_clips.py`): 20 FLEURS test sentences (CC BY 4.0) shared by English, Spanish, French,
  Japanese, Khmer, Lao and Portuguese, drawn at random from the ids no earlier October clip used, one
  recording per sentence, alternating male and female readers. Haitian Creole: 20 CMU Haitian Creole
  utterances not in the earlier set; its English reference is model-made (as in `../2026-10-real-voices`),
  and its text isn't published here. Each clip in two pause patterns:
  - *reg*: 1.0–1.95 s between sentences, as the earlier e2e clips;
  - *irr*: 0.3–1.2 s, irregular, closer to natural speech.
- **What was said** (`witness.py`): Gemini transcribed every recording verbatim and flagged ones that stop
  early or change the meaning. English: 8 of 20 (4 stop early, 4 misread; the stack's own Whisper hears the same on most). Other
  languages: 0–3. Each English direction is graded twice, against the written FLEURS text and against what was
  said (`results.json` `english_said`); for other sources the "said" score leaves the flagged sentences out.
- **Live runs**: the October client (`../2026-10-open-stack-e2e/scripts/e2e`), real-time streaming, one
  connection per direction, the published image with each system's code copied in, one A40.
  `analyze_e2e.py` is that analyser with Portuguese added.
- **Systems**:

  | | |
  |---|---|
  | A | `main` at 36693cc |
  | B | `feat/english-80` (#39): abbreviations kept whole; English waits 8 s / 400 ms, cut at 15 s |
  | C | B with MADLAD-400 7B as the Khmer translator |
  | D | B with a per-piece pick between Hy-MT2 7B and MADLAD-400 7B by MetricX-24 QE (`qe_pod.py`, `qe_pieces.py`), offline on B's live English pieces |
  | E | B's live English pieces re-translated by Hy-MT2-30B-A3B on OpenRouter (`e_mt.py`): the stack's prompt, sentence by sentence, no context, temperature 0 |

- **Grading** (`grade.py`, `round.py`): one blind call per direction and reference with every system that ran
  it, gemini-pro-latest, 0–3 per sentence plus a critical flag, the rubric of the earlier rounds. Quality is
  the share of the possible 3. Only same-call comparisons count.

Time ran to about 30 runs, so A ran only where B's changes could act: English sources, plus es→en as a
check on the abbreviation rule. Other sources ran on B alone; their turn rules are the same on A and B.

## Results

Quality against the written text / against what was said (critical errors in brackets). Latency is speaker
stops → last piece's audio starts, p50 / p90 in seconds.

**Out of English, regular pauses**

| | A main | B #39 | C | D QE pick | E 30B (hosted) | A latency | B latency |
|---|---|---|---|---|---|---|---|
| en→es | 56.7 (7) / 66.7 (7) | 56.7 (7) / 65.0 (8) | | 56.7 / 65.0 | 58.3 (8) / 68.3 (6) | 2.7 / 3.5 | 3.2 / 3.9 |
| en→fr | 56.7 (9) / 63.3 (8) | 56.7 (9) / 61.7 (8) | | 56.7 / 63.3 | 60.0 (8) / 61.7 (7) | 2.9 / 3.4 | 3.3 / 3.8 |
| en→ja | 48.3 (11) / 55.0 (9) | 48.3 (11) / 56.7 (9) | | 48.3 / 55.0 | 46.7 (12) / 53.3 (8) | 3.1 / 3.6 | 3.4 / 4.2 |
| en→pt | 48.3 (10) / 56.7 (8) | 48.3 (10) / 56.7 (8) | | 48.3 / 55.0 | 48.3 (11) / 60.0 (8) | 2.6 / 3.1 | 3.1 / 3.6 |
| en→km | 28.3 (16) / 40.0 (13) | 43.3 (11) / 55.0 (10) | 28.3 (15) / 38.3 (12) | | 36.7 (11) / 51.7 (10) | 24.7 / 33.2, 8 sentences silent | 29.4 / 46.2, 5 silent |
| en→lo | | 50.0 (12) / 53.3 (10) | | | | | 5.6 / 9.0 |
| en→ht | | 28.3 (9) / 38.3 (9) | | | | | 2.1 / 2.3 |

C (MADLAD for Khmer): 2.6 / 3.3 s and no silent sentences.

**Out of English, irregular pauses**

| | A main | B #39 | D QE pick | A latency | B latency |
|---|---|---|---|---|---|
| en→es | 53.3 (7) / 66.7 (6) | 53.3 (7) / 66.7 (6) | 53.3 / 66.7 | 2.9 / 9.1 | 3.4 / 9.1 |
| en→fr | 60.0 (8) / 68.3 (5) | 58.3 (8) / 66.7 (5) | 56.7 / 63.3 | 3.1 / 9.3 | 3.7 / 9.3 |
| en→ja | 45.0 (10) / 60.0 (7) | 46.7 (10) / 61.7 (7) | 46.7 / 61.7 | 3.3 / 9.5 | 3.7 / 9.8 |

**Into English** (B; A identical on es→en: 81.7 / 84.2)

| | Quality | Recognition CER | Latency |
|---|---|---|---|
| es→en | 81.7 (2) / 84.2 (1) | 1.0% | 2.7 / 3.2 |
| pt→en | 80.0 (3) / 80.0 (3) | 1.3% | 2.5 / 2.9 |
| fr→en | 68.3 (3) / 68.3 (3) | 5.6% | 2.6 / 2.9 |
| ja→en | 60.0 (6) / 61.1 (6) | 8.4% | 2.9 / 3.6 |
| ht→en | 46.7 (9) / 45.1 (8) | 5.2% | 3.9 / 5.0 |
| km→en | 43.3 (10) / 46.3 (8) | 15.6% | 3.3 / 4.5 |
| lo→en | 25.0 (8) / 24.6 (7) | 20.9% | 3.5 / 4.5 |

## Findings

1. **#39's quality gain does not hold on held-out speech.** Out of English, A and B differ by at most
   1.7 points in every direction and both pause patterns, inside one round's noise; es→en is identical.
   en→km (A 28.3, B 43.3) is the exception and isn't #39's doing: Hy-MT2 falls behind on Khmer and drops
   whole sentences (A 8 silent, B 5), which swings the score run to run. The longer English turns still cost
   0.3–0.6 s at the median (both patterns). On the tuning clip the gain came
   from four sentences a 280 ms breath split in two; these readers didn't pause that way. No regression
   either: B never scores below A by more than the noise.
2. **The held-out English clip is lost before translation.** Recognition is 16.6% of characters wrong
   against what was said (18.6% against the text; the tuning clip was under 4%). The grader's notes put most
   lost points on missing sentence starts: the first clause or whole first sentence of sentences 3, 11, 15, 17
   and 19. Each of those is a reader at about −60 dBFS straight after one at −18 to −30 dBFS
   (`english_sentence_dbfs`): the quiet boost's 1.5 s half-life hasn't caught up when the quiet reader starts.
   That is partly how FLEURS clips are joined (a 40 dB jump between readers in a second), but a quiet person
   answering a loud one is real, and it's the largest lever this round found.
3. **Portuguese** behaves like Spanish: pt→en 80.0, en→pt 48.3 / 56.7 (en→es 56.7 / 65–67), with the same
   English recognition losses.
4. **MADLAD for Khmer fixes the dropped sentences, not the quality.** Every sentence gets audio, starting
   2.6 s after the speaker stops (p50) instead of 25–29 s, but quality falls to 28.3 / 38.3 against
   Hy-MT2's 43.3 / 55.0 on the same speech (Hy-MT2 still drops 5 sentences). Khmer needs Hy-MT2's quality at
   MADLAD's speed: a faster Hy-MT2 runtime or a larger GPU, not a different model.
5. **The QE pick adds nothing.** MetricX picked MADLAD for 14–33% of pieces; quality moved by −3.4 to +1.6.
6. **Hy-MT2-30B (E) is not a clear gain on these pieces.** Against B, written / said: es +1.6 / +3.3,
   fr +3.3 / 0, ja −1.6 / −3.4, pt 0 / +3.3, km −6.6 / −3.3. On 9 of 99 pieces (in every target) the hosted
   model returned an empty answer at temperature 0, even after retries; they score
   as missing. Served by Tencent, fp8, with zero data retention requested (the provider is on OpenRouter's
   ZDR list). Hosted latency, one sentence per request: 1.0 s p50, 1.7 s p90; not a stack figure.
7. **Irregular pauses** merge more sentences per turn (A 18, B 14 turns for 20 sentences) and raise English
   recognition errors to 26% for both, with two sentences per clip getting no audio; the p90 wait rises to
   about 9 s on both.

## Limits

One clip per language and pattern, one grading round, one reader per sentence. A ran on English sources and
es→en only. The "said" reference for other sources drops the flagged sentences rather than rewriting them.
Haitian Creole's English reference is model-made. Lao and Khmer ran on Omnilingual 300M (the 7B needs an
80 GB GPU).
