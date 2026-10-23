# Fast mode out of English into Haitian Creole, Khmer and Lao, October 2026

Can phrase-by-phrase translation (fast mode, [../2026-10-simultaneous-phrases](../2026-10-simultaneous-phrases/))
extend from English → Spanish/Portuguese/French to English → Haitian Creole, Khmer and Lao?
The English side is easy (Azure hears English well, and the phrase cutter works on English);
the questions are whether the translators continue a sentence well in these languages, and
whether the voices keep up.

**Answer: not as the default.** Fast mode starts the voice about 5 s sooner, but it costs
12–15 points on read news and 5–10 on conversation (more than for Spanish/Portuguese/French),
about 1 phrase in 4 turns out wrong once the sentence is known, and the Haitian Creole voice
cannot keep up with it. Whole sentences stay the default; fast mode could be offered for
Khmer and Lao conversation as an opt-in at most.

## How it was run

- **English speech:** the recorded Azure standard partials already replayed in the
  simultaneous-phrases round (the unseen read-news clips, regular and irregular pauses, 20
  FLEURS sentences each) and in [../2026-10-concise-conversational](../2026-10-concise-conversational/)
  (a 2.5-minute AMI meeting excerpt, CC BY 4.0, 37 sentences; ids in that round's
  `sources.json`). The commit policy's chunks depend only on the English, so this round reuses
  those chunk plans (segment, commit time, English words) and translates each chunk into the
  new targets with a real call, one at a time per stream, timed as `simulate.py` times them.
- **Systems** (`mt.py`): **S-** one call per recogniser final (whole sentences, today's style),
  **P8-** phrases of up to 8 English words with the continuation prompt; translator **sol**
  (gpt-5.6-sol on Foundry, reasoning off) or **gemma31** (Gemma 4 31B on OpenRouter, restricted
  to named zero-retention hosts, no fallback; every call was served by CoreWeave).
- **Voices** (`tts.py`), synthesised for real per chunk:
  - Khmer `km-KH-PisethNeural`, Lao `lo-LA-ChanthavongNeural` (the faster of each Azure pair),
    with trimmed pauses (mstts:silence Leading/Tailing-exact 0, Comma-exact 100 ms), +8% and an
    energy edge trim. Both accept the settings: a test sentence went from 5.3 s to 4.0 s
    (Khmer) and 5.2 s to 3.9 s (Lao). `voice_check.json`.
  - Haitian Creole: Gemini TTS, the model and voice Talk uses (`gemini-3.8-flash-tts`, Kore),
    streamed. No rate or pause control applies; a "read briskly" instruction made the clip
    *longer* (4.3 → 6.5 s trimmed), so only the edge trim is used.
  - Chunks play in order, 120 ms apart within a segment and 300 ms after a segment's last chunk.
- **Timing** (`analyze.py`), per recogniser segment (one Azure final = one stretch of speech):
  - *first words (no queue)*: when the segment's first chunk could start (translation done +
    time to first audio) minus the segment's speech start. What fast mode buys.
  - *first audio / last*: the same with the voice queue (earlier audio must finish first), and
    the start of the segment's last chunk minus its speech end.
  - *all done*: end of all audio minus end of the speech, the monologue backlog.
  - Nine calls in 1,524 took 8–70 s (a provider stall or a retried request); each is replaced by
    its stream's median call time so one stall does not decide a comparison (`OUTLIER_MS=0`
    keeps them; `outlier_calls` in `results.json`).
- **Grading** (`grading.py`, Gemini Pro, blind), as in the voice-rate and conversational rounds:
  the 0–100 side-by-side grade (all four systems in one call per target and clip, against what
  was said, and for read news also against the written text); fixed meaning units and listener
  questions written from the English before any translation was seen (reused from those
  rounds), each unit judged conveyed / missing / distorted, and the questions answered from the
  translation alone; and the contradiction pass for phrase systems
  ([contradictions.py](../2026-10-simultaneous-phrases/contradictions.py)). Each system's stream
  is cut into sentences with the anchor method (`seg.py`); 36 of 37 meeting sentences were
  located (one short interjection merged into its neighbour).

## Results

Averages: read news over the two pause patterns; "wrong phrases" over all three clips. Scores
are against what was said unless marked. Translation cost is per hour of speech at list prices
from actual token counts (Gemma 4 on the allowed hosts; sol at its list rate).

