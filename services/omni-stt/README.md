# omni-stt: hosted speech to text for rare languages

A small WebSocket service that does one thing: turns live speech into text with
[Meta Omnilingual ASR](https://github.com/facebookresearch/omnilingual-asr), picking
the spoken language per utterance among the few a room uses. It exists for the
languages commercial speech APIs don't serve well or at all (Haitian Creole first,
then Khmer, Lao and the rest of the stack's `asr = "omni:..."` languages) and is
meant for Google Cloud Run on an NVIDIA L4, scaled to zero.

No translation, no voices: that is the stack's job (`server/server.py`). This
service reuses the stack's parts rather than copying them:

| Part | From the stack |
|---|---|
| Recogniser | `server/engines/omnilingual.py` (the same engine class, model card `omniASR_LLM_300M`) |
| Language ID | VoxLingua107 ECAPA (`speechbrain/lang-id-voxlingua107-ecapa`, the stack's pinned revision) with the stack's constrained argmax (`Pipeline.identify_conf`) |
| Endpointing | Silero VAD v6.2.3; 700 ms pause ends a turn, 280 ms past 5 s, forced cut at the quietest point at 9 s; a VAD copy per connection |
| Audio input | `server/audio_in.py` (fixed 96 ms blocks; 24 kHz resampled with carried filter state) |
| Tokens | `server/stack_auth.py` (`STT_TOKEN` static, or `STT_SIGNING_KEY` for the stack's signed tokens) |

## Protocol

```
connect   wss://<host>/listen?langs=ht,en[&rate=24000]
          Authorization: Bearer <STT_TOKEN>        (or ?token=<STT_TOKEN>; URLs get logged, so prefer the header)
server    {"type":"hello","langs":["ht","en"],"rate":16000}
client    binary: mono PCM16 at 16 kHz (24 kHz with ?rate=24000), ~100 ms per message is ideal
client    {"type":"flush"}                         optional: end the current utterance now (end of a file, push-to-talk release)
server    {"type":"inputTranscript","text":"...","lang":"ht","confidence":0.93,"start_ms":1200,"end_ms":4810}
server    {"type":"flushed"}                       everything before the flush has been sent
server    {"type":"error","detail":"..."}

GET /health   200 "ok" (the port opens only once the models are loaded and warm)
GET /mic      a one-file microphone test page: type the languages and the token, press Start, talk
```

- `langs` is the room's candidate languages in the stack's two-letter codes. One
  language: no language ID at all, `confidence` is 1.0. Several: the language ID
  chooses among them only, and `confidence` is the winner's share of their score.
  Omnilingual gives no confidence of its own.
- Served languages: `en es fr pt it de ru uk zh ja ko vi ar fa id tr bn ur hi sw ro ht km lo tl`
  (`OMNI_CODES` in `server.py`). Anything else is refused at connect with an error and
  close code 4400, as is a mix containing a language VoxLingua107 doesn't know.
- `start_ms`/`end_ms` count from the connection's first sample.
- Close codes: 4400 bad request, 4401 bad or missing token, 4429 at the connection limit.
- Several connections at once are fine (default limit 4 on Cloud Run, `STT_MAX_CONNECTIONS`).
  Each has its own VAD and endpointing; the models are shared and run one request at a
  time on a single worker thread, so a busy instance makes every stream later rather
  than mixing them. Each connection keeps at most 3 utterances waiting (`STT_MAX_PENDING`);
  past that the oldest is dropped and logged.

VoxLingua107 covers ht (Haitian), km (Central Khmer) and lo (Lao), checked
against the model's `label_encoder.txt` (107 labels; ht = 37, km = 49, lo = 55).

## Run it

```
STT_OPEN=1 STT_MODELS=/tmp/stt-models python3 services/omni-stt/server.py        # port 8080
node services/omni-stt/client.mjs eval/2026-10-real-voices/audio/ht.wav ht,en --refs eval/2026-10-real-voices
node services/omni-stt/client.mjs ht.wav ht,en en.wav ht,en fr.wav ht,fr          # three streams at once
python3 services/omni-stt/bench.py --eval eval/2026-10-real-voices --audio ht,en,fr --sets ht,en ht,fr ht,en,fr
```

Packages: as the stack's (`constraints.txt`): torch 2.8, `omnilingual-asr` with
`torchaudio==2.8.0 scipy==1.13.1` in one pip call, `speechbrain`, `websockets`.
On macOS (Apple silicon, Python 3.12) everything installs from wheels; pin
`pyarrow==25.0.1` too or Omnilingual's import fails on numpy 1.26.

The server refuses to start without `STT_TOKEN`/`STT_SIGNING_KEY` unless `STT_OPEN=1`:
an open GPU URL is a bill anyone can run up.

## Deploy (Cloud Run, L4)

`deploy.sh` (read it first; it does nothing until you call it):

```
export PROJECT=<project id>
openssl rand -hex 32 | ./deploy.sh secret    # Secret Manager secret omni-stt-token
./deploy.sh build                            # Cloud Build (32 GB machine) -> Artifact Registry
./deploy.sh deploy                           # gcloud run deploy --gpu 1 --gpu-type nvidia-l4 ...
```

Needed first, once: the APIs (Run, Artifact Registry, Cloud Build, Secret Manager),
an Artifact Registry Docker repository `omni-stt` in `us-central1`, and Cloud Run L4
GPU quota in that region (without zonal redundancy: the script deploys with
`--no-gpu-zonal-redundancy`).

The image (~12 GB unpacked) has every model inside, so a cold start reads disk
instead of downloading 6 GB. Rebuilding after a code change re-runs the model
fetch (the code is copied before it); fine for now, worth splitting if builds get frequent.

### Cost model

- **Scale to zero** (`--min-instances 0`): no instance, no bill. The first caller
  after idle waits for a cold start (image pull of a ~12 GB image plus model load
  and warm-up; measure it on the first deploy, expect tens of seconds to minutes).
  `--min-instances 1` removes that and bills the L4 around the clock.
- **Billed while an instance exists**, which with `--no-cpu-throttling` (required
  with a GPU) is from start until Cloud Run retires it after the last connection
  closes (about 15 idle minutes). Price: the L4 plus 4 vCPU and 16 GiB per second;
  check the current Cloud Run GPU pricing for the region.
- **One instance** (`--max-instances 1`), up to 4 streams. More rooms at once need
  a higher max (each instance is another L4) or a smaller per-stream cost.
- **WebSockets end after an hour** (`--timeout 3600` is Cloud Run's ceiling).
  Clients must reconnect when the socket closes and resend nothing: the server
  keeps no state between connections. A room longer than an hour sees one
  reconnect per hour, and an utterance in flight at that moment is lost.

## Measured locally

2026-10-17, MacBook Pro M2 Pro (16 GB, busy, swapping), CPU only, float32,
`omniASR_LLM_300M`, eval/2026-10-real-voices (30 read sentences per language;
ht real Haitian voices, en and fr from FLEURS). CER as judge.py: NFKC,
lowercase, letters and digits, pooled over all characters.

Clip by clip (`bench.py`, each sentence cut at its marks):

| Audio | CER (right language) | LID ht,en | LID ht,fr | LID ht,en,fr | CPU real-time factor |
|---|---|---|---|---|---|
| ht (298 s) | **4.2%** | 30/30 | 29/30 | 29/30 | 1.7 |
| en (216 s) | 10.5% (mostly numerals: "15" vs "fifteen") | 30/30 | – | 30/30 | 2.7 |
| fr (208 s) | 6.8% | – | 30/30 | 30/30 | 3.0 |

Haitian Creole vs French, confusion (rows: spoken, columns: picked):

| ht,fr | ht | fr | | ht,en,fr | ht | en | fr |
|---|---|---|---|---|---|---|---|
| ht | 29 | 1 | | ht | 29 | 0 | 1 |
| fr | 0 | 30 | | en | 0 | 30 | 0 |
| | | | | fr | 0 | 0 | 30 |

The one miss (ht sentence 28, 7 s, "Nan diskou l, Majistra Mase deklare pòt Jakmèl
louvri...") went to French at 0.514, a coin toss. Across the 30 Haitian clips the
Haitian share among ht,fr was 0.486 (that one), then 0.948, 0.969, 0.984 and 0.99+ for
the other 26; on all 30 French clips it was 0.000. So requiring French to win by
more than ~0.6 before overriding Haitian would have fixed the miss and cost
nothing on this set (30 clips each: a hint, not a calibration).
Decoding a sentence with the wrong language code mostly gives the same text:
Omnilingual follows the audio more than the hint.

Streaming in real time (server + `client.mjs`, ht.wav, langs=ht,en): 56 utterances
(forced 9 s cuts split the longer sentences), **CER 6.2%**, LID 56/56 Haitian (lowest
confidence 0.998), server-side real-time factor 1.76, so on this CPU the
transcripts fell minutes behind (median 82 s). On an L4 the model should be far
faster than real time; measure it after deploying.

Three streams at once (ht.wav ht,fr + en.wav ht,en + fr.wav ht,en,fr, stopped
after ~165 s of each): streams stayed separate, 83/83 utterances labelled with
their own language, ~16 min behind on this CPU. One English utterance came back
as Arabic-script text (decoded as eng_Latn): a hallucination on a streamed cut
that the clip bench did not show; watch for it on the GPU.

For reference: the same model in the stack on a GPU scored 5.7% CER on ht.wav.
