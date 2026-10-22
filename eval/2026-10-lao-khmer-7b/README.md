# Lao and Khmer on Omnilingual 7B, with longer turns (October 2026)

What changed in the stack (`languages.toml` `[lo]`/`[km]`, `OMNI_LARGE=1`):

- **Hearing:** Omnilingual's 7B card (`omni = "large"`) instead of the 300M,
  loaded only where there is room (`profiles/cuda-80gb.toml`).
- **Turns:** 700 ms of pause ends a turn at any length, and a turn without one
  is cut at 15 s. Before, run.sh's 900 ms dropped to a 280 ms gap after 5 s,
  with a forced cut at 12 s.
- **Repetition guard** on every Omnilingual text (moved from `services/omni-stt`).

## Method

One clip per language: 20 FLEURS sentences (CC BY 4.0) read one after the
other with 1.0–2.0 s pauses (Lao 273 s, Khmer 260 s). Each was streamed at real
time into one room (`/translate?src=lo&lang=en`) on one GPU, as the apps
connect. Character error is on the whole live transcript, against the FLEURS
text. Quality is one blind side-by-side call (Gemini Pro, the usual prompt:
0–3 per sentence against the English reference, plus critical errors) over
all three runs, as a % of the maximum. Latency is per sentence: from the end of
its speech to the end of its last translated audio, and from its start to its
first translated audio.

| Run | Hardware | Hearing | Turns |
|---|---|---|---|
| before | A40 48 GB, image 2026.10.09.2 | 300M | 900 ms, 280 ms after 5 s, cut at 12 s |
| 300M, new turns | A100 80 GB, this branch, `OMNI_LARGE=0` | 300M | 700 ms, cut at 15 s |
| 7B, new turns | A100 80 GB, this branch, `OMNI_LARGE=1` | 7B | 700 ms, cut at 15 s |

## Results

| Lao → English | before | 300M, new turns | **7B, new turns** |
|---|---|---|---|
| Characters wrong (live) | 19.6% | 19.3% | **15.9%** |
| Translation quality | 15% | 22% | **47%** |
| Critical errors (of 20) | 15 | 13 | **9** |
| Speech end → last audio, p50 / p90 | 2.8 / 4.2 s | 3.6 / 4.6 s | 4.0 / 5.3 s |
| Speech start → first audio, p50 | 8.4 s | 11.4 s | 11.1 s |

| Khmer → English | before | 300M, new turns | **7B, new turns** |
|---|---|---|---|
| Characters wrong (live) | 36.3% | 35.5% | **32.0%** |
| Translation quality | 23% | 30% | **47%** |
| Critical errors (of 20) | 5 | 5 | **3** |
| Speech end → last audio, p50 / p90 | 3.0 / 3.9 s | 3.0 / 4.6 s | 3.5 / 4.6 s |
| Speech start → first audio, p50 | 10.4 s | 15.9 s | 15.3 s |

- **The 7B is the gain:** about +25 points into English for Lao and +17 for
  Khmer over the same turns on the 300M. One sentence at a time (no live
  cutting) it hears Lao with 8.5% of characters wrong against the 300M's
  15.6%, and Khmer with 12.6% against 14.1%.
- **The longer turns help a little on their own** (+7 points both ways) and
  cost latency: the translation now arrives with the whole sentence, so first
  audio comes about 3 s (Lao) and 5 s (Khmer) later, and the last words about
  0.5–1 s later.
- **The repetition guard fired 5 times on the 7B** (2 loops cut back, 3
  dropped, all on fragments under a second) and once on the 300M.
- **Khmer stays hard:** this clip's recordings are at very different levels
  and the live error is twice the per-sentence one
  ([`2026-10-omni-sizes`](../2026-10-omni-sizes/README.md), "levelled").
- **Memory:** both cards together took 23.8 GB at load (the 300M alone 3.3 GB
  in the second run), so the 7B adds about 20 GB; the full stack with it came
  to about 44 GB on the card, plus VoxCPM2.

One clip, one grader call per direction: treat differences under ~5 points as
noise. The before run used the full language list on another card; the two
new runs used `LANGS=en,km,lo` on the same pod.
