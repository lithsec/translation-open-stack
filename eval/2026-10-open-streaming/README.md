# Open-weight streaming recognition for phrase-by-phrase translation, October 2026

Can an open-weight streaming recogniser, run on our own GPU, drive phrase mode the way the cloud
recognisers did in [`../2026-10-simultaneous-phrases`](../2026-10-simultaneous-phrases/)? We tested
three candidates on English, Spanish and French, both ways with English. They ran on the same unseen
clips, with the same commit and phrase rules and the same continuation prompt as that eval.

**Status.** Measured and graded: recognition, quality, "chunks wrong later", latency and GPU cost for
all three recognisers in phrase and sentence mode. Grading is the phrase eval's: one blind
gemini-pro-latest call per direction and clip, all systems side by side, after Gemini cuts each spoken
stream into the read sentences (`grade.sh`).

## History

The first pod (A100 80 GB) was terminated by RunPod at 20:37:59 UTC. By then every recogniser's
real-time pass was finished and copied out (`raw/rec/`). The re-run on a second pod (RTX PRO 6000
Blackwell 96 GB) did the following:

1. Rebuilt the clips. Recognition scores came out identical, so the clips are identical.
2. Reused the saved recordings, without re-recording.
3. Replayed **every** system's translation against that pod's Gemma, so all latencies share one
   translation server. The three replays first made on the A100 are kept in `raw/sim_a100/`.

## Setup

- **Clips:** the unseen set of [`../2026-10-unseen`](../2026-10-unseen/): 20 FLEURS sentences per
  language, with regular (*reg*) and irregular (*irr*) pauses.
  - They were rebuilt for en, es and fr by `build_unseen_subset.py`, from that run's `fleurs_ids` and
    with its reader choice and trimming. The script asserts that the gaps are identical.
  - The clips were not re-drawn, because the draw depends on folders that are not in the repository.
- **Recognisers:** each processed one whole clip as one stream, in real time, on an A100 80 GB. They
  ran one at a time under the pod's real-time lock. Each wrote the `stream_partials.py` shape
  (`{"partials":[{"t","text","offsetMs","stable"}],"finals":[...]}`), with `t` on the clip's clock.
  - **SimulStreaming** (ÚFAL, `ufal/SimulStreaming` @077ea37), AlignAtt policy on **Whisper
    large-v3** (OpenAI `large-v3.pt`, sha256 e5b1a55b…).
    - Settings: `frame_threshold` 25, 0.5 s minimum chunk, Silero voice-activity controller (VAC),
      greedy.
    - It ran in the tool's own real-time, computationally aware loop (`simul_run.py`, which loads the
      model once per process).
    - Its output is append-only, so every word is final. A VAC segment end is a final
      (`simul_to_partials.py`).
    - It kept up with real time on every clip: text trailed the audio by 0.9–1.0 s at the median and
      1.6 s at most. The fallback to `whisper_streaming` was not needed.
  - **Omnilingual CTC 3B streaming track:** omni-stt run as in
    [`../2026-10-ctc-stream`](../2026-10-ctc-stream/) "Reproduce" (`OMNI_CARD=omniASR_CTC_3B
    STT_CTC_STREAM=1`, 2 s look-ahead, 0.5 s passes).
    - It was opened to en/es/fr for this test only, by `STT_CTC_LANGS=en,es,fr` and a Latin script
      mask (`ctc_stream_en_es_fr.patch`, 4 lines). Nothing in `services/` was changed.
    - `stream_ctc.py` streamed each clip in real time over `/listen`, three connections at once.
    - A partial is the turn's committed text plus the revisable tail. Committed words are "stable",
      except the last one, because a commit can end inside a word.
    - A final is the turn's committed text when the segmenter ends the turn, with that utterance's
      audio span.
  - **NeMo cache-aware FastConformer-RNNT:** **`nvidia/nemotron-3.5-asr-streaming-0.6b`** @ea30d66
    (multilingual, 40 locales, licence **OpenMDW-1.1**).
    - It ran on NeMo 3.0.0 with `att_context_size` [56,6] (0.56 s chunks), `target_lang` en-US /
      es-US / fr-FR, in fp32 (`nemo_stream.py`).
    - Timing is computationally aware: a chunk starts when its audio has arrived and the previous step
      is done, and each step's GPU time is measured. One warm-up pass runs first and is not kept.
    - The model has no end-of-utterance signal, so Silero VAD (500 ms of silence) marks finals.
    - The finals' audio spans come from when their words appeared (`nemo_spans.py`). Silero missed the
      quietest English readers, so the English finals merge sentences: 12 finals for 20 sentences.
    - Its card lists FLEURS among its training data, so these numbers may be optimistic.
  - The English-only `nemotron-speech-streaming-en-0.6b` was not run.
