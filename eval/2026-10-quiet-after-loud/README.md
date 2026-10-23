# A quiet talker right after a loud one, October 2026

On the unseen English clip (`../2026-10-unseen`), five sentence starts were lost: each time a reader at
about −60 dBFS began 1–2 s after one at −18 to −30 dBFS. QuietBoost (#37) brings a quiet voice up for
Silero, but its 1.5 s half-life still remembered the loud voice when the quiet one began, so the first
words reached the VAD at a gain near 1, scored as silence and were trimmed with the idle pre-roll.

This branch changes two things in `server/audio_in.py`:

- **Forget a loud voice faster across a pause.** While a 96 ms block peaks 20 dB or more under the
  remembered level (a pause, or a much quieter voice), the level decays with a 0.25 s half-life instead of
  1.5 s. Inside one talker's speech, word gaps are short and the slow half-life still holds (a 0.2 s gap
  moves the gain by less than 2×; `tests/test_audio_in.py`).
- **Boost what the recogniser hears too**, not only the VAD's copy (`QUIET_ASR`). The gain never takes a
  block's peak above the −20 dBFS target, so it can't clip.

## Method

- **Clips**: the unseen round's clips (20 FLEURS sentences per language, regular 1.0–1.95 s and
  irregular 0.3–1.2 s pauses; `../2026-10-unseen/build_clips.py`), and the regular English clip with
  coloured noise added at −40 dBFS RMS, to check that boosting doesn't turn noise into words.
- **Offline replay** (`replay.py`, `score_replay.py`): the stack's cutting loop over each clip with each
  setting, each piece through the stack's own recogniser. Characters wrong against what was said (the
  unseen round's witness transcripts); a sentence start counts as lost when its first voiced 20 ms isn't
  inside any piece sent to the recogniser.
- **Live**: the October client, streaming in real time to the stack on one A100 80 GB, main against this
  branch, blind-graded in one call per direction (`../2026-10-unseen/grade.py`, gemini-pro-latest).
  Three or four directions ran at once, so latency carries some GPU contention; compare it within a
  row only.

## Offline replay

Characters wrong against what was said, and sentence starts lost (of 20):

| Clip | main | faster release | + recogniser boost |
|---|---|---|---|
| English, regular pauses | 16.5%, 5 lost | 6.4%, 1 | **6.0%, 1** |
| English, irregular pauses | 20.9%, 6 | 9.9%, 3 | **7.7%, 3** |
| Japanese, regular pauses | 9.0% | 4.9% | **4.6%** |
| English + noise at −40 dBFS | 70.8% | 70.8% | 70.8% |

The noisy clip is unchanged by either setting: the noise keeps the level up, so the faster release never
starts, and the quietest readers are buried under the noise whatever the gain. No regression; no help either.

## Live

Quality against the written text / against what was said (critical errors in brackets), characters
wrong, and speaker stops → last piece's audio starts (p50 / p90, s):

| Direction | main | this branch | CER main → branch | Latency main | Latency branch |
|---|---|---|---|---|---|
| en→es | 55.0 (4) / 61.7 (5) | **65.0 (4) / 73.3 (5)** | 18.6% → 8.6% | 3.4 / 4.6 | 3.2 / 5.1 |
| en→es, irregular | 58.3 (9) / 61.7 (7) | **68.3 (8) / 70.0 (6)** | 26.0% → 10.9% | 3.0 / 9.1 | 3.7 / 6.6 |
| ja→en | 63.3 (4) / 64.8 (4) | **73.3 (2) / 74.1 (2)** | 8.4% → 5.0% | 3.2 / 3.8 | 3.5 / 5.0 |
| ja→en, irregular | 63.3 (10) / 64.8 (9) | **71.7 (8) / 72.2 (7)** | 11.2% → 5.7% | 3.2 / 5.4 | 3.3 / 4.7 |
| fr→en | 78.3 (2) | **85.0 (2)** | 5.6% → 2.5% | 2.8 / 3.7 | 3.4 / 5.4 |
| km→en (Omnilingual 7B) | 51.7 (10) / 57.4 (8) | **58.3 (8) / 64.8 (6)** | 14.0% → 11.1% | 6.7 / 10.1 | 4.4 / 6.8 |
| es→en | 83.3 (1) / 86.0 (0) | 83.3 (1) / 86.0 (0) | 1.0% → 1.0% | 2.9 / 3.9 | 3.0 / 4.9 |
| pt→en | 78.3 (3) | 76.7 (3) | 1.3% → 1.2% | 4.1 / 5.9 | 2.8 / 4.5 |

Where the clip has quiet readers after loud ones (English, Japanese, French, Khmer), quality rises 7–12
points and characters wrong roughly halve in English and Japanese. Spanish and Portuguese, whose readers
are evenly loud, are unchanged (pt→en −1.6 is one sentence in one grading call). English irregular pauses
also stop losing whole sentences (2 without audio on main, 0 here).

## The #38 turn rules, checked on the same clips: inconclusive

`results.json` (`P38`) also holds main with Japanese, Haitian Creole, Khmer and Lao set back to their
turn rules before #38. That run had four directions at once, two of them on Omnilingual 7B, and the
pipeline fell behind: ht→en and lo→en dropped 6–7 sentences and waited 25–30 s, which no turn rule
explains. Japanese, the one direction that kept up, came out the same (61.7 against main's 63.3, 8.0%
against 8.4% characters wrong). Nothing here argues for reverting #38; a rerun one direction at a time is
needed to measure it.

## What isn't measured

- One clip per language, one grading call per direction.
- Room audio with real reverberation (only synthetic noise).
- A quiet talker who is quiet throughout was already handled by #37 and is unchanged.
