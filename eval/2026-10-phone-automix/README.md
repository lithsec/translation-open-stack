# One phone at a time, and our own PA as a reference: phone bleed in a conversation room (October 2026)

Live Translation's conversation rooms (phone-made groups) mix every phone that is talking. Phones
round one table hear each other, so a neighbour's words reach the mix a second time from your
phone, tagged with your language. Two production techniques, both plain DSP light enough for the
central Raspberry Pi 5 that runs Live Translation, were built into the app
(lithsec/live-translation PR #248) and measured here:

1. **An automixer** — "one phone at a time per room", as meeting-room automatic mixers do: only
   the phone nearest whoever is talking (the loudest) reaches the mix, or every phone is turned down
   by how far it is below the rest (Dugan-style gain sharing).
2. **The room speaker as a reference** — the PA plays audio we sent it, so we hold an exact copy:
   find it in each phone's audio and drop what is only the PA.

The owner-voice (speaker-embedding) gate is measured separately (`../2026-10-switch-detection`) and
listed for reference only; its scenario differs.

## The room (simulated; audio local only, not committed)

`build_room.py`. Four people round a 1.2 m × 1.0 m table, each with their phone 0.35 m in front of
them, all speaking English so a leak is recognisable in a transcript.

- **Speech:** FLEURS `en_us` test sentences (CC BY 4.0), 6 per person, 24 turns in random order, gaps
  −0.4 to 0.9 s (6 turns overlap the previous one). People differ in loudness (+3, 0, −3, −1.5 dB)
  and phones in mic gain (+2, 0, −2, +1 dB).
- **Paths:** every talker reaches every phone with distance attenuation (0.35 m / d: neighbours
  arrive 7.4–10.8 dB down), the matching delay, and a synthetic room tail (RT60 0.5 s, the same level
  at every phone).
- **PA:** a room speaker 2.5 m from the table plays "translations" (Azure TTS of other FLEURS
  sentences) 1–2 s after each turn, queued, through its own tail (RT60 0.7 s), sounding 250 ms after
  the app sent it. Scenes: **nopa**, **pa20** and **pa10** (PA 20 / 10 dB under a talker at their
  own phone), **pa0** (as loud as a talker: a table right under a speaker).
- **Uplink:** each phone's 100 ms frames arrive 120–200 ms after they end, plus 0–30 ms jitter.

## What runs (`run_methods.mts`)

The app's own code, frame by frame, as the app runs it:

- **Phone:** the listener page's hands-free gate (slider 0.031 RMS, 250 ms sustain, 900 ms
  hangover, 0.5 s pre-roll) and, in conversation rooms, `OwnVoiceGate` (pass only speech within
  12 dB of the wearer's learned level) — what ships today.
- **Server:** the PA filter on arrival, one queue per phone, a mixer tick every 100 ms taking one frame
  per phone through `PhoneAutomix`.

| Method | Phone | Server |
|---|---|---|
| slider | slider gate only (before OwnVoiceGate) | — |
| ownvoice | slider + OwnVoiceGate (**today**) | — |
| automix_gate | today | one phone at a time: open within 4 dB of the loudest, 300 ms hold, 300 ms pre-roll |
| automix_share | today | gain sharing |
| pa_gate | today | PA: drop frames whose waveform correlates ≥ 0.35 with the copy |
| pa_nlms | today | PA: 32 ms NLMS subtraction, drop frames mostly PA |
| pa_predict | today | PA: drop frames no louder (+1.5 dB) than the copy's reverb-smeared energy × a learned gain, that also correlate ≥ 0.1 |
| automix_pa_predict | today | automix_gate + pa_predict |

The PA filters first find the copy's delay in each phone by GCC-PHAT (whitened cross-correlation),
trusted once two estimates agree within 4 ms; frames within a burst of speech are laid back to back
to take out Wi-Fi jitter. They found 404–470 ms in every phone (the true values are 258 ms + each
phone's uplink + jitter). Loudness-envelope correlation, tried first, locked onto the talkers'
syllable rhythm instead.

## Scoring (`score.py`)

- **Time, from the ground truth:** share of each phone's owner-speech frames that reach the mix;
  share of frames where only *other* people (or only the PA) are sounding that do; turns that reach
  the mix from a second phone as well (a duplicate).
- **Words:** each phone's contribution, as it would enter the mix, is transcribed (Azure fast
  transcription, en-US) and aligned to the turns overlapping each phrase. **Owner words lost**: the
  owner's words missing. **Neighbours' words leaked**: other talkers' words found in a phone's output,
  as a share of all their words × 3 phones. **PA words leaked**: likewise × 4 phones.

Words are scored against FLEURS's written text, so recordings that differ from it count against
every method alike; owner words lost is about 11% even with nothing in the way.

## Results (`results.json`)

**No PA** (24 turns):

| Method | Owner speech kept | Owner words lost | Neighbours' words leaked | Only-others frames passed | Turns sent twice |
|---|---|---|---|---|---|
| slider | 95.5% | 11.8% | 26.5% | 31.1% | 13 |
| ownvoice (today) | 95.4% | 11.8% | 24.1% | 29.8% | 11 |
| **automix_gate** | **95.3%** | **10.8%** | **5.5%** | **11.4%** | **7** |
| automix_share | 95.4% | 11.3% | 21.5% | 29.8% | 11 |

**With a PA:**

| Scene | Method | Owner speech kept | Owner words lost | Neighbours' words leaked | PA-only frames passed | PA words leaked |
|---|---|---|---|---|---|---|
| pa20 | ownvoice (today) | 95.5% | 11.5% | 22.9% | 3.8% | 0.1% |
| pa20 | **automix_gate** | 95.5% | 12.0% | **5.8%** | 3.6% | 0.1% |
| pa20 | pa_gate | 90.4% | 10.8% | 22.5% | 2.0% | 0.1% |
| pa20 | pa_nlms | 95.5% | **86.8%** | 5.6% | 3.8% | 20.5% |
| pa20 | pa_predict | 84.7% | 15.4% | 23.1% | 1.1% | 0.1% |
| pa20 | automix_pa_predict | 84.6% | 15.9% | 12.4% | 1.0% | 0.1% |
| pa10 | ownvoice (today) | 95.7% | 12.5% | 23.7% | 5.5% | 0.2% |
| pa10 | **automix_gate** | 95.7% | 14.0% | **13.1%** | 5.3% | 0.5% |
| pa10 | pa_gate | 82.3% | 25.0% | 18.5% | 2.3% | 0.1% |
| pa10 | pa_nlms | 95.6% | 90.7% | 5.1% | 5.4% | 31.9% |
| pa10 | pa_predict | 84.6% | 16.9% | 22.2% | 1.4% | 0.4% |
| pa10 | automix_pa_predict | 84.6% | 16.9% | 12.8% | 1.4% | 0.2% |
| pa0 | ownvoice (today) | 97.9% | 69.4% | 6.0% | 94.9% | 72.9% |
| pa0 | automix_gate | 97.9% | 62.7% | 2.8% | 90.9% | 66.2% |
| pa0 | pa_gate | 65.8% | 63.5% | 7.8% | 40.6% | 3.9% |
| pa0 | pa_predict | 88.0% | 48.3% | 8.1% | 54.3% | 27.4% |
| pa0 | automix_pa_predict | 88.0% | 50.5% | 2.5% | 53.0% | 24.5% |

**CPU** (Node on an M2 Mac, per audio-second): automixer 0.3–0.6 ms for a room of four in gating
mode (gain sharing up to 1.3 ms); PA filter 2.5–3.2 ms per phone. On a Pi 5, assuming 3–5× slower,
that is well under 1% of a core per room for the automixer and about 1–1.5% per phone for the filter.

## What it shows

- **One phone at a time works.** With no PA, neighbours' words reaching the mix fall from 24% to
  5.5%, and turns sent from a second phone from 11 to 7, with no loss of the speakers' own words or
  sentence starts. It holds with a PA at −20 dB (22.9% → 5.8%); at −10 dB the PA keeps every phone's
  level up and the gain is smaller (23.7% → 13.1%).
- **Today's `OwnVoiceGate` does almost nothing at a table** (24.1% against 26.5% with the slider
  alone), as its own comment expects: with phones on the table and no headsets, a neighbour 7–11 dB
  down sits inside its 12 dB window.