- **Translation:** `simulate_open.py` is `../2026-10-simultaneous-phrases/simulate.py` with three
  changes:
  1. Its translator is **Gemma 4 31B 4-bit** (`google/gemma-4-31B-it-qat-w4a16-ct`) on the pod's vLLM,
     at temperature 0 with thinking off.
  2. A partial's `stable` words are committed at once.
  3. It runs only en↔es and en↔fr.

  It runs phrase mode (≤8 words; the same phrase rule, 300 ms pause and continuation prompt) and
  sentence mode (one call per recogniser final).
- **Latency:** `analyze_open.py` is that eval's `analyze.py`.
  - The voice is **that eval's measured Azure neural TTS** time to first audio (its `results.json`
    "tts": 146–207 ms median), not a new measurement.
  - **Sentence cut:** as that eval, each system's spoken stream is cut into the read sentences at
    verbatim anchors chosen by Gemini (`seg_all.py`). The first, ungraded tables used an audio-overlap
    cut instead; its jobs are kept as `raw/*_overlap_cut.json`.
- **GPU cost:** real-time factor (RTF) and memory for one stream on the A100 (`raw/rec_cost.json`):
  - SimulStreaming: one computationally unaware pass.
  - NeMo: the sum of its step times.
  - CTC: `../2026-10-ctc-stream/bench_ctc.py`.

## Results

Means over both pause patterns and the two directions in each group. Latencies are medians of the
per-direction medians, in seconds, on the phrase eval's definitions. Rows marked ¹ are the cloud rows
of `../2026-10-simultaneous-phrases/results.json` on the same four directions and clips. Their
translator was Gemma 4 31B on OpenRouter, their sentences were cut by Gemini and they are graded.

**Out of English (en→es, en→fr)**

| Recogniser | Mode | Quality, said | Critical | Speech starts → first audio (s) | Speech ends → last audio (s) | Chunks wrong later | Translation call p50 (s) |
|---|---|---|---|---|---|---|---|
| SimulStreaming, Whisper large-v3 | Phrase ≤8 | 35.8 | 10.8 | 3.9 | 1.5 | 13% | 0.5 |
| Omnilingual CTC 3B track | Phrase ≤8 | 27.9 | 14.2 | 5.0 | 1.3 | 27% | 0.5 |
| Nemotron 3.5 ASR streaming | Phrase ≤8 | 48.3 | 10.2 | 3.9 | 1.5 | 31% | 0.7 |
| SimulStreaming, Whisper large-v3 | Sentence | 55.0 | 10 | 6.4 | 2.0 | – | 0.8 |
| Omnilingual CTC 3B track | Sentence | 47.9 | 11.8 | 7.1 | 1.4 | – | 0.8 |
| Nemotron 3.5 ASR streaming | Sentence | 57.1 | 9.2 | 16.3 | 10.0 | – | 1.0 |
| MAI-Transcribe-2-Streaming ¹ | Phrase ≤8 | 64.2 | 6 | 4.1 | 2.2 | 12% | 0.9 |
| Azure standard real-time ¹ | Phrase ≤8 | 65.8 | 4.8 | 4.4 | 2.2 | 12% | 0.8 |
| MAI-Transcribe-2-Streaming ¹ | Sentence | 68.7 | 4.8 | 10.6 | 4.7 | – | 1.0 |
| Azure standard real-time ¹ | Sentence | 79.5 | 4.8 | 9.7 | 3.9 | – | 1.7 |

**Into English (es→en, fr→en)**

| Recogniser | Mode | Quality, said | Critical | Speech starts → first audio (s) | Speech ends → last audio (s) | Chunks wrong later | Translation call p50 (s) |
|---|---|---|---|---|---|---|---|
| SimulStreaming, Whisper large-v3 | Phrase ≤8 | 45.4 | 4.8 | 3.7 | 1.5 | 22% | 0.4 |
| Omnilingual CTC 3B track | Phrase ≤8 | 55.4 | 4 | 4.6 | 1.0 | 17% | 0.4 |
| Nemotron 3.5 ASR streaming | Phrase ≤8 | 48.5 | 2.5 | 3.6 | 1.7 | 27% | 0.5 |
| SimulStreaming, Whisper large-v3 | Sentence | 78.8 | 2 | 9.6 | 2.0 | – | 0.7 |
| Omnilingual CTC 3B track | Sentence | 77.8 | 3.2 | 7.1 | 1.3 | – | 0.6 |
| Nemotron 3.5 ASR streaming | Sentence | **85.3** | 1.8 | 8.6 | 2.0 | – | 0.8 |
| MAI-Transcribe-2-Streaming ¹ | Phrase ≤8 | 69.9 | 2.5 | 3.7 | 2.0 | 13% | 0.7 |
| Azure standard real-time ¹ | Phrase ≤8 | 61.0 | 3 | 4.0 | 1.6 | 11% | 0.6 |
| MAI-Transcribe-2-Streaming ¹ | Sentence | 88.5 | 1.2 | 15.0 | 7.3 | – | 1.2 |
| Azure standard real-time ¹ | Sentence | 83.9 | 2.5 | 10.1 | 2.8 | – | 1.5 |

