# Complete-thought sentence ends for Haitian Creole, Khmer and Lao. October 2026

[`../2026-10-complete-thought-endpointing`](../2026-10-complete-thought-endpointing/) found that CT (b) was the best way
to end a sentence early. At each decision point Gemma is asked whether the words heard so far form a complete thought,
and a thought is committed only when two checks in a row name the same end word. For en→fr, with Gemma deciding and sol
translating, CT (b) matched sol sentences (90.4) and cut the p90 last audio from 10.8 s to 6.3 s. This run asks the same
question for Haitian Creole, Khmer and Lao, where sol has to translate: is complete-thought faster than today's
sentences, without losing quality?

## Setup

- **Clips** (`build_clips.py`):
  - English, Khmer and Lao: 20 FLEURS test sentences (CC BY 4.0) shared by en_us, km_kh and lo_la, drawn with seed
    2026. Left out: every id named in an earlier eval's json files, the first 30 rows of the km and lo test lists (the
    set the CTC-stream and duo runs used), and any sentence whose text appears in an earlier json file. Only 33 ids
    were left to draw from.
  - Haitian Creole: FLEURS has none. The clip is 20 CMU Haitian Creole utterances from 20 speakers, none used before
    (checked by text and by utterance id). Their English reference is model-made by gemini-flash-latest
    (`make_refs.py`), so ht→en scores rank the arms against each other, not against a human translation. The CMU
    texts are not published here, and neither is anything that contains them.
  - The two pause patterns as before: *reg* (1.0–1.95 s between sentences) and *irr* (0.3–1.2 s).
- **What was said** (`witness.py` from the earlier run): 5 of the 20 English recordings stop early or are misread,
  and those are graded against what was said. 2 recordings each are flagged in ht, km and lo, and these are left out
  of the into-English scores.
- **Hearing**:
  - **English:** MAI-Transcribe-2-Streaming, streamed in real time, keeping every partial and final, as before.
  - **ht, km and lo:** omni-stt from the public repo's `main`, running on a short-lived GPU (one A40). Stock Meta
    checkpoints only. Each service ran with its defaults, and the clips were streamed at real time from the same host
    (`pod_setup.sh`, `pod_run.sh`, `stream_omni.py`). Four services shared the GPU, with up to eight sockets at once.
  - **Haitian Creole:** `omniASR_LLM_300M`, the **stock** card. Production uses a private fine-tune of it, which was
    not available here.
  - **Khmer and Lao:** the 7B service (`omniASR_LLM_7B`, bf16) for the finals, and beside it on the same audio, the
    CTC 3B streaming service (`?stream=ctc&lookahead=2`), as a solo Khmer or Lao room opens them.
  - The prototype partial passes for Haitian Creole (`STT_PARTIALS=1`, off in production) ran as a fourth service.
