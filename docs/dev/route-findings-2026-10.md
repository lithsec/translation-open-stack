# Choosing a route: hearing, translating, privacy (October 2026)

What we learned in October 2026 while deciding how Live Translation and Lithos
Talk should hear, translate and voice speech, with a private route in view and
Haitian Creole as the hardest case. The detail and the scripts are in the eval
folders linked from each section. Grades come from one blind Gemini grader per
round and move 5–10 points between rounds, so **compare numbers only inside
one table**.

## Summary

- **Best route found:** Azure speech-to-text → **gpt-5.6-sol on our Azure
  Foundry resource** (reasoning low) → Azure voice. sol was first or tied in
  22 of 25 directions. It was also 2.3× quicker than Gemini 3.5 Flash
  (2.0 s against 4.7 s per sentence, medians over the directions).
- **Haitian Creole:** **Omnilingual** hears it best (5.7% of characters wrong
  live; 4.2% one sentence at a time with the public card).
  Azure can't hear it at all. sol and Gemini Flash are the only usable
  translators. Into English from real speakers: sol 93%, Flash 90%, Azure
  Translator and the open translators 34–36%.
- **The open stack's translator (Hy-MT2) beats Azure Translator into
  English, but trails the LLMs by about 15 points.** It ties Azure Translator
  out of English. It has no Haitian Creole or Lao; MADLAD, its fallback, is
  weak there.
- **Privacy:** Microsoft's documentation says live speech-to-text, fast
  transcription, live text-to-speech and Translator do not retain or store
  customer data (section 4, with links). Foundry may store flagged prompts for
  human abuse review **unless modified abuse monitoring is approved**. With
  that approval, Microsoft's documentation describes no storage on the
  Azure → sol → Azure route, which is also the most accurate one. None of
  this is confirmed in writing for our resource.
- **Selected setup (2026-10-19):** Azure *streaming* speech-to-text → sol →
  Azure voice for every language except Haitian Creole, which goes
  Omnilingual → sol → Gemini 3.8 Flash TTS (section 12). Lao is the weak spot:
  no recogniser we can stream does it well yet.
- **Sentence cutting mattered more than the model** for live Omnilingual:
  waiting 0.7 s instead of 0.3 s for a pause, and forcing a cut at 15 s
  instead of 6 s, halved Lao's errors and cut Haitian Creole's by 40%
  (section 11). Live since revision `omni-stt-00008-luf`.
- **Audio quality:** a room mic adds 44–54 points of character error; a
  sound-board feed or close mic is the biggest single win (section 9).
- **Open reasoning LLMs** on the open stack were tried and fall short of sol
  (section 6).

## 1. Hearing Haitian Creole

From `eval/2026-10-real-voices` (CMU real speakers; character error rate;
lower is better).

| Recogniser | CER | Notes |
|---|---|---|
| **Omnilingual ASR 300M** (omni-stt, live) | **5.7%** | Full clip, 17 October. Whether the public card or a private Haitian Creole fine-tune served it was not recorded; the public card scores 4.2% one sentence at a time (`eval/2026-10-omni-sizes`) |
| Gemini 3.5 Transcribe Live, `ht-HT` | 6.3% | With the language given. Auto-detect: 46.7% |
| OpenAI gpt-transcribe (per sentence) | 6.8% | 4 sentences only; about 0.8 s. "ht" is refused as a code, so the prompt names the language |
| gpt-4o-transcribe | 7.5% | 4 sentences |
| gpt-live-transcribe (live) | 7.9% | 4 sentences; 0.3–0.5 s after each commit |
| gpt-live-1, its own transcript | 8.2% | 4 sentences |
| AssemblyAI (Universal-2) | ~10% | 2.6–3.0 s per sentence. Universal-3.5 Pro thinks Haitian Creole is French when auto-detecting |
| ElevenLabs Scribe v2 Realtime | 15% | Sentence 1 only |
| Gladia (Solaria-1) | 18.9% | |
| whisper-1 | 47% | |
| Azure speech-to-text | — | No Haitian Creole locale |

