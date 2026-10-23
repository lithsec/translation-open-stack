# Lao and Khmer into English: the cloud translator on today's recognition, and the data for fine-tuning

Two questions, October 2026:

1. With today's recognition (Omnilingual 7B, the stack's turn rules), how much does a cloud
   translator recover for Lao and Khmer speakers, compared with the stack's own translators?
2. Is there enough openly licensed Lao and Khmer speech to fine-tune Omnilingual, and what would a
   first experiment look like?

## 1. The same recognition, three translators

**Input.** The Lao → English and Khmer → English runs of [`../2026-10-full-stack`](../2026-10-full-stack/)
(both clip sets: the unseen FLEURS clips and set b, 20 read sentences each, regular pauses). Each
utterance the stack heard (its `inputTranscript`, exactly as recognised by Omnilingual 7B) was translated
again, with the previous two utterances as context, the way Talk's Omnilingual route passes what was just
said. The translations were mapped to the read sentences exactly as the stack's own live output was (the
run's sentence rows), so all three systems see the same pieces of the same recognition.

**Translators**
- **sol @low:** gpt-5.6-sol on our Azure AI Foundry deployment, `reasoning_effort: low`.
- **Gemma 4 31B:** `google/gemma-4-31b-it` on OpenRouter, zero data retention required, restricted to
  named US hosts (served by CoreWeave), reasoning off.
- **The stack's own translator,** from the full-stack run: MiLMMT-46 12B for Lao, Hy-MT2 7B for Khmer.

Every system got the translator shootout's prompt (it says the text comes from live speech and may contain
recognition errors). Grading: [`../2026-10-unseen/grade.py`](../2026-10-unseen/grade.py), gemini-pro-latest,
blind and side by side, one call per clip set and direction, against the English reference; "said"
leaves out the sentences whose recording does not match its text (the witness check of the full-stack
round). Grades move about 5 points between rounds, so compare within this table only; the stack's numbers
here differ slightly from the full-stack table for that reason.

**Results** (mean of the two clip sets; critical errors summed over both; 40 sentences per row)

| Direction | Translator | Quality, written | Quality, what was said | Critical errors | Latency p50 / p90 |
|---|---|---|---|---|---|
| Khmer → English | **sol @low** | **75.8** | **77.5** | **3** | 1.8 / 3.1 s |
| | Gemma 4 31B | 66.7 | 69.3 | 4 | 1.5 / 3.9 s |
| | Hy-MT2 7B (stack) | 57.5 | 60.5 | 9 | – |
| Lao → English | **sol @low** | **64.2** | **65.8** | **11** | 1.7 / 4.1 s |
| | Gemma 4 31B | 49.1 | 48.2 | 16 | 1.2 / 2.4 s |
| | MiLMMT 12B (stack) | 49.1 | 49.1 | 18 | – |