- **What the recognisers give for decision points.** See "Hearing" below. `convert_omni.py` puts the recordings into
  the replay's format:
  - **Haitian Creole (production):** one final per piece and nothing in between. The pieces end at 200 ms breaths,
    with a median of 3.4 s. Word times are not given, only the piece's start and end, so the replay spreads a piece's
    words over the time since the words before (as for MAI partials). This affects only the reported source times,
    not any latency figure. The decision points are the finals.
  - **Khmer and Lao:** the 7B's finals (pieces with a median of 3.4–4.4 s) are the text of record. Between them, the
    CTC 3B track gives committed text about every 500 ms, trailing the audio by 2.0–2.1 s, plus a revisable tail. The
    replay reads the live text the way Live Translation's solo room does (`omni-ctc.ts`): committed text that no 7B
    piece covers yet, then the tail, with the committed words counted as stable. Each 7B final replaces the live text
    it covers. The decision points are every live-text change and every final.
  - **Khmer and Lao words:** both languages write no spaces between words, so `words.py` splits them with ICU's word
    break (Node's `Intl.Segmenter`) for the numbered words Gemma sees, and joins them back without spaces.
- **Arms** (`simulate.py`, wrapping `../2026-10-complete-thought-endpointing/simulate_ct.py` unchanged):
  1. **Sentences, sol:** one sol call per recogniser final (gpt-6-sol on Azure AI Foundry, `FOUNDRY_DEPLOYMENT`,
     `reasoning_effort` low). For ht, km and lo, a final is an omni-stt piece, which is what production translates.
  2. **CT (b), Gemma decides, sol translates:** `google.gemma-4-31b` on Bedrock (us-east-2) decides. sol translates
     each committed thought.
  3. **CT (b), sol decides and translates:** run out of English on the *reg* clips only, because each check takes sol
     1.7–2.4 s and it is the costliest arm.
  4. **CT (b), Gemma only**, for reference.
  - **ht→en only:** CT (a) with Gemma deciding and sol translating (see the first finding), and Gemma-only CT (b) on
    the prototype partials.
  - **Unchanged from the earlier run:** the 2 s quiet / 30 words fallback, the prompts, and one call at a time per
    stream.
  - Foundry refused 12 Haitian Creole requests with HTTP 400. Each one was answered when sent again without its
    context, as Live Translation does.
- **Voice timing** (`tts_timing.py`): Azure Jenny (en), Sreymom (km) and Keomany (lo). Azure has no Haitian Creole
  voice, so the French voice Denise reading the Haitian text stands in for the speaking rate. Gemini TTS's own time to
  first audio is not modelled.
- **Grading** (`grade_all.py`, `split.py`, `analyze.py`): the earlier cut, grade, contradiction and split checks, with
  gemini-flash-latest. All arms of a direction and clip are graded side by side in one blind call. Both rounds ran in
  every direction (the second under new ids, so the arms are shuffled differently). `table.py` and `patterns.py` make
  the tables.

## Hearing

`hearing.py` produced these figures (`raw/hearing.json`). "Final after piece end" counts from the end of a piece's
audio to the arrival of its text, on the shared A40.

| Clip | Pieces (20 sentences) | Piece length p50 | Final after piece end p50 / p90 | CER finals | CTC committed: lag p50 / CER |
|---|---|---|---|---|---|
| ht reg / irr (300M, stock) | 44 / 46 | 3.4 s | 0.9 / 2.5 s, 1.0 / 2.5 s | 6.3% / 7.4% | – |
| km reg / irr (7B + CTC 3B) | 43 / 39 | 4.4 s | 1.8 / 3.0 s, 1.9 / 4.8 s | 21.2% / 26.7% | 2.0 s / 20.3%, 18.3% |
| lo reg / irr (7B + CTC 3B) | 53 / 54 | 3.4 s | 1.3 / 3.0 s, 1.5 / 4.3 s | 13.4% / 14.3% | 2.0 s / 15.9%, 15.5% |

- **Haitian Creole has no usable partials in production.** Only per-piece finals arrive. The prototype partial
  passes gave just 1.5–1.7 partials per piece, because a pass runs every 1.5 s of audio and the pieces are short.
- **Khmer and Lao do have usable live text,** from the CTC track.
- **Pieces are not sentences.** At 200 ms breaths, omni-stt cuts a read sentence into 2–2.7 pieces. "Sentences" for
  these languages therefore means pieces, and 25–47% of the read sentences reach the listener split mid-clause.

## Results

Each cell is the mean of both pause patterns and both grading rounds. Latencies are medians of the two clips, in
seconds, and the longest wait is the larger of the two. The columns are as in the earlier run. "Calls per sentence"
is per read sentence, counting Gemma calls plus sol calls where marked. "Thoughts by fallback" is the number of chunks
from the 2 s or 30-word fallback per read sentence, so it can exceed 100% where there are more pieces than sentences.
\* For sentence arms, "wrong later" counts the *reg* clip only, as before.

| Direction | Arm | Quality, said (round 1) | Round 2 | Mean | Critical | Speech starts → first audio (s) | Speech ends → last audio, p50 (s) | p90 (s) | Longest wait (s) | Chunks wrong later | Sentences split mid-clause | Quality of unsplit sentences | Calls per sentence | Thoughts by fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| en→ht | Sentences, sol | 90.8 | 87.5 | **89.2** | 0.5 | 10.5 | 4.3 | 10.6 | 23.2 | 14%* | 12% | 95.2 | 1.1 sol | – |
| en→ht | CT (b), Gemma decides, sol translates | 93.3 | 91.7 | **92.5** | 1.0 | 9.7 | 5.2 | 11.8 | 24.1 | 10% | 5% | 94.7 | 9.3 + 1.4 sol | 12% |
| en→ht | CT (b), sol decides and translates (reg clip only) | 88.3 | 85.0 | **86.7** | 0.0 | 12.4 | 6.8 | 15.2 | 20.9 | 23% | 5% | 89.5 | 4.3 sol | 25% |
| en→ht | CT (b), Gemma only | 76.7 | 77.5 | **77.1** | 2.0 | 8.6 | 3.2 | 7.7 | 14.3 | 6% | 8% | 80.2 | 13.0 | 12% |
| en→km | Sentences, sol | 90.0 | 90.8 | **90.4** | 0.5 | 10.9 | 5.1 | 11.3 | 23.4 | 17%* | 18% | 97.9 | 1.1 sol | – |
| en→km | CT (b), Gemma decides, sol translates | 88.3 | 86.7 | **87.5** | 1.0 | 10.0 | 5.3 | 10.7 | 23.4 | 9% | 8% | 89.1 | 9.1 + 1.4 sol | 18% |
| en→km | CT (b), sol decides and translates (reg clip only) | 95.0 | 96.7 | **95.8** | 0.0 | 12.1 | 7.1 | 12.3 | 20.4 | 17% | 0% | 95.0 | 4.5 sol | 25% |
| en→km | CT (b), Gemma only | 82.5 | 73.3 | **77.9** | 1.5 | 8.5 | 3.6 | 8.5 | 15.7 | 11% | 10% | 84.2 | 12.8 | 18% |
| en→lo | Sentences, sol | 90.8 | 92.5 | **91.7** | 1.0 | 12.5 | 7.0 | 16.1 | 26.8 | 10%* | 18% | 96.3 | 1.1 sol | – |
| en→lo | CT (b), Gemma decides, sol translates | 91.7 | 90.8 | **91.2** | 1.0 | 12.2 | 7.7 | 16.0 | 25.9 | 13% | 8% | 92.8 | 6.8 + 1.4 sol | 15% |
| en→lo | CT (b), sol decides and translates (reg clip only) | 93.3 | 91.7 | **92.5** | 1.0 | 14.2 | 11.2 | 15.6 | 24.9 | 35% | 10% | 94.4 | 3.1 sol | 40% |
| en→lo | CT (b), Gemma only | 76.7 | 80.0 | **78.3** | 2.0 | 8.6 | 3.6 | 8.1 | 15.6 | 8% | 8% | 78.4 | 13.1 | 15% |
| ht→en | Sentences (pieces), sol | 65.8 | 65.8 | **65.8** | 3.0 | 8.2 | 2.7 | 6.0 | 15.8 | 0%* | 28% | 61.5 | 2.2 sol | – |
| ht→en | CT (b), Gemma decides, sol translates | 69.5 | 70.3 | **69.9** | 2.5 | 10.4 | 4.9 | 8.1 | 18.5 | 5% | 19% | 65.6 | 2.2 + 1.9 sol | 188% |
| ht→en | CT (a), Gemma decides, sol translates | 72.2 | 72.2 | **72.2** | 2.0 | 9.7 | 4.2 | 6.6 | 16.1 | 1% | 19% | 67.8 | 2.1 + 2.0 sol | 90% |
| ht→en | CT (b), Gemma only | 52.8 | 49.0 | **50.9** | 3.5 | 8.8 | 3.7 | 6.3 | 17.4 | 3% | 17% | 51.1 | 3.1 | 188% |
| ht→en | CT (b), Gemma only, on the prototype partials | 44.4 | 45.3 | **44.9** | 5.0 | 11.7 | 7.2 | 12.1 | 21.1 | 30% | 19% | 41.2 | 5.2 | 75% |
| km→en | Sentences (pieces), sol | 71.3 | 71.3 | **71.3** | 1.5 | 10.4 | 3.6 | 6.5 | 20.3 | 5%* | 25% | 74.6 | 2.0 sol | – |
| km→en | CT (b), Gemma decides, sol translates | 73.2 | 72.2 | **72.7** | 2.0 | 14.9 | 5.5 | 10.5 | 19.5 | 11% | 0% | 73.2 | 10.6 + 1.3 sol | 82% |
| km→en | CT (b), Gemma only | 51.0 | 54.6 | **52.8** | 6.0 | 13.0 | 4.4 | 10.7 | 25.8 | 19% | 8% | 53.5 | 11.9 | 72% |
| lo→en | Sentences (pieces), sol | 60.2 | 65.8 | **63.0** | 3.0 | 9.2 | 4.4 | 6.8 | 22.5 | 6%* | 47% | 67.2 | 2.7 sol | – |
| lo→en | CT (b), Gemma decides, sol translates | 64.8 | 71.3 | **68.1** | 3.0 | 13.5 | 5.4 | 12.9 | 22.7 | 10% | 19% | 66.7 | 10.8 + 1.4 sol | 70% |
| lo→en | CT (b), Gemma only | 48.1 | 56.5 | **52.3** | 3.5 | 11.7 | 3.7 | 9.1 | 16.7 | 13% | 17% | 46.7 | 12.7 | 68% |

**By pause pattern** (`patterns.py`). Quality is the mean of the two rounds. "Wait p90" is the p90 of the per-chunk
wait.

| Direction | Pauses | Arm | Quality | Critical | First audio | Last audio p50 / p90 | Wait p90 | Longest wait |
|---|---|---|---|---|---|---|---|---|
| en→ht | reg | Sentences, sol | 88.3 | 1 | 8.5 | 2.8 / 4.6 | 12.7 | 14.1 |
| en→ht | reg | CT (b) Gemma-sol | 89.2 | 2 | 9.7 | 4.8 / 9.1 | 14.7 | 16.1 |
| en→ht | irr | Sentences, sol | 90.0 | 0 | 12.5 | 5.9 / 16.7 | 22.3 | 23.2 |
| en→ht | irr | CT (b) Gemma-sol | 95.8 | 0 | 9.7 | 5.5 / 14.5 | 15.0 | 24.1 |
| en→km | reg | Sentences, sol | 88.3 | 1 | 8.7 | 3.2 / 5.2 | 12.8 | 19.3 |
| en→km | reg | CT (b) Gemma-sol | 85.0 | 2 | 10.2 | 4.8 / 11.4 | 13.1 | 16.9 |
| en→km | irr | Sentences, sol | 92.5 | 0 | 13.1 | 6.9 / 17.5 | 23.2 | 23.4 |
| en→km | irr | CT (b) Gemma-sol | 90.0 | 0 | 9.8 | 5.7 / 10.1 | 14.6 | 23.4 |
| en→lo | reg | Sentences, sol | 91.7 | 1 | 10.4 | 4.4 / 12.0 | 20.6 | 22.3 |
| en→lo | reg | CT (b) Gemma-sol | 89.2 | 2 | 11.6 | 7.3 / 20.9 | 17.9 | 25.9 |
| en→lo | irr | Sentences, sol | 91.7 | 1 | 14.6 | 9.6 / 20.2 | 25.8 | 26.8 |
| en→lo | irr | CT (b) Gemma-sol | 93.3 | 0 | 12.9 | 8.1 / 11.2 | 17.0 | 20.0 |
| ht→en | reg | Sentences, sol | 62.0 | 4 | 9.1 | 2.5 / 4.9 | 11.2 | 14.8 |
| ht→en | reg | CT (a) Gemma-sol | 71.3 | 3 | 10.6 | 4.3 / 5.6 | 12.1 | 14.7 |
| ht→en | irr | Sentences, sol | 69.5 | 2 | 7.2 | 2.9 / 7.0 | 11.7 | 15.8 |
| ht→en | irr | CT (a) Gemma-sol | 73.2 | 1 | 8.9 | 4.0 / 7.7 | 12.1 | 16.1 |
| km→en | reg | Sentences, sol | 70.4 | 2 | 9.5 | 3.8 / 5.0 | 13.5 | 15.6 |
| km→en | reg | CT (b) Gemma-sol | 69.5 | 4 | 15.0 | 5.8 / 10.7 | 17.7 | 19.5 |
| km→en | irr | Sentences, sol | 72.2 | 1 | 11.4 | 3.4 / 8.0 | 14.1 | 20.3 |
| km→en | irr | CT (b) Gemma-sol | 75.9 | 0 | 14.7 | 5.3 / 10.3 | 17.3 | 19.5 |
| lo→en | reg | Sentences, sol | 68.5 | 2 | 9.1 | 3.9 / 5.4 | 10.8 | 15.4 |
| lo→en | reg | CT (b) Gemma-sol | 70.3 | 2 | 14.0 | 5.4 / 13.6 | 17.4 | 22.7 |
| lo→en | irr | Sentences, sol | 57.5 | 4 | 9.2 | 5.0 / 8.2 | 13.4 | 22.5 |
| lo→en | irr | CT (b) Gemma-sol | 65.8 | 4 | 13.1 | 5.3 / 12.2 | 17.8 | 20.8 |

Call times: Gemma's checks took a median of 0.29–0.40 s (p90 0.55–1.0 s). sol took 1.1–1.9 s to translate a thought,
1.0–2.3 s for a sentence, and 1.7–2.4 s for a check. Lao was the slowest. On en→lo, one sol sentence call took 16.8 s and one translate call took 16.6 s. The second accounts for most of
the 20.9 s p90 on the *reg* clip.

## Findings

1. **Out of English, quality holds.** With Gemma deciding and sol translating, CT (b) is +3.3 for en→ht, −2.9 for
   en→km and −0.5 for en→lo against sol sentences. It is never more than 5 points below, and its critical errors
   match those of sentences. Gemma's choice of thoughts works as well on English as it did before: 9–12% of thoughts
   came from the fallback.
2. **Out of English, it is faster only when the speaker runs sentences together.**
   - **Irregular pauses** (one MAI final often covers two or three sentences): CT (b) cuts the p90 last audio from
     16.7 to 14.5 s (en→ht), from 17.5 to 10.1 s (en→km) and from 20.2 to 11.2 s (en→lo). The p90 wait falls from
     22–26 s to 15–17 s, and first audio comes 1.7–3.3 s sooner.
   - **Regular pauses** (1–2 s): MAI already ends each sentence promptly, and CT is *slower*. Its p90 last audio is
     9.1–11.4 s against 4.6–5.2 s for en→ht and en→km. Each thought costs a second confirming check and then a sol
     call (1.1–1.9 s) that holds the stream.
   - Averaged over both patterns, the two arms come out about even (p90 10.7–16.0 s against 10.6–16.1 s). The
     en→fr gain of the earlier run (10.8 to 6.3 s) does not carry over in that form.
3. **sol deciding (out of English, *reg* only) is too slow.** Its quality is good (86.7, 95.8 and 92.5), but first
   audio is 12–14 s and the p90 last audio 12–15 s. Up to 47% of its chunks come from the fallback.
4. **Into English, today's pieces are already short, and CT makes the listener wait longer.**
   - **ht→en:** with finals only, CT (b) **never commits by agreement**. Every decision point is a new final, and a
     new final changes the tail, so the replay clears the previous check. 74 of its 75 chunks came from the 2 s
     fallback, so in practice it joins pieces until a 2 s pause. It added 2.2 s to first audio and 2.1 s to p90.
   - **ht→en, CT (a)** (commit on the first "complete"; one check per final) fits finals-only hearing better. It scored
     72.2 against 65.8 (+6.4), with 2.0 critical errors per clip against 3.0, mostly because it splits fewer sentences
     (19% against 28%). It cost 1.5 s more to first audio, 0.6 s more at p90, and 0.3 s more on the longest wait.
   - **km→en and lo→en:** CT (b) is +1.4 and +5.1. It cuts the sentences split mid-clause from 25% to 0% (km) and from
     47% to 19% (lo). It costs 4.3–4.5 s more to first audio, 4.0–6.1 s more at p90, and 10.6–10.8 Gemma calls per
     sentence. Gemma seldom finds a complete thought in Khmer or Lao recognition (CER 13–27%): 50–65% of its chunks
     came from the fallback.
   - Gemma alone translates far worse into English: 50.9–52.8 for all three languages.
5. **The prototype ht partials do not help.** Gemma-only CT (b) on them scored 44.9 against 50.9 on finals. It was
   slower (p90 12.1 s), and 30% of its chunks were contradicted later. Two passes a piece are too few to agree on.
6. **The Gemma-only reference** is 77–78 out of English, 11–13 points below sol sentences, so sol stays the translator, as
   assumed.

## Recommendation per direction

Phones run fast mode (the first audio matters most). The PA puts quality first, and CT takes the place of sentences
only if it is within 5 points of them. "Sentences" here means each direction's production unit: an MAI final out of
English, an omni-stt piece into English.

| Direction | Phones | PA |
|---|---|---|
| en→ht | **CT (b), Gemma decides and sol translates, when the speaker does not pause between sentences.** Otherwise keep sentences. It scores 92.5 against 89.2, and on run-on speech it starts 2.8 s sooner with the p90 wait at 15 s against 22 s. With regular pauses it ends later (p90 9.1 s against 4.6 s). | Passes the rule (+3.3). **Use it for run-on speakers only** (the room's existing run-on detection could switch it). With regular pauses, keep sentences. |
| en→km | The same: **CT (b) Gemma-sol for run-on speech** (p90 10.1 s against 17.5 s), sentences otherwise. | Passes the rule (−2.9). The same switch. |
| en→lo | The same: **CT (b) Gemma-sol for run-on speech** (p90 11.2 s against 20.2 s), sentences otherwise. | Passes the rule (−0.5). The same switch. |
| ht→en | **Keep pieces (sentences).** CT (b) cannot agree on finals-only hearing. CT (a) Gemma-sol is the candidate: +6.4 for 1.5 s more to first audio. | **CT (a) Gemma-sol is a candidate:** +6.4, with p90 +0.6 s. Confirm it on more clips and with the production fine-tune first. CT (b) as built: no. |
| km→en | **Keep pieces.** CT (b) is +1.4 but starts 4.5 s later. | **Keep pieces.** CT passes the rule (+1.4) but is 4 s slower at p90 for no clear gain. |
| lo→en | **Keep pieces.** CT (b) starts 4.3 s later. | **CT (b) Gemma-sol is a candidate:** +5.1 and far fewer mid-clause splits, for 6 s more at p90. Gemma decided only half of the thoughts itself. |

Not tested here:
- a cheaper rule for km/lo/ht→en that joins pieces until a longer pause without Gemma. That is mostly what CT did
  there.
- CT (b) with the agreement surviving a final that did not move the end word.
- pipelining the sol translation so that it does not hold the decider.
- the production Haitian Creole fine-tune.
- Gemini TTS timing for Haitian Creole.

## Limits

- One clip set per language: 20 read sentences, joined with artificial pauses. For ht→en the reference is
  model-made. A few points either way is noise: the two rounds differ by up to 8.4 points (lo→en, Gemma only).
- Hearing ran on one A40 with four services and up to eight sockets sharing it. That is not production's Cloud Run L4
  per service, so the omni-stt delays are indicative only (7B finals arrived 1.3–1.9 s after a piece ended, p50).
- Haitian Creole used the stock 300M card, not production's fine-tune. Its CER was 6–7% on these clips.
- The sol-decides arm ran on the *reg* clips only.
- The latency model is the earlier run's: one call at a time per stream, and the voice's time to first audio added to
  each chunk.
- The Haitian Creole voice timing is a stand-in (an Azure French voice reading the Haitian text).

## Files

- `build_clips.py`, `make_refs.py`: clips and the ht reference. `stream_omni.py`, `pod_setup.sh`, `pod_run.sh`: omni-stt
  on the GPU. `convert_omni.py`, `words.py`: recordings to the replay's format, and Khmer/Lao words. `hearing.py`: the
  hearing table.
- `simulate.py`: the arms. `tts_timing.py`: voice timing. `grade_all.py`, `split.py`: the cut, grade, contradiction
  and split checks. `analyze.py`: writes `results.json` (round 1) and `results_r2.json` (round 2). `table.py`,
  `patterns.py`: the tables.
- `raw/hearing.json` (the hearing table), `raw/tts.json` (voice timing) and `raw/refusals.json` (the Foundry
  refusals and how many were answered without context).

**Not included:**
- the clip audio and the clip metadata (`raw/clips/`: the FLEURS ids and texts for en, km and lo, the CMU utterance
  ids for ht): `build_clips.py` rebuilds them;
- the MAI and 7B/CTC recognition output (`raw/rec/`), each replay's chunks and calls (`raw/sim/`) and the cut (`raw/seg/`):
  about 3 MB of raw dumps that carry the transcripts and translations;
- the grading inputs and outputs (`jobs*.json`, `grades*.json`, `contra*.json`, `split*.json`) and `witness/`: raw
  dumps with the sentence texts. Their figures are in `results.json` and `results_r2.json`.
- anything that contains the CMU Haitian Creole text (see Setup).
- `simulate.py` wraps `../2026-10-complete-thought-endpointing/simulate_ct.py`, which needs the earlier commit-policy
  run's `simulate_policy.py` (not yet in this repository; see that folder's README).

## Reproduce

```
python3 -I build_clips.py CLIPS ../2026-10-real-voices USED_IDS.json ../ <other earlier eval roots>
GEMINI_API_KEY=... python3 -I make_refs.py CLIPS/clips_reg
AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 MODEL=mai-transcribe-2-streaming \
  <venv with azure-cognitiveservices-speech==1.52.0>/bin/python -I ../2026-10-complete-thought-endpointing/stream_partials.py CLIPS/clips_reg WORK/rec mai_reg en
#   (and clips_irr with tag mai_irr)
GEMINI_API_KEY=... python3 -I ../2026-10-complete-thought-endpointing/witness.py CLIPS/clips_reg <en|ht|km|lo> UO/witness/<lang>.json
# on a 48 GB GPU host: /w/stt.tgz (services/omni-stt staged as deploy.sh stages it), /w/clips, then
bash pod_setup.sh && bash pod_run.sh                       # -> /w/out/{o3,o3p,o7c}_<pattern>_<lang>.json
python3 -I convert_omni.py OMNI_OUT WORK/rec && python3 -I hearing.py OMNI_OUT CLIPS > raw/hearing.json
CLIPS_ROOT=CLIPS FOUNDRY_ENDPOINT=... FOUNDRY_KEY=... FOUNDRY_DEPLOYMENT=... <venv with boto3, numpy>/bin/python simulate.py WORK
AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus2 python3 -I tts_timing.py WORK
GEMINI_API_KEY=... python3 -I grade_all.py seg CLIPS WORK
python3 -I analyze.py jobs CLIPS UO WORK                   # jobs_r2.json: jobs.json with each id + ":r2"
GEMINI_API_KEY=... python3 -I grade_all.py grade WORK/jobs.json WORK/grades.json
GEMINI_API_KEY=... python3 -I grade_all.py grade WORK/jobs_r2.json WORK/grades_r2.json
GEMINI_API_KEY=... python3 -I grade_all.py contra WORK/contra_jobs.json WORK/contra.json
GEMINI_API_KEY=... python3 -I split.py WORK/split_jobs.json WORK/split.json
python3 -I analyze.py table CLIPS UO WORK && GRADES=grades_r2.json RESULTS=results_r2.json python3 -I analyze.py table CLIPS UO WORK
python3 -I table.py && python3 -I patterns.py
```
