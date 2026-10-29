# Agree live on the stack, and German turn length. October 2026

Two questions, answered live on the stack (one RTX PRO 6000 pod, every clip streamed in real time):

1. **Simultaneous mode.** [`../2026-10-llm-commit-policy`](../2026-10-llm-commit-policy/) replayed recorded streaming
   recognition through Gemma on the Gemini API and found that *agree* nearly matched whole sentences while speaking
   about as early as the 8-word phrase rule. Does that hold on the stack itself, with its Whisper re-transcription and
   its own 4-bit Gemma? This branch adds the policy (`server/agree.py`, `?stream=1&policy=agree`).
2. **German turns.** [`../2026-10-de-ru-ro`](../2026-10-de-ru-ro/) found long turns worth about 8 points for German
   speakers, but with a 15 s cap the slowest tenth of sentences waited almost 10 s. Does a lower cap keep the gain?

## Setup

- **Hardware and models:** one RTX PRO 6000 Blackwell 96 GB pod (RunPod US-NC-1), the stack image `2026.10.09.2` with
  this branch. Gemma 4 31B 4-bit (`google/gemma-4-31B-it-qat-w4a16-ct`) under vLLM 0.31 on the same GPU
  (`--gpu-memory-utilization 0.40`, prefix caching). Whisper large-v3 hears every language. MADLAD 3B was loaded only as
  the fallback; no request fell back to it (no "MADLAD instead" line in any stack log).
