# Omnilingual ASR: model sizes and omni-stt endpointing (October 2026)

Two evaluations on the real-voice clips from `../2026-10-real-voices`
(FLEURS km, lo, en; CMU Haitian Creole; 30 sentences each). Real-voice data
only. Everything is in `results.json`.

1. **Model sizes** (`sizes_eval.py`, `score.py`, `run_all.sh`, `cut.sh`):
   16 zero-shot cards on the clips cut per sentence. `results.json` → `runs`.
2. **Endpointing sweep** (`endpoint_sweep.py`, `score_sweep.py`): the full
   clips through omni-stt's own turn-taking, for several `ENDPOINT_MS` /
   `MAX_UTTERANCE_S`. `results.json` → `endpointing_sweep`.

## Endpointing sweep

Live through omni-stt, LLM 300M scored about 30% CER on Khmer and 21–24% on
Lao. Fed one sentence at a time, the same model scores 14–16%. The suspects
were the forced cut at `MAX_UTTERANCE_S` = 6 s (the FLEURS sentences run
8–21 s) and `ENDPOINT_MS` = 300 ms.

`endpoint_sweep.py` loads `services/omni-stt/server.py` from the service
checkout and replays each full clip through it:

- the clip goes in as 100 ms messages through the service's `AudioIn`
  (96 ms blocks);
- Silero VAD runs at the pinned ref (`vad_block`);
- `Segmenter(endpoint_ms, max_s)` cuts turns, with the service's
  `MIN_SPEECH_MS` 400, `SHORT_TURN_ENDPOINT_MS` 700 and `TRAILING_KEEP_MS` 250;
- each segment is decoded through `load_omni`, the service's own decoder
  (temp wav, batch 1, `is_nonspeech` filter). The packages are the service's
  pins: omnilingual-asr 0.1.0, fairseq2 0.6, torch 2.8.0, bf16.

`score_sweep.py` then computes CER on the joined text (`judge.cer`), plus the
segment counts, forced cuts, mid-sentence cuts and waits.

    STACK=<omni checkout> python3 endpoint_sweep.py --card omniASR_LLM_300M --audio audio --out out_sweep [--level 2000]
    python3 score_sweep.py out_sweep/omniASR_LLM_300M.json

### The clips are part of the problem

The FLEURS recordings were made at very different gains:

- **Khmer:** 5 of the 30 sentences peak near −42 dBFS.
- **English:** 23 of 30 peak below −30 dBFS.

Silero hears nothing in the quietest sentences, so the Segmenter drops them
whole: 4 Khmer sentences and 3 English ones. No endpoint setting brings them
back. That is why Khmer stays at about 28% as recorded, whatever the settings.

`--level 2000` scales each sentence to RMS 2000 (int16; peak capped at
−1 dBFS) before the VAD, as a microphone with AGC would deliver it. This
separates the endpointing effect from the gain effect. A live room microphone
behaves like the levelled column, not like the raw FLEURS joins.

### Results: LLM 300M, CER %

The waits are audio time. `seg wait` is the time from the end of speech to
the emit, for turns ended by a pause.

| ENDPOINT_MS : MAX_S | ht | km | lo | en | km raw | lo raw | segments ht/km/lo | forced ht/km/lo | seg wait |
|---|---|---|---|---|---|---|---|---|---|
| **300 : 6 (now)** | 7.0 | 18.7 | 36.2 | 12.6 | 30.1 | 28.4 | 86/84/106 | 13/32/14 | 384 ms |
| 300 : 10 | 6.9 | 16.1 | 25.8 | 11.7 | 28.8 | 25.1 | 76/59/94 | 3/6/2 | 384 |
| 300 : 15 | 6.8 | 16.2 | 25.8 | 11.7 | 28.7 | 25.0 | 73/53/92 | 0/0/0 | 384 |
| 500 : 6 | 7.5 | 20.6 | 32.0 | 14.7 | 30.2 | 37.6 | 76/78/85 | 26/43/36 | 576 |
| 500 : 10 | 5.9 | 16.5 | 19.8 | 11.7 | 29.8 | 24.7 | 56/48/62 | 6/11/13 | 576 |
| **500 : 15** | 5.4 | 15.1 | 18.4 | 10.9 | 27.8 | 23.4 | 50/38/52 | 0/2/2 | 576 |
| 500 : 25 | 5.4 | 15.1 | 17.9 | 10.9 | 28.0 | 23.4 | 50/37/50 | 0/0/0 | 576 |
| 700 : 6 | 7.1 | 19.3 | 35.1 | 12.4 | 30.6 | 32.1 | 70/76/85 | 31/45/44 | 768 |
| 700 : 10 | 5.2 | 16.6 | 23.6 | 10.8 | 29.8 | 22.7 | 51/47/58 | 11/16/16 | 768 |
| **700 : 15** | **4.2** | 15.2 | 18.2 | **10.7** | 28.0 | 18.3 | 41/35/44 | 0/3/2 | 768 |
| 700 : 25 | 4.2 | 15.1 | 17.7 | 10.7 | 27.7 | 17.7 | 41/33/42 | 0/0/0 | 768 |
| 800 : 6 | 7.8 | 18.7 | 31.1 | 15.6 | 30.7 | 30.1 | 70/74/82 | 32/43/45 | 864 |
| 800 : 10 | 5.2 | 16.7 | 20.2 | 14.6 | 30.1 | 20.0 | 51/46/57 | 12/16/18 | 864 |
| 800 : 15 | 4.4 | 15.8 | **17.3** | 13.9 | 27.9 | 17.4 | 40/36/40 | 0/5/2 | 864 |
| 800 : 25 | 4.4 | **14.6** | 17.3 | 13.7 | 27.8 | 17.4 | 40/32/39 | 0/0/0 | 864 |
| *per sentence (cut clips)* | *4.2* | *14.2* | *15.7* | | | | | | |

