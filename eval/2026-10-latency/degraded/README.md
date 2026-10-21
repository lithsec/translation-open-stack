# Live routes on degraded audio, October 2026

Is Azure-based routing really better than Gemini Live Translate on the
audio a real microphone gives you: a mic a few metres away in a hall,
crowd or HVAC noise, a Bluetooth hands-free headset? This runs the
end-to-end measurement from `../README.md` and `../languages/` on clean
audio and on four degraded copies of the same clips. The degradations come
from the Oct 19 STT test (`../../2026-10-real-voices`, section "Audio
degradation").

Date: 2026-10-20, 19:15–20:45 US Eastern, plus a level check at 21:00. Same
Mac, same wired connection in Massachusetts, same US endpoints as the
languages round: Azure Speech eastus, Foundry `gpt-5.6-sol-us` eastus,
Gemini API global, omni-stt and omni-stt-7b on Cloud Run us-east4. Live
Translation at `f622fb7` (origin/main), from the languages round's scratch
copy (`../harness/setup_lt.sh` + `../languages/omni-solo.patch`).

## Routes

| Route | What it is |
|---|---|
| `azure` | Azure alone: Azure Speech translation, then the Azure neural voice |
| `azure-foundry` | Azure STT, then Foundry `gpt-5.6-sol-us`, then the Azure voice |
| `omni-foundry` | LT's solo room with the speaker language fixed: omni-stt `/listen` (Omnilingual 300M, privately fine-tuned for Haitian Creole and not in the repo; Khmer on the public 7B), then Foundry, then the Azure voice. Azure still runs beside it (see "Duplicates") |
| `ht-exception` | ht→en only, replacing the Azure routes because Azure has no Haitian recogniser: speaker language on auto, omni-stt beside Azure, then Foundry, then the English voice |
| `gemini-lt` | Gemini Live Translate `gemini-3.5-live-translate-preview`, speech to speech, voice Kore |

## Audio and conditions

- Clips: the first 15 sentences of the latency round's clips (`../build_clips.py`).
  en, es, km and ht are all the same FLoRes sentences, with the same seeded
  1.0–2.0 s pauses. English, Spanish (es_419) and Khmer are FLEURS (CC BY
  4.0). Haitian is CMU Haitian Creole speech. Every condition uses the same
  15 sentences. References: the FLoRes text in the target language. For
  ht→en, the model-made English meanings from real-voices.
- `build_degraded.py` imports the Oct 19 `make_conditions.py` and reuses it
  unchanged: the identical seeded hall impulse response (measured again
  here: RT60 1.50 s T20 / 1.54 s T30, DRR 0 dB), the same HVAC noise
  (pink + brown) plus babble from the same public pool (the real-voices
  FLEURS / CMU clips), and the same CVSD coder (`cvsd.c`). The noise samples
  are regenerated with that recipe for each clip's length. Spanish wasn't in
  the Oct 19 pool, so its babble is the pool minus French (5 talkers, like
  the others). Measured SNR: 10.0–10.1 dB in every language.
  - `room-mic`: hall reverb, then noise at 10 dB SNR, with the noise also
    passed through the hall (`revnoise10`)
  - `noise-10dB`: dry speech plus noise at 10 dB SNR (`noise10`)
  - `bt-narrowband`: Bluetooth HFP, 300–3400 Hz, 8 kHz, CVSD at 64 kbit/s, back to 16 kHz (`hfp_nb`)
  - `hall-reverb`: reverb alone, RT60 1.5 s (`reverb`)
- Streaming and timing are as in the earlier rounds: 100 ms chunks at real
  time. Speech start and end are always taken from the clean clip. One run
  per condition × route × direction, n = 15. That makes 90 sessions plus
  one Gemini rerun, plus 2 level-check sessions.
- `run_all.py` runs Gemini LT one session at a time (never two Gemini LT
  sessions together; other routes' sessions did run beside it). It allows
  at most 3 Foundry sessions (≈36 requests/min, 0 × 429 out of 1,106
  calls), at most 2 omni-stt sessions and at most 6 sessions in all. A Gemini
  LT session that stalls (a voiced gap of 15 s or more during the clip, voice
  stopping more than 15 s before the end, or a redial) is rerun once.
- `analyze.py`: the timing, sentence matching and judge from `../analyze.py`
  (gemini-3.5-flash, 0–3 per sentence, shown as % of max). It adds the
  `../content_check.py` judge for each sentence (dup = content said twice,
  partial = a meaningful part left out). For the omni-stt routes it also
  records which recogniser each delivered segment came from. A fix: LT's
  reconnecting wrapper redials when no output follows 20 s of speech, and
  the redialled Azure/omni-stt session restarts its audio offsets at 0.
  `rebase_spans()` puts them back on the clip timeline. This happened in 6
  English room-mic pipeline runs, 20 redials in total. Without the fix those
  runs' sentences were attributed about 45 s off.
- **Missing** = sentences with no translation at all. **Last words** =
  stop → first audio of the segment holding the sentence's last words
  (pipelines). For `gemini-lt` it is stop → end of that sentence's audio,
  because streaming has no segment boundary, so the two are not directly
  comparable. When most of a sentence is lost, "last words" stops meaning
  much: the negative Azure values on English reverb and room-mic come from
  fragments of a sentence whose ending never reached the listener.

    <real-voices>/.venv/bin/python build_degraded.py <real-voices dir> <20-sentence clips from ../build_clips.py> <clips>
    set -a; . <env file, ../harness/env.example>; set +a
    python3 run_all.py <scratch LT dir> <clips> <runs>
    python3 analyze.py <clips> <runs> results.json
    python3 make_table.py

## Results

Per direction: quality % / missing (of 15) / last words p50 (s).

| Pair | Route | clean | room-mic | noise-10dB | bt-narrowband | hall-reverb |
|---|---|---|---|---|---|---|
| en-es | `azure` | 62 / 0 / 0.9 | 2 / 13 / -0.5 | 4 / 14 / 1.1 | 13 / 3 / -0.1 | 9 / 0 / -0.7 |
| en-es | `azure-foundry` | 64 / 0 / 1.8 | 2 / 12 / 0.4 | 4 / 14 / 2.1 | 20 / 3 / 1.5 | 16 / 0 / 1.4 |
| en-es | `omni-foundry` | 67 / 0 / 3.6 | 2 / 13 / 8.5 | 7 / 10 / 10.8 | 38 / 0 / 6.9 | 7 / 0 / 8.8 |
| en-es | `gemini-lt` | 56 / 0 / 3.4 | 0 / 9 / 3.2 | 2 / 9 / 6.9 | 51 / 0 / 3.1 | 53 / 0 / 3.2 |
| es-en | `azure` | 58 / 0 / 1.0 | 9 / 1 / 0.6 | 56 / 0 / 0.8 | 71 / 0 / 0.8 | 24 / 0 / 0.6 |
| es-en | `azure-foundry` | 67 / 0 / 1.7 | 16 / 1 / 2.6 | 56 / 0 / 1.9 | 69 / 0 / 1.7 | 40 / 0 / 1.7 |
| es-en | `omni-foundry` | 78 / 0 / 5.6 | 13 / 2 / 11.7 | 53 / 2 / 7.6 | 76 / 0 / 5.3 | 67 / 0 / 5.8 |
| es-en | `gemini-lt` | 67 / 0 / 3.0 | 33 / 0 / 2.9 | 49 / 0 / 2.8 | 69 / 0 / 3.1 | 58 / 0 / 3.1 |
| en-ja | `azure` | 58 / 0 / 1.0 | 0 / 11 / -1.2 | 4 / 14 / 0.8 | 11 / 3 / -0.0 | 11 / 0 / -0.6 |
| en-ja | `azure-foundry` | 76 / 0 / 2.1 | 4 / 13 / 0.5 | 7 / 14 / 2.2 | 9 / 3 / 1.6 | 18 / 0 / 1.7 |
| en-ja | `omni-foundry` | 73 / 0 / 5.6 | 4 / 13 / 8.0 | 7 / 11 / 12.2 | 44 / 0 / 6.8 | 18 / 1 / 9.5 |
| en-ja | `gemini-lt` | 56 / 0 / 3.6 | 2 / 9 / 3.0 | 2 / 14 / 25.0 | 42 / 0 / 3.5 | 47 / 0 / 3.1 |
| km-en | `azure` | 36 / 0 / 1.3 | 9 / 2 / 1.3 | 20 / 0 / 1.5 | 44 / 0 / 1.2 | 20 / 0 / 1.3 |
| km-en | `azure-foundry` | 49 / 0 / 2.8 | 7 / 2 / 4.9 | 24 / 0 / 5.2 | 53 / 0 / 3.5 | 31 / 0 / 3.4 |
| km-en | `omni-foundry` | 60 / 0 / 7.1 | 11 / 2 / 9.0 | 47 / 1 / 8.0 | 69 / 0 / 6.4 | 40 / 0 / 7.5 |
| km-en | `gemini-lt` | 42 / 0 / 3.1 | 2 / 6 / 9.5 | 24 / 0 / 2.9 | 38 / 0 / 3.2 | 16 / 0 / 3.2 |
| ht-en | `ht-exception` | 69 / 0 / 4.4 | 36 / 0 / 5.3 | 42 / 2 / 4.5 | 73 / 0 / 4.2 | 62 / 0 / 4.5 |
| ht-en | `gemini-lt` | 27 / 0 / 2.8 | 11 / 0 / 3.0 | 18 / 0 / 2.9 | 16 / 0 / 2.7 | 16 / 0 / 2.9 |

Averaged over en-es, es-en, en-ja, km-en (the four directions all four routes serve): quality % (Δ vs clean), missing of 60, duplicates, last words p50 (s).

| Route | clean | room-mic | noise-10dB | bt-narrowband | hall-reverb |
|---|---|---|---|---|---|
| `azure` | 54 / 0 / 1 / 1.0 | 5 (-48) / 27 / 1 / 0.1 | 21 (-32) / 28 / 1 / 1.0 | 35 (-19) / 6 / 2 / 0.4 | 16 (-38) / 0 / 2 / 0.0 |
| `azure-foundry` | 64 / 0 / 2 / 1.9 | 7 (-57) / 28 / 1 / 1.6 | 23 (-41) / 28 / 2 / 2.1 | 38 (-26) / 6 / 1 / 1.7 | 26 (-38) / 0 / 2 / 1.7 |
| `omni-foundry` | 70 / 0 / 9 / 5.6 | 8 (-62) / 30 / 3 / 8.8 | 28 (-41) / 24 / 7 / 9.4 | 57 (-13) / 0 / 7 / 6.6 | 33 (-36) / 1 / 7 / 8.1 |
| `gemini-lt` | 55 / 0 / 4 / 3.3 | 9 (-46) / 24 / 7 / 3.1 | 19 (-36) / 23 / 12 / 4.9 | 50 (-5) / 0 / 3 / 3.2 | 44 (-12) / 0 / 1 / 3.1 |

Per run (start→first audio p50, stop→last words p90, duplicates (judge), both-sources sentences (omni routes), stall):

| Pair | Route | Condition | Start→first audio p50 | Last words p90 | Partial | Dup | Both sources | Stall |
|---|---|---|---|---|---|---|---|---|
| en-es | `azure` | clean | 6.6 | 1.3 | 5 | 0 |  |  |
| en-es | `azure` | room-mic | 6.3 | 0.8 | 2 | 0 |  |  |
| en-es | `azure` | noise-10dB | 7.2 | 1.1 | 1 | 0 |  |  |
| en-es | `azure` | bt-narrowband | 2.8 | 0.7 | 12 | 0 |  |  |
| en-es | `azure` | hall-reverb | 1.7 | 1.1 | 13 | 0 |  |  |
| en-es | `azure-foundry` | clean | 7.9 | 2.8 | 5 | 0 |  |  |
| en-es | `azure-foundry` | room-mic | 7.3 | 1.5 | 3 | 0 |  |  |
| en-es | `azure-foundry` | noise-10dB | 8.7 | 2.1 | 0 | 0 |  |  |
| en-es | `azure-foundry` | bt-narrowband | 4.0 | 2.4 | 11 | 0 |  |  |
| en-es | `azure-foundry` | hall-reverb | 3.5 | 3.1 | 14 | 1 |  |  |
| en-es | `omni-foundry` | clean | 9.0 | 6.3 | 5 | 2 | 0 |  |
| en-es | `omni-foundry` | room-mic | 14.0 | 10.1 | 1 | 1 | 1 |  |
| en-es | `omni-foundry` | noise-10dB | 18.1 | 19.4 | 4 | 1 | 0 |  |
| en-es | `omni-foundry` | bt-narrowband | 13.2 | 8.3 | 10 | 1 | 2 |  |
| en-es | `omni-foundry` | hall-reverb | 12.5 | 12.4 | 15 | 1 | 3 (incl. 1st) |  |
| en-es | `gemini-lt` | clean | 2.2 | 4.5 | 4 | 0 |  |  |
| en-es | `gemini-lt` | room-mic | 1.2 | 39.9 | 6 | 0 |  |  |
| en-es | `gemini-lt` | noise-10dB | 1.9 | 39.2 | 5 | 2 |  |  |
| en-es | `gemini-lt` | bt-narrowband | 2.2 | 3.7 | 7 | 0 |  |  |
| en-es | `gemini-lt` | hall-reverb | 2.0 | 3.7 | 4 | 0 |  |  |
| es-en | `azure` | clean | 4.9 | 1.1 | 0 | 0 |  |  |
| es-en | `azure` | room-mic | 2.4 | 0.8 | 14 | 0 |  |  |
| es-en | `azure` | noise-10dB | 4.5 | 1.8 | 1 | 1 |  |  |
| es-en | `azure` | bt-narrowband | 5.0 | 1.0 | 1 | 1 |  |  |
| es-en | `azure` | hall-reverb | 1.7 | 0.9 | 11 | 0 |  |  |
| es-en | `azure-foundry` | clean | 5.7 | 2.2 | 0 | 1 |  |  |
| es-en | `azure-foundry` | room-mic | 4.0 | 4.6 | 14 | 1 |  |  |
| es-en | `azure-foundry` | noise-10dB | 5.9 | 3.4 | 1 | 2 |  |  |
| es-en | `azure-foundry` | bt-narrowband | 6.0 | 2.6 | 1 | 1 |  |  |
| es-en | `azure-foundry` | hall-reverb | 2.8 | 2.8 | 13 | 0 |  |  |
| es-en | `omni-foundry` | clean | 13.5 | 6.5 | 3 | 2 | 3 (incl. 1st) |  |
| es-en | `omni-foundry` | room-mic | 13.9 | 14.5 | 13 | 1 | 1 (incl. 1st) |  |
| es-en | `omni-foundry` | noise-10dB | 14.4 | 11.8 | 4 | 4 | 4 (incl. 1st) |  |
| es-en | `omni-foundry` | bt-narrowband | 13.7 | 6.2 | 4 | 2 | 2 |  |
| es-en | `omni-foundry` | hall-reverb | 13.0 | 7.4 | 5 | 5 | 5 (incl. 1st) |  |
| es-en | `gemini-lt` | clean | 1.7 | 3.7 | 4 | 1 |  |  |
| es-en | `gemini-lt` | room-mic | 1.2 | 3.7 | 11 | 0 |  |  |
| es-en | `gemini-lt` | noise-10dB | 1.3 | 4.1 | 7 | 3 |  |  |
| es-en | `gemini-lt` | bt-narrowband | 1.5 | 3.8 | 1 | 1 |  |  |
| es-en | `gemini-lt` | hall-reverb | 2.0 | 3.9 | 2 | 0 |  |  |
| en-ja | `azure` | clean | 6.7 | 1.4 | 6 | 1 |  |  |
| en-ja | `azure` | room-mic | 5.4 | 0.7 | 4 | 0 |  |  |
| en-ja | `azure` | noise-10dB | 7.3 | 0.8 | 0 | 0 |  |  |
| en-ja | `azure` | bt-narrowband | 2.8 | 0.7 | 11 | 0 |  |  |
| en-ja | `azure` | hall-reverb | 1.8 | 1.3 | 14 | 1 |  |  |
| en-ja | `azure-foundry` | clean | 7.6 | 3.0 | 3 | 1 |  |  |
| en-ja | `azure-foundry` | room-mic | 8.2 | 1.7 | 2 | 0 |  |  |
| en-ja | `azure-foundry` | noise-10dB | 9.4 | 2.2 | 0 | 0 |  |  |
| en-ja | `azure-foundry` | bt-narrowband | 4.3 | 2.1 | 11 | 0 |  |  |
| en-ja | `azure-foundry` | hall-reverb | 2.9 | 2.8 | 14 | 1 |  |  |
| en-ja | `omni-foundry` | clean | 12.1 | 7.7 | 5 | 1 | 1 (incl. 1st) |  |
| en-ja | `omni-foundry` | room-mic | 13.9 | 8.8 | 1 | 1 | 1 |  |
| en-ja | `omni-foundry` | noise-10dB | 19.0 | 16.1 | 3 | 1 | 0 |  |
| en-ja | `omni-foundry` | bt-narrowband | 13.5 | 9.7 | 9 | 1 | 2 |  |
| en-ja | `omni-foundry` | hall-reverb | 12.8 | 13.0 | 11 | 0 | 3 (incl. 1st) |  |
| en-ja | `gemini-lt` | clean | 2.3 | 3.9 | 7 | 3 |  |  |
| en-ja | `gemini-lt` | room-mic | 1.6 | 39.2 | 5 | 1 |  |  |
| en-ja | `gemini-lt` | noise-10dB | -44.8 | 25.0 | 0 | 1 |  | rerun (gap 54 s; silent from 65 s); gap 47 s; silent from 85 s |
| en-ja | `gemini-lt` | bt-narrowband | 2.2 | 4.1 | 10 | 2 |  |  |
| en-ja | `gemini-lt` | hall-reverb | 2.2 | 4.2 | 7 | 0 |  |  |
| km-en | `azure` | clean | 6.5 | 1.5 | 6 | 0 |  |  |
| km-en | `azure` | room-mic | 4.4 | 2.4 | 13 | 1 |  |  |
| km-en | `azure` | noise-10dB | 6.8 | 2.7 | 13 | 0 |  |  |
| km-en | `azure` | bt-narrowband | 6.3 | 1.5 | 8 | 1 |  |  |
| km-en | `azure` | hall-reverb | 8.7 | 1.8 | 15 | 1 |  |  |
| km-en | `azure-foundry` | clean | 8.3 | 4.0 | 6 | 0 |  |  |
| km-en | `azure-foundry` | room-mic | 6.9 | 7.9 | 13 | 0 |  |  |
| km-en | `azure-foundry` | noise-10dB | 10.6 | 8.2 | 11 | 0 |  |  |
| km-en | `azure-foundry` | bt-narrowband | 8.3 | 5.5 | 5 | 0 |  |  |
| km-en | `azure-foundry` | hall-reverb | 10.3 | 5.5 | 12 | 0 |  |  |
| km-en | `omni-foundry` | clean | 16.5 | 12.4 | 3 | 4 | 7 (incl. 1st) |  |
| km-en | `omni-foundry` | room-mic | 13.3 | 14.4 | 13 | 0 | 2 (incl. 1st) |  |
| km-en | `omni-foundry` | noise-10dB | 13.9 | 13.4 | 7 | 1 | 3 |  |
| km-en | `omni-foundry` | bt-narrowband | 16.5 | 12.1 | 3 | 3 | 5 (incl. 1st) |  |
| km-en | `omni-foundry` | hall-reverb | 13.9 | 10.5 | 8 | 1 | 3 (incl. 1st) |  |
| km-en | `gemini-lt` | clean | 3.5 | 3.7 | 10 | 0 |  |  |
| km-en | `gemini-lt` | room-mic | 3.5 | 22.4 | 9 | 6 |  |  |
| km-en | `gemini-lt` | noise-10dB | 1.3 | 4.2 | 14 | 6 |  |  |
| km-en | `gemini-lt` | bt-narrowband | 4.0 | 3.8 | 10 | 0 |  |  |
| km-en | `gemini-lt` | hall-reverb | 3.4 | 3.4 | 15 | 1 |  |  |
| ht-en | `ht-exception` | clean | 11.5 | 6.2 | 4 | 0 | 1 |  |
| ht-en | `ht-exception` | room-mic | 11.0 | 10.2 | 10 | 0 | 4 (incl. 1st) |  |
| ht-en | `ht-exception` | noise-10dB | 12.0 | 11.8 | 4 | 1 | 4 (incl. 1st) |  |
| ht-en | `ht-exception` | bt-narrowband | 11.5 | 6.4 | 4 | 0 | 1 |  |
| ht-en | `ht-exception` | hall-reverb | 11.5 | 8.3 | 7 | 0 | 1 |  |
| ht-en | `gemini-lt` | clean | 2.9 | 3.4 | 11 | 0 |  |  |
| ht-en | `gemini-lt` | room-mic | 2.6 | 3.6 | 15 | 2 |  |  |
| ht-en | `gemini-lt` | noise-10dB | 1.4 | 3.7 | 15 | 1 |  |  |
| ht-en | `gemini-lt` | bt-narrowband | 2.7 | 3.3 | 13 | 0 |  |  |
| ht-en | `gemini-lt` | hall-reverb | 3.0 | 3.7 | 14 | 0 |  |  |

## What it shows

- **Is Azure-based routing better than Gemini Live Translate on degraded
  audio? Not in general, and it depends on the source language.**
  - From **English** (en→es, en→ja) Gemini LT holds up far better under
    reverb and Bluetooth: hall-reverb 53/47% against 16/18% for Azure +
    Foundry and 9/11% for Azure alone. Bluetooth narrowband gives 51/42%
    against 20/9% and 13/11%. Azure turns reverberant English into
    fragments (13–14 of 15 sentences partial).
  - From **Spanish** they are close. Gemini LT is better in a room (33% vs
    16% for Azure + Foundry). Azure is a little better in noise (56% vs 49%).
    They tie on Bluetooth (69–71%). Omnilingual + Foundry is best in reverb
    (67%) and on Bluetooth (76%).
  - From **Khmer** Gemini LT is the weakest under degradation (reverb 16%,
    room 2%). Omnilingual 7B + Foundry is best in every condition (40–69%).
  - From **Haitian** the exception route stays far ahead (36–73% vs 11–27%).
- **Average loss against clean** (four directions): Gemini LT loses the
  least on Bluetooth (−5) and reverb (−12), against −19/−38 for Azure alone
  and −26/−38 for Azure + Foundry. In noise and room-mic every route loses
  32–62 points.
- **Most robust:** for absolute quality under degradation, `omni-foundry`
  (BT 57%, reverb 33%, noise 28% averaged; best from Spanish and Khmer). It
  is also the slowest: last words 5–12 s, rising in noise. For holding its
  clean quality and its speed, `gemini-lt`: about 3 s to the end of each
  sentence in every condition, apart from its stall. Azure alone is the
  least robust.
- **Missing sentences (the critical failure):**
  - English in noise: Azure routes went silent on 14 of 15 sentences, the
    same failure as the STT test (23 of 30). English room-mic: 11–13 of 15.
  - Gemini LT also dropped 9 of 15 English sentences in noise and room-mic.
    In en→ja noise it went silent from 65 s and, on the rerun, from 85 s
    (14 of 15 missing).
  - Omnilingual missed 10–13 English sentences in noise and room-mic.
  - From Spanish, Khmer and Haitian, no route missed more than 2 sentences
    in any condition, except Gemini LT km→en room-mic (6).
- **English noise is not a level artefact.** The English clip is about 9 dB
  quieter (−32 dBFS speech) than the others. Rerunning en→es noise-10dB
  7 dB louder (`level_check.json`) gave the same collapse: Azure + Foundry
  14 missing, Gemini LT 11 missing.
- **Stalls:** 1 Gemini LT stall, en→ja noise-10dB. The rerun stalled too
  (gap 47 s, silent from 85 s), and the rerun is the one in the table. No
  Gemini LT session ran alongside another, so this one isn't a concurrency
  stall: Gemini stopped answering in steady noise. Every other Gemini LT
  session was clean. Separately, LT's wrapper redialled the English room-mic
  pipelines 3–4 times each ("no translation output after 20 s of speech").
- **Duplicates / the Omnilingual-room leak** (LT bug, not fixed here):
  - `omni-foundry` delivered sentences from **both** Azure and omni-stt
    11 / 7 / 11 / 14 / 5 times (clean / noise / BT / reverb / room, across
    4 directions × 15). The first sentence was doubled in 11 of 20 runs.
  - Azure's share of delivered segments grows when Omnilingual struggles:
    36% clean, then 72% in hall-reverb (95 of 132) and 92% in room-mic.
    In en→es reverb, 37 of 41 segments were Azure's. That room is no
    longer an Omnilingual room.
  - `ht-exception`: 1 doubled sentence when clean, 4 in noise and in room-mic.
  - Judge-flagged duplicates per 60 sentences: Azure routes 1–2 in every
    condition. Gemini LT 1–4 when clean, rising to 9 (room) and 13 (noise),
    mostly from Khmer. omni-foundry 3–9.

## Caveats

- One run per cell, n = 15. Treat differences under about 10 points as noise.
  Cells near 0% (English in noise or room) don't rank the routes.
- The degradations are simulated and severe on purpose: one synthetic hall
  impulse response at DRR 0 dB, and a mixed HVAC + babble noise at 10 dB SNR.
  The babble is the same FLoRes sentences in other languages, and Spanish's
  includes English. Real rooms vary. Close-miking, or a mic with a high
  direct-to-reverberant ratio, avoids most of this.
- English is a single FLEURS en_us voice set that was already the fragile
  case on Oct 19. The English results may say more about that recording than
  about English.
- The judge (gemini-3.5-flash) may favour Gemini outputs. It is strict on
  recognition errors. For gemini-lt, last words is the end of the audio,
  not its onset (see Method).
- The omni-foundry route runs Azure-served languages through
  `omni-solo.patch` (not how LT routes them today), on Omnilingual 300M
  privately fine-tuned for Haitian Creole (not in the repo). Khmer uses the
  public 7B, as in LT. Azure STT ran beside it and delivered 36% of its
  segments clean, 72% in hall reverb and 92% in room-mic (see Duplicates).
- Cost is an estimate, not read from billing. About 270 session-minutes in
  total. Azure Speech translation (53 min) ≈ $2.2. Azure STT beside the
  Foundry / Omnilingual routes (125 min) ≈ $2.1. Azure TTS (78k characters)
  ≈ $1.3. Gemini Live Translate (88 min) ≈ $2. Foundry (1,106 calls) ≈
  $1–2. omni-stt Cloud Run GPUs ≈ $1.5–2. Judge ≈ $0.5. Total roughly
  **$10–12**.
- Audio and run logs are not committed. `build_degraded.py` rebuilds the
  audio deterministically, and `analyze.py` regenerates everything from the
  logs.