Quality is the phrase eval's score (0–100, against what was said); "Critical" is the mean count of
critical errors per graded clip.

**Recognition on the finals** (`../2026-10-whisper-vs-azure/score.py`, CER / WER %, against the written
text). The "en said" column is against what was said. Here that is the unseen run's witness text for
its 8 flagged English sentences; the cloud rows used the full witness.

| Recogniser | en reg | en irr | en said reg; irr | es reg | es irr | fr reg | fr irr |
|---|---|---|---|---|---|---|---|
| SimulStreaming, Whisper large-v3 | 27.8 / 33.0 | 25.7 / 31.7 | 24.9 / 29.8; 22.6 / 28.2 | 3.9 / 8.4 | 4.7 / 8.7 | 17.0 / 21.3 | 14.4 / 19.3 |
| Omnilingual CTC 3B track | 24.8 / 34.8 | 27.5 / 39.8 | 20.9 / 32.0; 23.7 / 37.1 | 4.6 / 10.8 | 4.4 / 10.4 | 6.9 / 15.0 | 6.1 / 13.2 |
| Nemotron 3.5 ASR streaming | **11.7 / 19.1** | **21.2 / 27.5** | 7.8 / 15.6; 17.0 / 23.7 | **2.4 / 6.1** | **2.8 / 7.6** | **3.8 / 10.4** | **4.1 / 10.7** |
| MAI-Transcribe-2-Streaming (cloud) | 8.4 / 13.9 | 10.2 / 14.1 | 6.1 / 11.5; 6.9 / 12.6 | 0.9 / 3.7 | 1.1 / 3.5 | 2.8 / 6.6 | 3.2 / 6.8 |
| Azure standard real-time (cloud) | 7.0 / 11.8 | 7.4 / 12.6 | 3.6 / 7.8; 3.7 / 8.3 | 2.7 / 6.5 | 2.7 / 6.5 | 3.8 / 10.2 | 3.3 / 8.6 |

**GPU cost, one stream, A100 80 GB**

| Recogniser | Real-time factor | GPU memory | Streams per GPU at this RTF (rough) |
|---|---|---|---|
| SimulStreaming, Whisper large-v3 | 0.37 | 7.5 GB allocated, 10.3 GB process | 2–3 |
| Omnilingual CTC 3B track | 0.072 alone; 0.038 per stream batched 16 | 6.5 GB; 10.1 GB for 16 streams | about 25 (batched) |
| Nemotron 3.5 ASR streaming (fp32) | 0.067 | 2.8 GB | about 13 |

## Findings

1. **Phrase mode on open recognisers is not ready.** In phrase mode the open recognisers score 28–48 out
   of English (cloud 64–66) and 45–55 into English (cloud 61–70). It is also
   no quicker to first audio once the sentences are cut by Gemini (3.6–5.0 s against 3.7–4.4 s).
   - Up to a third of the open phrases are later contradicted ("chunks wrong later" 17–31%, against
     11–13% on the cloud). Nemotron is the worst at 27–31%: committing its `stable` words at once
     probably commits too early. That is untested.
2. **In sentence mode, Nemotron 3.5 ASR streaming is close to the cloud into English.** It scores 85.3
   with 1.8 critical errors, against 88.5 on MAI and 83.9 on Azure standard, and its last audio comes
   2.0 s after the speaker stops.
3. **Out of English, Nemotron's sentence mode is held back by its English finals.** Silero VAD missed
   quiet readers, so finals merge sentences: first audio 16.3 s, last audio 10.0 s after the speaker
   stops. It still scores highest of the open three (57.1), but far below the cloud (69–80).
4. **Recognition:** Nemotron is the only open recogniser close to the cloud on Spanish (2.4–2.8% CER)
   and French (3.8–4.1%). On English it is behind (12–21% against 7–10%).
   - SimulStreaming on Whisper large-v3 invents text in the gaps ("Sous-titrage Société Radio-Canada",
     "♪", "*Gunshot*") and loses quiet English. It is also the most expensive (RTF 0.37).
   - The CTC 3B track writes no punctuation or capitals. Its Spanish is usable; its English and French
     are behind Nemotron.

