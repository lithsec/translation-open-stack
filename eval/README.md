# Evaluations

| Folder | Contents |
|---|---|
| `2026-09-model-eval/` | Translation, recognition and voice evaluations behind [`docs/dev/model-evaluation.md`](../docs/dev/model-evaluation.md). See its README. |
| `2026-09-commercial-refs/` | Metadata (text, engine, timing, recognition error, pitch) and picks for candidate reference voices. No audio is stored. |
| `2026-10-open-stack-e2e/` | The open stack end to end on real read speech (12 directions: latency, recognition, translation), plus Omnilingual 300M vs 7B for Lao/Khmer, English recognisers, Qwen3.5-122B / Hy-MT2-30B / QE pick, and DeepSeek V4-Flash. See its README and section 14 of [`docs/dev/route-findings-2026-10.md`](../docs/dev/route-findings-2026-10.md). |
| `2026-10-pauses/` | Turn rules per spoken language: an offline sweep of the stack's cutting and a live before/after with blind quality grading. See [its README](2026-10-pauses/README.md). |
| `2026-10-translator-shootout-gemma4/` | Addendum to the translator shootout on Azure's transcripts: Gemma 4 31B and 26B-A4B (OpenRouter) beside six of its systems, all graded again in one blind round. See [its README](2026-10-translator-shootout-gemma4/README.md). |
| `tools/` | The continuous-speech harness: stream a clip at real time to the stack, omni-stt or your own service, and measure first audio, per-piece lag, final lag, pauses, cuts and quality from its event log. See [its README](tools/README.md). |

## Where the data comes from

- **Test sentences** (`2026-09-model-eval/sentences/`) were written with Google Gemini (English originals and the native-language versions).
- **Gemini outputs in the results.** Gemini 2.5 Pro is the blind judge for every graded round, so the grades and notes in `2026-09-model-eval/results/` are Gemini output. Gemini Live translations are also included as a baseline in several rounds.
- **FLEURS** ([google/fleurs](https://huggingface.co/datasets/google/fleurs), CC BY 4.0) test audio is downloaded at run time by `2026-09-model-eval/scripts/new_asr.py`. The audio and transcripts are not stored in this repository; only the resulting error rates are kept (`2026-09-model-eval/results/round8_new_languages/new_asr.json`).

## Running the scripts

The scripts were run on a RunPod GPU pod and a Mac. Model and data paths (for example `/workspace/...`) are hard-coded for that setup; change them before rerunning.

Scripts in `2026-09-model-eval/scripts/` that call Vertex AI (`judge*.py` through `vertex.py`, and `lat.mjs`) need:

| Variable | Used by | Value |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` (or `VERTEX_PROJECT`) | `vertex.py`, `judge*.py`, `lat.mjs` | Your Google Cloud project with Vertex AI enabled |
| `TOK` | `lat.mjs` | An access token, e.g. `TOK=$(gcloud auth print-access-token)` |

The Python graders get their token from `gcloud auth print-access-token`, so run `gcloud auth login` first. `stack.mjs` and `asr_capture.mjs` connect to a local stack server on `ws://localhost:8790` (`PORT` overrides it for `stack.mjs`).
