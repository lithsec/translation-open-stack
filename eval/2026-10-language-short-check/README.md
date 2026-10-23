# Short check: eleven more languages, October 2026

A quick look at eleven languages beyond the ones measured in depth: Vietnamese,
Persian, Cape Verdean Creole, Mandarin, Cantonese, Arabic, Swahili, Hmong, Twi,
Filipino (Tagalog) and Ukrainian. For each: which recogniser hears it best, which
translator does best both ways with English (also from the recogniser's own
output, the route a live room takes), and whether there is a voice. It is a
short check, not a full evaluation: 20 read sentences per language, one grading
round. Use it to sort languages, not to rank close systems.

## How it was run

- **Speech:** 20 FLEURS test sentences per language (google/fleurs, CC BY 4.0),
  read by native speakers, each sentence alone (`fetch.py`). The English text of
  the same FLEURS id is the reference meaning. Arabic is FLEURS `ar_eg`: Egyptian
  readers of Modern Standard Arabic text, so spoken dialects were not tested.
- **Twi:** no openly licensed Twi speech was found, so text only: the first 20
  lines of FLORES-200 devtest (`twi_Latn` with `eng_Latn`; CC BY-SA 4.0). Only
  scores are published for it.
- **Hmong:** no openly licensed Hmong speech or parallel text was found. Not tested.
- **Recognition** (`asr.py`, `omni.mjs`), each sentence alone with its language given:
  - Azure fast transcription (the language's locale; Cantonese is `zh-HK`).
  - MAI-Transcribe-2, the same API's enhanced mode. It ran on our East US
    resource; the East US 2 resource refused it ("Enhanced mode with model is
    currently not supported yet").
  - Omnilingual 300M through the omni-stt service, for the languages that
    service maps (`OMNI_CODES`): not Cantonese or Cape Verdean Creole.
  - Scored with `score.py`: character error (and word error where words are
    spaced) against the FLEURS text, NFKC, lowercase, letters and digits only.
    Numbers are not spelled out, which costs every system alike.
- **Translation** (`mt.py`), one sentence per call, the translator shootout's
  prompt (it warns about recognition errors):
  - sol: gpt-5.6-sol on our Foundry deployment, reasoning low.
  - Gemma 4 31B on OpenRouter, restricted to the apps' named zero-retention
    hosts (`provider.only`, `zdr`, `data_collection: deny`).
  - Hy-MT2 7B on OpenRouter, where it has the language.
  - Graded blind (`round.py`, `grade.py`, copied from `../2026-10-es-pt-live-compare`):
    Gemini Pro, all systems side by side, one call per direction, 0–3 per
    sentence and a critical flag. Score = share of the possible points ×100;
    brackets = critical errors out of 20.
- **Voices** (`voice.py`): Azure's voice list per locale, and one sentence
  synthesised plain and with the apps' pacing (trimmed silences, +8%) to see that
  the voice takes it; Gemini TTS's published language list for the rest.

## Results

Recognition, characters wrong (%), best in bold:

| Language | Azure | MAI-Transcribe-2 | Omnilingual 300M |
|---|---|---|---|
| Vietnamese | 4.6 | **1.5** | 22.8 |
| Persian | 5.6 | **1.4** | 6.5 |
| Cape Verdean Creole | no locale | not supported | not mapped in omni-stt |
| Mandarin | 4.9 | **4.6** | 15.4 |
| Cantonese | **4.8** | 5.9 | not mapped |
| Arabic | 1.8 | **0.9** | 2.3 |
| Swahili | 16.3 (2 empty) | **2.3** | 10.5 |
| Filipino | 5.1 | **1.6** | 14.7 |
| Ukrainian | 4.8 | **0.7** | 3.3 |

Microsoft reports MAI-Transcribe-2's accuracy on FLEURS, so these clips may
flatter it. MAI here is batch, one sentence at a time; its streaming model is a
different model (`../2026-10-mai-streaming-pipelines`).

Translation, score (critical errors). "From speech" is X→English from the best
recogniser's output (Azure for Cantonese, MAI for the rest):

| Language | X→en: sol / Gemma / Hy-MT2 | en→X: sol / Gemma / Hy-MT2 | From speech: sol / Gemma / Hy-MT2 |
|---|---|---|---|
| Vietnamese | **96.7** (1) / 91.7 (2) / 86.7 (3) | **100** / 98.3 / 91.7 (1) | **96.7** / 91.7 (2) / 90.0 (2) |
| Persian | **100** / 95.0 / 86.7 (2) | **98.3** / 90.0 (1) / 88.3 (1) | **85.0** (1) / 81.7 (2) / 73.3 (3) |
| Cape Verdean Creole | 88.3 / **91.7** (1) / – | **96.7** / 81.7 / – | – |
| Mandarin | 93.3 (1)* / **98.3** / **98.3** | 95.0 (1)* / 96.7 / **98.3** | 95.0 (1)* / 96.7 / **100** |
| Cantonese | **96.7** (1) / 91.7 (3) / 91.7 (3) | **100** / 98.3 / 66.7 | **91.7** / 78.3 (3) / 71.7 (2) |
| Arabic | **100** / 93.3 / 91.7 | **96.7** (1) / 90.0 (1) / 85.0 (2) | **95.0** (1) / 93.3 (1) / 81.7 (4) |
| Swahili | **95.0** / 88.3 (2) / – | **100** / 86.7 / – | **88.3** (2) / 73.3 (5) / – |
| Filipino | **96.7** / 95.0 / 88.3 | **98.3** / 96.7 / **98.3** | **98.3** / 95.0 / 83.3 (3) |
| Ukrainian | **98.3** / 91.7 (1) / 90.0 (1) | **100** / 88.3 (1) / 75.0 (2) | **100** / 91.7 (1) / 91.7 (1) |
| Twi (text only) | **81.7** (5) / 28.3 (17) / – | **98.3**† / 36.7 (11) / – | – |
| Hmong | not tested | not tested | – |

\* One Mandarin sentence was refused by Azure's content filter and counts as a blank for sol.
† The grader reads Twi and Cape Verdean Creole output against the English
meaning; how well it reads those languages is not established, so treat the
into-Twi and into-Cape-Verdean scores as rough.

Voices:

| Language | Azure neural voices | Pacing works | First audio | Other |
|---|---|---|---|---|
| Vietnamese | 6 (vi-VN) | yes (6.7 → 5.0 s) | 418 ms | |
| Persian | 2 (fa-IR) | yes (11.7 → 10.0 s) | 521 ms | |
| Cape Verdean Creole | none | – | – | not in Gemini TTS's list; MMS (non-commercial) |
| Mandarin | 53 (zh-CN) | yes (5.8 → 4.7 s) | 204 ms | |
| Cantonese | 3 (zh-HK) | yes (6.5 → 5.6 s) | 427 ms | |
| Arabic | 4 (ar-EG, ar-SA) | yes (9.6 → 8.0 s) | 294 ms | |
| Swahili | 4 (sw-KE, sw-TZ) | yes (10.6 → 9.0 s) | 331 ms | |
| Filipino | 2 (fil-PH) | yes (7.6 → 6.4 s) | 303 ms | |
| Ukrainian | 2 (uk-UA) | yes (7.6 → 6.5 s) | 409 ms | |
| Twi | none | – | – | Gemini TTS lists Akan |
| Hmong | none | – | – | not in Gemini TTS's list; MMS (non-commercial) |

## Verdicts

| Language | Verdict | Route |
|---|---|---|
| Vietnamese | **tested-good** | MAI or Azure hears → sol. Gemma is close out of English (98.3 vs 100). |
| Persian | **tested-good** | MAI hears → sol. From speech it drops to 85 for every translator. |
| Mandarin | **tested-good** | MAI or Azure hears → Gemma or Hy-MT2, both as good as sol or better here. |
| Cantonese | **tested-good** | Azure hears → sol. Gemma is fine out of English, weaker from speech (78). |
| Arabic | **tested-good** (Modern Standard text) | MAI hears → sol; Gemma 3–7 behind. Dialects untested. |
| Swahili | **tested-good** with MAI | MAI hears (Azure 16%) → sol; Gemma 7–15 behind. |
| Filipino | **tested-good** | MAI hears → Gemma ≈ sol. |
| Ukrainian | **tested-good** | MAI hears → sol; Gemma 8–12 behind out of English. |
| Cape Verdean Creole | **experimental** | No tested recogniser, no voice. Translation works (sol or Gemma), so captions from typed text only. Omnilingual likely covers it but omni-stt doesn't map it. |
| Twi | **experimental** | Text only: sol 82 into English; Gemma unusable (28–37). Recognition untested; Gemini TTS lists Akan. |
| Hmong | **not supported** (untested) | No open test data; no Azure or Gemini voice. |

Omnilingual (the Omni Foundry route) was not the best recogniser for any of the
nine languages with speech; its case is languages Azure does not hear.

## Limits

- 20 read sentences per language and one grading round: differences of a few
  points are noise.
- Read FLEURS speech, not conversation; Arabic dialects, accents and room audio untested.
- Recognition is batch per sentence, not live streaming.
- The grader's command of Twi and Cape Verdean Creole is unverified.

## Files

`fetch.py`, `asr.py`, `omni.mjs`, `score.py`, `mt.py`, `round.py`, `grade.py`,
`voice.py`, `results.json` (FLEURS ids, scores and voice checks; no text).