- **Columns:** ht, km, lo and en are the levelled clips. "km raw" and
  "lo raw" are the clips as recorded. The segment counts and forced cuts are
  from the levelled clips.
- **`seg wait`:** the median and p90 are equal: `ENDPOINT_MS` plus up to one
  96 ms block. The exception is 800 : 6 on English, where the p90 is 1344 ms.
- **Not in the table:** median and p90 sentence waits, mid-sentence cuts,
  dropped sentences, the longest segment and the decode p90 are all in
  `results.json`.

### What the sweep shows

- **The 6 s cap is the main cause.** With 6 s, a third to a half of all
  Khmer and Lao segments are forced cuts. Going to 15 s removes nearly all
  of them. Going to 25 s adds little (at most 0–1.2 points), and it lets a
  speaker who never pauses run up to 25 s before any text arrives.
- **300 ms is too short for Lao.** It cuts Lao mid-sentence about 63 times
  in 30 sentences, at in-sentence pauses, even with no forced cuts at all.
  Lao goes from 25.8% to 18% at 500–700 ms.
- **Haitian Creole is the same.** It goes from 7.0% to 4.2% at 700 : 15,
  equal to the per-sentence score.
- **Levelled, 700 : 15 is within 1–2.5 points of per-sentence** on every
  language. The gap left on Khmer and Lao is the turns that still split at
  real pauses.
- **The cost is latency.**
  - The endpoint wait goes from about 384 ms to 768 ms (+384 ms per turn).
  - A non-stop speaker can now run up to 15 s before being cut, instead of 6 s.
  - The longer segments take longer to decode on this GPU: p90 1.1–2.0 s
    against 0.5–0.9 s.
  - The median sentence wait (sentence speech end to emit) goes from
    0.47–0.64 s to 0.86–1.02 s. The p90 sentence waits are long (6–11 s on
    ht/km/en at every setting) because FLEURS marks carry trailing noise
    that keeps some turns open into the next sentence.

### LLM 7B, levelled, CER %

| ENDPOINT_MS : MAX_S | ht | km | lo | en |
|---|---|---|---|---|
| 300 : 6 | 8.7 | 15.1 | 47.3 | 7.8 |
| 500 : 15 | 5.6 | **12.7** | 28.3 | 8.5 |
| 700 : 15 | 5.5 | 13.3 | 27.7 | 8.5 |
| 800 : 15 | 5.9 | 14.1 | **16.8** | 8.5 |
| *per sentence* | *4.2* | *12.6* | *8.4* | |

The 7B decoder falls into repetition loops ("ເອີ ເອີ ເອົາ ເອົາ ເອົາ …", about
200 characters) on Lao fragments under 1 s, such as a breath or a clipped
word. There are 6 of them at 300 : 6, 3 at 500–700 : 15 and 1 at 800 : 15,
and they account for most of its Lao gap. Its per-sentence Lao score (8.4%)
needs a repetition guard and fewer short fragments. Endpointing alone does
not get there.

The 7B checkpoint ran converted to bf16 on the pod: the fp32 file is 31 GB
and the pod's RAM limit was 31 GB. The pipeline decodes in bf16 anyway.

### Speed (batch 1, one stream)

The GPU was one MIG 1g.24gb slice of an RTX PRO 6000 Blackwell (RunPod,
$0.69/h). L4, 3090 and 4090 had no stock. RTF is the decode wall time over
the audio seconds, over every distinct segment decoded:

| Card | RTF | peak GPU memory |
|---|---|---|
| LLM 300M | 0.129–0.133 | 3.5 GB |
| LLM 7B (bf16) | 0.151 | 14.9 GB |

**This is not an L4 measurement.** The slice is in the same class as an L4
(a quarter of a 96 GB Blackwell card), and 7B costs only about 15% more
time than 300M. That fits the earlier finding that per-step overhead, not
weight reads, dominates. Both are far inside real time. The earlier L4
estimate (0.15–0.25 for 300M, 0.2–0.35 for 7B) is consistent with these
numbers but is not confirmed on an L4.
