# The 7B alone: Haitian Creole language ID and voices on the 7B service (October 2026)

Can an install drop omni-stt (the 300M card) and keep only the Omnilingual 7B
service, with Amazon Transcribe hearing Haitian Creole? omni-stt does three
jobs today: it hears Haitian Creole, it tells when a speaker switches into
Haitian Creole (VoxLingua107 language ID among the room's languages), and it
speaks Haitian Creole (`/speak`: MMS-TTS and Coqui VITS). The 7B service is the
same `server.py` with another card, so it already accepts `ht` among its
`?langs=` candidates and runs the same language ID; what it lacked was the
voices. This round puts the voices into the 7B image
(`services/omni-stt/7b/Dockerfile.base`) and measures the result on the GPU
Cloud Run uses:

1. GPU memory with the 7B, VoxLingua107, Silero VAD and both voices loaded,
   idle and while it hears and speaks at once. Does it fit an L4?
2. Hearing and voice latency against the separate services.
3. Haitian Creole language ID among realistic candidate sets on unseen clips,
   short ones included: false switches and missed switches.
4. The 7B's own Haitian Creole CER against the 300M's on the same clips (the
   fallback when no Transcribe hand-off is set up).

Run 2026-10-28 on one NVIDIA L4 (23 034 MiB usable, as on Cloud Run) in a
RunPod Secure Cloud pod (14 vCPU). `pod_setup.sh` rebuilt the 7B image's file
system by hand: `7b/Dockerfile.base`'s installs with the voices (coqui-tts
0.27.5, transformers 4.57.6, torch 2.8.0+cu128), Meta's stock checkpoint
converted to bf16 by `7b/to_bf16.py`, the cards, and the models fetched by the
server's own code. The 300M ran from a local copy of Meta's stock checkpoint
(a card with the same base, `omniASR_LLM_300M_local`). Servers ran open on
localhost with `EDITION=nonprofit` (both voices); clients on the pod itself
(`bench.py`), so the latencies below are the server's, not a network's.

Clips (`prep_clips.py`, not committed): 60 CMU Haitian Creole read sentences
(2-25 words, spread over speakers, none of the 30 sentences
[eval/2026-10-real-voices](../2026-10-real-voices/) used), and 60 each of FLEURS
test English (en_us), French (fr_fr) and Spanish (es_419), none of that
round's sentence ids. Nothing here tuned anything on them. `results.json`
holds the summaries; no audio and no transcripts are kept.

## Summary

- **It fits, with room.** The 7B service with the voices: 16.75 GB of GPU
  memory idle (16.36 GB without them), **17.4 GB at the peak** of six
  hearing streams beside four voice streams, and of four beside two: about
  **5.6 GB of the L4's 23.0 GB to spare**. Process memory 3.0-3.2 GB (16 GiB
  on Cloud Run is plenty, with `OMNI_MMAP=1`). The voices cost about 0.4 GB
  idle and 0.7 GB at the peak.
- **Voices as fast as on omni-stt.** First audio at the client, p50/p90:
  0.103/0.122 s alone, 0.113/0.173 s with four hearing streams beside, against
  0.105/0.131 s and 0.111/0.136 s on omni-stt. MMS ~0.08 s, Coqui ~0.12 s.
- **Hearing as fast.** The `language` message 0.04 s (p50) after an
  utterance's end on every server (p90 ~0.5 s: an utterance under a second
  waits for more, `MIN_SPEECH_MS`). The 7B's Haitian Creole words p50/p90
  0.50/1.34 s after the end with four streams, against 0.40/1.00 s on the
  300M; 0.64/1.63 s with six.
- **Language ID is the same model and rule on both services**, so the switch
  detection a 7B-only room gets is omni-stt's. On whole utterances: no false
  switch into Haitian Creole in 480 non-Haitian clip decisions, and 1-4
  missed of 60 Haitian Creole utterances (2-7%, worst beside French). Short
  utterances miss more: at 1 s, 5-16 of 60 in a two-language room and 22 of 60
  among four, with 3-6 false switches.
- **The 7B is not the better Haitian Creole recogniser**: pooled CER 8.1%
  against the 300M's 5.4% on the same 60 clips (median clip 3.4% against
  3.0%; each won about as many clips). Its losses are a few utterances
  written in French spelling ("est-ce que c'est pas pays...") and one loop.
  So the 7B-only layout hands Haitian Creole's words to Amazon Transcribe
  (`ht-HT`: 6.3% in the October real-voices round), and uses the 7B's own
  words only where no Transcribe is set up.

## Memory and latency

GPU memory from `nvidia-smi` every 200 ms; idle is after start-up and warm-up.
Latencies in seconds, p50 / p90. Hearing streams play their clips in a room's
order (English, Haitian Creole, English, ...; French and Spanish too in the
four-language run) at real time, `transcribe=ht` (the 7B writes the Haitian
Creole) unless stated. A voice stream asks for one CMU sentence after the
other, voices alternating, paced at each sentence's audio length.

