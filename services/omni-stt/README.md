# omni-stt: hosted speech to text for rare languages

A small WebSocket service that does one thing: turns live speech into text with
[Meta Omnilingual ASR](https://github.com/facebookresearch/omnilingual-asr), picking
the spoken language per utterance among the few a room uses. It exists for the
languages commercial speech APIs don't serve well or at all (Haitian Creole first,
then Khmer, Lao and the rest of the stack's `asr = "omni:..."` languages) and is
meant for Google Cloud Run on an NVIDIA L4, scaled to zero.

It also speaks Haitian Creole (`/speak`, below) with two open voices, so a client
whose speech service has no Haitian voice (Azure) need not send the text elsewhere.
No translation: that is the stack's job (`server/server.py`). This service reuses
the stack's parts rather than copying them:

| Part | From the stack |
|---|---|
| Recogniser | `server/engines/omnilingual.py` (the same engine class, model card `omniASR_LLM_300M`) |
| Language ID | VoxLingua107 ECAPA (`speechbrain/lang-id-voxlingua107-ecapa`, the stack's pinned revision) with the stack's constrained argmax (`Pipeline.identify_conf`) |
| Endpointing | Silero VAD v6.2.3 and the stack's forced-cut rule, with shorter values than the stack's (see Endpointing below); a VAD copy per connection |
| Audio input | `server/audio_in.py` (fixed 96 ms blocks; 24 kHz resampled with carried filter state) |
| Voices | `server/engines/mms.py` and `coqui.py` (the same engine classes and fixes: 24 kHz resample with 3 ms edge ramps, peak level, Coqui's dead-air trim, MMS's empty-input guard), each with its own lock |
| Tokens | `server/stack_auth.py` (`STT_TOKEN` static, or `STT_SIGNING_KEY` for the stack's signed tokens), plus `STT_TOKEN_NONPROFIT` (below, Credentials) |

## Protocol

```
connect   wss://<host>/listen?langs=ht,en[&rate=24000][&transcribe=ht]
          Authorization: Bearer <token>            (or ?token=<token>; URLs get logged, so prefer the header)
server    {"type":"hello","langs":["ht","en"],"rate":16000}
client    binary: mono PCM16 at 16 kHz (24 kHz with ?rate=24000), ~100 ms per message is ideal
client    {"type":"flush"}                         optional: end the current utterance now (end of a file, push-to-talk release)
server    {"type":"language","lang":"ht","confidence":0.93,"start_ms":1200,"end_ms":4810}   as soon as it is identified
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
- `transcribe` (default: all of `langs`) is the languages whose utterances get
  words. The others get only their `language` message, sent before any
  transcribing. Live Translation's Haitian Creole exception uses
  `langs=ht,en,ja,...&transcribe=ht`: Azure keeps every other language, and an
  English utterance costs the GPU only the language ID.
- Served languages: `en es fr pt it de ru uk zh ja ko vi ar fa id tr bn ur hi sw ro ht km lo tl`
  (`OMNI_CODES` in `server.py`). Anything else is refused at connect with an error and
  close code 4400, as is a mix containing a language VoxLingua107 doesn't know.
- `start_ms`/`end_ms` count from the connection's first sample.
- Close codes: 4400 bad request, 4401 bad or missing token, 4429 at the connection limit.
- Several connections at once are fine (default limit 4 on Cloud Run, `STT_MAX_CONNECTIONS`).
  Each has its own VAD and endpointing; the models are shared and run on a single
  worker thread that batches: the utterances waiting from every connection (up to
  `STT_BATCH_MAX`, default 8) go through Omnilingual in one call, each with its own
  language code, and likewise language ID. The batch is decoded by `omni_batch.py`,
  not the library's batched call: that one prefills only the shortest prompt and
  steps through the rest of each longer one a frame at a time, so a 2 s utterance
  beside a 12 s one cost more together than apart. `omni_batch.py` left-pads the
  prompts so all of them end together, masks the padding out of the decoder's
  attention, and gives each utterance the tokens it gets decoded alone (checked
  token for token against the library on a small random decoder,
  `tests/test_omni_stt_batching.py`). `STT_ALIGNED=0` goes back to the library's
  call, with batches grouped by length (`pick_group`). After the first utterance the worker
  waits up to `STT_BATCH_WAIT_MS` (default 10) for more, but only while fewer are
  waiting than there are open streams. Each result goes back to the connection it
  came from. Each connection keeps at most 3 utterances waiting (`STT_MAX_PENDING`);
  past that the oldest is dropped and logged.
- Repetition guard: a transcript that loops (one unit, a character up to a few
  words, `STT_MAX_REPEATS` = 6 or more times in a row) is cut back to the words
  before the loop plus one copy; one longer than `STT_MAX_CHARS_PER_S` (30) per
  second of audio, plus 10, is dropped. Fired guards are logged with lengths only.

### /speak: Haitian Creole voices

```
connect   wss://<host>/speak[?voice=mms|coqui]      same token as /listen
server    {"type":"hello","lang":"ht","voices":["mms","coqui"],"voice":"coqui","rate":24000,"edition":"nonprofit"}
client    {"type":"speak","text":"Nou gen 600 moun jodi a.","voice":"mms","id":"7"}   voice and id optional
server    {"type":"sentence","id":"7","index":0,"bytes":96000}   then that sentence's audio:
          binary frames of mono PCM16 at 24 kHz (at most 1 s each)
server    {"type":"done","id":"7","voice":"mms","sentences":1,"audio_ms":2000,"first_audio_ms":180,"ms":190}
server    {"type":"error","id":"7","detail":"..."}   a refused or failed request; the socket stays open
```

- Voices: `mms` = Meta MMS-TTS `facebook/mms-tts-hat`, **CC-BY-NC-4.0**: non-commercial
  use only (fine for a non-profit service; not for a paid product).
  `coqui` = Coqui VITS `multilingual-tts/VITS-OpenBible-Haitian-Creole`, **CC-BY-SA-4.0**:
  credit the OpenBible voice. Both are baked into the image (`--build-arg
  EDITION=commercial` leaves MMS out). Their licences are `server/licences.py`'s
  (`SERVICE_VOICES`), the stack's one licence authority.
- Editions, as the stack's: `EDITION=commercial` (the default here, and in
  `deploy.sh`) never loads MMS; `nonprofit` offers both; `both` serves each
  `/speak` socket in the edition its signed token's `ed` claim names
  (`STT_TOKEN_NONPROFIT` counts as `nonprofit`), and a token without one (the
  static `STT_TOKEN`) in commercial, the stricter. The hello lists
  only the voices that edition may use; asking for another is refused like a voice
  that is not loaded (the client falls back, rather than hearing a voice it did not
  pick). A token for an edition the server does not serve is closed with 4403.
  `/listen` is the same in every edition (its models are Apache/MIT).
- The voice: the request's `voice`, else the socket's `?voice=`, else `HT_VOICE`
  (default `coqui`) when the edition allows it, else the first voice it allows.
  `STT_VOICES` limits which are loaded (naming one the edition forbids stops the server).
- Numbers are spelled out first (`ht_numbers.py`): neither voice says digits, so
  "600" would vanish. 0 to 999 999 999 999, years ("1804" -> "mil ui san kat"),
  simple ordinals ("2e" -> "dezyèm"), decimals, `%` and `$`; the sources and
  the spelling choices are at the top of that file.
- The text is spoken a sentence at a time (long sentences are cut at commas), so
  the first sentence's audio goes out while the rest is made. Requests on one
  socket are answered in order; keep the socket open between sentences.
- The voices load beside the recogniser, not before the port opens (Coqui's import
  took ~30 s on a cold instance): a `/speak` socket opened meanwhile waits for them
  (up to 120 s) before its hello; if they failed to load it is closed with 4503.
- At most 2000 characters per request; `STT_MAX_SPEAKERS` (4) open sockets,
  counted apart from `/listen`'s. Nothing about the text is logged but its length.
- A WebSocket rather than an HTTP POST: the `websockets` server here answers GET
  only, and text in a URL would land in the request logs.
- Time to first audio, one sentence, warm: on a MacBook (M2 Pro CPU) ~0.22-0.28 s
  for MMS and ~0.3-0.5 s for Coqui. On the L4 (2026-10-19, tagged revision): ~0.10-0.12 s
  at the server for either voice, ~0.14-0.18 s at a client in the US over an open socket.
  A cold instance answers /listen at its usual time and /speak about 30 s later
  (Coqui's import on a fresh instance).

`STT_SERVE=speak STT_OPEN=1 python3 services/omni-stt/server.py` runs the voices
alone (no Omnilingual), which a laptop handles; it needs `coqui-tts==0.27.5` and
`transformers==4.57.6` beside the packages below.

### Endpointing

An utterance's `language` message can only go out once the utterance ends, and
Live Translation holds its other recogniser's sentences until then, so turns
are cut short:

- `ENDPOINT_MS` (default 300): this much quiet ends a turn. The stack uses 700.
- `MAX_UTTERANCE_S` (default 6.0): a speaker who never pauses is cut by then, at
  the quietest 20 ms of the last 2 s (never the live last 300 ms), so the cut
  falls between words rather than mid-word. The stack uses 9.
- `MIN_SPEECH_MS` (default 400): a turn with less speech than this ("wi", a
  cough) is not ended by a 300 ms pause; it waits up to 700 ms for more speech,
  which joins it. Language ID on a lone syllable is close to a guess, and a wrong
  `language` sends the utterance to the wrong recogniser in the client. A word
  that really stands alone still goes out, 700 ms after it ends.

`deploy.sh deploy` passes all three through when they are set in its environment.
Other settings: `STT_MAX_CONNECTIONS`, `STT_MAX_PENDING`, `STT_DEVICE`, `OMNI_CARD`,
`STT_MODELS`, `PORT`, `EDITION`, `HT_VOICE`, `STT_VOICES`, `STT_MAX_SPEAKERS`, `STT_SERVE`
(see the top of `server.py`).

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

The server refuses to start without a credential unless `STT_OPEN=1`: an open GPU
URL is a bill anyone can run up.

### Credentials

Each app gets its own credential, and the credential says its edition:

| Credential | Who | Edition |
|---|---|---|
| `STT_SIGNING_KEY` | an app with a server that signs a token per connection (`stack_auth.py`'s format, `aud` `stack`, at most 24 h): Lithos Talk's Worker, 10-minute tokens | the token's `ed` claim (Talk: `commercial`) |
| `STT_TOKEN_NONPROFIT` | an app an operator configures by hand: Live Translation (a non-profit's app) pastes it into Service settings | `nonprofit` |
| `STT_TOKEN` | the original static token, kept so nothing breaks | none, so `commercial` |

The two static tokens must differ. With `EDITION=both`, only a `nonprofit`
connection is offered MMS. `deploy.sh` mounts the signing key and the non-profit
token when `SIGNING_SECRET` and `NONPROFIT_SECRET` name their secrets.

## Deploy (Cloud Run, L4)

`deploy.sh` (read it first; it does nothing until you call it):

```
export PROJECT=<project id>
openssl rand -hex 32 | ./deploy.sh secret    # Secret Manager secret omni-stt-token
openssl rand -hex 32 | SECRET=omni-stt-signing-key ./deploy.sh secret       # optional (Credentials)
openssl rand -hex 32 | SECRET=omni-stt-token-nonprofit ./deploy.sh secret   # optional (Credentials)
./deploy.sh build                            # Cloud Build (32 GB machine) -> Artifact Registry
./deploy.sh deploy                           # gcloud run deploy --gpu 1 --gpu-type nvidia-l4 ...
                                             # (SIGNING_SECRET=, NONPROFIT_SECRET= to mount those two)
BASE_TAG=<tag> ./deploy.sh build-voices      # the voices layered on an image built before them
BASE_TAG=<tag> ./deploy.sh build-ft          # a fine-tuned card (FT_CARD, FT_WEIGHTS) on that image
DRY_RUN=1 ./deploy.sh build-ft               # print the gcloud/docker commands, run nothing
```

Private settings (a fine-tuned card's name, its private bucket, your project and
registry) go in `private.env` beside the script, which git ignores; start from
`private.env.example`. `build-ft` and `build-voices` refuse any image that is not
in an Artifact Registry repository (`<region>-docker.pkg.dev`), and anything naming
ghcr.io, docker.io or another public registry: a fine-tuned card may be derived
from data you may not redistribute.

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
(forced 9 s cuts split the longer sentences; that run predates the 300 ms / 6 s endpointing), **CER 6.2%**, LID 56/56 Haitian (lowest
confidence 0.998), server-side real-time factor 1.76, so on this CPU the
transcripts fell minutes behind (median 82 s). On an L4 the model should be far
faster than real time; measure it after deploying.

Three streams at once (ht.wav ht,fr + en.wav ht,en + fr.wav ht,en,fr, stopped
after ~165 s of each): streams stayed separate, 83/83 utterances labelled with
their own language, ~16 min behind on this CPU. One English utterance came back
as Arabic-script text (decoded as eng_Latn): a hallucination on a streamed cut
that the clip bench did not show; watch for it on the GPU.

For reference: the same model in the stack on a GPU scored 5.7% CER on ht.wav.
