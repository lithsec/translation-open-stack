# The commercial edition, live, every direction, November 2026

`EDITION=commercial` now decides per model, not only per voice (`server/licences.py`): Gemma 4 31B (Apache-2.0)
is used, MiLMMT-46 (Gemma Terms of Use, restricted) is not, so Lao goes to MADLAD out of English and to Hy-MT2
into English; and the voices change (ru, km, lo VoxCPM2; de, fr Piper `mls`; pt Kokoro only; ro eSpeak NG only;
ht Coqui OpenBible). This round measures that edition live, 20 directions, at real time, one direction at a
time, on the clips of `../2026-10-full-stack` and `../2026-10-de-ru-ro`.

**Since then commercial Lao uses Gemma 4 in both directions** (`languages.toml` lo `llmmt` is MiLMMT's line,
then Gemma's; commercial drops the first). The Lao rows below are the round's MADLAD 7B / Hy-MT2 routes; the
re-run on Gemma is in "Lao on Gemma 4 (re-run, 2026-11-03)": live it keeps up, ~0.3-0.4 s later first audio
out of English than MADLAD, and **its quality grades are still pending** (the grader's daily quota ran out
after 1 of 6 calls).

## Results

Commercial edition, both sets (40 sentences per direction). Quality against what was said, mean of sets a and
b (written text in brackets), critical errors over both sets against what was said; latency from the speaker
stopping, set a / set b, in seconds; drops = sentences without audio / utterances the pipeline dropped;
recognition = characters wrong against what was said (de/ru/ro: against the FLEURS text).

| Direction | Translator | Quality, said (written) | Critical | First audio p50 | First audio p90 | Last audio p50 | Last audio p90 | Drops | Recognition |
|---|---|---|---|---|---|---|---|---|---|
| en→es | Gemma 4 | 69.2 (63.4) | 8 | 1.2 / 1.2 | 1.6 / 1.4 | 1.4 / 1.2 | 1.6 / 1.6 | 0 / 0 | 5.1% |
| es→en | Hy-MT2 | 84.6 (83.3) | 3 | 1.5 / 1.5 | 1.7 / 1.6 | 1.5 / 1.5 | 1.8 / 1.7 | 0 / 0 | 0.8% |
| en→pt | Gemma 4 | 70.0 (64.2) | 9 | 1.2 / 1.2 | 1.5 / 1.4 | 1.4 / 1.3 | 1.6 / 1.6 | 0 / 0 | 5.1% |
| pt→en | Hy-MT2 | 78.3 (78.3) | 7 | 1.4 / 1.4 | 1.6 / 1.6 | 1.5 / 1.5 | 2.0 / 1.6 | 0 / 0 | 1.2% |
| en→fr | Gemma 4 | 71.7 (60.9) | 9 | 1.4 / 1.4 | 1.7 / 1.7 | 1.6 / 1.4 | 1.8 / 1.8 | 0 / 0 | 5.1% |
| fr→en | Hy-MT2 | 76.0 (75.0) | 7 | 1.5 / 1.6 | 1.7 / 1.9 | 1.5 / 1.6 | 1.8 / 1.9 | 0 / 0 | 2.4% |
| en→ja | Gemma 4 | 69.2 (63.4) | 11 | 1.4 / 1.2 | 1.6 / 1.5 | 1.4 / 1.3 | 1.7 / 1.7 | 0 / 0 | 5.1% |
| ja→en | Gemma 4 | 81.0 (79.2) | 6 | 1.9 / 2.1 | 2.2 / 2.4 | 1.9 / 2.1 | 2.2 / 2.4 | 0 / 0 | 3.6% |
| en→km | Gemma 4 | 64.2 (58.3) | 6 | 1.4 / 1.3 | 1.8 / 1.7 | 1.5 / 1.4 | 1.8 / 1.8 | 0 / 0 | 5.1% |
| km→en | Hy-MT2 | 60.3 (57.5) | 14 | 2.1 / 2.1 | 2.4 / 2.5 | 2.1 / 2.2 | 2.4 / 2.5 | 0 / 0 | 8.9% |
| en→lo | MADLAD 7B | **47.5** (54.1) | 13 | 1.2 / 1.1 | 1.5 / 1.4 | 1.2 / 1.2 | 1.6 / 1.6 | 0 / 0 | 5.1% |
| lo→en | Hy-MT2 | 53.2 (52.5) | 15 | 1.8 / 1.8 | 2.6 / 2.4 | 2.1 / 2.0 | 2.6 / 2.4 | 1 / 0 | 15.2% |
| en→ht | Gemma 4 | 74.2 (56.6) | 5 | 1.2 / 1.1 | 1.5 / 1.4 | 1.3 / 1.1 | 1.5 / 1.6 | 0 / 0 | 5.1% |
| ht→en | Gemma 4 | 52.0 (49.1)¹ | 17 | 2.2 / 1.6 | 2.3 / 2.2 | 2.2 / 2.0 | 2.5 / 2.2 | 0 / 0 | 2.9% |
| en→de | Gemma 4 | 71.7 | 7 | 1.1 / 1.2 | 1.4 / 1.7 | 1.2 / 1.4 | 1.6 / 1.7 | 0 / 0 | 8.0% |
| de→en | Hy-MT2 | 88.3 | 2 | 1.9 / 1.9 | 2.1 / 2.1 | 1.9 / 1.9 | 2.1 / 2.1 | 0 / 0 | 1.9% |
| en→ru | Gemma 4 | 70.8 | 10 | 1.1 / 1.0 | 1.3 / 1.7 | 1.1 / 1.2 | 1.5 / 1.7 | 0 / 0 | 8.0% |
| ru→en | Gemma 4 | 84.2 | 8 | 1.5 / 1.4 | 1.7 / 1.8 | 1.6 / 1.6 | 1.9 / 1.9 | 0 / 0 | 3.6% |
| en→ro | MADLAD 7B | 65.0 | 9 | 0.9 / 0.9 | 1.1 / 1.3 | 1.0 / 1.0 | 1.4 / 1.4 | 0 / 0 | 8.0% |
| ro→en | MADLAD 7B | 69.2 | 12 | 1.5 / 1.6 | 2.3 / 2.3 | 2.0 / 1.9 | 2.3 / 2.3 | 0 / 0 | 4.2%² |

¹ against the regenerated, model-made English references. ² Omnilingual 7B, where C1 used Whisper.

Per set (said): en→es 73.3 / 65.0, en→pt 75.0 / 65.0, en→fr 76.7 / 66.7, en→ja 73.3 / 65.0, en→km 71.7 / 56.7,
en→ht 80.0 / 68.3, es→en 84.2 / 85.0, pt→en 86.7 / 70.0, fr→en 78.3 / 73.7, ja→en 75.9 / 86.0, km→en
59.3 / 61.4, ht→en 60.8 / 43.1. Every number is in `results.json`.

**The 12 rows from es to ht other than Lao were graded alone** (one system per grading call): not comparable
with earlier rounds. For context only, the nonprofit full-stack round on an A100 80 GB (its README, best
translator, said; stop → last audio p50 a / b): es→en 84.6 (2.5 / 2.5 s), ja→en 80.9 (2.4 / 2.5), fr→en
76.8 (2.5 / 2.6), pt→en 73.3 (2.4 / 2.5), en→es 72.5 (1.7 / 1.6), en→fr 70.8 (1.9 / 1.8), en→ja 70.0
(1.7 / 1.7), en→ht 69.2 (1.7 / 1.5), en→pt 65.8 (1.7 / 1.5), en→km 63.4 (1.8 / 1.7), km→en 61.3 (3.9 / 3.7),
ht→en 49.6 (3.1 / 2.6); English recognition 5.0%. Its set b is probably, not certainly, this set b.

### Lao: commercial against nonprofit (same recognition, same clips, one grading call per set and reference)

| Direction | Edition | Translator | Quality, said (written) | Per set, said | Critical | First audio p50 | Last audio p50 / p90 | Drops |
|---|---|---|---|---|---|---|---|---|
| en→lo | commercial | MADLAD 7B | **47.5** (54.1) | 55.0 / 40.0 | 13 | 1.2 / 1.1 | 1.2 / 1.2, 1.6 / 1.6 | 0 / 0 |
| en→lo | nonprofit | MiLMMT-46 12B | **67.5** (62.5) | 70.0 / 65.0 | 9 | 1.7 / 1.5 | 1.8 / 1.5, 2.3 / 2.2 | 0 / 0 |
| lo→en | commercial | Hy-MT2 | 53.2 (52.5) | 50.9 / 55.6 | 15 | 1.8 / 1.8 | 2.1 / 2.0, 2.6 / 2.4 | 1 / 0 |
| lo→en | nonprofit | MiLMMT-46 12B | 56.0 (53.4) | 50.9 / 61.1 | 16 | 1.7 / 1.7 | 1.9 / 1.9, 2.5 / 2.3 | 1 / 0 |

Recognition is the same in both (Omnilingual 7B: 18.2% / 11.9% of characters wrong against the text, 15.2%
against what was said); the outputs differ in 19-20 of 20 sentences in every pair.

### German, Russian, Romanian: commercial against the saved nonprofit C1 (same clips, one grading call per direction and set)

| Direction | Commercial | C1 (`../2026-10-de-ru-ro`) | Quality commercial / C1 (critical) | Per set a, b | First audio p50, commercial / C1 | Sentences differing |
|---|---|---|---|---|---|---|
| en→de | Gemma 4 | Gemma 4 | 71.7 / 71.7 (7 / 7) | 75.0, 68.3 / 75.0, 68.3 | 1.1-1.2 / 1.6 s | 5 of 40 |
| de→en | Hy-MT2, long turns | Hy-MT2 | **88.3 / 82.5** (2 / 2) | 91.7, 85.0 / 85.0, 80.0 | **1.9 / 1.4 s** | 17 of 40 |
| en→ru | Gemma 4 | Gemma 4 | 70.8 / 71.7 (10 / 10) | 73.3, 68.3 / 75.0, 68.3 | 1.0-1.1 / 1.1-1.2 s | 6 of 40 |
| ru→en | Gemma 4 | Hy-MT2 | 84.2 / 80.8 (8 / 8) | 83.3, 85.0 / 83.3, 78.3 | 1.4-1.5 / 1.3-1.5 s | 37 of 40 |
| en→ro | MADLAD 7B | MADLAD | 65.0 / 64.2 (9 / 9) | 71.7, 58.3 / 70.0, 58.3 | 0.9 / 1.0 s | 3 of 40 |
| ro→en | MADLAD 7B, **Omnilingual 7B** | MADLAD, Whisper | 69.2 / 70.0 (**12 / 9**) | 65.0, 73.3 / 65.0, 75.0 | 1.5-1.6 / 1.1-1.4 s | 37 of 40 |

## Findings

1. **The commercial edition keeps up live in every direction.** 44 runs, no utterance dropped by the pipeline,
   no Gemma request failed over, and one sentence without audio in 880 (lo→en set a, in both editions).
   First translated audio comes 0.9-1.4 s after the speaker stops out of English and 1.4-2.2 s into English;
   the start of the last translated audio 1.0-2.2 s at the median, never above 2.6 s at p90.
2. **Lao out of English is what commercial loses.** MADLAD 7B scores 20 points below MiLMMT on what was said
   (47.5 against 67.5), lower on both sets (-15, -25) with more critical errors (13 against 9). It is
   0.4-0.6 s faster. Into English, Hy-MT2 is 2.8 points below MiLMMT (a tie on set a, -5.5 on set b), within
   about one round's noise; Lao recognition (15% wrong) holds both back. *These are the routes this round
   measured; commercial Lao is now Gemma 4 both ways (re-run below: live it keeps up, quality pending).*
3. **Every other route repeats the earlier rounds' findings.** de→en is +5.8 with the long German turns
   that are now in `languages.toml` (the de-ru-ro C3 result, about +8 there) for +0.5 s to first audio; ru→en
   on Gemma is +3.4 over Hy-MT2 (C2 was +4.1); en→de, en→ru and en→ro are the same translator on the same
   recognition as C1, with nearly identical outputs (3-6 of 40 sentences differ) and equal scores.
4. **Romanian into English on Omnilingual 7B instead of Whisper is level** (69.2 against 70.0, 37 of 40
   outputs differ) with three more critical errors and 0.2-0.4 s later first audio; recognition 4.2% against
   4.7% of characters wrong. One round, small differences: no evidence either way.
5. **Memory.** The stack with the 7B Omnilingual card, MADLAD 7B, VoxCPM2 and Gemma 4 at vLLM share 0.41 peaked
   at 95.9 GB of 97.9 on the 96 GB card. It ran, but `start-llmmt.sh`'s `auto` would not have started Gemma
   there (it asks for 97 GB); `LLMMT=gemma` (or `GEMMA_GB=39`) did. *Since fixed: in the re-run below,
   `auto` with `OMNI_LARGE=1` (profile `cuda-80gb`) started Gemma on the 96 GB card by itself (vLLM share 0.38).*

## Lao on Gemma 4 (re-run, 2026-11-03)

Commercial Lao now goes to Gemma 4 31B in both directions (`languages.toml` lo `llmmt` = [MiLMMT line, Gemma
line]; commercial drops MiLMMT; `stack_config.py check --edition commercial` on the pod: `lo asr=omni:lao_Laoo
mt=llmmt>madlad (to en: llmmt>hymt)`, `lo translator llmmt: google/gemma-4-31B-it-qat-w4a16-ct ✅`). Re-run
of en→lo and lo→en only, commercial, sets a and b, regular pauses, same harness (`live.sh`, the de-ru-ro
`e2e_client.mjs`, `analyze.sh`), graded side by side with this round's saved Lao outputs.

**`start-llmmt.sh` `auto` started Gemma.** Run as the template's start runs it (profile `cuda-80gb` sourced
first, so `OMNI_LARGE=1`; `EDITION=commercial`, `LLMMT` unset = auto): `== llmmt: gemma on GPU 0 (95 GB,
vLLM share 0.38)`. It installed vLLM (22 min on this pod's volume), compiled and answered at 00:24 UTC; the
stack logged `llmmt ... answering — de,es,fr,ht,ja,km,lo,pt,ru use it` before the first run and never flapped
or failed over during the runs (`results/lao-gemma/stack_G.log`). Peak GPU memory during the runs: 78.2 GB of
97.9 (with MADLAD **3B** as the fallback here, ~6 GB less than 7B, and share 0.38 against 0.41).

Same recognition (Omnilingual 7B), same clips; latency in s from the speaker stopping, set a / set b; drops =
sentences without audio / utterances the pipeline dropped; recognition = characters wrong against what was
said. Quality: share of the possible 3, gemini-pro-latest, three systems blind in one call per (set,
direction, reference).

| Direction | System | Quality, said (written) | Critical, said | First audio p50 | First audio p90 | Last audio p50 | Last audio p90 | Drops | Recognition |
|---|---|---|---|---|---|---|---|---|---|
| en→lo | **commercial, Gemma 4** (re-run) | pending (set a written: **60.0**) | pending (set a written: 6) | 1.6 / 1.4 | 2.0 / 2.1 | 1.7 / 1.5 | 2.0 / 2.1 | 0 / 0 | 5.1% |
| en→lo | commercial, MADLAD 7B (Nov round) | pending (set a written: 46.7) | pending (set a written: 8) | 1.2 / 1.1 | 1.5 / 1.4 | 1.2 / 1.2 | 1.6 / 1.6 | 0 / 0 | 5.1% |
| en→lo | nonprofit, MiLMMT-46 12B (Nov round) | pending (set a written: 55.0) | pending (set a written: 7) | 1.7 / 1.5 | 2.1 / 2.1 | 1.8 / 1.5 | 2.3 / 2.2 | 0 / 0 | 5.1% |
| lo→en | **commercial, Gemma 4** (re-run) | pending | pending | 1.7 / 1.6 | 2.6 / 2.3 | 1.9 / 1.9 | 2.6 / 2.3 | 1 / 0 | 15.4% |
| lo→en | commercial, Hy-MT2 (Nov round) | pending | pending | 1.8 / 1.8 | 2.6 / 2.4 | 2.1 / 2.0 | 2.6 / 2.4 | 1 / 0 | 15.2% |
| lo→en | nonprofit, MiLMMT-46 12B (Nov round) | pending | pending | 1.7 / 1.7 | 2.5 / 2.3 | 1.9 / 1.9 | 2.5 / 2.3 | 1 / 0 | 15.2% |

- **Quality is not graded yet.** gemini-pro-latest's daily request quota (250, Tier 1) was used up after the
  first of the six calls (`WRITTEN:a:en-lo`, the only numbers above: Gemma 60.0, MiLMMT 55.0, MADLAD 46.7 of
  20 sentences against the written text, one call: indicative only). To finish, once the quota resets (local,
  resumes from `out/grades.json`):
  `cd results/lao-gemma && GEMINI_API_KEY=... python3 -I ../../../2026-10-unseen/grade.py out/jobs.json out/grades.json && python3 -I round_lao.py table`
  (`grade.py` runs four calls at once and keeps nothing until they are all back; one call at a time is gentler
  on the quota). These calls grade three systems, not two, so their numbers for MADLAD / Hy-MT2 / MiLMMT will
  not be exactly the round's two-system numbers above.
- **Live, Gemma keeps up both ways**: no utterance dropped, one sentence without audio (lo→en set a, as in
  both saved runs), no failover. Out of English it is 0.3-0.4 s later to first audio than
  MADLAD (1.6 / 1.4 s against 1.2 / 1.1) and level with MiLMMT; into English level with both (1.7 / 1.6 s).
- The outputs differ from both saved systems in 20 of 20 sentences out of English and 19-20 of 20 into English.

Setup of the re-run (`results/lao-gemma/`): pod `tp0ewrg6uvssji`, RunPod secure cloud EU-CZ-1, one RTX PRO
6000 Blackwell Server Edition 96 GB, host CUDA 13.2, 32 vCPUs, template `dftcc24b6q` (image 2026.10.29)
with the start command `/start.sh`, `STACK_IDLE_MIN=0`, `EDITION=commercial`; created 23:48 UTC, deleted 00:40
UTC (52 min, ~$2.20). The working tree of `audit/clarity-docs` with its uncommitted changes, rsynced to
`/workspace/tos-commercial`. `setup.sh`: Gemma via `start-llmmt.sh` first, then Node 22 (the image's apt
`nodejs` is 18, without the global `WebSocket` the client needs), Piper voices, `prepare-mt.sh` with
`MADLAD=3b` (MADLAD is only Lao's fallback now; it served no Lao sentence), `prepare-voices.sh`, and the
clips rebuilt with the round's builders and seeds (`../2026-10-unseen/build_clips.py`, seed 2026;
`../2026-10-full-stack/build_clips_b.py`, seed 2027): en and lo `*.txt.json`, `*.json` and `ids.json` of both
sets are byte-identical to `results/seta`, `results/setb` (copies in `results/lao-gemma/clips/`), and the
saved runs' sentence texts equal them (`round_lao.py jobs` asserts it). Same 11 languages served, one stack
start (`run_lao.sh`: `live.sh` in a pod-only copy whose wait for Gemma is 40 min instead of 200 s and matches
`) answering —` only: `live.sh`'s own pattern also matches the `not answering —` line, harmless in the round,
where Gemma was already up). References: the round's (`results/seta`, `results/setb`: `said_en.json`,
witness flags). `round_lao.py` builds the six jobs and the table (`out/results.json`).


