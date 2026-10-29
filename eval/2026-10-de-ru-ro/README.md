# German, Russian and Romanian, October 2026

Which recogniser and translator should the stack use for German, Russian and Romanian? PR #74 moved
German and Russian out of English to Gemma 4 31B, on Lithos Talk's route table. This round checks that
choice on the stack itself, typed and live, and adds Romanian, which runs on Whisper and MADLAD today.
It also tests whether German gains from the longer turns Japanese, Haitian Creole, Khmer and Lao take.

## Setup

- **Clips** (`build_clips.py`): 40 FLEURS test sentences (CC BY 4.0) shared by en, de, ru and ro, that
  no earlier clip set used. Set a is the first 20 and set b the next 20 (seed 2027).
  - Pauses as `../2026-10-unseen`: *reg* 1.0–1.95 s between sentences, both sets; *irr* 0.3–1.2 s, set
    a only, for the German turn test.
  - Each sentence is also kept alone for per-sentence recognition.
- **Recognition** (`asr.py`, `score_asr.py`): one sentence at a time, language given.
  - Whisper large-v3 (faster-whisper, float16, the stack's options).
  - Omnilingual LLM 300M and 7B, through omni-stt's own engine path.
  - CER and WER after NFKC, lowercase and letters/digits only, with ş/ţ folded to ș/ț and ё to е. For
    Romanian, also the share of the reference's diacritics (ă â î ș ț) missing from the output.
- **Typed translation** (`mt.py`, `round_mt.py`): one sentence per call, no context, through the
  stack's own engines (`server/engines`).
  - Hy-MT2 7B 4-bit (no Romanian), MADLAD-400 7B CTranslate2 int8, and Gemma 4 31B 4-bit
    (`google/gemma-4-31B-it-qat-w4a16-ct`) under vLLM through `engines/llmmt.py`.
  - Jobs: L→en from the FLEURS text, en→L, and L→en from Whisper's output (what a live room translates).
- **Live** (`live.sh`, `e2e_client.mjs`, `analyze_live.sh`, `round_live.py`): the whole stack serving
  en, de, ru and ro, each clip streamed in real time, as `../2026-10-unseen`. The client sends
  `&context=1`. Three configurations (`configs/`):

  | | de, ru out of English | de, ru into English | ro both ways | German turns |
  |---|---|---|---|---|
  | **C1** (PR #74 as it is) | Gemma | Hy-MT2 | MADLAD | default |
  | **C2** (swapped) | Hy-MT2 | Gemma | Gemma | default |
  | **C3** (C1 + long German turns) | Gemma | Hy-MT2 | MADLAD | `LONG_TURNS` |

  The default turn is a 700 ms pause, cut at 9 s. `LONG_TURNS` (`server/stack_config.py`) is a 900 ms
  pause (500 ms after 8 s), cut at 15 s, with at least 2.5 s of speech.
- **Grading** (`grade.py`, as `../2026-10-language-short-check`): gemini-pro-latest, blind, all systems
  side by side, one call per direction and set, against the FLEURS text in the target language. Scores
  0–100; critical errors counted.
- **Hardware:** one RTX PRO 6000 Blackwell 96 GB pod (RunPod US-MD-1) with the stack image
  `2026.10.09.2`, Gemma at `--gpu-memory-utilization 0.40` beside the stack.

## Results

**Recognition, 40 sentences per language** (CER / WER %; Romanian diacritics lost in brackets)

| Recogniser | German | Russian | Romanian |
|---|---|---|---|
| Whisper large-v3 (stack today) | **1.8 / 4.4** | **2.1 / 5.1** | 3.8 / 11.5 (4.9% lost) |
| Omnilingual 7B | 4.1 / 7.3 | 3.6 / 7.6 | **2.8 / 8.5 (0% lost)** |
| Omnilingual 300M | 3.8 / 11.5 | 4.9 / 16.6 | 5.5 / 17.0 (0.8% lost) |

The first pod's CPU cap distorted the real-time factors, so they aren't reported.

**Typed translation, 40 sentences per direction** (score, critical errors)

| Direction | Gemma 4 | Hy-MT2 | MADLAD |
|---|---|---|---|
| de→en | **99.2** (0) | 94.2 (1) | 90.8 (1) |
| en→de | **95.0** (0) | 90.8 (2) | 89.2 (1) |
| ru→en | **98.3** (0) | 93.3 (3) | 92.5 (2) |
| en→ru | **96.7** (1) | 87.5 (3) | 81.7 (2) |
| ro→en | **95.8** (1) | – | 94.2 (3) |
| en→ro | **84.2** (0) | – | 81.7 (1) |
| de→en from Whisper's output | **87.5** (5) | 85.0 (6) | 83.3 (5) |
| ru→en from Whisper's output | **94.2** (3) | 84.2 (6) | 85.0 (4) |
| ro→en from Whisper's output | **76.7** (11) | – | 75.0 (12) |

Romanian diacritics in en→ro (counts over 40 sentences):

| | ș/ț (comma below) | ş/ţ (cedilla) | ă/â/î |
|---|---|---|---|
| MADLAD | 97 | 4 | 154 |
| Gemma | 82 | 0 | 135 |
| FLEURS reference | 96 | 0 | 158 |

**Live, sets a + b with regular pauses, 40 sentences per direction** (score, critical errors; speech
ends → first audio, median of the two sets' medians)

| Direction | C1 | Quality C1 | C2 | Quality C2 | First audio C1 / C2 (s) |
|---|---|---|---|---|---|
| en→de | Gemma | 70.8 (9) | Hy-MT2 | 72.5 (9) | 1.56 / 1.61 |
| de→en | Hy-MT2 | 84.2 (5) | Gemma | 84.2 (5) | 1.42 / 1.46 |
| en→ru | Gemma | **71.7** (8) | Hy-MT2 | 67.5 (7) | **1.14** / 1.41 |
| ru→en | Hy-MT2 | 81.7 (8) | Gemma | **85.8** (7) | 1.40 / 1.44 |
| en→ro | MADLAD | 65.8 (9) | Gemma | 65.0 (9) | 0.96 / 1.18 |
| ro→en | MADLAD | 67.5 (13) | Gemma | 67.5 (13) | 1.27 / 1.16 |

The C1 and C2 outputs differ in 36–39 of 40 sentences in every direction, so the tied scores aren't
copies.

**German turns, de→en live, set a** (score, critical errors; speech ends → first audio p50 / p90)

| Pauses | C1 (default turns) | C3 (long turns) | First audio C1 → C3 (s) |
|---|---|---|---|
| Regular | 85.0 (3) | **93.3** (1) | 1.41 / 1.60 → 1.93 / 2.14 |
| Irregular | 83.3 (2) | **91.7** (0) | 1.40 / 1.63 → 1.99 / **9.90** |

## Findings

1. **Gemma 4 is the best translator in all six directions on typed text.** It leads Hy-MT2 by 4–9
   points and MADLAD by 2–15 (1.6 on ro→en), with the fewest critical errors. From Whisper's output into English it
   still leads, by 10 points on Russian.
2. **Live, the translator matters much less.** C1 and C2 are within 0–4 points in every direction,
   about one grading call's noise. Gemma costs no time: first audio is 1.0–1.6 s in both, and into
   Russian Gemma is 0.27 s quicker than Hy-MT2.
3. **Live scores (65–86) sit well below typed ones (82–99).** Recognition explains part of the gap
   (2–10% CER live). The rest is likely how the stack's turns merge or split sentences, which this
   round doesn't separate.
4. **Long turns help German by about 8 points**, with fewer critical errors. That fits German putting
   the verb last. They cost about 0.5 s at the median, but with irregular pauses the slowest tenth
   waited almost 10 s.
5. **Romanian:** Gemma and MADLAD tie live. The Omnilingual 7B recognises Romanian better than Whisper
   (2.8% CER against 3.8%) and keeps every diacritic, where Whisper drops 4.9%. On typed text Gemma
   writes fewer diacritics than the reference (82 of 96 ș/ț); MADLAD keeps them but mixes in 4
   cedillas.

**Recommendations:**
- Keep PR #74 as it is: Gemma out of English for German and Russian. Russian into English on Gemma is
  a candidate follow-up (+4 live, +10 from Whisper's output); German into English is a tie.
- German long turns are worth having, but not with a 15 s cap. Retest with a lower cap before
  switching them on.
- Romanian: no case for changing the translator. If anything changes, it should be recognition, to the
  Omnilingual 7B.

## Limits

- One grading call per direction and set; a few points either way is noise.
- 40 read FLEURS sentences per language, joined with artificial pauses, one reader per sentence.
- Translation is one sentence per call on typed text; live uses the stack's own context.
- The German turn test is one set (20 sentences) per pause pattern.
- Gemma ran 4-bit under vLLM on the same GPU as the stack; a separate GPU may change latency.

## History

- The first pod (A100 SXM 80 GB) was terminated by RunPod after about 2.2 h, before translation
  started, and its disk was lost. Its CPU was capped at about 13.6 cores, which made the MADLAD
  conversion take over 75 min.
- On the second pod, the first pass of live runs was lost: `live.sh` started the stack with
  `HF_HUB_OFFLINE=1`, the stack pins a faster-whisper revision that wasn't cached, and it died at load.
  `live.sh` now stops if the stack dies before it is ready.

## Files

- Scripts: `build_clips.py`, `asr.py`, `score_asr.py`, `mt.py`, `round_mt.py`, `grade.py`, `live.sh`,
  `e2e_client.mjs`, `analyze_live.sh`, `round_live.py`, `setup_pod.sh`, `orchestrate.sh` (the phases on the pod),
  `configs/C1–C3.toml`.
- `results.json`: every table above.
- `results/`:
  - `asr/`, `asr_scores.json`: recognition outputs and scores.
  - `mt/`, `mt_grade_jobs.json`, `mt_grades.json`, `mt_scores.json`: typed translation.
  - `e2e_<config>_<set>_<pauses>/`: each live run's raw events (`out/runs/`), latency and per-sentence
    output (`out/`) and the stack's log.
  - `live_grade_jobs.json`, `live_grades.json`, `live_scores.json`, `german_grade_jobs.json`,
    `german_grades.json`: live grading.
  - `clips_*/`: the clip texts and timings (no audio), `ids.json`.

## Reproduce

On a RunPod pod with the stack image `2026.10.09.2` and a GPU of at least 80 GB:

1. `BRANCH=<branch> bash setup_pod.sh`: system packages, the repo at `/workspace/tos` with its models,
   and Gemma's vLLM venv at `/root/vllm`. Copy this folder to `/workspace/drr`.
2. `python3 -I build_clips.py work ../2026-10-real-voices ""`
3. Recognition: `STACK=/workspace/tos python3 -I asr.py work whisper` (and `omniASR_LLM_300M`,
   `omniASR_LLM_7B`), then `python3 -I score_asr.py work`.
4. `bash orchestrate.sh`: starts Gemma, then typed translation and every live run, about 2.5 h on an
   RTX PRO 6000.
5. `bash analyze_live.sh work`, then `python3 -I round_mt.py jobs work` and
   `python3 -I round_live.py jobs work`.
6. With `GEMINI_API_KEY` set: `python3 -I grade.py work/mt_grade_jobs.json work/mt_grades.json`, and the
   same for `live_` and `german_`.
7. `python3 -I round_mt.py table work; python3 -I round_live.py table work`
