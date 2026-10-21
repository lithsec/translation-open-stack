# Plan: open-weight LLMs with context for Haitian Creole, Lao and Khmer

*Translation Open Stack · research plan, written 2026-10-21. Nothing in this
plan has been run yet; every candidate below is untested unless a result is
quoted with its source.*

The stack translates with Hy-MT2 7B where it has the language and MADLAD-400
7B elsewhere. For speech into English from Haitian Creole (ht), Lao (lo) and
Khmer (km), that route is far behind the cloud LLMs. This plan asks one
question: can an open-weight LLM of 8–12B parameters, given the previous
pieces as context and run on one GPU, close enough of that gap to be worth
shipping? It sets out the candidates, the test, the budget and a stop rule.

## Contents

1. [The problem and the measured gap](#1-the-problem-and-the-measured-gap)
2. [Candidates](#2-candidates)
3. [What "context" means here, and the prompt](#3-what-context-means-here-and-the-prompt)
4. [Why self-hosted weights: no provider filter](#4-why-self-hosted-weights-no-provider-filter)
5. [Evaluation design](#5-evaluation-design)
6. [GPU and latency budget](#6-gpu-and-latency-budget)
7. [Fine-tuning options](#7-fine-tuning-options)
8. [Risks](#8-risks)
9. [Phases and the stop rule](#9-phases-and-the-stop-rule)

## 1. The problem and the measured gap

All figures are from the repository's own October rounds. Grades come from one
blind Gemini grader per round and move 5–10 points between rounds, so compare
only inside one table.

**Haitian Creole into English, real speakers.** In the translator shootout
([eval/2026-10-translator-shootout](../../eval/2026-10-translator-shootout/README.md),
round 1, `real:ht-en`: 30 CMU sentences heard by Omnilingual), the cloud LLMs
scored 90% (Gemini 3.5 Flash) and 93% (GPT-5.6-sol) against 36% for MADLAD,
34% for TranslateGemma 12B and 34% for Azure Translator. Hy-MT2 has no Haitian
Creole. The same round's `syn:ht-en` (short synthetic sentences): LLMs 71–78%,
MADLAD 26%.

**It is mostly the recognition errors.** On the gold text of the same
sentences the open models did much better: Gemma 4 31B 79%, TranslateGemma
27B 76%, NLLB-200 68%; on Omnilingual's transcript they fell to 52%, 42% and
46%, while the LLMs stayed at 87–91%
([route findings, section 2](route-findings-2026-10.md#2-translating-omnilinguals-haitian-creole);
`eval/2026-10-real-voices/text-mt`, run 12). The LLMs repair a misheard
name or word from the sentence around it; the translation models translate
the garble.

**Open reasoning LLMs did not fix it.** Shootout round 2 ran gpt-oss-120b,
gpt-oss-20b and Qwen3.8-27B on the same inputs, one sentence per call, no
context: `real:ht-en` 23–41% against sol's 91% in that round; Lao 3–28% over
its four directions; the best of them tie MADLAD overall (62–64%) and stay
under the stack's route (71%). gpt-oss-120b writes Haitian Creole well from
clean English (`syn:en-ht` 93–97%) but cannot read Omnilingual's transcripts.

**Lao and Khmer.** Round 1, real speakers into English: Lao, MADLAD 28%,
TranslateGemma 27%, Azure Translator 26%, LLMs 53–57%; Khmer, Hy-MT2 59%,
MADLAD 48%, LLMs 64–68%. Those inputs were Azure's transcripts (17.9% and
13.3% of characters wrong), so part of the Lao and Khmer gap is hearing, not
translation. Omnilingual per sentence: Lao 15.7% with the 300M model and
8.4% with the 7B, Khmer 14.2% and 12.6%
([route findings, section 10](route-findings-2026-10.md#10-omnilingual-model-sizes-2026-10-19)).

**Context restored quality for short pieces.** In the continuous Haitian
Creole test ([eval/2026-10-continuous-ht](../../eval/2026-10-continuous-ht/README.md)),
cutting at 200 ms breaths gave 3.8 s pieces and halved the lag, but quality
fell from 2.52 to 2.15–2.21 on the 0–3 scale (7 critical errors). Sending the
previous 2 source pieces and the last translation as context only brought it
back to 2.52, 2.67 and 2.21 (3, 2 and 4 critical errors) with the same or
better lag. That was a cloud LLM; whether an open model benefits the same way
is the thing to find out.

**Cost of the status quo.** The cloud translation step for Haitian Creole into
English is about $0.88 per hour of speech at list price
([eval/2026-10-translation-cost](../../eval/2026-10-translation-cost/README.md)),
and the text leaves the machine. An open model on the stack's GPU costs GPU
time and keeps the text local.

So: the stack is at 26–36% where the cloud LLMs are at 90–93% for Haitian
Creole into English, and roughly 10–30 points behind for Lao and Khmer. The
lead comes from repairing recognition errors from context, which the small
translation models cannot do and the open reasoning LLMs did not do without
context.

## 2. Candidates

Open-weight LLMs that could plausibly read Haitian Creole, Lao or Khmer, with
the two translation models as baselines and Hy-MT2 as the engine to beat.
Licence classes follow [licences.md](../licences.md) (✅ permissive, ⚠️
restricted or attribution, ⛔ non-commercial). The edition column says which
edition of the stack a candidate could serve (`server/stack_config.py`:
`nonprofit` loads everything; `commercial` loads only ✅ and ⚠️ attribution
or share-alike items, and a ⚠️ restricted licence needs a recorded licence
review; ⛔ can never be admitted to commercial). The language claims are what
the model cards say as we understand them and must be re-checked when the
test starts; **none of the LLM rows has been tested with context, and most
have not been tested at all here.**

| Candidate | Sizes to try | Licence | Edition | Claims ht / lo / km? | Status here |
|---|---|---|---|---|---|
| **Hy-MT2 7B** (Tencent), the stack's translator | 7B, 4-bit NF4 | Apache 2.0 at the pinned revision ✅ | both | no / no / yes (36 languages) | Tested: Khmer into English 42–59%; no ht or lo |
| **MADLAD-400** (Google), the stack's fallback | 7B int8 (3B, 10B exist) | Apache 2.0 ✅ | both | yes / yes / yes (400+ languages) | Tested: `real:ht-en` 36%, `real:lo-en` 28%, `real:km-en` 48%; 80.6% on clean Haitian text |
| NLLB-200 (Meta) | 1.3B, 3.3B | CC-BY-NC 4.0 ⛔ | nonprofit only | yes / yes / yes | Tested without context: 46% on Omnilingual's Haitian transcript, 68% on gold; loops, turns names into Bible names |
| Gemma 3 family (Google), or its current successor | 4B, 12B (27B too big for bf16 on 24 GB) | Gemma Terms of Use ⚠️ restricted | both, with a licence review | 140+ languages in pretraining; the three not listed individually | Untested as a plain LLM. TranslateGemma 12B (built on it): 77% clean Haitian text, 34% on transcripts; Gemma 4 31B 52% on transcripts, 79% gold |
| Qwen 3 family (Alibaba) | 8B, 14B, non-thinking | Apache 2.0 ✅ | both | the card's 119-language list includes Haitian Creole, Lao and Khmer, to be confirmed | Qwen3.8-27B with thinking, no context: `real:ht-en` 41%, `real:lo-en` 28%, 2.8 s a sentence |
| gpt-oss-20b (OpenAI) | 20B MXFP4 (~13 GB) | Apache 2.0 ✅ | both | no language list | Tested without context: `real:ht-en` 23%, Lao 1–6%; 0.4 s a sentence on an H100 |
| Llama 3.x (Meta) | 8B | Llama Community License ⚠️ restricted (user cap, attribution) | both, with a licence review | no: eight official languages, none of the three | Untested. Included as a control for "a strong general model with no claim" |
| Aya Expanse (Cohere) | 8B | CC-BY-NC 4.0 ⛔ | nonprofit only | no: 23 languages, none of the three | Untested; low priority |
| Mistral Small 3.x (Mistral) | 24B (4-bit only on 24 GB) | Apache 2.0 ✅ | both | no claim for the three | Untested; low priority; a Foundry-hosted Mistral Large scored 30% on the Haitian transcript |
| Kreyòl-MT (JHU) | 611M | MIT ✅ | both | ht only | Tested: 26% on the transcript, 40% gold; not a fallback |

Reading the table: the only open models with a stated claim to all three
languages are MADLAD, NLLB and (on its card) Qwen 3. Gemma's multilingual
pretraining is the other plausible source of ability, and TranslateGemma's
77% on clean Haitian text says it is there. Llama, Aya and Mistral Small make
no claim and are expected to fail; one of them is kept as a control so that a
"no claim" result is measured rather than assumed. Models above 12B are
outside the GPU budget (section 6) unless quantised, and quantised 24–30B
models have not been shown to beat the smaller ones on these languages.

Where a family has a newer release by the time the test runs, test the newest
dense model of each size that fits; the shootout already used Qwen3.8 and
Gemma 4 for that reason.

## 3. What "context" means here, and the prompt

Context is exactly what the continuous Haitian Creole test sent: **the
previous 2 source pieces and the last translation, as context only.** The
model translates the current piece; the earlier pieces are there to resolve a
cut-off name, a pronoun, a number spoken across a breath, or a misheard word
that the earlier pieces make obvious. Nothing in the context is translated
again.

The prompt is the shootout's LLM prompt with a context block:

```
System: Translate the current {source} piece, transcribed from live speech
(it may contain recognition errors), into natural {target}. The earlier
pieces and the last translation are context only: do not translate them
again, do not add anything they contain that the current piece does not
say. Keep numbers, names and negation exact. Output only the {target}
translation of the current piece.

User:
Earlier pieces (context):
  {piece n-2}
  {piece n-1}
Last translation (context):
  {translation n-1}
Current piece:
  {piece n}
```

Rules for the test:

- The same prompt for every LLM; the translation models (Hy-MT2, MADLAD,
  NLLB) have no prompt and get the current piece alone, as the stack sends
  it today.
- One request per piece, pieces in order, as the live pipeline would make
  them; the context is the model's own earlier output, not the reference.
- Thinking or reasoning off. Qwen3.8-27B spent about 500 tokens a sentence
  thinking and took 2.8 s on an H100 (shootout round 2); that is outside the
  latency budget before any quality question.
- Temperature 0 (greedy), so that runs are comparable; the model cards'
  sampled decoding can be a second pass if greedy loops.
- A control run with no context for every candidate, so the value of context
  is measured per model.

The first piece of a session has no context, and a piece after a refusal or a
timeout is sent with whatever context exists.

## 4. Why self-hosted weights: no provider filter

Cloud LLMs apply a content filter the caller cannot turn off. In the
continuous Haitian Creole test, one piece of a news programme was refused by
the provider's filter when sent with context, and the pipeline now retries
such a piece without context
([eval/2026-10-continuous-ht](../../eval/2026-10-continuous-ht/README.md)).
In the Haitian text round, a Foundry-hosted Mistral Large refused a Bible
verse ([route findings, section 2](route-findings-2026-10.md#2-translating-omnilinguals-haitian-creole)).
In the speech-to-text bake-off, three sentences never came back from Gemini
Flash (`promptFeedback.blockReason: OTHER`)
([eval/2026-10-real-voices](../../eval/2026-10-real-voices/README.md)).

A model whose weights run on the stack's own GPU has no provider in the
loop: there is no request to refuse, no block reason, and no policy that
changes between one release and the next. Whatever the model was trained to
decline is a property of the weights and can be measured once. That matters
for exactly the speech this stack is for: news bulletins, public meetings and
speeches, and religious services, which routinely contain violence, crime,
politics, disaster and scripture. A translator that drops a sentence about
a massacre, an election or a verse is not translating the speech. The test
in section 5 includes such material on purpose, and counts a refusal or a
silent omission as a score of 0 for that piece, the same for every system.

Self-hosting also keeps the text on the machine, which is the stack's reason
to exist; see the privacy notes in
[route findings, section 4](route-findings-2026-10.md#4-privacy-what-each-service-keeps).

## 5. Evaluation design

**Clips.** Continuous broadcast speech, because that is where short pieces
and context matter and where the measured gap is widest:

- Voice of America programmes in Haitian Creole, Lao and Khmer, fetched with
  `yt-dlp` from VOA's own channels. VOA programmes are US-government works in
  the public domain, as the continuous Haitian Creole test already uses. Five
  minutes per language per clip, a single studio presenter first; a second
  clip per language with interviews or field reports if the first is passed.
  Choose bulletins that contain names, numbers, dates and at least one
  violent or political story (section 4).
- The real-voice read sentences already in the repository, for continuity
  with the shootout: CMU Haitian Creole (30 sentences, 30 speakers) and FLEURS
  Lao and Khmer (30 sentences each, native readers) through Omnilingual, with
  the gold text run as well to separate hearing from translation.
- As in the earlier tests, only metrics are committed: no audio, transcripts,
  translations or references in the repository.

**References.** FLEURS Lao and Khmer come with FLoRes's professional English
translations (native-speaker references). The CMU Haitian Creole sentences
have model-made references (Gemini 2.5 Pro, `make_refs.py`), and the VOA
clips have none; for those, make a reference transcript and translation with
a strong cloud model as the continuous Haitian Creole test did, and have a
native speaker check as much of it as can be arranged, starting with the
Haitian Creole clip. Mark in the results which references are human-checked.
Scores against model-made references rank systems against each other; they
are not an absolute measure.

**Pieces.** The stack's own cutting: omni-stt's segmenter at the 200 ms
pause, 10 s cap and 1 s minimum used in the continuous test, giving pieces of
about 3.8 s (median). Every translator gets the same pieces from the same
recognition pass, so the comparison is of translation alone. Recognition is
Omnilingual 300M (the public card) for all three languages, with the 7B as a
second pass for Lao if its 8.4% against 15.7% per sentence holds on
continuous speech.

**Metrics**, as in the eval READMEs:

- **Quality, 0–3 per reference sentence** (3 correct and natural, 2 minor
  errors, 1 major meaning errors or mostly missing, 0 wrong or missing), by
  one judge model reading the whole output against the numbered reference
  sentences, blind, every system shuffled under letters in one call per
  clip. Reported as the mean and as the share of points.
- **Critical errors**: a wrong number, name, date, dose, negation or
  who-did-what, or reversed meaning. Counted per system per clip.
- **Refusals and omissions**: pieces with no output, counted separately and
  scored 0.
- **Per-piece latency** on the GPU the stack runs on (L4 or A10-class, 24 GB,
  section 6): median and p90 from the piece's text arriving at the translator
  to the full translation, one stream, no batching; and tokens per second,
  so the numbers transfer to another card.
- **Cost per hour of speech** from list prices only: GPU hours at the pod or
  Cloud Run L4 rate from `site/data/list-prices.json` (an L4 instance is about
  $1.05 an hour while running), divided by the streams one instance keeps up
  with, beside the cloud translation step's measured $0.88 an hour. No
  figure from a bill.

**Grading hygiene**, learned from the earlier rounds: every system in one
grading round; a second round on the same outputs to show the grader's
spread; the grader's notes kept per sentence; and one direction and clip per
grading call. Differences of a few tenths on the 0–3 scale are within noise
(the three context runs alone spread 2.21–2.67).

## 6. GPU and latency budget

The stack is sized for one 48 GB card, or 32 GB with a smaller translator
([model evaluation, section 5](model-evaluation.md#5-fitting-on-a-24-gb-card)),
and omni-stt runs on a 24 GB L4. The translator shares that card with
recognition and voices, so the realistic budget for an LLM translator is
**about 8–16 GB of weights plus KV cache**:

| Model size | bf16 | 8-bit | 4-bit | Fits beside the stack? |
|---|---|---|---|---|
| 8B | ~16 GB | ~8 GB | ~5 GB | 4-bit or 8-bit on a 48 GB card; 4-bit on 24 GB with omni-stt alone |
| 12–14B | ~24–28 GB | ~12–14 GB | ~7–8 GB | 4-bit; 8-bit only on 48 GB |
| 20–27B | 40–54 GB | 20–27 GB | 11–15 GB | 4-bit only, and only on 48 GB |

Precision cost Hy-MT2 nothing (4-bit 92.7%, bf16 93.0% in September); that
must be re-checked for each LLM, since a low-resource language may sit in the
part of the model that quantisation hurts first.

**Latency.** Pieces arrive every 3.8 s on average (69 pieces in five
minutes), so the translator must average well under 3.8 s per piece or it
falls behind, and each second it takes is a second of lag for the listener.
Target: **1 s median, 2 s p90 per piece, one stream.** A 3.8 s piece is
about 10 words of source, 12–15 words of English, 20–30 output tokens; the
prompt with two context pieces and the last translation is about 200–300
input tokens. Prefill of 300 tokens on a 24 GB card is well under 0.1 s for
an 8B model, so the budget is decode: 30 tokens in 1 s needs **30 tokens
per second** single-stream, which an 8B model at 4-bit should give on an L4
and a 12B should give on an A10G or L40S; these are expectations, to be
measured. Anything that thinks before it answers is out: 500 thinking tokens
at 30 tokens per second is 17 s per piece.

**Streams per GPU.** With batching, a vLLM-class server serves several
streams at little extra per-token cost; the figure to measure is how many
rooms one card keeps within the 1 s / 2 s target, because that sets the cost
per hour in section 5. For comparison, gpt-oss-20b did 0.4 s a sentence and
gpt-oss-120b @low 0.6 s on an H100 single-stream (round 2); the H100 is
several times an L4.

**Cost of the test itself** at list prices: a 48 GB pod at about $0.99 an
hour (the shootout's RTX 6000 Ada rate) for the candidate screen, roughly
2–4 hours including model loads, so $2–4; the continuous-speech runs on an
L4 class card for the latency numbers, a few more hours. Under $20 in GPU
time for phases 0 and 1; fine-tuning (section 7) is separate.

## 7. Fine-tuning options

If a candidate is close but not over the bar, a LoRA on parallel data is the
cheap next step: a few hours on one 24–48 GB card for an 8–12B model, with
the adapter merged or served alongside the base weights.

**Data.** The hard part is not the compute but the data and its licence:

- FLoRes-200 (CC-BY-SA 4.0) has Haitian Creole, Lao and Khmer, but it is the
  test set this plan grades against (FLEURS reads its sentences). Keep it for
  evaluation; never train on it.
- NLLB-SEED and the other NLLB training resources, the OPUS collections for
  `ht`, `lo` and `km` (Tatoeba, Bible-uedin, GNOME, Ubuntu, QED and others),
  Kreyòl-MT's assembled Haitian Creole training set (JHU), and the Asian
  Language Treebank for Lao and Khmer. Each source carries its own licence;
  several are non-commercial or research-only, and a model fine-tuned on
  non-commercial data inherits that restriction in practice. **Check and
  record the licence of every source before training, and keep two lists:
  data clean for the commercial edition, and data usable only for the
  non-profit edition.**
- The VOA clips are public domain but monolingual. Their model-made
  references could be used as training pairs only if the provider's terms
  allow using its output to train another model; check before doing so.
- Speech with a matching published text that is not ours to redistribute,
  and any model trained on it, stays out of this repository, as the route
  findings already say for recognition.

**Which edition each candidate serves** (section 2): Hy-MT2, MADLAD, Qwen 3,
gpt-oss, Mistral Small and Kreyòl-MT are ✅ and can serve both editions if
their fine-tune data is clean; Gemma and Llama are ⚠️ restricted and need a
recorded licence review for the commercial edition; NLLB-200 and Aya Expanse
are ⛔ and, like Meta's MMS voices, can only serve the non-profit edition.
A ⛔ model is a perfectly good answer for the non-profit edition, which is
why NLLB stays on the list despite its licence.

**What to fine-tune for.** Not general translation ability (the data for
that is thin) but the specific failures measured: reading recognition errors
(train on Omnilingual transcripts of read speech paired with the gold text's
translation, so the model learns the recogniser's mistakes), names and
numbers, and the context format. A few thousand such pairs may be worth more
than a million clean sentences.

## 8. Risks

- **Hallucination with context.** A model given earlier pieces may translate
  them again, repeat the last translation, or "continue" the story instead of
  translating the current piece. Mitigations: the prompt's explicit rule,
  greedy decoding, a length check (an output more than about twice the
  source's length in words is flagged and re-run without context), and the
  no-context control run so that the net effect of context is visible per
  model.
- **Language confusion.**
  - *Haitian Creole and French*: cloud recognisers write Haitian speakers as
    French on auto-detect (46.7% CER against 6.3% with the code), and
    Omnilingual v2 drifts Haitian spelling toward French; a French-heavy LLM
    may read Haitian Creole as broken French and translate the French it
    imagines. Check for French-looking source interpretations in the grader's
    notes.
  - *Lao and Thai*: several vendors write Lao in Thai script, and open LLMs
    sometimes produce Thai for Lao (shootout round 2). Into English this
    shows up as a model reading Lao words through Thai, which is wrong often
    enough to matter; out of English (not in scope here) it produces the
    wrong script outright. Count any Thai in the output as an error.
  - *Khmer numerals and number words*: Khmer digits (១៥) and spelled-out
    numbers (ដប់ប្រាំ) are both common, and NFKC does not fold the digits.
    Numbers are critical errors by definition, so the grading must be strict
    and the test sentences must contain them.
- **The grader is a Gemini model** and some references are model-made. It
  may favour fluent output over faithful output. Human checking of the
  Haitian Creole references is the cheapest correction.
- **Quantisation.** 4-bit may cost more on low-resource languages than it
  cost Hy-MT2 on high-resource ones; measure bf16 or 8-bit on the pod once,
  before deciding the served precision.
- **Licence drift.** Model cards and terms change between releases (the
  stack already pins Hy-MT2 to a revision for this reason). Pin every
  candidate's revision in the results and record the licence text seen.
- **The result may be "no".** Round 2 already showed that open reasoning
  LLMs without context do not read these transcripts. Context and a smaller,
  non-thinking model may not change that. The stop rule below is there so
  that this is a cheap and recorded answer, not an open-ended project.

## 9. Phases and the stop rule

**Phase 0: text screen (one GPU session, no new audio).** The shootout's
inputs rebuilt with `shootout.py inputs` (Omnilingual's transcripts of the
CMU Haitian Creole sentences and the FLEURS Lao and Khmer clips, and the gold
text), every candidate in section 2 that fits, no context, one sentence per
call, greedy. Hy-MT2 (Khmer), MADLAD and NLLB run again in the same round as
baselines, since the earlier rounds' outputs are not committed. One blind
grading round. Output: a table like the shootout's, with the untested rows
filled in. Drop any LLM that does not reach MADLAD on its best language.

**Phase 1: context on continuous speech.** The VOA clips through omni-stt's
200 ms / 10 s pieces; the survivors of phase 0 with and without context,
MADLAD and Hy-MT2 (Khmer) as baselines, and one cloud LLM run with the same
context for scale. Quality, critical errors, refusals, per-piece latency and
tokens per second on an L4-class card. One grading round, repeated once on
the same outputs.

**Stop rule.** After phase 1, for each language into English, compare the
best open candidate with the stack's current engine for that language
(Hy-MT2 for Khmer, MADLAD for Haitian Creole and Lao) in the same grading
round. **If no open model beats the current engine by at least 0.3 on the 0–3
scale (10 points of the share) with no more critical errors, within the
latency budget, on any of the three languages: stop.** Record the result in
the route findings, keep Hy-MT2 and MADLAD on the stack, and keep the cloud
LLMs for these languages where privacy allows. The margin is 0.3 because
that is the spread seen between identical runs (2.21–2.67) and between
grading rounds (5–10 points); a smaller lead is not a result.

**Phase 2: fine-tune, only if phase 1 passes for at least one language.** A
LoRA on licence-checked data (section 7) for the one or two best models,
re-run on phase 1's clips, separate grading round. Stop if the adapter does
not add at least another 0.2 on the scale or cut the critical errors.

**Phase 3: ship behind a flag.** Add the winner as an engine
([adding an engine](adding-an-engine.md)), off by default, selected per
language in `languages.toml`; a `languages.toml` entry for the non-profit
edition where the model or its data is ⛔. Re-run the stack's own September
suite for the languages it serves, so the change is visible in
[model-evaluation.md](model-evaluation.md).

Each phase ends with its numbers in an `eval/` folder in the usual form
(README with method, results and caveats; `results.json`; no audio, no
transcripts, no keys) and a dated note in
[route-findings-2026-10.md](route-findings-2026-10.md) or its successor.
