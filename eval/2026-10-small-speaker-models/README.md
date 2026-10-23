# Small speaker models for in-browser owner checks, October 2026

Live Translation's open-mic phones need an "is this the phone's owner?" check (see
[`../2026-10-switch-detection`](../2026-10-switch-detection/), phone bleed). On a Pi setup the
check is best done in each phone's browser, so the model has to be small. This round looks for a
speaker-embedding model of a few MB that keeps the owner/other separation of the 22 M-parameter
ECAPA used before.

**Status: complete for the recommended model.** The first pod stopped mid-run (account credit),
so the bleed test, a larger English trial set and browser timing ran in a second pass on new
clips, with the ECAPA baseline re-run on the same clips as a control.

## Candidates

All ungated on Hugging Face; licences from each model card (checked 23 October 2026).

| Model | Source | Licence | Trained on | Params | fp32 | int8 |
|---|---|---|---|---|---|---|
| ECAPA-TDNN (baseline) | `speechbrain/spkrec-ecapa-voxceleb` | Apache-2.0 | VoxCeleb1+2 | 20.8 M | 83.4 MB | 21.4 MB (dynamic) |
| CAM++ | `Wespeaker/wespeaker-voxceleb-campplus` | Apache-2.0 | VoxCeleb2 dev | 7.2 M | 29.3 MB | 8.4 MB (dynamic) |
| ECAPA-TDNN 512 | `Wespeaker/wespeaker-voxceleb-ecapa-tdnn512` | Apache-2.0 | VoxCeleb2 dev | 6.2 M | 24.9 MB | 6.4 MB (dynamic) |
| ResNet34 | `Wespeaker/wespeaker-voxceleb-resnet34` | Apache-2.0 | VoxCeleb2 dev | 6.6 M | 26.5 MB | **6.8 MB (static QDQ)** |
| ResNet34, CN-Celeb | `Wespeaker/wespeaker-cnceleb-resnet34` | Apache-2.0 | CN-Celeb1+2 (Mandarin) | 6.6 M | 26.5 MB | **6.8 MB (static QDQ)** |

- **Not tested:** TitaNet-Small. NVIDIA doesn't publish it on Hugging Face; the copies there are
  third-party repacks with an undocumented front end.
- **Training languages:** VoxCeleb is celebrity interviews from YouTube, mostly English with many
  nationalities and accents. CN-Celeb is Mandarin. No model was trained on Haitian Creole, Lao or
  Khmer speech specifically.
- **Front ends:** the WeSpeaker models take 80-bin Kaldi fbank minus its time mean (25/10 ms, no
  dither), which is simple to compute in JavaScript. The speechbrain ECAPA uses its own Fbank plus
  sentence mean normalisation.

## int8 conversion

Every fp32 ONNX model was quantised two ways with onnxruntime, then compared with its own fp32
version on 20 FLEURS recordings (en/es/fr/ja; cosine of the embeddings):

- **Dynamic** (weights int8, `ConvInteger`/`MatMulInteger`): about 4× smaller.
- **Static QDQ**: per-channel weights, activations calibrated on 200 windows from FLEURS files
  never used in a test.

| Model | Dynamic int8: cosine min / mean | Static QDQ: cosine min / mean |
|---|---|---|
| ECAPA (speechbrain) | 0.992 / 0.996 | failed (pooling produced non-finite ranges) |
| CAM++ | 0.950 / 0.970 | 0.50 / 0.73 (broken) |
| ECAPA 512 | 0.957 / 0.978 | 0.03 / 0.26 (broken) |
| **ResNet34** | 0.989 / 0.993 | **0.985 / 0.993** |
| **ResNet34, CN-Celeb** | 0.980 / 0.989 | **0.980 / 0.988** |

Only the two ResNet34s pass the 0.98 bar in a form that is also fast. CAM++ and ECAPA-512 lose too
much with full static quantisation, probably in their attention and pooling layers. Leaving those
layers in float might fix it, but wasn't tried.

## CPU time per window (onnxruntime, 1 thread, x86 server core)

Network only; the fbank front end adds about 1 ms. The pod was busy with other jobs during these
measurements, so treat them as upper bounds and compare only within this table.

