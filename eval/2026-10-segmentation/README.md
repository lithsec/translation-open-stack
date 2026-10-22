# Where the stack loses speech before recognition (October 2026)

The October end-to-end run of the stack (seven languages, FLEURS and CMU
Haitian Creole read speech, `../2026-10-latency/build_clips.py`) heard English
with 11% of characters wrong, against under 5% when Whisper got each sentence
whole. This folder finds where the words went and measures the fix.

## Method

`replay.py` runs the stack's own utterance cutting (a copy of `handle_room`'s
loop, utterance mode) over a clip offline, block by block through the same
Silero model, with the same rules `scripts/run.sh` starts the stack with:
900 ms pause ends a turn, 280 ms will do past 5 s, forced cut at 12 s after
the last sentence end Whisper heard. Each piece then goes to the stack's
recognisers (faster-whisper large-v3; Omnilingual 300M for ht, km, lo).
`score.py` joins all the pieces and scores them against all the sentences, so a
cut costs nothing unless words are lost or garbled. `levels.py` prints each
sentence's peak level and how much of it Silero calls speech. The replay of
the old rules reproduces the live run (English 11.0% against 11.3% live).

## What was lost

1. **Quiet sentences never started an utterance.** Several recordings peak
   around -45 dBFS (most of the English clip; two Japanese and five Khmer
   sentences). Silero scored them under 0.5 throughout, so the stack never
   saw speech, and the idle microphone trim (keep half a second of pre-roll)
   discarded them. English lost one whole sentence and the first half of
   another this way, plus the soft start or end of others; Japanese lost two
   whole sentences and Khmer three (and most of two more). With the fix all
   of them are heard, a few from their second word or clause.
2. **A quiet reader right after a loud one.** One English sentence peaks
   35 dB below the one before it. Any gain that tracks the talker's level
   has to forget the loud one within a second or two to catch it.
3. **Pauses inside a sentence.** The 280 ms rule past 5 s and readers'
   own long pauses split sentences (English 23 pieces for 20 sentences, Lao
   44). Whisper copes; Omnilingual loses a little at each cut. A longer
   endpoint helps Haitian Creole and Lao by 1–2.5 points but adds 0.3–0.6 s
   before every Spanish and French sentence, so it is not changed here.

Not segmentation: English into Khmer dropped utterances because the
translator into Khmer is slower than real time ("pipeline behind").

## The fix

`audio_in.QuietBoost`: the VAD (only the VAD) sees each 96 ms block times a
gain of `0.1 / level`, capped at 16 (+24 dB) and never below 1, where `level`
is a running peak with a 1.5 s half-life. Speech at a normal level is
untouched; the buffer, the recogniser and passthrough still get the raw audio.
Stationary noise does not trigger it: pink noise and mains hum at -40, -50
and -60 dBFS stayed under 0.5 with and without the gain (worst block 0.28).

## Results

Replay, characters wrong (%), all pieces joined:

| | en | es | fr | ja | ht | km | lo | mean |
|---|---|---|---|---|---|---|---|---|
| Before | 11.0 | 0.5 | 3.6 | 18.4 | 7.5 | 35.8 | 19.3 | 13.7 |
| Gain, 4 s half-life | 9.4 | 0.5 | 4.0 | 15.5 | 7.5 | 32.4 | 18.2 | 12.5 |
| **Gain, 1.5 s half-life (this change)** | **6.7** | 0.5 | **2.7** | **11.8** | 7.5 | **25.2** | **18.3** | **10.4** |
| Gain, 1.0 s | 5.5 | 0.5 | 2.2 | 10.7 | 7.5 | 22.9 | 20.7 | 10.0 |
| Gain, 0.7 s | 4.8 | 0.5 | 2.2 | 9.8 | 8.3 | 21.6 | 20.1 | 9.6 |

