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
| Endpointing | Silero VAD v6.2.3, shorter values than the stack's, and a forced cut at a pause the VAD heard (the stack's quietest-instant rule only as a fallback) (see Endpointing below); a VAD copy per connection |
| Audio input | `server/audio_in.py` (fixed 96 ms blocks; 24 kHz resampled with carried filter state) |
| Voices | `server/engines/mms.py` and `coqui.py` (the same engine classes and fixes: 24 kHz resample with 3 ms edge ramps, peak level, the dead-air trim, MMS's empty-input guard), each with its own lock |
| Tokens | `server/stack_auth.py` (`STT_TOKEN` static, or `STT_SIGNING_KEY` for the stack's signed tokens), plus `STT_TOKEN_NONPROFIT` (below, Credentials) |

## Protocol

```
connect   wss://<host>/listen?langs=ht,en[&rate=24000][&transcribe=ht]
          Authorization: Bearer <token>            (a browser: Sec-WebSocket-Protocol: omni-stt, bearer.<token>)
server    {"type":"hello","langs":["ht","en"],"rate":16000}
client    binary: mono PCM16 at 16 kHz (24 kHz with ?rate=24000), ~100 ms per message is ideal
client    {"type":"flush"}                         optional: end the current utterance now (end of a file, push-to-talk release)
server    {"type":"language","lang":"ht","confidence":0.93,"start_ms":1200,"end_ms":4810}   as soon as it is identified
server    {"type":"inputTranscript","text":"...","lang":"ht","confidence":0.93,"start_ms":1200,"end_ms":4810}
server    {"type":"flushed"}                       everything before the flush has been sent
server    {"type":"error","detail":"..."}

          with STT_PARTIALS=1 only (off by default), while a piece is still being spoken:
server    {"type":"partial","text":"...","lang":"ht","confidence":0.93,"start_ms":1200,"end_ms":2700}
server    {"type":"stable","text":"...","delta":"...","lang":"ht","confidence":0.93,"start_ms":1200,"end_ms":2700}

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
- The token: the `Authorization` header, or, from a browser (which cannot set
  that header on a WebSocket), the two subprotocols `omni-stt` and
  `bearer.<token>` (`new WebSocket(url, ["omni-stt", "bearer." + token])`; the
  server answers `omni-stt` and never echoes the token). `?token=<token>` still
  works but is deprecated: a URL is written to Cloud Run's request log, and the
  server logs a warning when a client uses it.
- Signed tokens (`STT_SIGNING_KEY`): `"aud": "omni-stt"` or `"stack"`. A token
  with `omni-stt` opens this service and not a stack (the stack takes only
  `stack`), so a leaked one cannot open a stack signed with the same key.
  Issuers mint `stack` today and should move to `omni-stt`; `stack` stays
  accepted until they have.
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
- Partial text (`STT_PARTIALS=1`; off by default): about every `STT_PARTIAL_MS`
  (1500) of audio the piece being spoken is decoded again as it stands, and
  the whole hypothesis goes out as `partial`; the leading words that two
  passes in a row agree on go out as `stable` (`text`: everything committed so
  far for the piece; `delta`: the words this message adds). A `stable` is never
  retracted within a piece, but the final `inputTranscript` replaces every
  partial of its piece, and is exactly what it would be with partials off.
  `start_ms` is the piece's (the same as its final's); `end_ms` is how far the
  pass heard. The pass's `lang` is the language ID's guess on the audio so
  far, and may differ from the final's. Costs the GPU about 3-4x per piece:
  [docs/dev/omni-stt-partials.md](../../docs/dev/omni-stt-partials.md).

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
  static `STT_TOKEN`) in commercial, the stricter. A token without a claim is
  commercial in every edition: on a `nonprofit`-only server its `/speak` is
  refused with 4403 (there are no commercial voices to give it; its `/listen` is
  served as ever). Unlike the stack, whose claim-less `STACK_TOKEN` gets the
  edition served; an open server (`STT_OPEN=1`) still does that. The hello lists
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
- Dead air is trimmed (`trim_silence` in `server/engines/common.py`, shared with
  the stack): both voices pad silence onto each sentence, and the listener waits
  through it twice, before the first sound and before the next sentence. A 10 ms
  frame counts as voiced when its RMS is within 40 dB of the clip's peak (the
  audio is peak-normalised to -1 dBFS first) and above -45 dBFS; the sentence
  keeps 60 ms before the first voiced frame and 80 ms after the last, nothing is
  padded when there was less, and audio with no voiced frame is sent as it is.
  The 3 ms edge ramps are applied after the trim. Measured on the stored samples
  of `eval/2026-10-ht-voices` (six sentences per voice, `silence.py`): MMS
  padded 10-300 ms in front (median 280) and 50-380 ms behind (median 266),
  7% of its audio and up to 17% of a short sentence, so the trim takes 5% off;
  Coqui had already been cut by its earlier rule (a second of dead air at each
  end, trimmed to 50 ms) and showed 40-50 ms in front and 35-51 ms behind, 1%,
  which the new rule leaves alone. Thresholds from 35 to 50 dB below the peak
  moved the edges by at most 30 ms on these samples, so the rule is nowhere
  near the speech. Not yet measured: the live voices on the GPU with the trim
  in place (the samples here went through an MP3 round trip).
- The voices load after the recogniser is built and warm, while the port is
  already open (Coqui's import took ~30 s on a cold instance). Not at the same
  time as the recogniser: transformers builds a voice under `init_empty_weights`,
  which patches `torch.nn.Module.register_parameter` for every thread, and a
  recogniser built meanwhile came up with weights on the meta device (cold
  starts crashed in the warm-up, 2026-10-21). A `/speak` socket opened meanwhile waits for them
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

- `ENDPOINT_MS` (default 200): this much quiet ends a turn. The stack uses 700.
- `MAX_UTTERANCE_S` (default 10.0): a speaker who never pauses is cut by then. The
  stack uses 9. The cut goes at the best pause of the last `CUT_WINDOW_S` (3.5 s,
  at most a third of the cap: 3.33 s with the default): a run of Silero's 32 ms
  windows under `CUT_DIP_PROB` (0.5) lasting `CUT_DIP_MS` (96) or more, the
  longest (then the lowest, then the latest), at its quietest 20 ms. The audio
  after the cut starts the next utterance (nothing lost, nothing sent twice).
  Inside that window a shorter pause, `CUT_ENDPOINT_MS` (200) of quiet, cuts at
  once rather than waiting for the cap (0: off). With no pause at all it falls
  back to the old rule, the quietest 20 ms of the last 2 s, which on unbroken
  speech often lands inside a word (a stop consonant's closure is as quiet as a
  gap); `CUT_WINDOW_S=0` restores that rule. Measured in `eval/2026-10-pause-cut`.
- `CUT_EARLY_S` (default 4.0): the progressive pause cut. Once a turn has run
  this long, the quiet that ends it falls in a straight line from `ENDPOINT_MS`
  to `CUT_ENDPOINT_MS` at the cap, so a long piece ends at a breath of its own
  well before the cap instead of at the cap's look-back. It only matters when
  `ENDPOINT_MS` is above `CUT_ENDPOINT_MS` (with the 200 ms default the two are
  equal); 0 disables it. On the news clip below, 700 ms / 15 s with it gives
  32 pieces of 8.9 s (median) and none cut at the cap, against 27 of 12.7 s.
- `MIN_SPEECH_MS` (default 1000): a turn with less speech than this ("wi", a
  cough, a phrase under a second) is not ended by a 200 ms pause; it waits up to
  700 ms for more speech, which joins it. Language ID on a lone syllable is close
  to a guess, and a wrong `language` sends the utterance to the wrong recogniser
  in the client; a sub-second fragment is also a poor piece to translate. A word
  that really stands alone still goes out, 700 ms after it ends.

The defaults were 300 ms / 6 s / 400 ms, and the Haitian Creole service ran at
700 ms / 15 s until 2026-10-21. Five minutes of continuous news speech
(`eval/2026-10-continuous-ht`, one presenter) showed what each setting does.
The presenter's pauses, from Silero's probability per 32 ms window (threshold 0.5):

| Gaps of at least | Per minute | Speech between them, p50 / p90 / max |
|---|---|---|
| 200 ms | 21 | 2.2 / 4.5 / 9.5 s |
| 300 ms | 14 | 3.0 / 6.8 / 17.2 s |
| 500 ms | 6 | 6.6 / 16.3 / 31.3 s |

So a 700 ms pause rule leaves a 15 s cap to do most of the cutting. The
segmenter alone (`sim.py` there, this `Segmenter` class fed the clip's audio and
VAD probabilities) on the same clip:

| Pause / cap / min. speech | Pieces | Length p50 / p90 | Cut at the cap | Cut mid-speech | Within 1 s of a sentence end | First piece out |
|---|---|---|---|---|---|---|
| 700 ms / 15 s / 0.4 s (the service before) | 27 | 12.7 / 14.2 s | 2 | 0 | 10 | 13.0 s |
| 300 ms / 6 s / 0.4 s (the old defaults) | 75 | 4.1 / 5.6 s | 20 | 4 | 25 | 5.4 s |
| 300 ms / 10 s / 1 s | 54 | 5.4 / 8.7 s | 2 | 0 | 16 | 5.5 s |
| **200 ms / 10 s / 1 s (now)** | 70 | 3.8 / 7.2 s | 1 | 0 | 19 | 5.4 s |
| 700 ms / 15 s / 0.4 s, progressive from 4 s | 32 | 8.9 / 13.8 s | 0 | 0 | 11 | 5.8 s |

Live, through the whole route (recogniser, translator, voice), 700 ms / 15 s
put the first translated audio out at 19.5 s and each piece 18.2 s behind the
speaker; 200 ms / 10 s / 1 s gave 8.4 s and 9.1 s. The trade-off is translation
quality: a 3.8 s piece gives the translator less to work out a misheard name or
phrase from (2.52 to 2.21 on the eval's 0-3 scale), unless it is sent the
previous pieces and the last translation as context, which restores it
(2.52-2.67) and which the companion apps now do. A client whose translator
gets no context may prefer `ENDPOINT_MS=300` or more, with `CUT_EARLY_S` to keep
the cap from doing the cutting.

`deploy.sh deploy` passes all three through when they are set in its environment,
and the five `CUT_*` settings and the four `STT_DENOISE*` settings when set
(unset: the defaults above and below).
Other settings: `STT_MAX_CONNECTIONS`, `STT_MAX_PENDING`, `STT_DEVICE`, `OMNI_CARD`,
`STT_MODELS`, `PORT`, `EDITION`, `HT_VOICE`, `STT_VOICES`, `STT_MAX_SPEAKERS`, `STT_SERVE`
(see the top of `server.py`); `STT_PARTIALS` (default 0: off) and `STT_PARTIAL_MS`
(1500), the partial text above, which when on costs the GPU about 3-4x per piece
(the growing piece is decoded again every interval; `deploy.sh` passes both
through when set).

### Noisy input

Off by default. `STT_DENOISE=1` puts a spectral noise reducer (`denoise.py`,
numpy only) in front of the VAD on each connection, with its own state:

- `STT_DENOISE_NR_DB` (default 12): the most any band is attenuated, in dB
  (ffmpeg `afftdn`'s `nr`). The residual it leaves keeps speech from sounding
  hollowed out and the gaps from warbling.
- `STT_DENOISE_TRACK_S` (default 1.5): the noise floor of a band is the
  quietest it has been in this long (minimum statistics). A drop in the noise
  is followed at once, a rise after this long; a tone held longer than this
  starts to count as noise, as it would for any tracking reducer.
- `STT_DENOISE_OVERSUB` (default 3.0): over-subtraction, how far above its
  floor a band must be to count as speech. The tracked minimum sits below the
  noise's mean power, and this makes up for it.

The method: 512-point STFT at 16 kHz, 256-sample hop, Hann window (its root at
analysis and at synthesis), a Wiener gain from a decision-directed a priori SNR
against the tracked floor, never below `-NR_DB`, overlap-add. It adds 16 ms of
latency (the overlap), no model, no dependency, and about 0.2 ms of CPU per
96 ms block (a laptop core; real-time factor 0.002). The
VAD hears the denoised audio, because the measured gain came from the
segmenter getting its pauses back; the cost is that a soft onset the reducer
attenuates is one the VAD may miss too.

When to use it: a distant or noisy microphone. In the audio-degradation test
(`eval/2026-10-real-voices/README.md`, "Cleanup on the room mic";
`docs/dev/route-findings-2026-10.md`, section 9) ffmpeg's `afftdn` (nr 12 dB)
in front of Omnilingual brought a room mic (reverb plus noise at 10 dB SNR)
from +54 to +39 character-error points over clean, mostly by stopping whole
sentences from vanishing (English: 25 of 30 dropped, 9 with the filter). The
same filter made Azure a little worse (+44 to +45) and RNNoise made Azure worse
still (+54), which is why this is a plain spectral method and not a learned
one, and why it is off unless asked for. That measurement was ffmpeg's filter on
files; this implementation is an equivalent of it (on speech plus white noise at
5 dB SNR both gain about 7 dB, `tests/test_omni_stt_denoise.py`), and its
effect through the service has not been measured yet. On clean close-mic audio
it can only cost a little (under 0.2 dB of level on the test clips, more on
speech with no pauses), so leave it off there.

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

### omni-stt-7b: Meta's stock 7B for Lao and Khmer

A second service, same protocol (`/listen` only, no `/speak`), serving Meta's
stock `omniASR_LLM_7B` (no fine-tuned weights) converted to bf16 (`7b/to_bf16.py`:
31 GB fp32 -> 15.6 GB; the pipeline decodes in bf16 anyway). A client changes
only the URL; `?langs=lo` (or `km`) skips language ID.

```
REPO_REGION=us-east4 EXTRA_REPO_REGIONS=us-central1 MODEL_BUCKET=<your private bucket URL> ./deploy.sh 7b-build
TAG=<tag> REPO_REGION=us-east4 STORAGE=baked MAX_STREAMS_7B=6 ./deploy.sh 7b-deploy
```

(Endpointing as the defaults above; `ENDPOINT_MS`, `MAX_UTTERANCE_S` and
`MIN_SPEECH_MS` in the environment override them, as for `deploy`.)

Cold start, zero to the hello (2026-10-20, us-east4, L4, 4 vCPU / 16 GiB):

| checkpoint from | instance -> ready | of which checkpoint read |
|---|---|---|
| image (baked, `STORAGE=baked`) | 34-56 s (client: 43-61 s to hello) | 15-27 s (~0.6-1 GB/s) |
| Cloud Storage volume (`gcs`), mmap or sequential, buffered reads or not | 314-378 s | 300-350 s (~50 MB/s) |
| copy into /tmp at start (`fetch`, 16 parallel ranged reads) | 312 s | 281 s download + 7 s load |

Without Direct VPC (the project has no VPC) Cloud Storage gave ~55 MB/s to an
instance by every route; the image is read at ~0.6-1 GB/s. The registry region
(us-central1 or us-east4) made no consistent difference: Cloud Run copies the
image at deploy time. The rest of a baked cold start: ~2-5 s to the container,
~7 s of imports, ~10 s for VAD, language ID and fairseq2's imports (now beside
the checkpoint read: `STT_PARALLEL_LOAD`), ~4-6 s warm-up.
`OMNI_MMAP=1` keeps the process at ~1.6 GB of RAM, so 16 GiB is enough (fetch
needs 32 GiB: /tmp is memory).

Accuracy through the service (real-voice clips streamed at real time, measured
with ENDPOINT_MS 700 and MAX_UTTERANCE_S 15, the settings of the time, not the
defaults now; CER on the joined text; quiet km sentences the VAD never
hears count against both): lo 13.5% (7B) vs 17.8% (omni-stt, its 300M card),
km 24.7% vs 28.1%. The aligned batched decode (omni_batch.py) works for the 7B card
(same decoder): six streams at once gave the same CER as one, 72 of 76 utterances
word for word. The repetition guard cut 7B's loops on sub-second fragments
(5-8 per lo/km pass).

Capacity (load7b.mjs, lo and km rooms, 120 s): transcript delay after the speech
ends, p50/p90: 1 stream 2.2/3.3-3.9 s, 4 streams 3.3/6.4 s, 6 streams 4.5/7.0-7.7 s,
8 streams 5.9/7.9 s; nothing dropped at 8, but the GPU was ~80% busy at 6. So
`STT_MAX_CONNECTIONS` and `--concurrency` are 6. GPU memory ~17-18 GB of 24.

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