| Model | fp32, 1 s / 1.5 s | dynamic int8, 1 s / 1.5 s | static QDQ, 1 s / 1.5 s |
|---|---|---|---|
| ECAPA (speechbrain) | 44.6 / 63.5 ms | 102.5 / 148.9 ms | – |
| CAM++ | 13.1 / 17.2 ms | 39.5 / 57.9 ms | (4.9 / 7.1 ms, broken) |
| ECAPA 512 | 8.9 / 13.1 ms | 25.2 / 38.4 ms | (4.3 / 4.7 ms, broken) |
| ResNet34 | 28.8 / 46.0 ms | 127.8 / 199.8 ms | **8.2 / 14.3 ms** |
| ResNet34, CN-Celeb | 32.1 / 42.3 ms | 129.1 / 195.0 ms | **8.0 / 11.9 ms** |

- **Dynamic int8 is slower than fp32** on this CPU: onnxruntime's integer convolution kernels
  aren't optimised for it. Use it only to cut the download size.
- **Static QDQ ResNet34 is 3–4× faster than fp32.** At one 1.5 s window every 0.5 s, that's about
  3% of one core.
- **Browser timing** is in [its own section](#browser-onnxruntime-web-wasm) below.

## Owner versus other, per language (EER, 3 s against 3 s)

Equal error rate in %, lower is better.

| Set | ECAPA | CAM++ | CAM++ int8 | ECAPA512 | ECAPA512 int8 | ResNet34 | ResNet34 QDQ | CN ResNet34 QDQ |
|---|---|---|---|---|---|---|---|---|
| **LibriSpeech en** (16 speakers) | 0.8 | 1.3 | 1.3 | 2.5 | 2.1 | **0.5** | 3.3 | 2.1 |
| **CMU ht** (12 speakers) | 9.8 | 9.8 | 10.1 | 11.3 | 11.1 | **7.8** | 8.3 | 8.0 |
| FLEURS en | 25.8 | 22.6 | 22.6 | 25.5 | 21.9 | 22.7 | 22.6 | 19.3 |
| FLEURS es | 21.2 | 18.9 | 18.9 | 18.9 | 18.9 | 21.6 | 19.6 | 16.2 |
| FLEURS fr | 26.6 | 25.7 | 26.7 | 26.1 | 25.7 | 26.3 | 26.3 | 26.6 |
| FLEURS pt | 25.9 | 24.2 | 23.9 | 24.3 | 23.7 | 26.3 | 25.9 | 20.8 |
| FLEURS ja | 25.0 | 27.5 | 27.0 | 25.3 | 25.0 | 24.9 | 22.5 | 25.0 |
| FLEURS lo | 25.7 | 21.7 | 21.1 | 18.5 | 20.5 | 21.3 | 21.6 | 20.7 |
| FLEURS km | 34.7 | 32.5 | 30.3 | 27.5 | 29.9 | 29.7 | 28.0 | 27.5 |

How to read it:

- **LibriSpeech and CMU have speaker ids**, so their trials are real: two different recordings of
  one speaker against different speakers (same gender for LibriSpeech). These two rows are the
  trustworthy ones.
  - English owner checks are easy for every model (under 4%).
  - Haitian Creole is harder (8–11%): CMU's recordings are short and noisier.
  - ResNet34 is best on both in fp32. Its QDQ int8 version keeps Haitian Creole (8.3%) but loses
    ground on English (0.5 → 3.3%, from 240 target trials).
- **FLEURS has no speaker ids.** Its trials compare the two halves of one recording against
  recordings of the same listed gender. FLEURS uses few readers per language, so many
  "different speaker" trials are really the same reader. That inflates every model's FLEURS EER
  to about 20–30%. These rows only say that no model falls apart on Spanish, French, Portuguese,
  Japanese, Lao or Khmer relative to English; they are not absolute error rates.
- **Enrolling in one language and speaking another can't be tested here:** FLEURS has no bilingual
  speakers.

## Bleed test (phone hearing a neighbour or the PA)

The protocol of [`../2026-10-switch-detection`](../2026-10-switch-detection/) (phone bleed):
- **Clips:** 7 owners (4 LibriSpeech, 3 CMU Haitian) × 5 conditions × normal/quiet owner, giving
  70 clips.
- **Windows:** 1.5 s windows every 0.25 s, with a 0.75 s hold-back.
- **Thresholds:** chosen leave-one-owner-out, on wider grids than #58 (cosine 0.05–0.5, level
  3–12 dB) because #58's choices sat at the grid edges.
