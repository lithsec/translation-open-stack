# omni-stt streaming track: Omnilingual CTC 3B for Khmer and Lao (October 2026)

A GPU run of omni-stt's streaming track (`services/omni-stt/ctc_stream.py`,
README "Streaming track"). Each pass decodes Meta's `omniASR_CTC_3B` (stock
weights, cast to bf16) over 8 s of left context every 500 ms of audio. The
track commits the frames older than now minus the look-ahead (1 or 2 s) and
applies a script mask (the language's script, Basic Latin, digits and
punctuation). It sends `partial` (the revisable tail) and `committed` (never
revised) on `/listen`. The questions were:

1. Does the 3B fit beside the 7B (the per-piece finals for km and lo) on one L4?
2. How many real-time streams does an L4 carry?
3. Latency through the real service: first partial, commit and final.
4. Accuracy on the 30-sentence FLEURS set and on **unseen, non-FLEURS audio**,
   so the settings are not judged on one set alone.

Everything was measured through the service itself: `server.py` on an NVIDIA
L4 (24 GB), and clients streaming 100 ms PCM16 messages at real-time pace
over a local WebSocket (`eval_client.py`). Each clip got its own connection:
0.5 s of digital silence, the clip, 1.5 s of silence, then a flush. Metrics
are in `results.json`; this directory holds no audio and no transcripts.

## Summary

- **The 3B does not fit beside the 7B on an L4.** The 7B's bf16 weights take
  15.6 GB, and its peak on a batch of six 10 s utterances (omni-stt-7b runs six
  streams) is 17.0 GB. The 3B adds 6.2 GB of weights, and loading it beside
  the 7B ran out of memory (22.0 GiB usable; 20.3 GiB already allocated). So
  the track runs as a **separate streaming service**: omni-stt with
  `OMNI_CARD=omniASR_CTC_3B` and `STT_CTC_STREAM=1`. The track shares that
  service's copy of the 3B, and the service's own per-piece finals for km and
  lo are the 3B's, decoded with the same mask. The 7B service stays the
  source of final text.
- **Capacity: about 6 streams per L4** with every stream talking without a
  break. Commit lag holds at the look-ahead plus 0.1-0.3 s up to 6 streams
  (63% GPU). At 8 streams it slips by about 0.35 s (89%), and from 10 the GPU
  saturates (96-98%). Passes then get rarer and their windows longer, so
  latency grows. Accuracy does not change: committed CER was flat from 2 to
  16 streams. Rooms with pauses fit more streams: while the VAD hears nothing,
  a stream decodes once every 2 s instead of every 0.5 s.
- **Latency (one stream; seconds after speech onset):** first partial 0.6-0.8
  (p50). First committed text 2.4-2.8 with a 2 s look-ahead, or 1.3-1.8 with
  1 s. While someone speaks, committed text trails the audio by the look-ahead
  plus 0.03-0.1. When the VAD ends a turn, the closing commit and the 3B's
  final arrive 0.1-0.6 s after the speech ends. The 7B service's finals
  arrive 0.8-1.6 s after (p50) on the same clips.
- **Accuracy (2 s look-ahead):** the committed text is within 2 CER points of
  the same service's per-piece 3B finals, and better than them on three of
  the four sets. A 1 s look-ahead costs 3-3.5 points (1 on FLEURS Khmer).
  Against the 7B finals the streaming text gives up 1.0-3.8 points per set.
  The one large gap is Common Voice Lao (20.1 against 5.7), which is in the
  training data (table below).

## Accuracy

CER (%), as the earlier evals' `judge.cer`: NFKC, lowercase, only
`str.isalnum()` characters, Levenshtein over the joined references and the
joined hypotheses. `committed` is a clip's committed text in order. `final`
is its `inputTranscript`s joined, from the 3B streaming service or from the
7B service.

| Set | clips | committed, 2 s | committed, 1 s | 3B final (same service) | 7B final (omni-stt-7b) |
|---|---|---|---|---|---|
| FLEURS km | 30 | 16.1 | 17.1 | 14.2 | 12.3 |
| FLEURS lo | 30 | 18.3 | 21.7 | 18.7 | 16.3 |
| unseen km | 40 | 25.2 | 28.2 | 27.2 | 24.2 |
| unseen lo | 36 | 7.7 | 10.8 | 8.0 | 4.9 |

Unseen, by source:

| Source | kind | licence | clips | committed, 2 s | committed, 1 s | 3B final | 7B final |
|---|---|---|---|---|---|---|---|
| km: Digital-Divide-Data/khm-asr-cultural | read, 7 speakers | CC-BY-SA-4.0 | 16 | 4.2 | 4.4 | 4.1 | 3.6 |
| km: byumatrixlab/cohp-asr (Cambodian oral-history interviews) | spontaneous, room recordings | CC-BY-NC-SA-4.0 | 24 | 46.3 | 52.1 | 50.4 | 44.9 |
| lo: SiangLao/lao-asr-thesis-dataset | read, 9 speakers, 3 accents | CC-BY-NC-4.0 | 27 | 5.4 | 7.4 | 5.0 | 4.8 |
| lo: Common Voice 26.0 (lo) | read, browser and phone mics, 9 speakers | CC0-1.0 | 9 | 20.1 | 28.1 | 23.4 | 5.7 |

For context, the 2026-10-26 research run used the same 30 FLEURS sentences,
fed whole and without the service, on an A40. There the same chunked 3B
scored km 15.1 and lo 15.7 at a 2 s look-ahead (17.3 and 18.9 at 1 s). Azure
streaming scored 13.5 and 17.9, and the 7B per sentence 12.6 and 8.4.

Notes on the unseen sets:

- No permissively licensed spontaneous Lao turned up. Lao is read speech
  only, and the one spontaneous Khmer source (COHP) is non-commercial. Both
  non-commercial sets were used for this evaluation only; no audio or
  transcript from them is in the repository.
- COHP's references are the project's manual transcripts, but its segment
  edges come from forced alignment, so a clip can lose or gain a syllable at
  either end. That inflates every system's CER on it alike. The interviews
  also contain fillers and overlapping talk.
- Common Voice is in Omnilingual's training data. Its clips are new only by
  speaker, which may be why the 7B does so well on it.
- No unseen clip's reference matched a FLEURS km or lo transcript.

## Latency through the service

One stream per run (four runs at once, so four streams on the GPU). Seconds,
p50 / p90.

| Set, look-ahead | first partial after onset | first commit after onset | commit lag while speaking | turn's closing commit after speech end | 3B final after speech end |
|---|---|---|---|---|---|
| FLEURS km, 2 s | 0.83 / 2.64 | 2.50 / 4.22 | 2.10 / 2.21 | 0.55 / 0.72 | 0.67 / 0.93 |
| FLEURS km, 1 s | 0.82 / 2.57 | 1.46 / 3.17 | 1.04 / 1.19 | 0.42 / 0.65 | 0.59 / 0.77 |
| FLEURS lo, 2 s | 1.16 / 1.88 | 2.79 / 3.59 | 2.07 / 2.21 | 0.11 / 0.70 | 0.11 / 0.68 |
| unseen km, 2 s | 0.64 / 1.64 | 2.37 / 3.15 | 2.03 / 2.11 | 0.43 / 0.86 | 0.49 / 0.68 |
| unseen lo, 2 s | 0.72 / 1.53 | 2.43 / 3.25 | 2.03 / 2.09 | 0.42 / 0.59 | 0.50 / 0.67 |