Speech straight to English with no transcript was weaker:
- gpt-realtime-translate is quick but garbles the meaning.
- gpt-live-1, told to interpret, got 2 of 4 sentences right.

## 2. Translating Omnilingual's Haitian Creole

From `eval/2026-10-real-voices/text-mt` (run 12): Omnilingual's live
transcript of the 30 real-voice sentences, translated into English, one blind
round.

| Translator | Mean | Notes |
|---|---|---|
| **Foundry gpt-5.6-sol @low** | **91%** | 83% fully correct, 3 critical; 3.1 s median, 5.6 s p90 |
| Gemini 3.5 Flash @medium | 90% | |
| Gemini 3.5 Flash (default) | 89% | |
| OpenAI gpt-5.5 @low | 87% | |
| Gemini 3.5 Flash @low | 79% | Live Translation's setting at the time |
| Foundry gpt-5.6-luna | 72% | |
| gpt-5.4-mini | 60% | |
| Gemma 4 31B (open) | 52% | 0.7 s on an H100 |
| gpt-4.1 | 52% | |
| Google Translate | 50% | |
| Foundry DeepSeek-V4.1-Flash | 47% | 1.5 s |
| NLLB-200 3.3B (open) | 46% | Loops; turns names into Bible names |
| TranslateGemma 27B (open) | 42% | |
| Azure Translator | 42% | |
| Foundry Mistral-Large-3 | 30% | Azure's content filter refused one Bible verse |
| Kreyol-MT | 26% | |

From the gold text, the open models did better (Gemma 4 79%, TranslateGemma
76%, NLLB 68%). They lose most of that on a transcript with recognition errors,
which they translate literally. The LLMs repair the errors from context.

## 3. Translators on Azure's transcripts (25 directions)

From `eval/2026-10-translator-shootout` (commit `50658f3`). All seven
translators were given identical sentence text: Azure's transcripts, or
Omnilingual's for Haitian Creole speakers. Score is the share of 0–3 points;
critical errors (wrong number, time, dose, negation or who-did-what) are in
brackets.

| Group | Hy-MT2 7B | MADLAD 7B | TranslateGemma 12B | Azure Translator | Gemini 3.5 Flash | **gpt-5.6-sol @low** |
|---|---|---|---|---|---|---|
| Into English: ja, zh, km, fr (6) | 67% (54) | 59% (71) | 66% (59) | 54% (71) | 80% (37) | **82% (32)** |
| Out of English: 8 languages (11) | 89% (24) | 76% (46) | 85% (35) | 86% (35) | **94% (15)** | **94% (15)** |
| Lao, both ways (4) | n/a | 52% (56) | 46% (60) | 51% (54) | 69% (38) | **71% (37)** |
| Haitian Creole, both ways (4) | n/a | 47% (45) | 49% (42) | 47% (38) | 85% (13) | **88% (11)** |
| All 25 | 71%* (179) | 64% | — | 67% (198) | 85% (~100) | **87% (95)** |
| Median time per sentence | ~1.1 s GPU (Khmer 5–8 s) | 0.3 s GPU | 1.2 s GPU | **0.17 s** | 4.7 s | 2.0 s |

\* The stack's route: Hy-MT2, with MADLAD where Hy-MT2 lacks the language.

- **Into English:** Hy-MT2 beat Azure Translator in all six directions it
  could run (zh→en 94 vs 76; real km→en 59 vs 48). It still trails the LLMs.
- **Out of English:** Hy-MT2 and Azure Translator are about even (89 vs 86).
  - Azure wins German, Russian and Ukrainian.
  - Hy-MT2 wins Japanese and Khmer.
- **Gemini Flash at medium thinking and at default thinking** scored the same
  and took the same time.
- **Caveats:**
  - The real-voice sentences are longer news text, so every real-voice score
    is lower.
  - Lao and Khmer speakers' scores are capped by Azure's mishearing.
  - The grader is a Gemini model.

### Earlier: Azure STT → Gemini vs Gemini Live (`eval/2026-10-azure-stt-gemini`)

The hearing decides it. Into English from Japanese and Mandarin:
- Azure misheard 2–4% of characters and Gemini Live 6–20%.
- Gemini translating Azure's text scored 92% and 97%; Gemini Live scored 50% and 57%
  (`results.json`).