- **Interferers:** these clips use different FLEURS interferers and PA renderings than #58, so
  **ECAPA was re-run on the same clips** as the control. #58's numbers aren't directly comparable.

| Method | Owner words lost, normal / quiet owner | Bleed accepted, normal / quiet owner |
|---|---|---|
| (a) level gate only | 6.0% / 8.3% | 28.5% / 45.1% |
| **ECAPA fp32** (b) voice, 10 s enrolment | 11.2% / 18.1% | 11.1% / 7.3% |
| ECAPA fp32 (b) voice, 5 s | 10.3% / 16.7% | 12.0% / 8.7% |
| ECAPA fp32 (b) voice, 3 s | 11.7% / 18.8% | 11.6% / 8.3% |
| **ECAPA fp32** (c) level + voice, 10 s | 8.9% / 14.5% | 7.8% / 5.9% |
| ECAPA fp32 (c) level + voice, 5 s | 8.7% / 13.4% | 8.1% / 6.7% |
| ECAPA fp32 (c) level + voice, 3 s | 10.0% / 15.7% | 7.8% / 6.2% |
| **ResNet34 QDQ int8** (b) voice, 10 s | 7.7% / 15.9% | 15.4% / 9.4% |
| ResNet34 QDQ int8 (b) voice, 5 s | 8.5% / 17.3% | 14.7% / 8.7% |
| ResNet34 QDQ int8 (b) voice, 3 s | 10.0% / 19.4% | 15.4% / 9.1% |
| **ResNet34 QDQ int8** (c) level + voice, 10 s | 8.5% / 14.1% | 8.9% / 7.0% |
| ResNet34 QDQ int8 (c) level + voice, 5 s | 8.9% / 15.0% | 8.7% / 6.7% |
| ResNet34 QDQ int8 (c) level + voice, 3 s | 8.2% / 14.7% | 9.6% / 7.6% |

- **With the level gate (c), which is the setup to ship,** the 6.8 MB ResNet34 is within about 1
  point of ECAPA on both measures: owner loss 8.5% against 8.9%, bleed 8.9% against 7.8%.
