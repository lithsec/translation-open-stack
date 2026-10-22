# Turn rules per spoken language (October 2026)

After the quiet-talker fix (`../2026-10-segmentation/`), the stack still cut
Haitian Creole into 34 pieces and Lao into 42 for 20 read sentences: their
readers pause inside sentences, the 280 ms clause gap past 5 s ends a turn
there, and Omnilingual mishears pieces of sentences more than whole ones.
A longer pause for every language helped them but slowed every Spanish and
French sentence. This change lets `languages.toml` give each spoken language
its own turn rules, and gives Japanese, Haitian Creole, Khmer and Lao longer
turns; English, Spanish and French keep the flags.

## New per-language keys

`long_utterance_s` and `long_endpoint_ms` (the clause gap: past this much
audio, this shorter pause ends a turn) and `min_speech_ms` (a pause doesn't
end a turn holding less speech than this until the quiet lasts 1.5 s, so a
piece waits for the rest of its sentence and a speaker who stopped is still
answered). With them, `endpoint_ms` and `max_utterance_s` as before
([docs/reference.md](../../docs/reference.md)). Utterance mode, rooms and
single connections; simultaneous mode keeps its own rules.

Japanese, Haitian Creole, Khmer, Lao: `endpoint_ms = 900`,
`long_utterance_s = 8`, `long_endpoint_ms = 500`, `max_utterance_s = 15`,
`min_speech_ms = 2500`. (Lao and Khmer had 700 ms at any length and 15 s.)

## Method

`sweep.py` replays the room's cutting loop (utterance mode, with
`audio_in.QuietBoost`) over the October clips (FLEURS and CMU Haitian Creole
read speech, `../2026-10-latency/build_clips.py`) for a list of settings, and
recognises each piece with the stack's recognisers (faster-whisper large-v3;
Omnilingual 300M for ht, km, lo), once per distinct piece. `score_sweep.py`
scores all pieces joined against all sentences joined (a cut costs nothing
unless words are lost or garbled), counts pieces, and measures the wait from
each sentence's end to the cut that holds it (p50/p90): what the rule adds to
latency.