Shorter half-lives help English, Japanese and Khmer further but cost Lao and
Haitian Creole, whose quiet readers pause mid-sentence: 1.5 s is the shortest
that hurts no language. Endpoint variants (with the 4 s gain):

| | en | es | fr | ja | ht | km | lo |
|---|---|---|---|---|---|---|---|
| Shorter pause only past 8 s (not 5) | 9.3 | 0.8 | 3.7 | 15.5 | 6.0 | 31.6 | 17.6 |
| ...and 400 ms, 15 s forced cut | 9.3 | 0.5 | 3.7 | 14.6 | 5.4 | 31.9 | 17.9 |
| 1.2 s pause, 500 ms past 8 s, 15 s | 9.4 | 0.5 | 3.4 | 14.5 | 5.0 | 31.6 | 17.5 |

## End to end

The stack live on one A40 with `scripts/run.sh`'s settings, each clip streamed
in real time (the October run's client and analysis), before and after this
change. English is one clip, so its CER is the same into every language.

| Direction | CER before | CER after | sentences with no audio | stop → last audio p50 / p90 (s), before | after |
|---|---|---|---|---|---|
| en-es | 11.3 | **6.7** | 1 → 0 | 2.6 / 3.9 | 2.7 / 3.8 |
| en-fr | 11.3 | **6.7** | 1 → 0 | 2.8 / 3.8 | 3.2 / 4.2 |
| en-ja | 11.3 | **6.7** | 1 → 0 | 2.9 / 4.2 | 3.4 / 4.8 |
| en-ht | 11.3 | **6.7** | 1 → 0 | 2.0 / 2.3 | 1.8 / 2.2 |
| en-lo | 11.3 | **6.7** | 1 → 0 | 9.9 / 13.7 | 12.4 / 17.6 |
| es-en | 0.4 | **0.4** | 0 → 0 | 2.9 / 3.4 | 3.0 / 3.9 |
| fr-en | 4.4 | **2.1** | 0 → 0 | 2.7 / 3.2 | 2.9 / 3.5 |
| ja-en | 18.4 | **11.6** | 2 → 0 | 1.1 / 3.4 | 2.0 / 4.1 |
| ht-en | 7.5 | **7.6** | 0 → 0 | 2.6 / 3.4 | 2.9 / 5.2 |
| km-en | 36.3 | **26.0** | 2 → 0 | 3.0 / 3.9 | 3.4 / 5.1 |
| lo-en | 19.6 | **19.0** | 0 → 0 | 2.8 / 4.2 | 3.4 / 5.2 |

- English 11.3% → 6.7%, Japanese 18.4% → 11.6%, Khmer 36.3% → 26.0%, French
  4.4% → 2.1%. Every sentence now gets audio. Spanish, Haitian Creole and
  Lao (loud or evenly quiet clips) are unchanged within run-to-run noise.
- Latency: no change from the cutting. In the replay, the time from each
  sentence's end to the cut is the same before and after (p50 0.3–0.9 s in
  every language; Haitian Creole's cuts are identical). The live differences
  are run-to-run: Haitian Creole into English, cut identically, moved
  +0.3 s at p50 and +1.8 s at p90. Japanese into English now includes the
  two recovered sentences; English into Lao waits on its translator.
- English into Khmer is not in the table: its translator runs slower than
  real time and drops queued utterances either way (38.5% → 42.7%, more
  heard means more dropped).
- Over-fragmentation in Haitian Creole and Lao is not fixed here (35 and 44
  pieces for 20 sentences): see "Pauses inside a sentence" above.

## Files

| File | |
|---|---|
| `replay.py` | the cutting loop offline + recognition (GPU, the stack's `server/`) |
| `score.py` | CER of the joined pieces, pieces, cuts inside sentences |
| `levels.py` | per-sentence peak level and speech probability, raw and boosted |
| `results.json` | the numbers above |

No audio or transcripts are stored; the clips are rebuilt with
`../2026-10-latency/build_clips.py`.
