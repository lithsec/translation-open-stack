# Evaluations

| Folder | Contents |
|---|---|
| `2026-09-model-eval/` | Translation, recognition and voice evaluations behind [`docs/dev/model-evaluation.md`](../docs/dev/model-evaluation.md). See its README. |
| `2026-09-commercial-refs/` | Metadata (text, engine, timing, recognition error, pitch) and picks for candidate reference voices. No audio is stored. |
| `2026-10-voice-rate-compact/` | Voice speaking rate (+0/10/15/20%, measured Azure TTS audio) and a concise interpreter-style prompt, in phrase mode and whole sentences, en→es/pt/fr: backlog behind the speaker, graded with fixed meaning units, listener questions and the 0–100 grade. See [its README](2026-10-voice-rate-compact/README.md). |
| `2026-10-concise-conversational/` | The concise (interpreter-style) prompt and faster voices on spontaneous speech (AMI meeting English, VoxPopuli Spanish and French): meaning units, listener questions, distortion and measured voice backlog. See [its README](2026-10-concise-conversational/README.md). |
| `2026-10-simultaneous-phrases/` | Phrase-by-phrase (simultaneous) translation against whole sentences and Gemini Live Translate: MAI-Transcribe-2-Streaming or Azure standard partials, a per-language commit policy, continuation translation with Gemma 4 or GPT-5.6-sol, latency, blind quality and chunks wrong later, on the unseen clips. See [its README](2026-10-simultaneous-phrases/README.md). |
| `2026-10-mai-streaming-pipelines/` | MAI-Transcribe-2-Streaming in a live pipeline: each final translated as it arrives by sol, Qwen 3.5 122B, Qwen 3.8 2.4T or Gemma 4 31B (OpenRouter, zero retention), against today's Azure standard real-time → sol; recognition, latency, one blind grading round, cost. See [its README](2026-10-mai-streaming-pipelines/README.md). |
| `2026-10-open-stack-e2e/` | The open stack end to end on real read speech (12 directions: latency, recognition, translation), plus Omnilingual 300M vs 7B for Lao/Khmer, English recognisers, Qwen3.5-122B / Hy-MT2-30B / QE pick, and DeepSeek V4-Flash. See its README and section 14 of [`docs/dev/route-findings-2026-10.md`](../docs/dev/route-findings-2026-10.md). |
| `2026-10-es-pt-live-compare/` | Azure speech-to-text with Hy-MT2 7B, Gemma 4 31B or GPT-5.6-sol (Spanish and Portuguese both ways, and out of English), against Gemini Live Translate on the same unseen English audio: blind quality, latency, translation cost per hour. See [its README](2026-10-es-pt-live-compare/README.md). |
| `2026-10-pauses/` | Turn rules per spoken language: an offline sweep of the stack's cutting and a live before/after with blind quality grading. See [its README](2026-10-pauses/README.md). |
| `2026-10-unseen/` | The October pause and sentence work (#36–#39) on unseen FLEURS sentences and irregular pauses: main vs #39, MADLAD for Khmer, a QE pick, Hy-MT2-30B, Portuguese. See [its README](2026-10-unseen/README.md). |
| `2026-10-quiet-after-loud/` | A quiet talker right after a loud one: QuietBoost forgets the loud voice faster across a pause and boosts what the recogniser hears. Offline replay and live on the unseen clips. See [its README](2026-10-quiet-after-loud/README.md). |
| `2026-10-llm-translator-live/` | Gemma 4 31B (Haitian Creole) and MiLMMT-46 12B (Lao) in the live stack through the new `llmmt` engine, against MADLAD-400 7B, on the unseen clips; GPU memory. See [its README](2026-10-llm-translator-live/README.md). |
| `2026-10-ht-lo-translators/` | Haitian Creole and Lao translators on correct text: MADLAD 7B/10B, NLLB-200, TranslateGemma 27B, MiLMMT-46 12B, Gemma 4 31B, Qwen3.5-122B, gpt-oss-120b and sol, graded blind in one round, with speed and memory on an A100. See [its README](2026-10-ht-lo-translators/README.md). |
| `2026-10-translator-shootout-gemma4/` | Addendum to the translator shootout on Azure's transcripts: Gemma 4 31B and 26B-A4B (OpenRouter) beside six of its systems, all graded again in one blind round. See [its README](2026-10-translator-shootout-gemma4/README.md). |
| `2026-10-english-80/` | Out of English: seven of the English clip's 20 recordings don't say what the reference says (grading against what was said instead), and two fixes for pieces cut mid-sentence and abbreviations. Live before/after with blind grading. See [its README](2026-10-english-80/README.md). |
| `2026-10-whisper-vs-azure/` | Recognition on the same unseen clips with one scorer: Whisper large-v3 per sentence and live in the stack, Azure real-time and fast transcription, MAI-Transcribe-2 (en, es, pt, fr, ja). See [its README](2026-10-whisper-vs-azure/README.md). |
| `2026-10-full-stack/` | The whole current stack live, 14 directions, one at a time, on the unseen clips and a second fresh set: best accuracy per direction, Hy-MT2 vs Gemma 4 (4-bit, `llmmt`) out of English, and #38's turn rules re-checked. See [its README](2026-10-full-stack/README.md). |
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