- **Margin:** a sweep (time metrics only) of 3, 4, 6 and 8 dB, envelope release 60–300 dB/s and hold
  250–400 ms put the knee at 3–4 dB with a 150 dB/s release; 4 dB is the default, leaving room for
  two people of different loudness talking at once. Comparing each phone against its own wearer's
  learned level instead of raw levels was tried and did slightly worse.
- **Gain sharing** barely helps (24.1% → 21.5%): turning a neighbour's copy down 8 dB still leaves
  it recognisable.
- **The PA is mostly kept out already.** The phones' own voice gates rarely open on a PA at −10 or
  −20 dB: 4–6% of PA-only frames pass, and PA words almost never reach a transcript (≤ 0.5%).
  Every PA filter cut that further but also dropped 5–18% of the owner's own audio while the PA
  played, because the PA's level in a phone has to be learned from frames that also carry speech.
- **Right under a speaker** (pa0) the PA dominates: 73% of its words reach the mix and owners lose
  69% of theirs. The energy-prediction filter cuts PA words to 27% and owners' words lost to 48%,
  at the cost of 10% of owner frames; waveform-correlation gating cuts PA words to 4% but drops a
  third of owner frames.
- **NLMS cancellation failed:** as implemented, without a proper double-talk detector, the filter
  adapted on the talkers' speech and its output came out louder than its input (owners lost 87–91% of
  their words). It is not kept; `mic-duck.ts` in the app records the same limit for the room mic.

## Recommended defaults (as shipped in the app PR)

- **One phone at a time: on** in conversation rooms, 4 dB margin, 300 ms hold, 300 ms pre-roll,
  150 dB/s release. A phone alone in its room passes untouched.
- **Room-speaker filter: off,** offered as experimental, for a table right under a speaker.
- Owner-voice gate (speaker embeddings): pending the small-model results; it would plug in per phone,
  before the mixer.

## Limits

- One simulated room, one seat layout, synthetic reverb, one TTS voice on the PA, one run.
- Everyone speaks English, so leaks are recognisable; in a real conversation room phones speak
  different languages, and a leaked copy of another language does more damage (it is translated as
  if it were this phone's language).
- Phone uplink is simulated as constant plus 0–30 ms jitter; no packet loss or bursts.
- The phones' browser echo cancellation and noise suppression are not simulated.
- No real phones or Pi measured; Pi 5 CPU is estimated from the Mac figures.

## Reproduce

```
# needs sox, numpy; Azure Speech key (TTS and fast transcription)
AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I build_room.py ../2026-10-real-voices ROOM
npx tsx run_methods.mts <live-translation>/src ROOM OUT      # LT at 0ccdf82 (pa_gate/pa_nlms: c439b40)
AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python3 -I score.py ROOM OUT results.json
```

`run_methods.mts` takes `ONLY`, `SCENES`, `AUTOMIX` and `PACANCEL` (JSON option overrides) for
tuning runs, and `NOASR=1 score.py` scores time metrics only.