| Server | Streams (hear + speak) | GPU memory | GPU busy | `language` after end | Words after end | Voice first audio | RSS |
|---|---|---|---|---|---|---|---|
| omni-stt (300M + voices) | idle | 4.10 GB | | | | | 3.9 GB |
| | 1 + 0 | 4.32 GB | 5% | 0.04 / 0.52 | 0.48 / 1.00 | | |
| | 0 + 1 | 4.54 GB | 1% | | | 0.105 / 0.131 | |
| | 4 + 2 | 4.62 GB | 20% | 0.04 / 0.49 | 0.40 / 1.00 | 0.111 / 0.136 | 4.1 GB |
| 7B, `/listen` only (today's omni-stt-7b) | idle | 16.36 GB | | | | | 2.0 GB |
| | 1 + 0 | 16.71 GB | 6% | 0.05 / 0.52 | 0.58 / 1.18 | | |
| | 4 + 0 | 16.73 GB | 23% | 0.04 / 0.52 | 0.47 / 1.28 | | 2.1 GB |
| **7B with the voices** | idle | **16.75 GB** | | | | | 3.0 GB |
| | 1 + 0 | 16.96 GB | 6% | 0.04 / 0.52 | 0.53 / 1.15 | | |
| | 0 + 1 | 16.99 GB | 1% | | | 0.103 / 0.122 | |
| | 4 + 2 | 17.19 GB | 25% | 0.05 / 0.52 | 0.50 / 1.34 | 0.113 / 0.173 | 3.1 GB |
| | 4 + 2, `ht,en,fr,es`, `transcribe=none` | 17.40 GB | 2% | 0.03 / 0.38 | (none asked) | 0.081 / 0.133 | 3.1 GB |
| | **6 + 4** | **17.40 GB** | 35% | 0.05 / 0.53 | 0.64 / 1.63 | 0.114 / 0.157 | 3.2 GB |

Per voice, 7B with the voices at 6 + 4: MMS 0.086 / 0.140 s (34 sentences),
Coqui 0.128 / 0.157 s (33). No errors and no voice failures in any run. Start
to ready: 10 s for the 7B (checkpoint from the page cache), the voices 8 s
after that.

With `transcribe=none` (language ID only, what the Transcribe hand-off asks
for) the GPU is idle but for the voices and the language ID: 2% busy with four
streams, against 25% when the 7B also writes the Haitian Creole.

## Haitian Creole language ID (`offline.py lid`)

VoxLingua107 ECAPA with the service's constrained argmax
(`server.constrained_choice`), on each clip whole and cut to its first 3, 2,
1.5 and 1 s. "Missed" is a Haitian Creole clip given to another language (a
switch into Haitian Creole the room would not catch); "false" is another
language's clip given to Haitian Creole.

| Candidates | whole: missed / false | 3 s | 2 s | 1.5 s | 1 s |
|---|---|---|---|---|---|
| ht, en | 2/60 · 0/60 | 1/58 · 0/59 | 5/60 · 0/60 | 7/60 · 0/60 | 9/60 · 3/60 |
| ht, fr | 4/60 · 0/60 | 8/58 · 0/60 | 13/60 · 1/60 | 12/60 · 2/60 | 16/60 · 4/60 |
| ht, es | 1/60 · 0/60 | 0/58 · 0/60 | 2/60 · 0/60 | 3/60 · 0/60 | 5/60 · 3/60 |
| ht, en, fr | 4/60 · 0/120 | 8/58 · 0/119 | 14/60 · 1/120 | 15/60 · 2/120 | 21/60 · 6/120 |
| ht, en, fr, es | 4/60 · 0/180 | 8/58 · 0/179 | 14/60 · 1/180 | 16/60 · 2/180 | 22/60 · 6/180 |

(Two Haitian Creole clips are under 3 s, so their 3 s row is the whole clip.)

- French is the confusable, as before: the misses beside French are most of
  the misses everywhere. Spanish and English are rarely mistaken for Haitian
  Creole on whole utterances (none here).
- The service never decides on a lone second: an utterance with less than
  `MIN_SPEECH_MS` (1 s) of speech waits up to 700 ms for more. Through the
  service, 96-97% of `language` messages matched the clip they fell in with
  `ht,en` on both servers (109 of 113 at 4 + 2, 164 of 170 at 6 + 4), and 92%
  (107 of 116) among `ht,en,fr,es` (the bench's attribution by time is
  approximate at clip boundaries).
- A hint, not a calibration: a Haitian Creole bias (Haitian Creole whenever
  its share among the candidates is at least 0.2) took the whole-utterance
  misses beside French from 4 to 0 without a false switch on these clips,
  and at 2 s from 13 to 5 for one more false switch. It was found on the same
  clips, so it needs other unseen clips before it changes a default.

## Haitian Creole CER (`offline.py cer`)

The 60 Haitian Creole clips whole, each decoded with the `ht` code
(`hat_Latn`), batched as the service does (`server.decode_batch`), then the
repetition guard. CER as `eval/tools/judge.py`.

| Card | Pooled CER | Mean clip CER | Median clip CER |
|---|---|---|---|
| omniASR_LLM_300M (omni-stt) | **5.4%** | 6.4% | 3.0% |
| omniASR_LLM_7B (bf16) | 8.1% | 9.9% | 3.4% |

The 7B was better on 20 clips, the 300M on 18, the rest equal. Its worst
clips: one sentence in French spelling throughout (58% against 17%), two
partly so, and one loop the guard cut. The 7B's Lao and Khmer advantage does
not carry over to Haitian Creole.

## Files

- `pod_setup.sh`: the pod's installs and models (the 7B image's file system).
- `prep_clips.py`: the unseen clips.
- `offline.py`: language ID (`lid`) and CER (`cer`) by the server's code.
- `bench.py`: hearing and voice streams at once against one server, GPU sampled.
- `run_all.sh`: every server run in the tables, one server at a time.
- `results.json`: the summaries.