- The delay is about 1.3 s after each sentence ends.

## 4. Privacy: what each service keeps

What Microsoft's data, privacy and security pages say (checked 2026-10-19 and
2026-10-20). These are statements of vendor documentation, not confirmed in
writing for our resource.

| Service | Kept by Microsoft, per its documentation? |
|---|---|
| Azure speech-to-text, live and fast transcription | [Says no](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/speech-service/speech-to-text/data-privacy-security): "Microsoft does not retain or store the data provided by customers." Batch transcription can store results. |
| Azure text-to-speech, live | [Says no](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/speech-service/text-to-speech/data-privacy-security): "Microsoft doesn't retain or store the text" and "doesn't store audio" from the real-time synthesis API |
| Azure Translator (text) | [Says no](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/translator/data-privacy-security): "Translator doesn't persist customer data submitted for translation" ("No Trace") |
| Foundry models sold by Azure (gpt-5.6-sol) | [Microsoft's page](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/openai/data-privacy) says prompts and completions are "NOT available to OpenAI", are processed in Microsoft's Azure environment and are not used to train models. **[Abuse monitoring](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/abuse-monitoring) may store flagged prompts for human review** unless modified abuse monitoring is approved (Limited Access application). A US Data Zone deployment may process prompts anywhere in the US. |

So by Microsoft's documentation, Azure hearing + Azure voice + Translator (or
sol with modified abuse monitoring) is a route with nothing stored at
Microsoft; we have not had that confirmed for our resource. Running our own
translator in the middle adds
no privacy over Azure Translator, since Microsoft already sees both the
source and the translated text. It is a quality choice.

Not a "keeps nothing" claim for any provider until it's in writing for our
resource. Pages:
- [Speech to text](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/speech-service/speech-to-text/data-privacy-security)
- [Text to speech](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/speech-service/text-to-speech/data-privacy-security)
- [Translator](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/translator/data-privacy-security)
- [Foundry Models sold by Azure](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/openai/data-privacy) and [abuse monitoring](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/abuse-monitoring)

## 5. What we built to try it

- **An Azure Foundry resource** (`<your-foundry-resource>`; AI Services,
  eastus). One key covers speech, Translator and the Foundry models.
  - The deployments include a gpt-5.6-sol **Data Zone Standard** (US)
    deployment (`<deployment>`).
  - Only Whisper is offered for speech among the Foundry models in eastus.
- **Live Translation.** The Haitian Creole
  exception can translate with a Foundry deployment instead of Gemini, and a
  new **Azure + Foundry** mode streams Azure speech-to-text into sol for every
  language.
  - The Foundry address, key and deployment are entered in Settings.
  - It never falls back to another provider.
  - Live test: 2.6–5.9 s per sentence on the US deployment (4 sentences).