**Recommendation:**
- Don't ship open phrase mode.
- If an open recogniser is wanted for whole sentences, use **Nemotron 3.5 ASR streaming into English**
  (es→en, fr→en). Out of English, it needs a better end-of-utterance signal than Silero VAD at default
  settings.
- Keep the CTC 3B track for Khmer and Lao only. Don't use SimulStreaming.

## Limits

- One grading call per direction and clip: differences of a few points are within its noise.
- One clip per language and pattern, read FLEURS sentences joined with artificial pauses. Nemotron may
  have seen FLEURS in training.
- **Two different machines:**
  - Recognition timing and GPU cost were measured on an A100 80 GB pod. Its CPU was capped at 13.6
    cores and shared with other jobs.
  - The first SimulStreaming attempt (three clips at once) fell behind real time and was discarded.
    The kept passes ran one at a time, on a quiet box, under the real-time lock.
  - The CTC service ran three streams at once.
  - Translation timing comes from Gemma on a second pod (RTX PRO 6000), beside other jobs.
- Silero VAD at default settings missed some quiet English readers. That affects the NeMo finals, so
  NeMo's sentence mode, not its phrase mode.

## Files

- **Recognition:**
  - `simul_run.py`, `simul_to_partials.py`: SimulStreaming.
  - `stream_ctc.py`, `ctc_stream_en_es_fr.patch`, `run_ctc.sh`, `run_ctc_lock.sh`: the CTC track.
  - `nemo_stream.py`, `nemo_spans.py`, `run_nemo.sh`: NeMo.
  - `run_all.sh`: all three in turn, under the real-time lock.
- **Clips and references:** `build_unseen_subset.py` (clips); `make_refs.py`, `rec_manifest.py`
  (references, the scoring manifest, and the voice timing taken from the phrase eval).
- **Replay and analysis:** `simulate_open.py` (replay and translation); `analyze_open.py` (latency,
  grading jobs, `results.json`); `table.py` (the tables above); `grade.sh` (grading).
- **`raw/`:**
  - `rec/`: per-clip partials and finals for all recognisers.
  - `sim/`: every translation replay, from the RTX PRO 6000 pod.
  - `sim_a100/`: the first replays of three systems.
  - `rec_score.json`, `rec_cost.json`, `tts.json`.
  - `seg/`, `jobs.json`, `grades.json`, `contra_jobs.json`, `contra.json`: the Gemini cut, grading
    jobs and grades.
  - `jobs_overlap_cut.json`, `contra_jobs_overlap_cut.json`: the earlier jobs on the audio-overlap cut.
  - No audio.

## Reproduce

1. **Venvs:**
   - **eval:** numpy, num2words 0.5.14.
   - **omni:** torch 2.8 + `omnilingual-asr`, with the repo's `constraints.txt`.
   - **simul:** torch 2.8 cu128 + SimulStreaming's `requirements_whisper.txt`. It needs `tqdm`, which
     a plain torch install lacks.
   - **nemo:** torch 2.8 + `nemo_toolkit[asr]` 3.0.0 + `silero-vad` 5.1.2.
2. **Clips:** `python3 -I build_unseen_subset.py CLIPS ../2026-10-real-voices ../2026-10-unseen/results.json en es fr`
3. **omni-stt:** copy `services/omni-stt` plus `server/{audio_in,stack_auth,licences}.py`,
   `server/engines/` and `constraints.txt` (as `deploy.sh stage` does) to `/workspace/stream/omni-stt`,
   then apply `ctc_stream_en_es_fr.patch`.
4. **Recognition:** `bash run_all.sh`, about 35 min on an A100 and 10 GB at most at a time.
5. **Replay:** `CLIPS_ROOT=CLIPS VLLM_URL=http://127.0.0.1:8101/v1 python3 -I simulate_open.py WORK`, about
   10 min.
6. **Recognition scores:** `python3 -I make_refs.py UO; python3 -I rec_manifest.py CLIPS UO WORK; python3 -I ../2026-10-whisper-vs-azure/score.py WORK/rec_manifest.json WORK/rec_score.json`
7. **Grading:** `GEMINI_API_KEY=... bash grade.sh CLIPS UO WORK`.

Lessons from setup:

- Check the container's CPU quota (`/sys/fs/cgroup/cpu.max`) before any real-time run, and never run
  real-time recognisers in parallel on a capped box.
- SimulStreaming took about 4 min to start under load.
- Wait for omni-stt's `ready on :PORT` line: the 3B is an 11.5 GB download on first start.
- Use `pkill`/`pgrep` patterns that cannot match your own ssh command line.
