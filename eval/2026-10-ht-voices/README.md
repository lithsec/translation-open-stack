# Haitian Creole voices (2026-10-19)

Which text-to-speech voice sounds most like a native Haitian Creole speaker.
Six sentences from `../2026-10-real-voices/sentences/ht.json` (0–5), read by
seven voices, judged blind (shuffled, names hidden) by Gemini 3.1 Pro with
audio in: "sounds Haitian" 1–5 (1 = French accent) and "clear" 1–5.

| Voice | Where | Sounds Haitian | Clear | First audio |
|---|---|---|---|---|
| **Gemini 3.8 Flash TTS** (voice Kore) | Google | **3.8** | **4.5** | ~0.7–0.95 s |
| gpt-4o-mini-tts, coral | Azure eastus2 | 2.8 | 3.7 | 0.28 s (streamed) |
| Meta MMS-TTS `facebook/mms-tts-hat` | open, CC-BY-NC | 2.8 (5 judged) | 4.2 | ~0.6 s (CPU, whole sentence) |
| gpt-4o-mini-tts, coral + accent instruction | Azure eastus2 | 2.7 | 3.3 | 0.28 s |
| Gemini 3.8 Flash Lite TTS | Google | 2.5 | 4.3 | ~0.67 s |
| Coqui VITS `multilingual-tts/VITS-OpenBible-Haitian-Creole` | open, CC-BY-SA | 2.5 | 4.0 | ~0.9 s (CPU, whole sentence) |
| gpt-4o-mini-tts, sage + accent instruction | Azure eastus2 | 2.3 | 3.7 | — |

- An earlier round (same judge, not blind) gave Flash 4.2 and Lite 3.0; a
  second gave Flash 3.5, Lite 2.5. Scores move between rounds: compare within
  one table. Flash led in all three.
- The judge heard the French uvular "r" (wòch as "roche") and French nasals
  in every other voice, the open ones included, and marked the open voices
  down for flat delivery. Both open voices drop digits ("600").
- No voice read the accent instruction aloud (gpt-4o-mini-tts takes it in a
  separate `instructions` field; Gemini reads in-text instructions aloud).
- Caveats: 6 sentences; a Google model judging a Google voice; an AI judge is
  not a Haitian listener. `listen.html` has every sample with a blind mode.
- Our eastus Foundry resource offers no OpenAI text-to-speech; gpt-4o-mini-tts
  ran on a second resource in eastus2 (`AZ_ENDPOINT` in `run.mjs`, e.g.
  `https://<your-foundry-resource>.cognitiveservices.azure.com`).

Files: `run.mjs` (Gemini and gpt-4o-mini-tts samples, timing, judge),
`gen_open.py` (Coqui and MMS on CPU), `judge.json`, `scores.json`, `mp3/`,
`listen.html` (built by `build_listen.py` from `listen_template.html`).