- **Voice alone (b)** trades the other way: the left-out owners' thresholds came out higher for
  ResNet34 (cosine 0.4 against ECAPA's 0.3). It drops less of the owner and lets in more bleed.
- **Enrolment length barely matters** (3, 5 or 10 s within about 1.5 points), as in #58.
- **CAM++ (dynamic int8)** was stopped at 46 of 70 clips to stay within the time budget. It can't
  run in the browser anyway (below), so it has no bleed numbers.

## Larger English trial set (EER)

40 LibriSpeech test-clean speakers × 10 utterances, 3 s against 3 s: 1,800 target and 38,000
same-gender non-target trials.

| Model | EER |
|---|---|
| ResNet34 fp32 | 0.89% |
| CAM++ dynamic int8 | 1.17% |
| ECAPA (speechbrain) fp32 | 1.39% |
| **ResNet34 QDQ int8** | **1.78%** |

The earlier 0.5% → 3.3% drop came from 240 target trials. With 1,800 it's 0.89% → 1.78%: QDQ
roughly doubles ResNet34's English EER, which still leaves it close to ECAPA's.

## Browser (onnxruntime-web WASM)

onnxruntime-web 1.20.1 under Node 20 (WASM, SIMD) on an x86 server core, network only, median of 15
runs. A phone will be slower; this is for comparing the models with each other.

| Model | Size | 1 thread: 1 s / 1.5 s | 4 threads: 1 s / 1.5 s |
|---|---|---|---|
| **ResNet34 QDQ int8** | 6.8 MB | **67.8 / 100.8 ms** | **27.3 / 37.8 ms** |
| ResNet34 fp32 | 26.5 MB | 126.1 / 222.6 ms | 63.5 / 87.5 ms |
| ECAPA (speechbrain) fp32 | 83.4 MB | 120.5 / 168.0 ms | 54.3 / 78.2 ms |
| CAM++ dynamic int8 | 8.4 MB | **doesn't load** | doesn't load |

- **WASM is about 7× slower than native onnxruntime.** At one 1.5 s window every 0.5 s, one
  thread spends about 100 ms per 500 ms, roughly 20% of a core.
- **Multi-threaded WASM** needs cross-origin isolation (COOP/COEP headers) on the phone page.
  Without it, the page is single-threaded.
- **Dynamic int8 models don't run in the browser at all:** onnxruntime-web's WASM build has no
  `ConvInteger` kernel. For the browser, only fp32 or static QDQ models work.

## VoxLingua107 coverage

`speechbrain/lang-id-voxlingua107-ecapa` (Apache-2.0) has **107 languages**. All eight of ours are
in it: en (English), es (Spanish), fr (French), pt (Portuguese), ja (Japanese), ht (Haitian),
lo (Lao), km (Central Khmer). VoxLingua is only for strict mode and shared-mic switching, so it
stays on the central machine, not in the phone's browser.

## Recommendation for the browser model

**WeSpeaker ResNet34 (VoxCeleb), static QDQ int8.**
- **Licence and size:** Apache-2.0, 6.8 MB.
- **Speed:** about 100 ms per 1.5 s window in single-thread WASM.
- **Bleed:** level + voice is within about 1 point of ECAPA on these clips.
- **English EER:** 1.8%, against ECAPA's 1.4%.

Still to do:
- Time it on real phones (Safari on iOS, Chrome on Android).
- Check whether enrolling in one language and speaking another holds up. This data can't test it.
- **The CN-Celeb ResNet34 QDQ** is the same size and speed. It's the alternative if Mandarin or
  other non-European speakers dominate, but it wasn't bleed-tested.
- **CAM++ and ECAPA-512** are out for the browser: their dynamic int8 doesn't load in WASM, and
  their static QDQ breaks the embeddings.

## Re-running

On a CPU or GPU pod, from this folder plus `../2026-10-switch-detection`:

```
python3 fetch_data.py /w/data                                        # LibriSpeech, CMU, FLEURS (streamed)
python3 make_ctl.py /w/data/fleurs /w/sw                              # interferer pools
python3 ../2026-10-switch-detection/bleed_clips.py /w/data/libri /w/data/cmu /w/sw PA_DIR /w/bclips
python3 vl_feats.py /w/bclips /w/vl                                   # VoxLingua + RMS, shared
python3 export.py /w/data/fleurs export.json && python3 export_static.py /w/data/fleurs export.json export2.json
python3 feats_models.py /w/bclips /w/vl /w/ft sb_ecapa_fp32 resnet34_qdq cn_resnet34_qdq campplus_fp32 ecapa512_fp32 resnet34_fp32
BUF=0.75 python3 ../2026-10-switch-detection/bleed_analyze.py /w/bclips /w/ft/<model> <model>.json
python3 eer.py /w/data eer.json <models>
node bench_web.mjs /w/models resnet34_qdq cn_resnet34_qdq campplus_fp32 ecapa512_fp32   # onnxruntime-web@1.20.1
```

- **PA playback:** `PA_DIR` holds a few Azure TTS renderings of FLEURS sentences, as before.
- **Threshold grids:** the earlier bleed thresholds landed at the edges of their grids (cosine 0.2,
  level 6 dB, language margin −2). The widened grids for the re-run are cosine 0.05–0.5, level
  3–12 dB and margin −4 to 0. They're a one-line change to `bleed_analyze.py`'s `GRIDS`.

## Data

- LibriSpeech test-clean (CC BY 4.0).
- FLEURS (CC BY 4.0).
- CMU Haitian Creole speech (free use with its acknowledgement); scores only.

No audio is in the repository.

## Files

| File | What |
|---|---|
| `fetch_data.py` | Audio for the clips and trials (pod) |
| `make_ctl.py` | FLEURS interferer pools for `bleed_clips.py` |
| `models.py` | One embedding interface for every model and precision |
| `export.py` | fp32 ONNX, dynamic int8, int8-vs-fp32 cosine, CPU timing |
| `export_static.py` | Static QDQ int8, with the same checks |
| `vl_feats.py`, `feats_models.py` | Bleed features per model, in `bleed_analyze.py`'s layout |
| `eer.py` | Per-language owner/other EER |
| `bench_web.mjs` | onnxruntime-web WASM timing (`THREADS=1` or `4`) |
| `bleed_analyze.py` | `../2026-10-switch-detection`'s analyser with widened grids and `METHODS`/`WINS` switches |
| `run_all.sh` | The second pass, end to end, on one pod |
| `results.json` | Model checks, timings, EERs, bleed tables, browser timing, VoxLingua coverage |