The onset is an energy estimate (-30 dB from the clip's peak). On the noisier
FLEURS Lao clips it lands at the clip's first frame, before the speech,
which inflates that row's first-partial figure. "Commit lag" is a commit's
arrival minus the audio time it reaches (`end_ms`), so it is the look-ahead
plus the pass's own delay. The 7B service's finals on the same clips arrived
1.56 / 2.52 s (FLEURS km), 0.83 / 1.82 (FLEURS lo), 1.63 / 2.34 (unseen km)
and 1.38 / 2.59 (unseen lo) after the speech ended.

## Capacity (L4)

`bench_ctc.py`: one batched pass of K streams, each a 10.5 s window (8 s left
context + 2 s look-ahead + 0.5 s of new audio), bf16:

| K passes in one batch | 1 | 2 | 4 | 6 | 8 | 12 | 16 |
|---|---|---|---|---|---|---|---|
| batch time (s) | 0.096 | 0.178 | 0.345 | 0.470 | 0.616 | 0.958 | 1.293 |
| peak allocated (GB) | 6.5 | 6.7 | 7.2 | 7.7 | 8.2 | 9.2 | 10.1 |

The cost grows linearly with K (about 78 ms a stream), so batching saves
little. A stream needs one pass every 500 ms while it speaks: six streams use
0.47 s of each 0.5 s. One stream costs the GPU about 0.19 times real time on
an L4, against 0.12 on an A40 in the research run.

Load test through the service (`eval_client.py --streams`: half km, half lo,
10 FLEURS clips each, every stream talking without a break, 2 s look-ahead):

| streams | GPU util | commit lag p50 / p90 (km) | first partial p50 (km) | 3B final after speech end p90 (km) | committed CER km / lo |
|---|---|---|---|---|---|
| 2 | n/a | 2.04 / 2.13 | 0.68 | 0.65 | 22.9 / 21.0 |
| 4 | 42% | 2.03 / 2.12 | 0.74 | 0.70 | 22.9 / 20.8 |
| 6 | 63% | 2.09 / 2.28 | 0.76 | 0.85 | 23.0 / 21.2 |
| 8 | 89% | 2.35 / 2.69 | 0.92 | 1.32 | 22.6 / 21.7 |
| 10 | 96% | 2.73 / 2.95 | 1.41 | 2.31 | 23.3 / 20.5 |
| 12 | 96% | 2.96 / 3.14 | 1.71 | 2.78 | 23.6 / 20.7 |
| 16 | 98% | 3.42 / 3.62 | 2.47 | 3.36 | 23.0 / 20.8 |

The CER here covers the first 10 clips only, which are harder than the full
30. It shows that load does not change the text.

## Cold start

From process start to `ready` on the pod, with the checkpoint already in the
page cache: the separate streaming service took **5-9 s**. That is 1.0-1.2 s
to read the 3B's 6.2 GB bf16 checkpoint, 0.1 s for the track (it shares the
recogniser), 1.0 s to warm up, and the rest for VAD, language ID and imports.
The container would not let the page cache be dropped, so no cold-disk figure
was taken. At the 0.6-1 GB/s that Cloud Run read a baked image at for the 7B
(README), the checkpoint read alone would be about 6-10 s. Beside the 7B (on a
GPU large enough for both), the track would add its own load: 3.4-3.7 s here,
from the page cache, plus 0.7 s of warm-up.

## Found by this run, and fixed in the service

- **VAD-gated skipping lost words.** The first version moved the commit edge
  over audio the VAD called silent, without decoding it. On the quiet FLEURS
  Lao clips Silero passed 0.5 on as little as half of the speech, and those
  words were lost. The track now always decodes: once every 500 ms while the
  VAD hears speech, once every 2 s (`STT_CTC_QUIET_MS`) while it does not.
- **Thai script in Lao finals.** Unmasked, the 3B wrote some short Lao pieces
  in Thai script. Lao finals scored 27.8 on FLEURS. The streaming service's
  km and lo finals now use the masked decode (18.7). The research had found
  the mask costs nothing on whole sentences.
- **Digital silence.** Beside exact zeros (this client's padding, a muted
  mic), a quiet Lao clip's frames went wrong. Unpadded, the same clip decoded
  correctly. A trace of noise under every window (`STT_CTC_DITHER`, 1e-4 rms,
  about -80 dBFS) fixed it. Across the four sets it moved committed CER by
  FLEURS lo -4.0, unseen km -4.1, unseen lo -2.8 and FLEURS km +1.7 (2 s
  look-ahead). Runs are deterministic: a repeat of FLEURS km gave 16.1 again.
  The dither is kept on the strength of the three sets it helped, not tuned
  further on any one.
- **Commits split grapheme clusters.** A commit could end on a Khmer
  consonant whose vowel sign arrived in the next commit. The edge now moves
  back so it never falls before a combining mark or after a coeng.

The finals of the 7B service may share the digital-silence weakness. That was
not measured here.

## Reproduce

On a GPU machine with the omni-stt dependencies
(`services/omni-stt/7b/Dockerfile.base`'s packages):

```
# the streaming service: the 3B as recogniser and track
OMNI_CARD=omniASR_CTC_3B STT_CTC_STREAM=1 STT_OPEN=1 STT_SERVE=listen PORT=8080 \
  python services/omni-stt/server.py
# a set: SETDIR/manifest.json {"rows": {"km": [{"i", "clip", "ref"}, ...]}}, 16 kHz mono wavs
python eval/2026-10-ctc-stream/eval_client.py ws://127.0.0.1:8080/listen SETDIR km out_km.json --lookahead 2
python eval/2026-10-ctc-stream/eval_client.py ws://127.0.0.1:8080/listen SETDIR km load.json --streams 6 --limit 10
python -I eval/2026-10-ctc-stream/score_stream.py SETDIR out_km.json load.json
python eval/2026-10-ctc-stream/bench_ctc.py SETDIR/clips/km [--with7b omniASR_LLM_7B]
```

`--nostream` runs the same clips without the track, for example against the
7B service.
