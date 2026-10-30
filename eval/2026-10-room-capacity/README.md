# How many rooms one 96 GB card serves. October 2026

A fresh pod from the RunPod template (`dftcc24b6q`, image `2026.10.29`, all 25 languages, nonprofit edition), on one
RTX PRO 6000 Blackwell 96 GB (RunPod EUR-IS-2, 32 vCPUs). Gemma 4 31B 4-bit ran beside the stack in vLLM, started by
the template's own `start-llmmt.sh` (#88). How many rooms can it serve at once before translations fall behind the
speaker?

## Setup

- **Load** (`load.py`): N rooms connected at once to the stack on the pod itself (`ws://127.0.0.1:8790`, so the
  network is not part of it). Each room is one English speaker, the same 20-sentence clip (2 min 40 s of read FLEURS
  speech with 1.0–1.95 s pauses, the unseen clip of `../2026-10-open-streaming`), streamed in real time with room
  starts spread over 7 s, plus one listener connection per language (`?context=1`).
  - **4 languages a room:** es, fr, de, ja, all translated by Gemma.
  - **12 languages a room:** es, fr, pt, de, ru, ja, zh, ko, it, vi, ar, hi: Gemma for nine, Hy-MT2 for it, ko and hi.
- **Levels** (`run_levels.sh`): 1, 4, 8, 12 and 16 rooms of 4 languages, then 1 and 4 rooms of 12. Each level stops
  climbing at the first one that drops an utterance. GPU memory and use are sampled every 2 s.
- **What is measured** (`analyze.py`):
  - **Added delay:** how much later each turn's first audio arrives than with one room. The same audio cuts into the
    same turns at every load (23 turns for 20 sentences), so this compares like with like. With one room the stack
    speaks about 1.4–1.9 s after the speaker stops (`../2026-10-agree-live`, `../2026-10-thought-live`).
  - **Backlog:** how long after the clip ends the last audio arrives. It stays near a sentence's length when the stack
    keeps up and grows when it falls behind.
  - **Dropped:** the stack's `pipeline behind, dropped` lines. A room holds at most a few utterances in its queue and
    drops the oldest past that.
- **Connection limits:** the stack's defaults are 30 connections per access token and 60 in total
  (`STACK_MAX_PER_CLIENT`, `STACK_MAX_CONNECTIONS`, `server/stack_auth.py`). Eight rooms of four languages hit the
  first. The levels from 8 rooms on ran with both raised to 1000.

## Results

**As shipped** (`results/before`): the image `2026.10.29`.

| Rooms × languages | Listeners | Added delay, p50 / p90 (s) | Backlog when the clip ends (s) | Dropped |
|---|---|---|---|---|
| 1 × 4 | 4 | – | 1.4 | 0 |
| 4 × 4 | 16 | +0.4 / +0.7 | 1.6 | 0 |
| 8 × 4 | 32 | +1.5 / +2.5 | 3.0 | 0 |
| 12 × 4 | 48 | +13.7 / +21.3 | 24.1 | 0 |
| 16 × 4 | 64 | – | 37.1 | 66 |
| 1 × 12 | 12 | – | **31.3** | 1 |
| 4 × 12 | 48 | – | 13.0 | 44 |

One room in 12 languages fell behind on its own. Its translation took 5–8 s for each 5 s utterance, while the GPU's
median use was 40%. `engines/llmmt.py` sent the nine Gemma languages one after another, about 0.7 s each.

**With every target's Gemma calls sent at once** (`results/targets-at-once`): `llmmt` submits every
(target, sentence) together and vLLM batches them.

| Rooms × languages | Listeners | Added delay, p50 / p90 (s) | Backlog when the clip ends (s) | Dropped |
|---|---|---|---|---|
| 1 × 4 | 4 | – | 0.7 | 0 |
| 4 × 4 | 16 | ±0.0 / +0.1 | 0.7 | 0 |
| **8 × 4** | 32 | **+0.2 / +1.0** | 1.1 | 0 |
| 12 × 4 | 48 | +3.9 / +6.5 | 2.3 | 0 |
| 16 × 4 | 64 | – | 33.8 | 48 |
| **1 × 12** | 12 | – | **3.5** | 0 |
| 4 × 12 | 48 | – | 10.9 | 38 |

- **GPU memory** was flat at 68–71 GB at every level (the stack about 33 GB, Gemma's vLLM 36 GB). Memory is not
  the limit.
- **GPU use:** 8 rooms of 4 languages reached a median of 74% (p90 100%); 12 rooms 99%. Compute is the limit.
- **Translation per utterance:** 0.7 s for a 4-language room alone, all Gemma. A 12-language room alone still took
  3.4–3.8 s. With Gemma's nine languages at about a 4-language room's cost, most of that is likely Hy-MT2's batch
  for Italian, Korean and Hindi (the stage log doesn't split it).
- **Also tried** (`results/targets-at-once-translators-side-by-side`): running Hy-MT2 and Gemma side by side for
  one utterance. The 12-language room went from 3.75 to 3.4 s of translation, and the levels moved within run-to-run
  noise, so that change was not kept.

## Findings

1. **One 96 GB card with Gemma serves about 8 rooms of 4 languages (32 listeners)** with at most a second of added
   delay, once the Gemma calls go out together. At 12 rooms it still keeps up, but each sentence waits about 4 s
   longer. At 16 it falls behind and drops utterances.
2. **A room in many languages costs more than its count of listeners.** One 12-language room keeps up; four of them
   (48 listeners, as many as 12 rooms of 4) don't. The likely slowest part is Hy-MT2, which still translates three of
   the twelve.
3. **The connection limits can bind first.** With the defaults, one access token gets 30 connections (7 rooms of 4
   languages) and the stack 60 in total (15 rooms of 4). Where one token opens every room, 7 rooms is the cap before
   the card is busy; raise `STACK_MAX_PER_CLIENT` to use the card's ~8–12.
4. **The fix matters on every card:** sending a room's Gemma targets together took one 12-language room from 31 s
   behind to keeping up. It is in the same PR as this eval (`engines/llmmt.py`).

## Limits

- One clip, read speech with regular pauses, every room speaking at the same time from start to end: a harder load
  than real rooms, where speakers pause and rooms rarely all talk at once.
- English speakers only, and nonprofit voices (Piper and Kokoro on the CPU). Rooms whose listeners need VoxCPM2
  (Khmer, Lao, Tagalog; ten languages in commercial) are limited by its one-voice-at-a-time service first
  (docs/user-guide.md, "GPUs and capacity").
- Utterance mode only. Simultaneous mode (`?stream=1`) re-transcribes each room every second and costs more.

## Files

- `load.py`, `run_levels.sh`, `analyze.py`: the load, the levels and the summary.
- `results/<run>/`: per level the arrival times per listener (`r<N>.json`, `w<N>.json`), GPU samples (`.gpu`),
  dropped lines (`.drops`) and `summary.json`.

## Reproduce

On a pod from the template, with the clip in `CLIP` (`en.wav`, `en.json`) and the stack's log at
`/workspace/stack.log`: `bash run_levels.sh CLIP RUNS /workspace/stack.log`, then, anywhere,
`python3 -I analyze.py RUNS CLIP`.