Then the stack live on one A40, each clip streamed at real time with the
October client, for main (after #37) and this branch, and one blind
side-by-side grading per direction (gemini-pro-latest, the October rubric) of
three live outputs together: the October run, main, this branch. Quality is
the % of the 3-point maximum over the 20 sentences.

## Replay

Characters wrong (%) · pieces (20 sentences) · wait after a sentence ends p50/p90 (s):

| Setting | ja | ht | km | lo | en | es | fr |
|---|---|---|---|---|---|---|---|
| Flags (900 ms; 280 ms past 5 s; cut at 12 s) | 11.8 · 27 · 1.0/1.0 | 7.5 · 34 · 0.3/0.9 | 25.2 · 34 · 0.4/1.0 | 18.3 · 42 · 0.2/0.6 | 6.7 · 24 · 0.3/1.0 | 0.5 · 26 · 0.3/1.0 | 2.7 · 22 · 0.3/0.9 |
| 700 ms always, cut at 15 s (Lao, Khmer on main) | 10.3 · 25 · 0.8/0.8 | 5.2 · 27 · 0.7/0.7 | 25.2 · 27 · 0.8/0.8 | 19.1 · 31 · 0.4/0.7 | 6.7 · 20 · 0.8/0.8 | 0.5 · 21 · 0.7/0.8 | 2.4 · 20 · 0.8/0.8 |
| 600 ms; 280 ms past 5 s; 12 s | 11.4 · 27 · 0.3/0.8 | 7.6 · 34 · 0.3/0.6 | 25.4 · 35 · 0.4/0.7 | 18.9 · 46 · 0.2/0.4 | 6.7 · 24 · 0.3/0.7 | 0.5 · 27 · 0.3/0.7 | 2.7 · 22 · 0.3/0.6 |
| 1.2 s; 500 ms past 8 s; 15 s | 9.6 · 21 · 0.6/0.7 | 5.0 · 24 · 0.6/1.1 | 26.7 · 24 · 0.6/1.3 | 17.9 · 25 · 0.5/0.9 | 6.7 · 18 · 0.7/10.0 | 0.5 · 20 · 0.6/0.7 | 2.4 · 19 · 1.1/1.3 |
| 900 ms; 400 ms past 8 s; 15 s | 9.7 · 24 · 0.5/0.6 | 5.4 · 29 · 0.5/0.9 | 24.4 · 27 · 0.5/1.0 | 18.0 · 32 · 0.5/0.8 | 6.7 · 20 · 0.5/1.0 | 0.5 · 20 · 0.5/0.7 | 2.7 · 21 · 0.9/1.0 |
| Flags + 2.5 s of speech | 11.9 · 25 · 1.0/1.6 | 7.5 · 33 · 0.3/0.9 | 24.5 · 32 · 0.4/1.0 | 18.0 · 40 · 0.2/0.6 | 8.2 · 23 · 0.3/1.4 | 0.5 · 25 · 0.3/1.0 | 3.1 · 20 · 0.3/0.9 |
| 900 ms; 400 ms past 8 s; 15 s; 2.5 s of speech | 9.6 · 21 · 0.5/0.6 | 5.2 · 27 · 0.5/1.0 | 23.2 · 24 · 0.5/1.0 | 18.0 · 31 · 0.5/0.7 | 6.7 · 20 · 0.5/1.0 | 0.5 · 20 · 0.5/0.7 | 2.8 · 20 · 0.9/1.0 |
| ... 3 s of speech | 9.6 · 21 · 0.5/0.6 | 5.1 · 27 · 0.5/1.3 | 23.3 · 24 · 0.5/1.5 | 18.0 · 29 · 0.4/0.7 | 6.7 · 20 · 0.5/1.0 | 0.5 · 20 · 0.5/0.7 | 2.8 · 20 · 0.9/1.0 |
| 700 ms always; 15 s; 2.5 s of speech | 9.6 · 21 · 0.8/0.8 | 5.1 · 25 · 0.7/0.8 | 24.1 · 24 · 0.8/0.8 | 18.0 · 29 · 0.4/0.7 | 6.7 · 20 · 0.8/0.8 | 0.5 · 20 · 0.7/0.8 | 2.4 · 20 · 0.8/0.8 |
| **900 ms; 500 ms past 8 s; 15 s; 2.5 s of speech (this change)** | 9.6 · 21 · 0.6/0.7 | 5.1 · 26 · 0.5/0.9 | 22.8 · 22 · 0.6/1.0 | 17.8 · 27 · 0.5/0.7 | 6.7 · 20 · 0.6/1.0 | 0.5 · 20 · 0.6/0.7 | 2.4 · 20 · 0.9/1.0 |

- Japanese, Haitian Creole and Khmer gain 2.2-2.4 points against the flags and
  Lao 0.5 (1.3 against main's 700 ms rule). Pieces drop to 21-27.
- The wait barely moves: Japanese is quicker (1.0 → 0.6 s at p50: its long
  sentences ended on the 12 s cut), the others +0.1-0.3 s at p50.
- A minimum of 2.5 s of speech is what helps Khmer most (pieces of one or two
  words); 3 s adds 0.3-0.5 s at p90 for nothing more.
- English, Spanish and French: no setting beats the flags by more than noise,
  and the longer ones add 0.2-0.6 s, so they keep the flags. (600 ms was as
  accurate on these clips with a shorter p90 wait; not changed here, since
  read speech has fewer hesitations than conversation.)

## Live

| Direction | Quality: Oct · main · **this** | Critical | CER %: Oct · main · **this** | Utterances | Stop → last audio p50/p90 (s): Oct · main · **this** |
|---|---|---|---|---|---|
| ja-en | 58.3 · 60.0 · **70.0** | 6 · 5 · 3 | 18.4 · 11.6 · **10.3** | 21 · 25 · 20 | 1.1/3.4 · 1.8/3.4 · **2.1/3.7** |
| ht-en | 21.7 · 20.0 · **31.7** | 14 · 15 · 13 | 7.5 · 7.6 · **5.7** | 35 · 35 · 26 | 2.6/3.4 · 2.7/3.4 · **3.0/3.9** |
| km-en | 26.7 · 36.7 · **33.3** | 17 · 16 · 17 | 36.3 · 25.4 · **22.8** | 31 · 27 · 23 | 3.0/3.9 · 4.5/5.6 · **3.9/5.0** |
| lo-en | 10.0 · 23.3 · **25.0** | 16 · 14 · 14 | 19.6 · 18.8 · **18.0** | 44 · 31 · 29 | 2.8/4.2 · 4.4/5.3 · **4.1/5.1** |
| es-en | 71.7 · 71.7 · **71.7** | 6 · 6 · 6 | 0.4 · 0.4 · **0.4** | 26 · 26 · 26 | 2.9/3.4 · 2.8/3.4 · **2.9/3.7** |
| fr-en | 76.7 · 81.7 · **81.7** | 5 · 3 · 3 | 4.4 · 2.1 · **2.1** | 23 · 22 · 22 | 2.7/3.2 · 2.7/3.3 · **2.7/3.2** |
| en-es | 56.7 · 61.7 · **61.7** | 6 · 4 · 4 | 11.3 · 6.7 · **6.7** | 23 · 24 · 24 | 2.6/3.9 · 2.6/3.7 · **2.6/3.7** |
| en-fr | 48.3 · 50.0 · **50.0** | 5 · 4 · 4 | 11.3 · 6.7 · **6.7** | 23 · 24 · 24 | 2.8/3.8 · 3.1/4.1 · **3.0/4.0** |
| en-ja | 56.7 · 60.0 · **60.0** | 4 · 3 · 3 | 11.3 · 6.7 · **6.7** | 23 · 24 · 24 | 2.9/4.2 · 3.2/4.4 · **3.1/4.1** |
| en-ht | 28.3 · 31.7 · **31.7** | 11 · 11 · 11 | 11.3 · 6.7 · **6.7** | 23 · 24 · 24 | 2.0/2.3 · 1.8/2.1 · **1.8/2.1** |
| en-lo | 50.0 · 55.0 · **55.0** | 9 · 8 · 8 | 11.3 · 6.7 · **6.7** | 23 · 24 · 24 | 9.9/13.7 · 13.2/19.1 · **8.1/12.0** |
| en-km | 36.7 · 38.3 · **40.0** | 4 · 2 · 3 | 38.5 · 34.9 · **34.7** | 16 · 16 · 17 | 25.5/32.8 · 27.3/34.2 · **26.1/32.2** |

- Into English from the four languages: quality 35.0 → **40.0** (October
  29.2): Japanese +10, Haitian Creole +11.7, Lao +1.7, Khmer −3.3 with its
  characters wrong 25.4% → 22.8% (one grading of 20 sentences moves a few
  points; treat under ~5 as noise).
- All 12 directions: 49.2 → **51.0** (October 45.1); critical errors 91 → 89
  (103).
- Directions out of English are unchanged by design (English keeps the
  flags); main and this branch graded the same there, which shows the grading
  is consistent.
- Latency: Haitian Creole and Japanese into English +0.3 s at p50; Khmer and
  Lao into English −0.6 and −0.3 s against main (whose 700 ms rule waited for
  whole sentences more often). English into Lao 13.2 → 8.1 s at p50 is the
  translator's queue, not the cutting (Lao is not spoken there).
- The #37 quiet-talker fix itself, October → main: 45.1 → 49.2 over all
  directions; English sources +1.6 to +5 points, French into English +5, Lao
  into English +13.3, Khmer into English +10.

## Limits

One clip per language and one grading. Lao and Khmer ran on the base
Omnilingual card (the 7B needs `OMNI_LARGE=1` on 80 GB); the 7B with these
rules wasn't measured. English into Khmer stays translator-bound (Khmer
output slower than real time).

## Files

| File | |
|---|---|
| `sweep.py` | the cutting loop offline for several settings + recognition (GPU, the stack's `server/`) |
| `score_sweep.py` | CER, pieces, cuts inside sentences, wait after each sentence |
| `results.json` | the replay and live numbers above |

No audio, transcripts or translations are stored.
