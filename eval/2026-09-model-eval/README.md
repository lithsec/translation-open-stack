# Model evaluation, 26–27 September 2026

The raw material behind [`docs/dev/model-evaluation.md`](../../docs/dev/model-evaluation.md).

| Folder | Contents |
|---|---|
| `sentences/` | `en.json` (the 24 English test sentences) and `src_<lang>.json` (native versions written by Gemini 2.5 Pro). **`src_uk.json` is known bad**: it came back in broken English, so Ukrainian→English results are invalid. |
| `results/` | Blind grades per round (per sentence: score 0–3, critical flag, note). `asr/` holds each recogniser's transcripts and character error rates. |
| `scripts/` | What produced them: translation runs (`mt2.py`, `mt3.py`, `nllb.py`, `hymt_q.py`, `mt_lo.py`, `tg.py`), recognition (`asr_one.py`, `asr_eval.py`, `asr_lo.py`), voices (`voxcpm_*.py`, `baseline_tts.py`), Gemini Live and stack clients (`lat.mjs`, `stack.mjs`, `asr_capture.mjs`, `e2e.py`) and the graders (`judge*.py`, `vertex.py`). |

| Results file | Round |
|---|---|
| `round1_text_vs_gemini.json` | Translators on typed text; Gemini Live from audio (not a fair comparison, superseded by round 2) |
| `round2_stack_asr_vs_gemini.json` | Translators on what the stack's own recogniser heard; Gemini on the same audio |
| `round3_real_server_vs_gemini.json` | The recommended stack through the real server against Gemini Live |
| `round4_translators_incl_nllb.json` | MADLAD 3B/7B, Hy-MT2, NLLB-200 on typed text |
| `round5_hymt_precision.json` | Hy-MT2 4-bit vs FP8 vs bf16 |
| `round6_lao.json` | Lao, both directions, with Gemini Live |
| `round7_translategemma.json` | TranslateGemma 4B and 12B against Hy-MT2 and MADLAD 7B, 19 directions |
| `round7_translategemma_lao.json` | Lao with TranslateGemma, MADLAD 7B, NLLB and Gemini Live |

The scripts were run on a RunPod pod and a Mac, with paths for that setup
(`/workspace/...` on the pod); adjust them before rerunning. The graders call
Vertex AI (Gemini 2.5 Pro) with `gcloud` credentials in the project named by
`GOOGLE_CLOUD_PROJECT` (or `VERTEX_PROJECT`); `lat.mjs` also needs `TOK` set to
an access token. See [`../README.md`](../README.md) for data sources (Gemini-written
sentences, Gemini as judge and baseline, FLEURS downloaded at run time).