- **Client** (`e2e_client.mjs`, ../2026-10-de-ru-ro's): one connection in its own room, fixed `?src=`, `?context=1`,
  100 ms chunks in real time. `Q` adds the mode's query parameters.
- **Simultaneous mode** (`configs/S.toml`): en↔es and en↔fr on the unseen clips of
  [`../2026-10-open-streaming`](../2026-10-open-streaming/) (20 FLEURS sentences, regular *reg* 1.0–1.95 s and
  irregular *irr* 0.3–1.2 s pauses, rebuilt on the pod by its `build_unseen_subset.py`). Gemma translates both ways in
  this config (into English is Hy-MT2 by default), so the three arms differ only in when they speak:
  - **Utterance:** today's default; each turn is translated once it ends (700 ms pause, cut at 9 s).
  - **Clause** (`?stream=1`): the stack's simultaneous mode as it was. Whisper re-transcribes the turn every second,
    words two passes agree on are committed, and committed words are spoken a clause at a time (a sentence end, a
    comma after 6 words, or 8 words).
  - **Agree** (`?stream=1&policy=agree`): the same commits; at each pass with new words Gemma translates the turn so
    far and the words two successive translations agree on are spoken. The turn's end completes it. More than 10
    words untranslated speak the latest translation; at most 8 calls a turn.
- **German turns:** de→en on set a of ../2026-10-de-ru-ro (rebuilt on the pod by its `build_clips.py`), both pause
  patterns, utterance mode, Hy-MT2 translating (`configs/G*.toml`, `make_configs.py`):
  - **G1** default turns (700 ms pause, cut at 9 s);
  - **G3** long turns as ja/ht/km/lo (900 ms pause, 500 ms after 8 s, at least 2.5 s of speech) cut at 15 s;
  - **G5** the same cut at 12 s; **G4** cut at 10 s.
- **Analysis** (`analyze.py`): ../2026-10-unseen/analyze_e2e.py, per sentence. In simultaneous mode a turn's
  translation is spoken before the stack sends what it heard (`inputTranscript`, at the turn's end), so a turn opens at
  the stack's `route` message instead.
- **Grading** (`grade.py`, `round.py`): gemini-pro-latest, blind, the arms side by side, one call per direction and
  clip, against the FLEURS text in the target language. Scores 0–100; critical errors counted.

## Results

**Simultaneous mode** (mean of the two directions and two pause patterns in each group, 4 graded clips of 20
sentences; latencies are medians of the per-clip medians, in seconds; negative: before the speaker stops)

| Group | Arm | Quality | Critical per clip | Speech starts → first audio | Speech ends → first audio | Speech ends → audio ends, p50 / p90 |
|---|---|---|---|---|---|---|
| Out of English (en→es, en→fr) | Utterance | **60.8** | 7.8 | 7.0 | 1.4 | 8.0 / 12.0 |
| | Clause | 49.2 | 9.0 | 4.5 | −1.5 | 6.1 / 8.3 |
| | **Agree** | **60.4** | 7.5 | **4.3** | −1.8 | 6.4 / 9.9 |
| Into English (es→en, fr→en) | Utterance | **81.2** | 1.3 | 8.0 | 1.5 | 7.9 / 11.6 |
| | Clause | 66.2 | 1.8 | 4.5 | −2.4 | 5.9 / 8.0 |
| | **Agree** | 79.2 | 1.3 | **3.6** | −3.1 | 6.9 / 8.9 |

Per clip (quality, critical errors):

| Clip | Utterance | Clause | Agree |
|---|---|---|---|
| en→es reg | 58.3 (8) | 50.0 (9) | 60.0 (8) |
| en→es irr | 61.7 (9) | 55.0 (9) | 60.0 (9) |
| en→fr reg | 68.3 (8) | 50.0 (11) | 70.0 (7) |
| en→fr irr | 55.0 (6) | 41.7 (7) | 51.7 (6) |
| es→en reg | 83.3 (1) | 61.7 (2) | 83.3 (1) |
| es→en irr | 80.0 (2) | 58.3 (3) | 76.7 (2) |
| fr→en reg | 81.7 (1) | 71.7 (1) | 78.3 (1) |
| fr→en irr | 80.0 (1) | 73.3 (1) | 78.3 (1) |

**German turns, de→en** (quality, critical errors; speech ends → first audio, p50 / p90 in seconds)

| Turns | Regular pauses | Irregular pauses | First audio, regular | First audio, irregular |
|---|---|---|---|---|
| G1 default (cut at 9 s) | 86.7 (2) | 88.3 (1) | 1.5 / 1.7 | 1.5 / 1.7 |
| G3 long, cut at 15 s | **93.3** (1) | **96.7** (0) | 1.9 / 2.1 | 2.0 / **10.0** |
| **G5 long, cut at 12 s** | 91.7 (1) | 91.7 (1) | 2.0 / 2.1 | 2.0 / 6.8 |
| G4 long, cut at 10 s | 86.7 (2) | 73.3 (3) | 1.9 / 2.1 | 1.7 / 4.9 |

## Findings

1. **Agree holds up live.** It scores within 0.4 points of whole utterances out of English (60.4 against 60.8) and
   2.0 into English (79.2 against 81.2), with the same critical errors. It starts speaking 2.7–4.4 s sooner, usually
   before the speaker has finished the sentence (1.8–3.1 s before, at the median).
2. **The stack's clause rule does not.** It is 11–15 points below utterances, with more critical errors. Agree is
   11–13 points above it and starts no later (0.2–0.9 s sooner).
3. **The replay's ranking carries over to the live stack, with its Whisper and its own Gemma:** agree near whole
   sentences, the fixed cut well below. The live gap between agree and utterances is smaller than the replay's MAI
   gap into English (−2.0 against −6.8).
4. **German: a 12 s cap keeps most of the gain.** Long turns cut at 12 s score 91.7 with both pause patterns, against
   86.7 and 88.3 for default turns. The slowest tenth with irregular pauses waits 6.8 s, against 10.0 s at 15 s. At
   10 s the gain is gone and irregular pauses get worse (73.3): the cut lands mid-sentence before the verb.
5. **Out-of-English scores are low for every arm** (51.7–70.0). 8 of the 20 English recordings say something other
   than the FLEURS text (../2026-10-open-streaming's witness: stopped early, misread, or a name heard differently), and grading here is against the FLEURS text, not what was said, so
   every arm loses the same points. Compare arms, not absolute values.

**Recommendations:**
- Keep agree as the stack's simultaneous policy, opt-in (`?stream=1&policy=agree`); consider making it the default for
  `?stream=1` once a room has been heard with it. The clause rule has no case left.
- German speakers: long turns cut at 12 s (PR #83).

## Limits

- One grading call per clip; a few points either way is noise, and the German table is one clip per cell.
- Read FLEURS sentences, one reader each, joined with artificial pauses; English, Spanish and French only for agree.
- Gemma ran on the same GPU as the stack; agree's calls per turn weren't counted.
- Utterance mode's first audio here (7.0–8.0 s from speech start) counts from the first word of a sentence; a turn
  holding two sentences makes the first one wait for the second.

## Files

- Scripts: `setup_pod.sh`, `clips.sh` (rebuilds both clip sets on the pod), `make_configs.py` (`configs/` from the
  repo's languages.toml), `live.sh`, `e2e_client.mjs`, `orchestrate.sh`, `analyze.py`, `round.py`, `grade.py`.
- `results.json`: every table above, with per-clip latency.
- `results/`:
  - `e2e_<arm>_<pattern>/`: each run's raw events (`out/runs/`), latency and per-sentence output (`out/`), the stack's
    log and the query (`query`). `st_U/C/A`: utterance, clause, agree; `de_G1/G3/G4/G5`: the German turns.
  - `stream_jobs.json`, `stream_grades.json`, `german_jobs.json`, `german_grades.json`: grading.
  - `clips_unseen_*`, `clips_de_a_*`, `ids.json`: the clip texts and timings (no audio).

## Reproduce

On a RunPod pod with the stack image `2026.10.09.2` and a GPU of at least 80 GB:

1. `BRANCH=<branch> bash setup_pod.sh`; copy this folder to `/workspace/al`.
2. `bash clips.sh`, then `bash orchestrate.sh` (about 2 h of live runs after setup).
3. Locally, with the work folder copied back: `python3 -I analyze.py WORK`, `python3 -I round.py jobs WORK`, then with
   `GEMINI_API_KEY` set `python3 -I grade.py WORK/stream_jobs.json WORK/stream_grades.json` (and `german_`), then
   `python3 -I round.py table WORK`.
