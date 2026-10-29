# Khmer: fine-tuning Omnilingual 300M on public data

Can the stack's small recogniser (`omniASR_LLM_300M`) catch up with the 7B for Khmer if it is
fine-tuned on openly licensed Khmer speech? This follows the data survey in
[`../2026-10-lao-khmer-cloud-and-data`](../2026-10-lao-khmer-cloud-and-data/).

**Answer: not enough to ship.** The fine-tune roughly halves the error on speech like its training
data (read cultural-topic Khmer, 7.9% → 4.6% CER) but moves our FLEURS clips by only 1–1.5 points,
and stays behind the 7B on every clip. Through the stack's own endpointing it is better than stock
300M on one clip and worse on the other. Khmer stays on the 7B.

## Data

| Corpus | Licence | Used | Hours | Clips |
|---|---|---|---|---|
| Digital Divide Data, Khmer ASR Cultural ([Hugging Face](https://huggingface.co/datasets/Digital-Divide-Data/khmer-speech-dataset)) | CC BY-SA 4.0 | train: 110 of its 653 shards, spread evenly; dev: 400 clips from 3 other shards | 101.2 (train), 0.8 (dev) | 43,975 / 400 |
| FLEURS `km_kh` | CC BY 4.0 | train and dev splits | 7.0 (train), 1.3 (dev) | 1,659 / 324 |

- **The DDD corpus is larger than the survey said.** Its card now lists 727.9 h from 12 speakers
  (5 female, 7 male), 450,396 utterances; the survey's 134.6 h and 8 speakers were an older figure.
  We sampled about 100 h to fit the budget. All 12 speakers appear in the sample.
- **Nothing we evaluate on was trained on.** Every FLEURS sentence id or text used by
  `../2026-10-real-voices`, `../2026-10-unseen` and the full-stack set b was removed from FLEURS train
  and dev (FLEURS test, which those clips come from, was never used).
- **Labels** went through Meta's `text_normalize(text, "khm")` from the omnilingual-asr data-prep
  tools; 26 labels that still held a character the tokenizer lacks were dropped.

## Training

- Recipe: `omnilingual-asr` `workflows.recipes.wav2vec2.asr` (checkout `81f51e2`), omnilingual-asr
  0.1.0, fairseq2 0.6, torch 2.8.0; [`llm-finetune-km-public.yaml`](llm-finetune-km-public.yaml).
- One A100 80 GB: lr 3e-6, ≤120 s of audio per batch × 2 accumulated, bf16, 3,000 steps
  (~1.7 passes over the sample), 76 minutes, 37 GB peak.
- Mixture sampling: `beta_corpus 0.5`, so FLEURS (6% of the hours) is drawn about 3× its share.
- The recipe's own validation (pooled WER) is off: it means little for unspaced Khmer. Every
  500-step checkpoint was scored by `eval_km.py` instead, and **step 2500** was picked on dev CER.

| Step | DDD dev CER | FLEURS dev CER |
|---|---|---|
| 0 (stock 300M) | 7.91 | 12.79 |
| 1000 | 5.75 | 11.93 |
| 1500 | 4.99 | 11.42 |
| 2000 | 4.75 | 11.67 |
| **2500** | **4.55** | **11.35** |
| 3000 | 4.61 | 11.41 |

## Results on our clips

Character error rate (%), lower is better, one sentence at a time (batch 1, as the stack decodes):
- **written**: against FLEURS's text; **said**: against what was said (the witness transcripts of
  `../2026-10-unseen`; the real-voice clip has none).
- Normalisation: NFKC, lower case, letters, **marks** and digits. `judge.py`'s normalisation drops
  Unicode marks, which are Khmer's vowel signs, so it under-counts vowel errors; both are in
  `results.json` (`*_judge`, `*_full`). The judge-normalised numbers reproduce the earlier sizes round
  (stock 300M 14.2, 7B 12.7 on the real-voice clip).

| Clip | Sentences | Stock 300M | **Fine-tuned 300M** | Stock 7B |
|---|---|---|---|---|
| real voices, written | 30 | 13.44 | **11.89** | 11.16 |
| unseen, written / said | 20 | 13.01 / 11.83 | **12.02 / 10.71** | 10.05 / 8.12 |
| set b, written / said | 20 | 12.51 / 9.41 | **11.22 / 8.41** | 8.38 / 5.32 |

**Through the stack's own path** (omni-stt's AudioIn, Silero VAD and Segmenter at 700 ms / 15 s,
each sentence levelled to RMS 2000 as `../2026-10-omni-sizes/endpoint_sweep.py --level 2000`):

| Clip | Stock 300M | Fine-tuned 300M | Stock 7B |
|---|---|---|---|
| real voices, written | 13.92 | **11.36** | 10.34 (9.61 with the repetition guard) |
| unseen, said | 10.13 | 11.12 | **9.06** |

- The fine-tune never loops (at most 15 characters per second of audio, against 18–22 for the stock
  cards), so the repetition guard never fires on it.
- **It does not reach the 7B** anywhere; the gap on set b (8.4 vs 5.3 said) is the biggest.
- **The gain is mostly in-domain.** DDD dev nearly halves; FLEURS dev moves 1.4 points. The corpus is
  read text on cultural topics by 12 voices, while FLEURS is Wikipedia sentences by many voices.

## Licence note

The DDD corpus is **CC BY-SA 4.0**. Whether a model trained on share-alike data must itself be
released share-alike is not settled; ask counsel before shipping weights trained on it in a
commercial product. The non-profit edition is not affected by that question. The weights from this
run are not published here.

## Next, if Khmer recognition needs to move

1. Use far more of the DDD corpus (it has ~7× what we sampled) and train longer; the dev curve was
   still edging down at step 2500.
2. Fine-tune the 7B instead (multi-GPU full fine-tune; no LoRA recipe is published).
3. Add conversational Khmer, which neither corpus has, before judging it on live speech.

## Files

- `prep.py`: builds the Parquet dataset (both corpora, the exclusions, normalisation).
- `eval_km.py`: per-sentence CER on the three clips and dev CER, both normalisations.
- `ep_score.py`: scores `../2026-10-omni-sizes/endpoint_sweep.py` runs on the Khmer clips.
- `llm-finetune-km-public.yaml`: the training config.
- `run_prep_baselines.sh`, `run_train.sh`, `run_endpointed.sh`: the pod scripts, in order.
- `results.json`: every number above, per checkpoint.

Clip audio and transcripts are rebuilt from FLEURS by the earlier rounds' scripts; nothing else is
committed.