- **Lithos Talk** (TestFlight, internal only). Settings → Test engines offers:
  - Azure; Azure → Gemini 3.5 Flash; Azure → Foundry sol;
    Omnilingual → Foundry sol (build 10, PRs #20/#21);
  - **Azure + Omnilingual → sol** (build 13, PR #24): each language is heard
    by its best recogniser. Haitian Creole goes to Omnilingual, everything else
    to Azure; when both could apply, both listen and the result is arbitrated.
  - The badge on the Talk page names the test route (build 11, PR #22).
  - Azure hearing **streams** over WebSocket with continuous language ID
    (build 12, PR #23); finals arrive a median 207 ms after the sentence ends,
    and Pair mode shows partial captions. The Worker issues short-lived
    Azure tokens (`POST /v1/azure/token`).
  - Haitian Creole is spoken with Gemini 3.8 Flash TTS instead of Flash Lite
    (PR #25), which sounded French (section 12).

  Haitian Creole is a test-only language. Omnilingual is woken when Haitian
  Creole is picked, since a cold start took 47 s.

## 6. Next

1. **Open-weight reasoning LLMs on the open stack: tried, not good enough.**
   The question was whether an open reasoning LLM could replace the stack's
   translation models (Hy-MT2, MADLAD), since the LLMs' lead comes from
   repairing recognition errors. Round 2 of the shootout
   (`eval/2026-10-translator-shootout`, README "Round 2") ran gpt-oss-120b
   (@low and @medium), gpt-oss-20b @low and Qwen3.8-27B (FP8, thinking @low)
   on the same 25 directions, graded blind beside sol, Flash, Hy-MT2 and
   MADLAD:
   - Overall 54–64%, against sol 87% and Flash 86%, and under the stack's own
     route (Hy-MT2, else MADLAD) at 71%.
   - Into English 58–66%, not better than Hy-MT2 (68%). They do not repair
     misheard Khmer or Haitian Creole the way sol does.
   - Lao 3–28%; Haitian Creole 43–57% (gpt-oss-120b writes it well from
     clean English, but cannot read Omnilingual's transcripts).
   - gpt-oss-120b @low is fast (0.6 s a sentence on an H100) but needs ~65 GB,
     more than the stack's 24–48 GB card. The ones that fit (gpt-oss-20b,
     Qwen3.8-27B) score lower, and Qwen takes ~2.8 s.

   No current DeepSeek model fits one GPU; the R1 8B distill did not run
   cleanly. Keep Hy-MT2 and MADLAD on the stack. The cloud LLM routes (sol,
   Flash) stay the quality bar.
2. **Apply for modified abuse monitoring** on the Foundry resource. With it,
   Microsoft's documentation describes no storage on Azure → sol → Azure
   (to be confirmed in writing for our resource).
3. **Hear the Talk test routes on real conversations** (streaming, hybrid, Haitian Creole voice).
4. **More Haitian Creole training speech.** Speech with a matching published
   text can fine-tune hearing, but where the audio is live interpretation
   rather than a reading of the text, keep an utterance only where
   Omnilingual's transcript matches the text closely. Data that is not ours to
   redistribute, and any model trained on it, stay out of this repository.

## 7. Cost per hour of speech (2026-10-19)

List prices (Azure Retail Prices API, eastus; Cloud Run's published L4 rate),
not our bill. sol's usage was measured: 40 sentences of a recorded talk
(130 words/min, so ~413 sentences per hour of continuous speech) into
Spanish and Haitian Creole with Talk's prompt and 4 sentences of context:
218 tokens in (none cached: the prompt is under the caching minimum), 52 out
(~7 of them reasoning at `low`), 2.4 s per sentence.

| Per hour of continuous speech | Price | Cost |
|---|---|---|
| Azure STT, real time (Live Translation) | $1.00/h | $1.00 |
| Azure fast transcription, per sentence (Talk routes) | $0.36/h ($0.10 promo listed) | $0.36 |
| Omnilingual on Cloud Run (L4 $0.67/h + 4 vCPU + 16 GiB ≈ $1.05/h while up; 8 connections per instance, with GPU batching) | ≈ $1.05/h | ~$1.05, plus ~15 idle min (~$0.26) after the last use |
| gpt-5.6-sol, DataZone Standard, per target language | $4.40 / $22 per 1M tokens in / out | $0.40 + $0.48 = $0.87 |
| Azure neural voice, per target language | $15 per 1M characters | ~65k chars = $0.98 |

Hearing is paid once per room; each language adds ~$1.85/h (two thirds of it
the voice). Azure → sol: ~$2.20/h for one language on Talk, ~$2.85/h on Live
Translation, ~$6.55/h for three languages. Omnilingual → sol: about the same,
but billed while the instance is up, so it is cheapest when one instance serves
several rooms. For scale, Glossa charges $5 per hour per language.

## 8. Speech-to-text bake-off: Japanese, Khmer, Lao (2026-10-19)

Azure is weakest on these three. Vendors on the same FLEURS real-voice clips,
character error rate (`eval/2026-10-real-voices/README.md`, raw output in
`out/stt-bakeoff/`):

| | Azure | Best alternative | Others |
|---|---|---|---|
| Japanese | 10.2 | gpt-4o-transcribe 5.4 (batch) | Google live 7.3, ElevenLabs batch 6.7, OpenAI live 9.0 |
| Khmer | 13.3 | ElevenLabs batch 9.1 | Google live 10.8, ElevenLabs Realtime 31–52, Omnilingual 30 (old cutting) |
| Lao | 17.9 | Gemini 3.1 Pro per sentence 8.5 (28 s a sentence) | Gemini Flash 16.9, Omnilingual 24 (old cutting); several vendors write Lao in Thai script |

Also: English Azure 6.4, ElevenLabs Realtime 4.5, Google live 14.2;
French Azure 4.9, Google live 2.2; Haitian Creole Omnilingual 5.7, Google
(ht-HT) 6.3, Azure none.

**Verdict:** the clear wins are batch-only or slow, which doesn't suit live
speech. ElevenLabs Realtime is good in English but collapses on Khmer.
Google live is close to Azure overall and better on Khmer and Japanese.
None justifies switching the live route yet. **ElevenLabs retains data by
default**, according to its [Zero Retention Mode page](https://elevenlabs.io/docs/eleven-api/resources/zero-retention-mode); that mode
(`enable_logging=false`) is for Enterprise customers only, so it doesn't fit
the private route.

## 9. Audio quality: what degrades recognition (2026-10-19)

Clean clips put through simulated conditions; mean added character error
points, Azure / Omnilingual (`eval/2026-10-real-voices/README.md`,
`out/stt-degrade/`):

| Condition | Azure | Omnilingual |
|---|---|---|
| Room mic (distance + reverb + noise) | +44 | +54 |
| Large-hall reverb (RT60 1.5 s) | +20 | +25 |
| Crowd/HVAC noise, 10 dB | +30 | +20 |
| Bluetooth hands-free, narrowband | +10 | +6.5 |
| Bluetooth hands-free, wideband | ~1 | ~0 |
| Opus 24 / 12 kbit/s | 0–1.5 | 0–3 |
| Denoiser in front of the room mic | worse (+45 to +54) | better (+39) |

Azure English silently dropped 23 of 30 sentences in noise. Compression is
harmless; distance and noise are not. **Feed recognition from the sound
board or a close mic.** Bluetooth headsets should use wideband.

## 10. Omnilingual model sizes (2026-10-19)

Zero-shot, per sentence, character error (`eval/2026-10-omni-sizes`):

| Model | ht | km | lo |
|---|---|---|---|
| LLM 300M (served) | 4.2 | 14.2 | 15.7 |
| LLM 1B | 4.6 | 13.4 | 11.7 |
| LLM 3B | 5.5 | 13.0 | 11.8 |
| LLM 7B | 4.2 | 12.6 | 8.4 |
| LLM 3B v2 | 7.3 | 12.7 | 9.8 |
| LLM 7B v2 | 7.2 | 12.5 | 9.1 |

The v2 models drift Haitian Creole towards French spelling. 7B is the best
on Lao, but on fragments under ~1 s it can repeat one syllable ~200 times,
so it needs a repetition guard. Speed (batch 1): 300M 0.13 × real time,
3.5 GB; 7B 0.15 × real time, 14.9 GB, measured on an RTX PRO 6000 MIG slice
(no L4 was available). Both fit omni-stt's L4. For Haitian Creole, 7B is not
better than 300M, so the served model stays 300M; a privately fine-tuned
300M card (not distributable) is what omni-stt serves now, and its details
stay outside this repository.

## 11. Live sentence cutting in omni-stt (2026-10-19)

omni-stt cut speech after a 0.3 s pause and forced a cut at 6 s, which
chopped 15–45% of sentences. The full real-voice clips through omni-stt's own
Segmenter, gain-normalised as a mic with automatic gain would be, LLM 300M,
character error (`eval/2026-10-omni-sizes/README.md`):

| Pause : max | ht | km | lo | en | Wait after speech ends |
|---|---|---|---|---|---|
| 0.3 s : 6 s (old) | 7.0 | 18.7 | 36.2 | 12.6 | 384 ms |
| 0.3 s : 15 s | 6.8 | 16.2 | 25.8 | 11.7 | 384 ms |
| 0.5 s : 15 s | 5.4 | 15.1 | 18.4 | 10.9 | 576 ms |
| **0.7 s : 15 s (now)** | **4.2** | 15.2 | 18.2 | **10.7** | 768 ms |
| 0.8 s : 25 s | 4.4 | 14.6 | 17.3 | 13.7 | 864 ms |
| whole sentences | 4.2 | 14.2 | 15.7 | | |

`ENDPOINT_MS=700`, `MAX_UTTERANCE_S=15` went live on 2026-10-19 as revision
`omni-stt-00008-luf` (same image; rollback to `omni-stt-00006-mab`). On 91 s
of Haitian Creole the service now returns 15 segments instead of 24, following
sentence boundaries. Cost: ~0.4 s more wait per turn, and up to 15 s before
text if the speaker never pauses.

Revised 2026-10-21: on five minutes of continuous news speech those settings
left the 15 s cap doing most of the cutting (12.7 s pieces, first translated
audio at 19.5 s). The defaults are now `ENDPOINT_MS=200`, `MAX_UTTERANCE_S=10`,
`MIN_SPEECH_MS=1000`, with the translator given the previous pieces as context
to make up for the shorter pieces, and a progressive pause cut (`CUT_EARLY_S`)
for anyone who keeps a longer pause: `eval/2026-10-continuous-ht/README.md`
and the omni-stt README's Endpointing section.

Separately, very quiet input (peaks below −30 to −40 dBFS) is never heard by
the speech detector and dropped whole; gain normalisation before it would fix
that.

## 12. Selected setup and error rates (2026-10-19)

| Language | Hears | Error (clean speech) | Translates | Speaks |
|---|---|---|---|---|
| Most languages (en, es, fr, …) | Azure, streaming | en 6.4, fr 4.9 | sol | Azure neural voice |
| Japanese | Azure | 10.2 | sol | Azure |
| Khmer | Azure | 13.3 | sol | Azure |
| Lao | Azure | 17.9 (weakest) | sol | Azure |
| Haitian Creole | Omnilingual 300M (a privately fine-tuned card, not distributable) | ~4.5 live | sol | Gemini 3.8 Flash TTS |

**Haitian Creole voice:** Talk's Gemini Flash Lite TTS read Haitian Creole
with a French accent. In the blind judge (section 13, `judge.json`) it scored
2.5/5 for sounding Haitian, against 3.8 for full Flash TTS (first audio 0.67 s
against 0.7–0.95 s), so Talk
now uses full Flash for Haitian Creole only. An in-text instruction about
accent gets read aloud, so it is selected by model, not prompt.

**Next for Lao and Khmer:** a private fine-tune of the 300M model for them is
being tried (not distributable; data and results stay outside this
repository). Lao or Khmer move to Omnilingual only if it beats Azure live.

## 13. Haitian Creole voices (2026-10-19)

Azure has no Haitian Creole voice, so the route's one step off Microsoft is
Haitian Creole speech. Seven voices, judged blind on six sentences (five for
MMS-TTS: one judge reply had no score) (`eval/2026-10-ht-voices`):

| Voice | Sounds Haitian (1–5) | Clear (1–5) |
|---|---|---|
| **Gemini 3.8 Flash TTS** | **3.8** | **4.5** |
| gpt-4o-mini-tts (Azure eastus2), coral | 2.8 | 3.7 |
| Meta MMS-TTS (open, non-commercial) | 2.8 | 4.2 |
| gpt-4o-mini-tts, coral + accent instruction | 2.7 | 3.3 |
| Gemini 3.8 Flash Lite TTS | 2.5 | 4.3 |
| Coqui VITS OpenBible (open) | 2.5 | 4.0 |
| gpt-4o-mini-tts, sage + accent instruction | 2.3 | 3.7 |

Gemini Flash TTS stays Talk's Haitian Creole voice. Neither Microsoft's voice
nor the open stack's voices sound more Haitian, despite the open ones being
trained on Haitian readers. In Live Translation, a Haitian Creole listener on
Azure + Foundry gets captions only (everything on Microsoft) or, set to
Azure + Gemini, Gemini's voice. A native listener should confirm with the
blind mode in `listen.html`: the judge is a Google model and the sample is
small.
