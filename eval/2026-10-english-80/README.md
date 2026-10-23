# Out of English to 80: what the live score was losing, and two fixes

The live score out of English (`../2026-10-pauses`, `../2026-10-open-stack-e2e`) was 50–62 for
Spanish, French and Japanese. Given the correct English text, the same translator scores 92–100.
This round looks at where the missing points go. It uses the same 20-sentence English clip (FLEURS
read speech, CC BY 4.0), the same live client and the same blind grader (Gemini, 0–3 per sentence,
quality = 100 × mean / 3).

`results.json` holds every number below.

## 1. Seven of the 20 recordings don't say what the reference says

Whisper and Canary-Qwen were each given one sentence at a time (`../2026-10-open-stack-e2e`, section 3).
Both "mishear" the same words in the same 7 sentences. A third witness was then added: Gemini,
asked to transcribe each sentence verbatim (`witness.py`). It confirms that the recordings, not the
recognisers, are the cause:

| # | Written text | What the recording has |
|---|---|---|
| 0 | ...reach a higher level of performance. | stops at "level of p-" |
| 4 | Duvall, who **is married with** two adult children... | "who **was married to** two adult children" |
| 9 | ...for cost-saving **and** functionality factors... Taipei IT **Month**. | no "and"; stops before "Month" |
| 14 | ...two individual races **at the Championships**. | stops at "at the" |
| 15 | ...Mountain Gorilla **tracking** in Africa. | "trafficking" |
| 17 | ...and **the country with the lowest population**. | stops at "and the population" |
| 19 | ...the cave is **completely** isolated... | "closely" |

Two more sentences are uncertain: 1 ("March 2017") and 10 ("in others").

The grader treats the written text as authoritative. A system that faithfully translates what was
said therefore scores at most 1 on these 7 sentences. Its ceiling on this clip is about 77, and no
system can reach 80 against the written text.

**How we score from now on:** grade against what was said. The reference used here is the written text with those
7 sentences replaced by the recording's words, so recordings that stop early are cut at the same
point.

Old outputs, re-graded against what was said in one blind round:

| | Stack live (main) | Stack, given the written text | sol on the stack's transcript | Hy-MT2 on Whisper, one sentence at a time | Hy-MT2 on Canary, one sentence at a time |
|---|---|---|---|---|---|
| en→es | 73.3 | 88.3 | 76.7 | 85.0 | 83.3 |
| en→fr | 61.7 | 85.0 | 76.7 | 75.0 | 83.3 |
| en→ja | 70.0 | 91.7 | 83.3 | 80.0 | 85.0 |
| en→km | 45.0 | 85.0 | 81.7 | | |
| en→lo | 66.7 | 73.3 | 80.0 | | |
| en→ht | 43.3 | 46.7 | 85.0 | | |

With whole sentences and open models only, 80 is within reach for Spanish and Japanese. What the
live stack still lost was in how it cut and split the speech.

## 2. Where the rest went (en→es, main, graded against what was said)

- **Pieces ending mid-sentence:** 4 of 20 sentences reached the translator in two pieces. In each case a
  pause inside the sentence came after more than 5 s of speech, and the 280 ms clause gap ended
  the turn: "...on Miller." | "to whom the story was related." The listener hears two
  sentences, and the grader marks it down.
- **A full stop inside an abbreviation:** `split_sentences` split "...announced U.S." from "troops
  would be leaving Syria." The translator returned "anunció que Estados Unidos… Las tropas
  estarían saliendo de Siria."
- **Recognition:** "March 2016" (sentence 1, uncertain) and "and their research" (sentence 2, live only).
- **The start of sentence 7 is lost:** sentence 6 is read at −17 dBFS and sentence 7 at −54 dBFS
  by a different reader. The quiet-speech gain (QuietBoost, half-life 1.5 s) is still near 1× when
  sentence 7 starts, so its first 2.3 s are never heard as speech. A 37 dB jump between two readers
  is an artifact of joining the clip together, and this round doesn't change QuietBoost.
- **Translator on correct text:** one sentence ("loose pet cats" → "sin dueño").

## 3. The fixes tried