Per clip set (written / said): Khmer sol 73.3 / 77.8 and 78.3 / 77.2; Lao sol 60.0 / 61.4 and
68.3 / 70.2. Recognition on the same runs (from the full-stack round, characters wrong against what was
said): Lao 19.1% and 12.4%, Khmer 8.3% and 9.5%. Latency is the translation call alone (OpenRouter's or
Foundry's round trip), not end to end.

**What it shows**
- **The cloud translator recovers a lot from the 7B's transcripts:** +17 points over the stack's own
  translator for Khmer, +17 for Lao, with far fewer critical errors. Khmer → English with sol is now
  close to the other languages (77.5).
- **Gemma 4 sits between them for Khmer** (69.3) **but does not help Lao** (48.2, the same as MiLMMT):
  given clean Lao text MiLMMT and Gemma score 94–98 ([`../2026-10-ht-lo-translators`](../2026-10-ht-lo-translators/)),
  so on live Lao the limit is recognition, and only the strongest model repairs part of it.
- **Lao stays the weakest direction even with sol (65.8):** about one character in six is still misheard.

## 2. Lao and Khmer speech data for fine-tuning Omnilingual

Desk research, 23 October 2026; nothing large was downloaded. Hours and licences as stated by each
source; check again before training. "Commercial" means usable for a commercial product (Lithos Talk).

| Dataset | Language | Hours | Speakers | Kind | Licence | Commercial? | Access |
|---|---|---|---|---|---|---|---|
| FLEURS | lo, km | ~10–12 each (train) | many | read Wikipedia sentences | CC BY 4.0 | yes | open (Hugging Face) |
| Common Voice | lo, km | small (both languages open for contribution; Khmer has a 750-sentence target, Lao 5,000) | crowd | read | CC0 | yes | open (Mozilla Data Collective) |
| OpenSLR 42 (Google) | km | ~4 | few | read, studio quality (made for TTS) | CC BY-SA 4.0 | share-alike | open |
| Digital Divide Data Khmer ASR Cultural | km | 134.6 | 8 (4 f, 4 m) | read, cultural topics, 16 kHz | CC BY-SA 4.0 | share-alike | open (Hugging Face) |
| seanghay/km-speech-corpus | km | ~10 | unclear | mixed | check card | unclear | open (Hugging Face) |
| YODAS2 (YouTube, uploader-licensed) | lo, km | one shard each, hours not checked | many | broadcast/vlog, captions of mixed quality | CC BY 3.0 (per uploader) | yes in principle, provenance risk | open (Hugging Face) |
| IARPA Babel Lao (LDC2017S08) | lo | ~207 | many (Vientiane) | conversational and scripted **telephone** | LDC licence | for-profit licence available, paid | LDC |
| Shaip Lao | lo | ~500 | – | spontaneous IVR and scripted | commercial terms | yes, paid | vendor |
| MMS / Bible-derived data | lo, km | not checked | few | read scripture | CC BY-NC / restricted | no (non-profit edition only, and only if the source text's terms allow) | various |
| Omnilingual ASR corpus (Meta) | – | – | – | – | CC BY 4.0 | yes | open; **does not include Lao or Khmer** (checked its 349 language configs) |

**Fine-tuning code.** The omnilingual-asr repository publishes fine-tuning recipes for its CTC and LLM-ASR
models (`workflows/recipes/wav2vec2/asr`, configs `ctc-finetune.yaml` and `llm-finetune.yaml`) and a
data-preparation guide for registering a custom corpus. No LoRA or adapter recipe was found; fine-tuning
is full-parameter. The paper reports about one hour on 32 GPUs for its multilingual CTC fine-tune at 300M;
a single-language fine-tune on tens to a hundred hours is far smaller. How many hours of Lao and Khmer
went into Omnilingual's own training is not stated in what we found.

**Recommendation**
- **Khmer: a first experiment is viable now.** Fine-tune the 300M LLM-ASR card (the stack's base card) on
  the Digital Divide Data corpus (134.6 h) plus FLEURS train, leaving out every FLEURS sentence our eval
  clips use. One 80 GB GPU for a few hours (roughly $5–15 on RunPod). Measure CER on our unseen and set-b
  Khmer clips through the live stack, then Khmer → English end to end, against the 7B (8–10% CER today).
  Two open questions before shipping it in Talk: the corpus is CC BY-SA (whether a model trained on
  share-alike data must itself be share-alike is not settled law; ask counsel), and it is read speech by
  8 speakers, so test on conversational audio too.
- **Lao: open data alone is too thin.** FLEURS and Common Voice give perhaps 10–20 hours. A meaningful
  fine-tune needs the LDC Babel Lao pack (207 h, paid for-profit licence; telephone audio, which also helps
  phones) or purchased data. Until then, the cloud route (sol) is the best Lao → English we have.
- **7B fine-tuning** needs multi-GPU full fine-tuning (no LoRA recipe) and is not a first step; start with
  300M and compare with the 7B.

## Files

- `run.py` maps the stack's heard utterances to sentences, translates them (sol, Gemma 4), builds the
  grading jobs and the table.
- `results.json`: per direction and translator, quality per clip set against both references, critical
  errors and translation latency.

The recognised text and the translations are not committed (FLEURS text only); they are rebuilt from the
full-stack run logs.
