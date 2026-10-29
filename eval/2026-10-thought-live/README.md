# Complete thought live on the stack, English and German. October 2026

Live Translation found complete-thought cutting (CT (b)) the best way to end a sentence early: one Gemma decision
asks whether the words not yet translated begin with a complete thought, and a thought commits when two decisions in
a row end at the same word (`eval/2026-10-complete-thought-endpointing`, Gemma on Bedrock deciding over MAI's streaming
transcripts: 85.0 over ten directions against 80.4 for agree and 92.2 for whole sentences). It beat agree most where
agree guesses a late verb: into German, Hindi and Turkish, and from German and Turkish into English.

This branch adds it to the stack's simultaneous mode (`server/thought.py`, `?stream=1&policy=thought`), on those
five directions. Does it help on the stack itself, en↔de, against agree and against waiting for the pause?

## Setup

- **Hardware and models:** as `../2026-10-agree-live` (#84): one RTX PRO 6000 pod (RunPod US-NC-1), the stack image
  `2026.10.09.2` with this branch, Gemma 4 31B 4-bit under vLLM on the same GPU, Whisper large-v3, Gemma translating
  into German and Hy-MT2 into English. No request fell back to MADLAD; no thought decision failed.
- **Clips:** sets a and b of `../2026-10-de-ru-ro` (#76), 20 FLEURS sentences each shared by en and de, rebuilt on the
  pod by its `build_clips.py`: a with regular (1.0–1.95 s) and irregular (0.3–1.2 s) pauses, b with regular.
- **Arms** (`orchestrate.sh`; every arm runs with German long turns cut at 12 s (#83, `configs/G5.toml`) except U1):
  - **en→de:** U5 utterance mode; A agree (`?stream=1&policy=agree`); T complete thought (`?policy=thought`).
  - **de→en:** U1 utterance mode with default turns (700 ms pause, cut at 9 s); U5 with long turns cut at 12 s; T
    complete thought. Agree isn't offered from German.
- **Analysis and grading:** as `../2026-10-agree-live`: per sentence by `analyze.py` (turns open at the stack's
  `route` message), then gemini-pro-latest, blind, the arms side by side, one call per direction and clip, against the
  FLEURS text in the target language (`round.py`, `grade.py`).

## Results

Mean of three graded clips of 20 sentences; latencies are medians of the per-clip medians, in seconds (negative: before
the speaker stops).

| Direction | Arm | Quality | Critical per clip | Speech starts → first audio | Speech ends → first audio | Speech ends → audio ends, p50 / p90 |
|---|---|---|---|---|---|---|
| en→de | Utterance (U5) | 74.4 | 4.0 | 7.9 | 1.7 | 7.7 / 11.0 |
| | Agree | 67.8 | 4.0 | **3.8** | −2.8 | 5.7 / 9.9 |
| | Complete thought | **74.5** | 4.0 | 7.8 | 1.6 | 7.6 / 10.7 |
| de→en | Utterance, default turns (U1) | 82.8 | 2.0 | 9.0 | 1.4 | 8.5 / 11.4 |
| | Utterance, long turns at 12 s (U5) | **86.1** | 1.7 | 10.3 | 1.9 | 9.5 / 13.3 |
| | Complete thought | **86.1** | 1.7 | 9.4 | 1.9 | 9.0 / 13.3 |

Per clip:

| Clip | en→de U5 | A | T | de→en U1 | U5 | T |
|---|---|---|---|---|---|---|
| a, regular | 75.0 | 68.3 | 76.7 | 85.0 | 90.0 | 90.0 |
| a, irregular | 78.3 | 71.7 | 76.7 | 80.0 | 85.0 | 85.0 |
| b, regular | 70.0 | 63.3 | 70.0 | 83.3 | 83.3 | 83.3 |

How often each policy spoke before its turn ended (turns with a piece spoken before the stack's end-of-turn, of all
turns): complete thought 0–5 of 22–25 per run; agree 19–22 of 24–25.

## Findings

1. **Complete thought changes nothing on the stack.** It scores the same as utterance mode in both directions (74.5
   against 74.4; 86.1 both, clip for clip into English) at the same latency. It spoke before the turn's end in only
   0–5 of about 25 turns per run. The stack's turns already end at each pause (700 ms, or 900 ms for German speakers),
   so a turn rarely holds more than one thought. In Live Translation's runs, CT's gain came from cutting recogniser
   finals that held two or three sentences, which the stack doesn't produce.
2. **Agree costs 6.6 points into German** (67.8 against 74.4), for first audio 4.1 s sooner. That matches the Bedrock
   run (agree 77.5 against 89.2 for sentences). #84 now leaves German, Hindi and Turkish out of agree.
3. **German long turns help again**, by less than in `../2026-10-agree-live`: 86.1 against 82.8 (+3.3), for 1.3 s later
   first audio from speech start and 0.5 s from speech end. The p90 from speech end to the end of audio grows from 11.4
   to 13.3 s.

**Recommendation:** don't merge the thought policy; keep it on this branch with this record. It might help a speaker
who never pauses, where the stack cuts at 12–15 s, but these clips don't test that, and the forced cut already looks for
a sentence end (`forced_cut`). Agree stays the stack's simultaneous policy, for the directions #84 lists.

## Limits

- One grading call per clip, three clips per direction; a few points either way is noise.
- Read FLEURS sentences with artificial pauses: no speaker who runs sentences together for longer than a turn.
- Gemma decided on the stack's GPU, deciding once per Whisper pass (every second), where Live Translation decided at
  every partial.

## Files

- Scripts: `boot.sh` (the whole run on the pod; it stops the pod afterwards), `setup_pod.sh`, `clips.sh`,
  `make_configs.py`, `live.sh`, `e2e_client.mjs`, `orchestrate.sh`, `analyze.py`, `round.py`, `grade.py`.
- `results.json`: the tables above, with per-clip latency.
- `results/`: each run's raw events, latency, per-sentence output, stack log and query (`e2e_<arm>_<clip>/`);
  `jobs.json`, `grades.json`; the clip texts and timings (`clips_*`, `ids.json`; no audio).

## Reproduce

On a RunPod pod with the stack image `2026.10.09.2` and a GPU of at least 80 GB, as root:
`curl -fsSL <raw url of boot.sh> | BRANCH=<branch> bash` (about 1.3 h with setup). Then, with the work folder copied
back: `python3 -I analyze.py WORK`, `python3 -I round.py jobs WORK`, `GEMINI_API_KEY=... python3 -I grade.py
WORK/jobs.json WORK/grades.json`, `python3 -I round.py table WORK`.