> **Merged: fix 1 only.** On unseen clips ([`../2026-10-unseen`](../2026-10-unseen/)) the
> English turn rules (fix 2) gained nothing (main and this branch within 1.7 points in every
> direction, regular and irregular pauses) and still added 0.3–0.6 s at the median, so they were
> left out. The 86.7 for en→es below was specific to this clip. The numbers in section 4 are this
> clip's, with both fixes on.


1. **Abbreviations don't end sentences:** `server/engines/common.py`, `split_sentences` and
   `voice_sentences`. This covers initials ("U.S.", "J. R. R.") and common titles ("Dr.", "Mr.",
   "St."…).
2. **English turn rules:** `languages.toml [en]`. When English is spoken, the shorter clause gap
   starts at 8 s instead of 5 s and is 400 ms instead of 280 ms, and the forced cut moves from 12 s
   to 15 s.
   - In the offline replay (`../2026-10-pauses`, setting `long8_400`): 24 → 20 pieces, 8 → 4 cuts
     inside a sentence. The 4 that remain are recordings that stop mid-sentence.
   - It adds a median +0.18 s before the cut.

## 4. Live, main vs this branch (one blind round per direction, both systems in it)

Each cell is quality (critical errors), then the time from the end of a sentence to the last
audio in seconds, p50/p90:

| | Against what was said | Against the written text | Stop → last audio (main → branch) |
|---|---|---|---|
| en→es | 76.7 (2) → **86.7 (2)** | 51.7 → 65.0 | 2.6/3.7 → 3.2/3.8 |
| en→fr | 65.0 (3) → **76.7 (3)** | 55.0 → 63.3 | 3.1/4.1 → 3.5/4.1 |
| en→ja | 65.0 (3) → **80.0 (3)** | 61.7 → 71.7 | 3.2/4.4 → 3.5/4.5 |
| en→km | 46.7 (10) → 65.0 (7) | 38.3 → 60.0 | 27/34 → 32/43 (falling behind; 6 → 5 sentences without audio) |
| en→lo | 63.3 → 65.0 | 50.0 → 51.7 | |
| en→ht | 40.0 → 40.0 | 31.7 → 31.7 | |

What each fix contributed, sentence by sentence, graded against what was said:

- **Abbreviation fix (sentence 5):** +1 point for es, +2 for fr and ja.
- **Whole sentences (4, 11, 16, 19):** +1 to +2 per sentence, +5 to +7 points out of 60 per direction.
- **Recognition:** unchanged. 6.7% of characters wrong against the written text in both runs.

**Grading between rounds is noisy.** The same main outputs for en→es scored 61.7 in
`../2026-10-pauses` and 51.7 here, both against the written text. Only compare systems graded in the same round.

## 5. Not fixed here

- **Khmer out of English falls behind:**
  - Hy-MT2 takes 4–11 s per 5–8 s utterance into Khmer on an A40.
  - When the room's pipeline falls behind it drops whole utterances, 5–8 per clip.
  - With those sentences missing, en→km can't reach 80. Fixing it means a faster translator path for
    Khmer (batching, a CTranslate2 or vLLM build, or MADLAD), not cutting.
- **Lao and Haitian Creole:** limited by the translator even on correct text (73 and 47 against what was said).
- **Recognition options, tried offline on this branch's pieces** (`asr_variants.py`), percent of
  characters wrong against what was said:

  | Option | Characters wrong (%) | Notes |
  |---|---|---|
  | Today's settings | 3.6 | |
  | Beam 5 | 3.4 | fixes "Rib" → "Rip", "Duval", "Nyiragongo"; slower decoding |
  | The previous piece as a prompt | 3.7 | made up "The most common problem of..." and "...is about 1,000" |
  | Whisper's own VAD off | 3.5 | |

  None of these is in this PR.
- **QuietBoost after a much louder voice:** sentence 7, section 2.

## Files

- `witness.py`: verbatim transcription of each English sentence by Gemini, which flags recordings
  that stop early.
- `asr_variants.py`: Whisper settings over the stack's own pieces. It runs where the stack runs.
- `results.json`: the reference with the recording's words, the witness output, both grading
  rounds, latency and the recognition variants.

The grades and the witness transcripts are Gemini output.