## Setup

- **Code.** The working tree of `audit/clarity-docs` with its uncommitted changes (the commercial routing:
  `server/licences.py`, `stack_config.py`, `engines/manager.py`, the `server.py` split into
  `pipeline.py`/`rooms.py`/`handlers.py`/`connection.py`, `scripts/start-llmmt.sh`), copied to the pod and
  started with its own `scripts/run.sh` (`EDITION=commercial`, `STACK_PROFILE=cuda-80gb`, so `OMNI_LARGE=1`),
  on the image's Python (`ghcr.io/lithsec/translation-open-stack:2026.10.29`). `languages.toml` as it is in
  that tree; what it routes is `python3 server/stack_config.py check --edition commercial`.
  The stack served en, es, pt, fr, ja, km, lo, ht, de, ru, ro (11 languages, one start for all 40 commercial runs).
- **Hardware.** One RTX PRO 6000 Blackwell Server Edition 96 GB (RunPod secure cloud, host CUDA 13.2,
  32 vCPUs), not the A100 80 GB of `../2026-10-full-stack`. GPU memory in use during the runs: 94.8-95.7 GB
  of 97.9 (stack 39 GB + VoxCPM2 7 GB + vLLM 47.5 GB).
- **Models.** Whisper large-v3 (en es pt fr ja de ru); Omnilingual 7B for Lao, Khmer and (now) Romanian
  (`omni = "large"` / `"large-only"`), 300M for Haitian Creole; Hy-MT2 7B 4-bit; **MADLAD-400 7B** CTranslate2
  int8 (the real one, built by `prepare-mt.sh`'s steps; it fitted); Gemma 4 31B 4-bit QAT
  (`google/gemma-4-31B-it-qat-w4a16-ct`) under vLLM 0.31 on :8101, started with the tree's
  `scripts/start-llmmt.sh` (`LLMMT=gemma GEMMA_GB=39`: vLLM share 0.41, `--max-model-len 8192`; the script's
  `auto` check wants 53 + 36 + 8 = 97 GB and would not have started it on a 96 GB card).
- **Commercial routes measured** (`table.py` `translator`):

  | | out of English | into English |
  |---|---|---|
  | es, pt, fr, de | Gemma 4 | Hy-MT2 |
  | ja, ru, ht | Gemma 4 | Gemma 4 |
  | km | Gemma 4 | Hy-MT2 |
  | lo | MADLAD 7B | Hy-MT2 |
  | ro | MADLAD 7B | MADLAD 7B |

  No Gemma request failed over to its next translator, and no utterance was dropped by the pipeline, in any
  run (`stack_C.log`: no `llmmt ... failed`, no `pipeline behind, dropped`).
- **Lao, nonprofit beside it** (`lao_nonprofit.sh`): after the commercial runs, Gemma's vLLM stopped, MiLMMT-46
  12B started on :8102 (same script, `EDITION=nonprofit LLMMT=milmmt`), the stack restarted with
  `EDITION=nonprofit`, and en→lo, lo→en ran on both sets. Same recogniser (Omnilingual 7B).
- **Clips** (`build_clips.sh`, rebuilt on the pod; the clips aren't in the repository):
  - set **a**: `../2026-10-unseen/build_clips.py` (seed 2026). Its FLEURS ids match `../2026-10-unseen/results.json`.
  - set **b**: `../2026-10-full-stack/build_clips_b.py` (seed 2027) with set a as the earlier set it excludes.
    The full-stack round didn't keep its ids, so this is **not verified** to be its set b (see Limits).
  - de/ru/ro sets a and b: `../2026-10-de-ru-ro/build_clips.py` (seed 2027). Ids and all eight text files
    match `../2026-10-de-ru-ro/results/` (`ids.json`, `clips_*_reg/*.txt.json`).
  - Regular pauses only (1.0-1.95 s), 20 read sentences per clip.
- **Client and analysis.** `../2026-10-de-ru-ro/e2e_client.mjs` (the October e2e client with `?context=1`),
  one connection per direction; `live.sh` (as `../2026-10-de-ru-ro/live.sh`, plus the stack log and
  nvidia-smi samples per run); `analyze.sh` = `../2026-10-unseen/analyze_e2e.py` with all 20 directions
  (`trim_logs.py` first gives each run its own log lines, so drops are counted per run).
- **References** (`make_refs.py`, `witness_fill.py`):
  - set a: witness flags and what was said in English, from `../2026-10-unseen/results.json`
    (as `../2026-10-open-streaming/make_refs.py`).
  - set b: witnessed again with `../2026-10-unseen/witness.py` (Gemini, gemini-pro-latest) on the rebuilt
    recordings; rate-limited answers re-asked with `witness_fill.py`. Flagged: en 2, 4, 5, 11, 15; fr 17;
    ja 1; km 2; lo 10, 15; ht 6, 7, 15; es, pt none (the full-stack round reported en 4, fr 2, ht 2, ja, km,
    lo 1 each).
  - **Haitian Creole English references (`meaning_ht.json`) regenerated for both sets** with
    `../2026-10-real-voices/make_refs.py`'s prompt on gemini-pro-latest (the earlier files aren't in the
    repository). Model-made, and not the same text the earlier rounds graded against.
- **Grading.**
  - The 12 full-stack directions other than Lao: `round.py` (`../2026-10-full-stack/round.py`'s jobs and
    table) and `../2026-10-unseen/grade.py`, gemini-pro-latest, 0-3 per sentence with a critical flag,
    against the written text and against what was said. **Commercial graded alone**: one system per call,
    so these scores are not comparable with earlier rounds' (their numbers below are context only).
  - Lao: commercial and nonprofit side by side in one call per (set, reference).
  - de, ru, ro: `round_drr.py` and `../2026-10-de-ru-ro/grade.py`: the commercial output and the saved C1
    output (`../2026-10-de-ru-ro/results/e2e_C1_{a,b}_reg`) side by side in one call per direction and set,
    against the FLEURS text (that round's method; no "said" reference).
  - Quality is the share of the possible 3. Rounds move 5-10 points between calls; read single-set
    differences under 5 points as noise.
- **Measures.** Speech end → first translated audio and → start of the last translated audio of the
  sentence (p50 / p90 per set), sentences without audio and pipeline drops, recognition CER (characters
  wrong; against what was said for the 14, against the FLEURS text for de/ru/ro).

## Limits

- **Graded alone.** The 12 non-Lao full-stack directions had one system per grading call; their numbers are
  not comparable with `../2026-10-full-stack` (different calls, different hardware: an A100 80 GB there, an
  RTX PRO 6000 96 GB here, and a newer stack). The A100 latencies are context, not a comparison.
- **Set b rebuilt, not verified.** `build_clips_b.py` reproduces set b only if it was run with set a as its
  only earlier set; the full-stack round kept no ids. The rebuilt set's witness flags (en 5, fr 1, ht 3,
  ja 1, km 1, lo 2) are close to, not equal to, the ones it reported (en 4, fr 2, ht 2, ja/km/lo 1), and a
  re-run of the witness differs between calls anyway.
- **Haitian Creole references regenerated** (model-made, gemini-pro-latest) for both sets: ht→en is graded
  against a different reference than any earlier round's.
- **Romanian's recogniser changed** (Omnilingual 7B here, Whisper in C1), so the ro→en comparison changes two
  things; en→ro has the same Whisper English.
- **Voices differ from C1** in de (Piper `mls`), ru (VoxCPM2) and ro (eSpeak NG), which can move audio
  timing slightly; quality is graded on text.
- **Lao nonprofit** ran on a second stack start (`EDITION=nonprofit`) with MiLMMT in place of Gemma on the
  same card, after the commercial runs; same 11 languages, same clips.
- One 20-sentence read clip per language and set, FLEURS (CMU for Haitian Creole) read speech; one grading
  call per (set, direction, reference). Differences under ~5 points are noise.
- The MiLMMT download first failed on a full volume (`/workspace`, 100 GB); it was started again from the
  container disk's copy (`results/llmmt-milmmt*.log`). No effect on the runs.


## Files

- `README.md`, `results.json` (`table.py`): per direction and system, quality (said, written), critical
  errors, latency, drops, CER, translator; `raw` has every per-set number.
- `build_clips.sh`, `live.sh`, `lao_nonprofit.sh`, `analyze.sh`, `trim_logs.py`: the pod side.
- `make_refs.py`, `witness_fill.py`, `round.py`, `round_drr.py`, `table.py`: references, grading, tables (local).
- `configs/`: the `languages.toml` both stack starts ran (a copy of the tree's) and its `check --edition commercial`.
- `results/`: clip texts and metadata (no audio), `e2e_*/out/` (runs, latency, sentences), the stack logs,
  witness files, regenerated `meaning_ht.json`, grading jobs and grades.
- `results/lao-gemma/`: the Lao-on-Gemma re-run: `setup.sh`, `deadline.sh`, `run_lao.sh` (pod side),
  `round_lao.py` (jobs, table), `e2e_G_{a,b}/out/`, `clips/` (en, lo texts and ids), the stack, vLLM and
  setup logs, `out/` (jobs, grades so far, results).