| Target | System | Read news | Meeting | Read, written text | Wrong phrases | First words p50 (no queue) | All done, read / meeting | Translation $/h |
|---|---|---|---|---|---|---|---|---|
| ht | S-sol | **86.7** | **94.6** | **72.5** | – | 9.8 s | 25 / 48 s | 0.74 |
| ht | P8-sol | 74.2 | 84.7 | 59.2 | 23% | **5.0 s** | 31 / 77 s | 2.83 |
| ht | S-gemma31 | 76.7 | 93.7 | 62.5 | – | 10.0 s | 28 / 43 s | 0.02 |
| ht | P8-gemma31 | 64.2 | 82.0 | 52.5 | 24% | **5.0 s** | 25 / 60 s | 0.12 |
| km | S-sol | **79.2** | **94.6** | **70.0** | – | 9.7 s | 25 / 38 s | 1.27 |
| km | P8-sol | 66.7 | 87.4 | 51.7 | 26% | 4.5 s | **11** / 38 s | 4.02 |
| km | S-gemma31 | 75.8 | 91.0 | 66.7 | – | 10.0 s | 25 / 36 s | 0.03 |
| km | P8-gemma31 | 61.7 | 82.0 | 48.3 | 24% | **4.0 s** | **11** / 34 s | 0.13 |
| lo | S-sol | **81.7** | **92.8** | **73.3** | – | 10.7 s | 26 / 41 s | 2.89 |
| lo | P8-sol | 70.0 | 88.3 | 60.8 | 22% | 4.8 s | **9** / 30 s | 7.69 |
| lo | S-gemma31 | 77.5 | 88.3 | 66.7 | – | 9.7 s | 34 / 47 s | 0.03 |
| lo | P8-gemma31 | 62.5 | 89.2 | 51.7 | 23% | **4.4 s** | 13 / 42 s | 0.15 |

Per clip, with meaning units, listener questions and queued timings: [table.md](table.md);
everything in `results.json`.

## What it shows

- **Phrases cost more here than for Spanish/Portuguese/French.** Against whole sentences with
  the same translator: 12–15 points on read news and 5–10 on the meeting (sol), against roughly
  10 for es/pt/fr in the earlier round. About **1 phrase in 4** turned out wrong once the
  sentence was known (22–26%), against about 1 in 7 for es/pt/fr; on read news with irregular
  pauses Khmer reached 35%. Listener questions held up better than the grade (phrase systems
  83–97 correct against 87–98), so most of the loss is phrasing, word order and the occasional
  wrong guess rather than lost facts.
- **The meeting is kinder to phrases** (82–89 against 88–95 for sentences): people pause at
  phrase boundaries and say shorter things.
- **sol is the better phrase translator for Haitian Creole and Khmer** (3–10 points over Gemma 4),
  and costs 20–50× more per hour in phrase mode (each phrase resends the sentence so far). For
  Lao the two are close in phrase mode on the meeting (88 vs 89).
- **Speed:** a sentence's first translated words could start about **4–5 s** after its speech
  begins in phrase mode, against **10–11 s** for whole sentences. On a monologue the voice queue
  eats most of that unless the voice keeps up:
  - **Khmer and Lao (Azure, trimmed pauses, +8%) keep up on read news:** the phrase output's
    audio is shorter than the speech (133–150 s for 147–162 s), and all audio ends 8–17 s after
    the speaker (14–46 s for whole sentences). On the meeting the audio runs longer than the
    speech (161–174 s for 149 s) and the backlog grows (30–42 s).
  - **The Haitian Creole voice does not keep up in phrase mode.** Gemini TTS takes about 0.94 s to
    first audio per chunk (Azure Khmer/Lao about 0.4 s), has no rate or pause control, and phrase
    output ran 161–208 s of audio for 147–162 s of speech; on the meeting all audio ended 60–77 s
    after the speaker, against 43–48 s for whole sentences.

## Recommendation

- **Haitian Creole:** no fast mode. Whole sentences with sol (87–95), Gemini voice.
- **Khmer and Lao:** keep whole sentences as the default (sol: 79–95). Fast mode is usable only
  as an opt-in for conversation rooms: Khmer with sol (87 on the meeting) or Lao with either
  translator (88–89), Azure voice with trimmed pauses and +8%. Expect about 1 phrase in 4 to be
  slightly off, with captions corrected when the sentence ends.
- Not for read speech or long talks.

## Limits

- One read-news clip per pause pattern and one meeting excerpt, one run, one grading round per
  target; the grader is a Gemini model.
- The English partials are recorded, so recognition is identical across systems; live, the phrase
  cutter would see the same partials.
- The meeting's English reference is a model-made verbatim transcript; read news has both.
- Voice timing uses each chunk's measured time to first audio and length; nothing was played.

## Files

`mt.py` (translate the chunk plans), `tts.py` (voice check and synthesis), `seg.py` (sentence
cut), `grading.py` (units, listener questions, 0–100 jobs, contradiction jobs; the 0–100 and
contradiction passes run `../2026-10-es-pt-live-compare/grade.py` and
`../2026-10-simultaneous-phrases/contradictions.py`), `analyze.py` (timeline and tables),
`results.json`, `voice_check.json`, `table.md`.
