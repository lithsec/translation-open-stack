# Reference

Everything an operator can set, run or check, in one place. For how to do a
task step by step, see the [user guide](user-guide.md); for licences,
[licences.md](licences.md); for the wire protocol, [protocol.md](dev/protocol.md).

**Contents**

- [Environment variables](#environment-variables)
- [languages.toml](#languagestoml)
- [Command line](#command-line)
- [Access, rooms and limits](#access-rooms-and-limits)
- [The models, stage by stage](#the-models-stage-by-stage)
- [Pins and the supply chain](#pins-and-the-supply-chain)
- [The Docker image](#the-docker-image)
- [The volume](#the-volume)
- [Repository layout and tests](#repository-layout-and-tests)

## Environment variables

Set these in `.env` (Docker: every line reaches the container) or in the pod's
environment (RunPod).

### Access

| Variable | Default | Meaning |
|---|---|---|
| `STACK_TOKEN` | unset | Static access token clients send as `Authorization: Bearer <token>` (subject `static`). RunPod also reads `/workspace/.stack-token`. |
| `STACK_SIGNING_KEY` | unset | Key for short-lived signed tokens issued by a launcher ([Signed tokens](#signed-tokens)). RunPod also reads `/workspace/.stack-signing-key`. |
| `STACK_OPEN` | `0` | Docker only: `1` = run with no credential (a private LAN only). RunPod always requires one. |
| `STACK_ACCEPT_LEGACY_TOKENS` | `0` | `1` = also accept signed tokens without an `aud` claim (issued before audiences existed). For a transition only; a `pod:` subject is refused even then. |
| `STACK_REPORT_URL` | unset | RunPod only: where the pod POSTs "ready" or "failed", signed with audience `report`. No default: unset (and no `/workspace/.stack-report-url` file) means no report and nothing leaves the pod. Set but empty also means no report. Needs `STACK_SIGNING_KEY`. |

### Languages, edition and models

| Variable | Default | Meaning |
|---|---|---|
| `LANGS` | all 25 | Languages people listen in (voices are fetched for these). |
| `SRCS` | all 25 | Languages people may speak. |
| `EDITION` | `nonprofit` | `nonprofit` or `commercial` ([licences.md §2](licences.md#2-editions-what-edition-changes)). |
| `COMMERCIAL_ALLOW_UNCLEAR` | unset | `1` = admit every ❓ item in commercial at once, with a loud warning at start-up and in `check`. Prefer `[licence_review]`. |
| `MADLAD` | `7b` | `3b` = the smaller fallback translator, for a 32 GB card (`[models.madlad3b]`). |
| `STACK_CONFIG` | `languages.toml` at the repository root | Another model file (languages and `[models]`). |
| `STACK_PROFILE` | unset | A hardware profile: `profiles/<name>.toml`, or a path ([Profiles](#profiles-and-devices)). |
| `STACK_DEVICES` | unset | Per-model devices, winning over `[devices]` and the profile: `whisper=cuda:1,hymt=cuda:0`. |
| `STACK_ENGINES_PATH` | unset | Directories (`:`-separated) of extra engine files ([adding-an-engine.md](dev/adding-an-engine.md)). |

### VoxCPM2 and eSpeak NG

| Variable | Default | Meaning |
|---|---|---|
| `VOXCPM` | `1` | `0` = don't start the VoxCPM2 voice service (its languages fall back). |
| `VOXCPM_REV` | `[models.voxcpm]` revision | VoxCPM2 revision; wins over `languages.toml`. |
| `VOXCPM_LANGS` | from `languages.toml` (`voxcpm = true` for the edition) | Languages VoxCPM2 speaks. |
| `VOXCPM_INSTANCES` | `auto` (commercial), `1` (nonprofit) | VoxCPM2 services to start: `auto` = one on the main GPU plus one on each other GPU with ≥ 10 GB, a number, or `0` = none. |
| `VOXCPM_GPUS` | unset | Exactly these GPUs, in order, one instance each (`0,1,1`: two on GPU 1); a number in `VOXCPM_INSTANCES` then takes the first n. |
| `VOXCPM_MAX_INSTANCES` | `4` | Most instances `auto` starts. |
| `VOXCPM_MAX_INFLIGHT` | `1` | Sentences one instance takes at once. A service makes one voice at a time and answers "busy" rather than queue, so the server does the queueing. |
| `VOXCPM_QUEUE_S` | `2` | How long a sentence waits for a free instance before the next voice in its chain (eSpeak NG) speaks it. |
| `VOXCPM_WAIT_S` | `15` | The same for a language with no voice after VoxCPM2 (km lo tl in commercial), before it is text only. |
| `VOXCPM_RETRY_S` | `15` | An unreachable instance is skipped this long, then tried again. |
| `VOXCPM_TIMEOUT_S` | `30` | Connect/read timeout for one request to an instance. |
| `VOXCPM_STATS_S` | `60` | Most frequent `VoxCPM2 stats` log line (per instance: served, peak in flight, errors; overflow), while there is traffic. |
| `VOXCPM_VENV` | `/workspace/venv_voxcpm` (`/opt/venv_voxcpm` in the image) | VoxCPM2's own virtualenv. |
| `VOXCPM_LOG` | `/workspace/voxcpm.log` | Log of the first instance; the others log to `voxcpm-<port>.log` beside it. |
| `VOXCPM_REF_DIR` | `/workspace/voices/voxcpm` | Reference voices the service clones (`<lang>.wav`). |
| `ESPEAK` | `1` | `0` = no eSpeak NG last-resort voice (VoxCPM2 overflow is then silent; fa, ro text only in commercial). |
| `ESPEAK_SPEED` | `160` | eSpeak NG speaking rate, words per minute. |

### Connection limits

| Variable | Default | Meaning |
|---|---|---|
| `STACK_MAX_PER_CLIENT` | `30` | Live connections per token subject (a room opens one per language). |
| `STACK_MAX_CONNECTIONS` | `60` | Live connections in total. |
| `STACK_MAX_SESSION_MIN` | `360` | Longest a single connection may last, in minutes. |

### Docker and RunPod

| Variable | Default | Meaning |
|---|---|---|
| `STACK_PORT` | `8790` | Docker only: host port. |
| `STACK_IDLE_MIN` | `15` | RunPod only: stop the pod after this many idle minutes (counted from ready). |
| `STACK_MAX_UPTIME_H` | `8` | RunPod only: stop the pod after this many hours regardless. |

### Paths, caches and builds

| Variable | Default | Meaning |
|---|---|---|
| `HF_HOME` | `/workspace/hf-cache` | Hugging Face cache on the volume. |
| `TORCH_HOME`, `FAIRSEQ2_CACHE_DIR` | `/workspace/torch-cache`, `/workspace/fairseq2-cache` (Docker) | Silero VAD's and Omnilingual's caches on the volume. |
| `VOICES_DIR` | `/workspace/voices` | Piper voices. |
| `VOICES_LOCK` | `voices.lock` at the repository root | The lock `fetch-voices.sh` checks against. |
| `MT_SCRATCH` | `/root/mt-build` (`/workspace/.mt-build` under Docker) | Scratch for the translator build's full-precision downloads (~45 GB), deleted afterwards. |
| `MT_DIR` | `/workspace/mt` | Where `prepare-mt.sh` builds Hy-MT2 and MADLAD 7B (`scripts/run.sh` reads `/workspace/mt`). |
| `CONSTRAINTS` | `constraints.txt` | The pins `install-deps.sh` installs with. |
| `STRICT` | `0` | `1` = `install-deps.sh` fails on any optional extra instead of warning (the image build). |
| `PYTORCH_CUDA_ALLOC_CONF` | `expandable_segments:True` | Less GPU memory fragmentation. |
| `CUDA_DEVICE_ORDER` | `PCI_BUS_ID` | So `nvidia-smi` and CUDA number GPUs the same way (`VOXCPM_GPUS`). |
| `STACK_GPUS` | unset | Stands in for `nvidia-smi` in `voxcpm-plan` (`0:81920,1:46068`: id and MB), for dry runs and tests. |

The start scripts also set `HF_HUB_ENABLE_HF_TRANSFER=0` when the
`hf_transfer` package is missing: RunPod's image sets it to 1 without the
package, and then every Hugging Face download fails.

### Tuning (`LITHOS_*`)

| Variable | Default | Meaning |
|---|---|---|
| `LITHOS_SENTENCE_CUT` | `1` | `0` = a forced cut lands at the quietest point, not after the last sentence end. |
| `LITHOS_STREAM_MAX_WORDS` | `8` | Simultaneous mode: uncommitted words that force a clause out with no punctuation. |
| `LITHOS_STREAM_MIN_WORDS` | `4` | Simultaneous mode: shortest clause spoken by itself, unless the turn is over. |
| `LITHOS_STREAM_COMMA_WORDS` | `6` | Simultaneous mode: words before a comma is accepted as a boundary. |
| `LITHOS_TRIM`, `LITHOS_TRIM_S` | off, `8` | Simultaneous mode: trim a turn's buffer past this many seconds. |
| `LITHOS_MT_BEAM` | `4` | MADLAD beam size. |
| `LITHOS_TTS_WORKERS` | `8` | Voice synthesis threads. |
| `LITHOS_SEG_STATS` | unset | `1` = log every Whisper segment's confidence numbers. |
| `LITHOS_ROOM_HEARTBEAT` | unset | `1` = a periodic per-room log line. |

Each is explained where it is read, at the top of `server/server.py` and in
the engine files; the measurements behind them are in
[lessons-learned §6](dev/lessons-learned.md#6-latency-and-throughput).

## languages.toml

At the repository root (Docker mounts it read-only into the container).
`server/server.py` and the scripts read it, or the file `STACK_CONFIG` names;
without it the built-in defaults in `server/stack_config.py` apply, and they
are exactly what the shipped file says (`tests/test_stack_config.py` fails if
the two drift). Validate with `python3 server/stack_config.py check`, which
also runs at every start. The file's own header lists every key.

### Language tables

`[<lang>]`, one per language. A section **replaces** that language's defaults
entirely. All keys are optional.

| Key | Value | Meaning |
|---|---|---|
| `kokoro` | `"<lang_code>:<voice>"` | Kokoro 82M (GPU), e.g. `"a:am_michael"`. Catalogue: `hexgrad/Kokoro-82M`. |
| `voxcpm` | `true` | VoxCPM2 (GPU), via `server/voxcpm_service.py`, in the language's reference voice. |
| `coqui` | `"<hugging face repo>"` | A Coqui VITS checkpoint (started in commercial). |
| `piper` | `"<voice name>"` | A Piper voice (CPU), e.g. `"de_DE-thorsten-high"`; must be in `voices.lock`. |
| `mms` | `"<hugging face repo>"` | Meta MMS-TTS (CC-BY-NC; nonprofit only). |
| `asr` | `"whisper"` \| `"omni:<code>"` | Recogniser when this language is **spoken**. |
| `translator` | `"hymt"` \| `"madlad"` | Translator **into** this language. Hy-MT2 covers the 36 languages in `stack_config.HYMT_LANGS`; anything else must be `"madlad"`. |
| `madlad` | `"<code>"` | MADLAD's language tag, when it differs from the code (Tagalog: `fil`). |
| `voice` | `["<name>", ...]` | The voice chain in this order, instead of the default. |
| `<engine>` | per engine | A plug-in engine's own per-language value, under its name. |

The default voice chain is `kokoro`, `voxcpm`, `coqui`, `piper`, `mms`, with
eSpeak NG as the last resort where it speaks the language. An engine takes
part only when the server runs it: Kokoro with `--kokoro`, VoxCPM2 when its
service is up, Coqui with `--coqui` (commercial), MMS with `--mms`
(nonprofit), eSpeak NG with `--espeak`. A language with none is text only. An
unknown engine name is an error.

### `[<lang>.commercial]`

The voice keys (`kokoro`, `voxcpm`, `piper`, …, `voice`) that replace the
language's voices when `EDITION=commercial`; `asr`, `translator` and `madlad`
still come from `[<lang>]`. Without one, commercial keeps the language's own
voices minus any it may not load.

### `[licence_review]`

```toml
[licence_review]
"ro_RO-mihai-medium" = "reviewed 2026-10-01 by Example Org: CC0 data; we accept the lessac fine-tune"
```

An informed opt-in for one unclear (❓) item after your own review of its
licence. The key is the voice name, repo or engine; the value says who, when
and why (`check` refuses an empty one). There is no override for ⛔: a review
naming one is an error. [licences.md §2](licences.md#2-editions-what-edition-changes).

### `[models.<name>]`

Every model that is not chosen per language, with its exact upstream
revision. A `[models.<name>]` table is **merged key by key** over the default,
so give only the keys you change. A revision of `""` means unpinned.

| `[models.<name>]` | Keys (defaults) | Read by | On a change |
|---|---|---|---|
| `whisper` | `model` (`large-v3`), `revision` (of `model`'s repo, Systran/faster-whisper-large-v3), `multi_model` (`""` = same model, loaded once), `multi_revision` (the revision of `multi_model` when it differs; `""` = unpinned, avoid) | `scripts/run.sh` → `--asr-model`, `--asr-revision`, `--asr-multi-model`, `--asr-multi-revision` | downloads on the next start |
| `omnilingual` | `card` (`omniASR_LLM_300M`; a fairseq2 card names one fixed checkpoint, no revision) | `server/engines/omnilingual.py` | downloads on the next start (fairseq2 cache) |
| `lid` | `repo` (`speechbrain/lang-id-voxlingua107-ecapa`), `revision` | `server/server.py` | downloads on the next start |
| `vad` | `repo` (`snakers4/silero-vad`), `ref` (a git tag, branch or commit; pinned to the commit of tag v6.2.3) | `server/server.py` (torch.hub) | downloads on the next start |
| `hymt` | `repo` (`tencent/Hy-MT2-7B`), `revision` (required) | `scripts/prepare-mt.sh` | **rebuilt** (4-bit quantisation, needs the GPU) |
| `madlad` | `repo` (`google/madlad400-7b-mt`), `revision` (required) | `scripts/prepare-mt.sh` | **rebuilt** (CTranslate2 int8 conversion) |
| `madlad3b` | `repo` (`google/madlad400-3b-mt`), `revision` (required) | `scripts/prepare-mt.sh` with `MADLAD=3b`, `scripts/runpod/provision-runpod.sh` | **rebuilt** |
| `kokoro` | `repo` (`hexgrad/Kokoro-82M`), `revision` | `server/engines/kokoro.py` | downloads on the next start |
| `voxcpm` | `repo` (`openbmb/VoxCPM2`), `revision` (required) | `scripts/prepare-voices.sh`, `scripts/run.sh` → `voxcpm_service.py` | `prepare-voices.sh` downloads it; `VOXCPM_REV` wins |

The built-in defaults are `MODEL_DEFAULTS` in `server/stack_config.py`, pinned
by `tests/test_stack_config.py`. A plug-in engine may declare its own
`[models.<name>]` table. How to change one and what must be rebuilt:
[user guide, "Replace a model or a revision"](user-guide.md#replace-a-model-or-a-revision).

### Profiles and devices

A **profile** is the hardware half of a setup, kept apart from the languages
and the edition: `profiles/<name>.toml`, chosen with `STACK_PROFILE=<name>`.
It wins over `languages.toml`. Every table is optional:

| Table | What | Merged |
|---|---|---|
| `description = "..."` | One line, for `stack_config.py profiles`. | |
| `[env]` | Defaults for the scripts' variables (`MADLAD`, `VOXCPM_GPUS`, `LANGS`, …), applied by `scripts/profile-env.sh` at the start of `run.sh`, the Docker entrypoint and `runpod-start.sh`. | the environment wins |
| `[devices]` | Which device each model loads on (below). | key by key |
| `[models.<name>]` | As in `languages.toml`. | key by key over the file's |
| `[languages.<lang>]` | Keys of a language table, e.g. `asr = "whisper"` where Omnilingual can't run. | key by key over the language's table |

Shipped profiles:

| Profile | For |
|---|---|
| `cuda-48gb` | One 48 GB NVIDIA GPU, all 25 languages. The reference; the same as no profile. |
| `cuda-32gb` | One 32 GB NVIDIA GPU: `MADLAD=3b`. |
| `cuda-2gpu` | Two NVIDIA GPUs of 24 GB or more: translators on GPU 0, recognition and voices (and VoxCPM2) on GPU 1. |
| `radeon-32+16` | **Preview, not yet run:** AMD Radeon AI PRO R9700 32 GB + RX 9060 XT 16 GB under ROCm. Needs a ROCm build (the image is CUDA only). |

**`[devices]`** (in `languages.toml`, a profile, or `STACK_DEVICES`, each
winning over the one before): keys `default`, any engine name (`whisper`,
`omni`, `hymt`, `madlad`, `kokoro`, `coqui`, `mms`, `cosyvoice`, a plug-in's
name) and `lid` (language ID, on the CPU unless set). Values: `auto` (the first
GPU, or the CPU), `cpu`, `cuda`, `cuda:<n>`, `mps`. AMD cards under ROCm are
`cuda` too: PyTorch and CTranslate2 keep the name. VoxCPM2 runs in processes of
its own, placed by `VOXCPM_GPUS`. A device that isn't there stops the start.
While loading, the server prints each model's share of its card
(`[stack] hymt on cuda:0: +5.6 GB (12.0 GB in use there)`), the numbers to
plan a split from.

## Command line

### `server/stack_config.py`

Python 3.11+, standard library only (it imports the engine files, which keep
heavy imports out of module level).

| Command | What it does |
|---|---|
| `check [--edition nonprofit\|commercial]` | Loads and validates `languages.toml`; prints per language the recogniser, translator and voice chain with licence classes, what the edition leaves out, the `[models]` entries, VoxCPM2's languages and instance plan, and a summary (text only, eSpeak NG only, credits owed). Non-zero exit on a bad file, or a `[models]` entry the edition may not load. `EDITION` is the default edition. |
| `get <path>` | One value, for scripts: `get models.hymt.revision`. |
| `engines` | Every registered engine: kind, name, title, licence and class, and its file. |
| `docs [--write]` | The generated tables of [licences.md](licences.md) (§3 and §7); `--write` updates them in place. `tests/test_licences.py` fails when they drift. |
| `voxcpm-plan [--edition …]` | Where VoxCPM2 instances would run on this machine: one `<gpu> <port>` line each (ports 8791, 8792, …; `-` = no `CUDA_VISIBLE_DEVICES`), with the summary on stderr. |
| `piper <langs>` | `<lang> <piper voice>` per line, for the edition (used by `fetch-voices.sh`). |
| `profiles` | The profiles in `profiles/`, with their descriptions. |
| `profile [<name>]` | What a profile changes: `[env]` (and which the environment overrides), devices, models, language routes. Default: `$STACK_PROFILE`. |
| `profile-env` | `export` lines for `$STACK_PROFILE`'s `[env]` values the environment lacks (for `scripts/profile-env.sh`). |

### Scripts

| Script | What it does |
|---|---|
| `scripts/run.sh [langs] [srcs]` | Starts the server the way it is deployed: prints `check`, starts the VoxCPM2 instances, picks the translators on the volume, and passes the flags in [Server flags](#server-flags). |
| `scripts/docker-entrypoint.sh` | The container's start: refuses without a credential or a GPU, then `fetch-voices.sh`, `prepare-mt.sh`, `prepare-voices.sh`, `run.sh`. |
| `scripts/runpod/runpod-start.sh` | The pod's start command: the same steps, plus the package install on the stock image, the idle stop and the ready report. |
| `scripts/runpod/provision-runpod.sh` | Installs the packages on a bare pod and converts MADLAD 3B (run by `runpod-start.sh` when needed). |
| `scripts/install-deps.sh` | Every Python package, pinned (the image and the pods). |
| `scripts/fetch-voices.sh <langs>` | Downloads and verifies the edition's Piper voices for these languages ([Piper voices](#piper-voices-voiceslock)). |
| `scripts/prepare-mt.sh` | Builds the translators from their pinned revisions; rebuilds on a revision change. |
| `scripts/prepare-voices.sh` | VoxCPM2's virtualenv, weights and reference voices. |
| `scripts/idle-stop.sh` | Stops an idle RunPod pod (started by `runpod-start.sh`). |
| `scripts/lock-voices.py [voice ...] [--revision <commit>]` | Writes `voices.lock`: adds voices, or moves to another upstream commit. |

### Tools

Against a running stack (`--url`, `--token` or `$STACK_TOKEN` where they
connect):

| Tool | What it does |
|---|---|
| `tools/smoke.py` | The end-to-end check after any model or dependency change ([user guide](user-guide.md#verify-with-the-smoke-test)). `--load N` is the VoxCPM2 capacity test. |
| `tools/client.py` | Streams a 24 kHz mono WAV at real-time pace, prints transcripts, saves `out-<lang>.wav`, reports end-of-utterance to first audio. `--url wss://…` (or `--host`/`--port`), `--token` or `$STACK_TOKEN`, `--lang`, `--src`. |
| `tools/bench.py` | Fan-out (one clip into N languages) and X→English latency. |
| `tools/cough-test.py`, `tools/coverage-test.py` | Does a cough make the stack speak; does a long reading lose words. |
| `tools/dev-cpu.sh` | The whole stack on CPU with stand-in models, then the bench: before renting a GPU. |
| `tools/voice_refs.py` | Generates and scores VoxCPM2 reference voice candidates. |

### Server flags

`server/server.py --help` lists every flag. What `scripts/run.sh` passes:

| Flag | Why |
|---|---|
| `--langs`, `--srcs` | `LANGS`, `SRCS`. |
| `--asr-model large-v3`, `--asr-multi-model`, `--asr-revision`, `--asr-multi-revision` | From `[models.whisper]`. large-v3 adds ~0.2 s for proper nouns and capitalisation, and replaces the multilingual model rather than adding one, so memory goes down. (`server.py` alone defaults to distil-large-v3.) |
| `--xeng --omni --kokoro` | Any-language sources, Omnilingual, Kokoro. |
| `--mms` (nonprofit) / `--coqui` (commercial), `--edition` | The edition's voices; the server enforces the edition. |
| `--voxcpm <urls>`, `--voxcpm-langs` | The VoxCPM2 instances that came up. |
| `--espeak` | The last-resort voice, when `espeak-ng` is installed and `ESPEAK=1`. |
| `--voices-dir /workspace/voices` | Every launch path passes it. |
| `--endpoint-ms 900` | +0.2 s, fewer sentences cut mid-thought (bare default 700). |
| `--max-utterance-s 12` | Forced cut for unbroken speech; only bites on genuinely unbroken speech (bare default 9). |
| `--mt-ct2 <dir>`, `--hymt <dir>` | The translators built on the volume. |

## Access, rooms and limits

The stack has no accounts: a token is the only lock
(`server/stack_auth.py`). The full wire contract is in
[protocol.md](dev/protocol.md).

**Credentials.** Clients send `Authorization: Bearer <token>`. The URL forms
(`wss://HOST/<token>/translate`, `?key=<token>`) still work for old clients,
but a URL ends up in proxy and server logs. A bad or missing token closes with
4401 and logs `refused: bad or missing token`. `GET /health` needs no token and
answers `ok` once the models are loaded (and reveals nothing else). With
neither `STACK_TOKEN` nor `STACK_SIGNING_KEY` the start scripts refuse to run
(Docker allows `STACK_OPEN=1`).

### Signed tokens

`<payload>.<signature>`, both base64url; the signature is
HMAC-SHA256(`STACK_SIGNING_KEY`, payload); the payload is
`{"sub", "iat", "exp", "aud"}`:

- `sub`: the subject, e.g. `client:<name>` or `talk:<account>`; connection
  limits and rooms are per subject.
- `aud` must be `"stack"`. The pod's ready report is signed with the same key
  but carries `"aud": "report"`, so it can never open a connection. A token
  without `aud` is refused unless `STACK_ACCEPT_LEGACY_TOKENS=1`, and even then
  a `pod:` subject is refused.
- `exp` must be a finite number, and a token may live at most **24 hours**
  (`exp - iat` and `exp - now`). Lithos's launcher issues 2-hour tokens for
  Lithos Talk and 12-hour ones for Live Translation.

`stack_auth.sign(key, sub, ttl_s)` makes one (tests and tools). A static
`STACK_TOKEN` has subject `static`; both credentials may be set at once.

**Rooms.** `?room=<id>` shares one pipeline among connections. Room ids are
1-64 characters of `[A-Za-z0-9_-]`. **A room belongs to the token subject that
opened it**: rooms are keyed by subject and id together, so two clients with
different tokens that both say `room=main` get separate rooms and never hear
each other. Several connections may listen to the same language in one room;
each receives the output (translated and synthesised once), and one leaving
takes only itself out. If the primary connection leaves, another member is
promoted.

**Limits and close codes.**

| Code | When |
|---|---|
| 4401 | bad or missing token (including a token for another audience) |
| 4429 | too many connections for this subject (`STACK_MAX_PER_CLIENT`, 30) or for the server (`STACK_MAX_CONNECTIONS`, 60) |
| 4408 | the connection reached `STACK_MAX_SESSION_MIN` (360) |
| 4400 | a query parameter the server does not accept (unknown `lang`, `src`, `route` or `cands` language, more than 8 `cands`, a malformed `room`); an `error` message naming it comes first |
| 4413 | audio sent faster than 2x real time, beyond 60 s of audio in hand |
| 1009 | a WebSocket message over 256 KB (a 100 ms frame is 4.8 KB) |

**Long speech.** Every connection, in a room or solo, is cut at
`--max-utterance-s` (12 s via `scripts/run.sh`) when the speaker never pauses,
after the last sentence the recogniser heard.

**RunPod.** A pod URL is public, so `runpod-start.sh` refuses to start without
a credential; the pod stops after `STACK_IDLE_MIN` idle minutes and after
`STACK_MAX_UPTIME_H` hours regardless, so a credential holding a connection
open can't keep a pod billing. The ready report goes only to
`STACK_REPORT_URL` ([Access](#access)).

## The models, stage by stage

![The pipeline](images/pipeline.png)

### Detection: Silero VAD and VoxLingua107

Two small models decide *when* to translate and *which models* to use.
Together they use under 0.2 GB of GPU memory.

- **Silero VAD** marks speech and silence every few milliseconds, on the CPU.
  - It decides when a sentence is finished: 0.9 s of quiet (`--endpoint-ms
    900`), or a 0.28 s breath once someone has spoken for 5 s.
  - It keeps silence away from Whisper, which otherwise invents text ("thanks
    for watching", "gracias por su comentario") that the translator would speak.
  - The sentence-end cut for long speeches builds on it.
  - The stack can't work without it.
- **VoxLingua107** (SpeechBrain, 107 languages) names the language of each
  utterance, restricted to `SRCS`, when a room runs with `src=auto`. That
  choice:
  - picks the recogniser (Whisper, or Omnilingual for the `omni:` languages);
  - tells the translator the source language;
  - lets listeners who already speak that language hear the original instead
    of a translation.

  In testing it routed a clip mixing English, Spanish and French correctly,
  sentence by sentence, and sent every Khmer, Lao and Haitian Creole utterance
  to the right recogniser. Its only confusion was Ukrainian against Russian.
  It costs ~10 ms per utterance. Rooms with one fixed spoken language
  (`src=es`) skip it. Whisper's own language detection isn't a substitute: it
  is weakest in exactly the languages that need Omnilingual.

### Recognition: Whisper and Omnilingual

faster-whisper large-v3 for most sources; Meta's Omnilingual ASR 300M for
Persian, Bengali, Urdu, Hindi, Swahili, Haitian Creole, Khmer and Lao
(`asr = "omni:<code>"`), where Whisper is weak or produces fluent nonsense.

**Long speeches: forced cuts land on sentence ends.** A speaker who never
pauses for `--max-utterance-s` used to be cut at the quietest instant, usually
mid-sentence. Now the server runs the recogniser with word timings on the
buffer and cuts after the last sentence end (a clause comma past 4 s as the
fallback), carrying the unfinished sentence into the next utterance. On a 78 s
pause-free reading: es 90 -> 93%, de 89 -> 90%, ja 86 -> 90%. Omnilingual
sources have no word timings and keep the quietest-point cut.
`LITHOS_SENTENCE_CUT=0` restores the old behaviour.

### Translation: Hy-MT2 where it can, MADLAD 7B for the rest

`scripts/prepare-mt.sh` builds both into `/workspace/mt/` from the **pinned**
upstream revisions in `[models]` (full-precision downloads go to scratch; only
the results land on the volume). `scripts/run.sh` uses them when present, and
the server loads them from disk with `local_files_only`, so nothing is fetched
at runtime.

| | Model | Size on disk | Licence |
|---|---|---|---|
| the 36 languages it supports (incl. en es fr de pt ru uk zh ja km) | Hy-MT2 7B (Tencent), 4-bit NF4 | 4.4 GB | Apache 2.0 |
| everything else (ht sw lo ro) | MADLAD-400 7B, CTranslate2 int8 | 7.8 GB | Apache 2.0 |

Measured 2026-09-27: 24 sentences x 19 directions, the same audio Gemini heard,
through this stack's own ASR, graded blind. Hy-MT2 95% with 13 critical errors,
MADLAD 7B 87% / 23, MADLAD 3B 82% / 26, Gemini Live 79% / 38; the full stack
beat Gemini in 16 of 19 directions. Hy-MT2 does not support Haitian Creole
(10%): MADLAD 7B gets 78% there, Gemini 90%. A source Hy-MT2 does not know
pivots through English via MADLAD.

MADLAD still translates **sentence by sentence** (one batch): given two
sentences as one input it dropped one of them for Ukrainian and Japanese.
Hy-MT2's output cap is generous (10x the source tokens): Khmer took 136 tokens
for an 18-token English sentence, and a 3x cap truncated every Khmer line.

**TranslateGemma 12B** (Google, Gemma licence) was also tested and is the one
alternative worth keeping in mind: 92% in the major languages, 77% in Haitian
Creole, so a single model could replace both translators. It lost in Khmer (67%
vs 94%) and into Lao, so it isn't the default. Its Gemma licence carries
Google's usage policy ([licences.md §9](licences.md#9-evaluated-but-not-deployed)).
Details: [model-evaluation.md](dev/model-evaluation.md).

### Voices

Which engine speaks each language, with its licence class, is in
[licences.md §3](licences.md#3-every-language-per-edition);
`python3 server/stack_config.py check` prints the table your `languages.toml`
produces. In short: Kokoro (GPU, Apache 2.0) for en es fr it pt ja zh hi,
VoxCPM2 (GPU, Apache 2.0, its own venv and service on :8791) for km lo tl
(and seven more in commercial), Piper (CPU, licence per voice) for the rest and
as the fallback, Coqui OpenBible (CC-BY-SA) or MMS (CC-BY-NC) for Haitian
Creole depending on the edition, and eSpeak NG as the last resort.

**Kokoro** (82M, Apache 2.0) was chosen by ear against Piper on identical
sentences (Hindi too, since 2026-09-28). Beyond how it sounds: it emits
**24 kHz, the pipeline's own rate**, so those languages skip the resample step
and the edge-ringing that comes with resampling short segments; one 82M model
covers several languages, against a 63-114 MB Piper file each; and it is
Apache 2.0, unlike MMS. It is a GPU model and that is the point: ~98x real
time on the GPU against Piper's ~30x on CPU, but only **2x on CPU**, so do not
run it without one. Measured end to end it changed the pipeline by nothing
(first audio 0.33-0.37 s either way), because TTS was never the bottleneck and
the GPU work overlaps the CPU work instead of competing with it. Piper remains
for every language Kokoro does not cover, and the router falls back to it
automatically if Kokoro errors. Japanese and Mandarin need Kokoro's G2P extras,
`misaki[ja,zh]`, plus MeCab's dictionary (UniDic); without the dictionary both
Kokoro Japanese and Coqui fail at load with "Failed initializing MeCab". The
image and the provisioner install both.

**Piper** runs on the CPU at roughly 20x real time after the onnxruntime
thread fix, so a voice is a small share of the latency. The Japanese Piper
voice is phonemised by `pyopenjtalk`, not espeak-ng like every other Piper
voice: without it the voice loads and then throws at synthesis time. It is
installed in the image, and it is slow: **2.4x real time against Korean's
37x**, still faster than speech, but ~15x the cost of any other voice.

**MMS** (non-profit edition) has one model per language and no quality tiers,
so there is nothing to choose. It renders about 11 dB quieter than Piper; the
server normalises for that. Khmer, Lao and Haitian Creole have no Piper voice,
which is why MMS and VoxCPM2 serve them.

**VoxCPM2** runs as its own service (`server/voxcpm_service.py`, its own
virtualenv, ports 8791 and up) and clones a fixed reference voice per
language ([voices/voxcpm/](../voices/voxcpm/README.md)); without one it picks a
new speaker every sentence. Capacity:
[user guide, "GPUs and capacity"](user-guide.md#gpus-and-capacity).

**eSpeak NG** runs as a separate process per sentence (GPL-3.0, run, not
linked): robotic but intelligible, the last voice of every language it speaks,
and the only voice for fa and ro in commercial.

**Memory.** The server with everything loaded (both ASR models, Omnilingual,
both translators, all voices) peaked at ~25-26 GB; VoxCPM2 adds ~7 GB per
instance. Recognition and translation models are shared by every language.

## Pins and the supply chain

Everything the stack installs or downloads is pinned to an exact version,
revision or hash, and checked where it is fetched.

### Python packages: `constraints.txt`

`constraints.txt` holds every Python package in the image at the version a
real build resolved: the stack-image workflow's `installed-packages` artifact
(`pip freeze` of the image built from the pinned base, Python 3.12.3), taken
on 2026-09-30 from an unpinned `install-deps.sh` run that passed the
workflow's import and smoke tests. Local version labels are dropped
(`torch==2.8.0` matches the base image's `2.8.0+cu128`). `scripts/install-deps.sh`
(the image and every RunPod pod) installs with `pip install -c
constraints.txt`: a line pins a package, it never installs one. The base
image's own packages are listed too, so nothing the stack pulls in can move
them.

**The Coqui exception.** Omnilingual's fairseq2 needs numpy 1.x, so the last
step settles on numpy 1.26.4 and scipy 1.13.1, below what librosa 1.0.0 and
contourpy 1.4.0 (Coqui's) declare; `pip check` reports exactly those three
lines. That is the combination the pods run and Omnilingual was verified on.
`install-deps.sh`'s Coqui step therefore drops the numpy and scipy lines from
the constraints and pins numpy 2.5.3 and scipy 1.18.1 (what that step resolved
to in the measured build); the Omnilingual step then puts them back to the
constrained 1.26.4 and 1.13.1.

`constraints-voxcpm.txt` does the same for VoxCPM2's virtualenv
(`--system-site-packages`, so only what it adds: `pip freeze --local` of
`/opt/venv_voxcpm`). VoxCPM2 brings its own transformers 5 and numpy 2 there,
which is why it has a venv at all; `voxcpm==2.0.3` itself is pinned in
`scripts/prepare-voices.sh`.

**Refreshing them.** Remove the lines you want to move (or run
`install-deps.sh` with `CONSTRAINTS=/dev/null`), run the **Stack image**
workflow (Actions -> Stack image -> Run workflow), and rebuild the list from
its `installed-packages` artifact: `stack.txt` for `constraints.txt`,
`voxcpm-venv.txt` for `constraints-voxcpm.txt` (`pip-check.txt` shows the
expected conflicts). Review the diff against the pins below. The workflow
fails when an installed package differs from its pin, or isn't pinned.

### Pins you should not casually change

Each exists because of a specific failure ([lessons-learned §2](dev/lessons-learned.md#2-environment-and-dependency-pins)):

- **`transformers==4.57.6`, and below 5.** 5.x makes MADLAD generate
  `"ll ll ll…"`, and pulls `huggingface_hub` 1.x, which `fairseq2` rejects,
  taking Khmer, Lao, Haitian and Swahili with it. Anything in 4.x is fine:
  4.49.0 and 4.57.6 both generate MADLAD correctly and leave Omnilingual
  importing and transcribing. The old 4.46.3 pin was too tight: the failure
  had only ever been seen on v5 and was never bisected.
- **`torchaudio==2.8.0`**: must match torch minor for minor.
- **`scipy==1.13.1`**: `fairseq2` downgrades numpy to 1.26, which strands
  newer scipy with `module 'numpy' has no attribute 'long'` at T5 import.
- **CUDA 12.8**: Blackwell (`sm_120`) needs it. Older cards are fine with it.

### Piper voices: `voices.lock`

`voices.lock` names the `rhasspy/piper-voices` commit the stack downloads
from and the sha256 of every voice file it may fetch: every Piper voice
`languages.toml` names in either edition, and every voice `server/licences.py`
has an entry for (the candidates an operator may switch to).
`server/licences.py` was read against that commit's model cards.

`scripts/fetch-voices.sh` downloads only from that commit and checks every
file, new or already on the volume, against the lock. A file on the volume
that doesn't match is fetched again; a download whose hash differs, or a voice
the lock doesn't list, is refused, and the script exits non-zero after trying
the rest, which **stops the start** (Docker and RunPod both run it before the
server).

**Adding a Piper voice** means locking it first:

```bash
python3 scripts/lock-voices.py de_DE-karlsson-low      # add a voice (the rest are kept)
python3 scripts/lock-voices.py                         # same commit, same voices + any new ones
python3 scripts/lock-voices.py --revision <commit>     # move to another upstream commit
```

It downloads and hashes each file; for the `.onnx` files (Git LFS) it also
checks the hash against the sha256 Hugging Face records for that commit, so a
corrupted download can't be locked in. Standard library only. Review the diff
before committing it.

### Models, images and downloads

| What | Pinned by | Where |
|---|---|---|
| Shared models (Whisper, language ID, Hy-MT2, MADLAD 7B/3B, Kokoro, VoxCPM2) | exact Hugging Face revision | `[models]` in `languages.toml` |
| Silero VAD | a git **commit** (tag v6.2.3's; a tag can be moved), loaded by torch.hub | `[models.vad] ref` |
| Omnilingual ASR | a fairseq2 model card, one fixed checkpoint | `[models.omnilingual]` |
| Translator builds | `PROVENANCE.txt` (`<repo> @ <revision>`) beside each build | `/workspace/mt/…`, `/workspace/madlad-ct2` |
| Base image | tag **and digest** (`runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404@sha256:0a36…`, a tag can be re-pushed); the build also asserts torch 2.8 | `Dockerfile` `BASE_IMAGE`; to move it, `docker buildx imagetools inspect <tag>` and take `Digest:` |
| spaCy `en_core_web_sm` 3.8.0 | release wheel URL and sha256 (pip checks the `#sha256=` fragment), not `spacy download` | `scripts/install-deps.sh` |
| UniDic 3.1.0 (MeCab dictionary) | zip URL and sha256, unpacked with unidic's own routine, not `python -m unidic download` (which picks a URL from GitHub at install time) | `scripts/install-deps.sh` |
| `voxcpm` | `==2.0.3` | `scripts/prepare-voices.sh` |

## The Docker image

**What's in it.** The pinned `runpod/pytorch` base (torch 2.8, CUDA 12.8.1,
Ubuntu 24.04: the same image the RunPod pods run), `espeak-ng`, `lsof`,
`iproute2` and `curl`; every Python package from `scripts/install-deps.sh`
with `STRICT=1` (a missing optional extra fails the build); VoxCPM2's
virtualenv at `/opt/venv_voxcpm`; and this repository at `/opt/stack`. The
build fails if any import the server needs is missing, if spaCy's model
doesn't load, or if transformers isn't 4.x. Using the pods' own install
script keeps the image and the pods from drifting apart, and using the pods'
base image means it can replace the stock one on RunPod
(`runpod-start.sh` sees the packages and skips its ~3 minutes of installs).

**What's not in it: model weights.** They are ~38 GB, they change
independently of this code, and a mounted `/workspace` lets several machines
share one warm copy. This is also how vLLM and TGI ship. They go on the volume
on the first start.

**Users.** The image adds an unprivileged user `stack` (uid and gid 10001).
`docker-compose.yml` runs the stack as that user, after a one-shot
`volume-init` service (as root) re-owns the model volume to 10001:10001 (a
fresh volume needs nothing; one filled by an older root container is re-owned
once). The image's *default* user stays root on purpose: RunPod's start
command replaces the image's command and must `exec /start.sh`, whose SSH
server needs root, and RunPod mounts its network volume at `/workspace` owned
by root. Everything the stack writes at run time goes to `/workspace` or
`$HOME`.

**Not published.** The image is built locally (Compose) or by the manual
**Stack image** workflow, which also lints the scripts, runs the unit tests
inside it, checks the unprivileged user and the entrypoint's refusals, and
records the installed packages. Publishing it would redistribute the stack,
including GPL-3.0 binaries ([licences.md §8](licences.md#8-libraries)), so it
is a deliberate decision left disabled in the workflow.

## The volume

Everything big lives on `/workspace` (a Docker named volume, or a RunPod
network volume):

| Path | What |
|---|---|
| `/workspace/mt/hymt2-7b-nf4`, `/workspace/mt/madlad7b-ct2` | The translators, each with `PROVENANCE.txt` and (Hy-MT2) its `LICENSE.txt` |
| `/workspace/madlad-ct2` | MADLAD 3B (`MADLAD=3b`) |
| `/workspace/voices` | Piper voices (checked against `voices.lock`) |
| `/workspace/voices/voxcpm` | VoxCPM2 reference voices (copied from `voices/voxcpm/`, never overwritten) |
| `/workspace/hf-cache` | Hugging Face cache (Whisper, language ID, Kokoro, VoxCPM2, MMS, Coqui) |
| `/workspace/torch-cache`, `/workspace/fairseq2-cache` | Silero VAD, Omnilingual (Docker) |
| `/workspace/venv_voxcpm` | VoxCPM2's virtualenv (RunPod; the image has its own) |
| `/workspace/translation-open-stack` | This repository (RunPod) |
| `/workspace/voxcpm.log`, `/workspace/voxcpm-<port>.log` | VoxCPM2 instances' logs |
| `/workspace/stack.log`, `/workspace/idle-stop.log` | The stack's and the idle stop's logs (RunPod; under Docker, `docker compose logs`) |
| `/workspace/.stack-token`, `/workspace/.stack-signing-key`, `/workspace/.stack-report-url` | Optional credential and report files (RunPod) |

A volume prepared for the non-profit edition holds MMS and ⛔ Piper voices:
don't hand it out ([licences.md §10](licences.md#10-before-you-deploy-commercially)).

## Repository layout and tests

| Path | What |
|---|---|
| `languages.toml` | Which model serves each language, and every shared model's pinned revision (`[models]`); edit this one. |
| `profiles/` | Hardware profiles: devices, smaller models and script defaults per setup ([Profiles](#profiles-and-devices)). |
| `Dockerfile`, `docker-compose.yml`, `.env.example` | The Docker path. |
| `constraints.txt`, `constraints-voxcpm.txt`, `voices.lock` | The pins ([Pins and the supply chain](#pins-and-the-supply-chain)). |
| `server/server.py` | The server: the pipeline (VAD, language ID, rooms, streaming) and the WebSocket protocol. |
| `server/engines/` | The recognisers, translators and voices, one file each, and the routing between them ([adding-an-engine.md](dev/adding-an-engine.md)). |
| `server/stack_config.py` | Reads and validates `languages.toml`. |
| `server/stack_auth.py` | Tokens and connection limits. |
| `server/licences.py` | The licence of every model and voice, as data. |
| `server/voxcpm_service.py` | The VoxCPM2 voice service (its own virtualenv). |
| `scripts/`, `scripts/runpod/` | Start, install, download and build scripts ([Scripts](#scripts)). |
| `tests/` | Unit tests (no GPU, no models, no server); `tests/test_protocol.py`, the real server on CPU with stand-in models; `tests/audio/`, short test clips. |
| `tools/` | Tools against a running stack ([Tools](#tools)). |
| `voices/voxcpm/` | The VoxCPM2 reference voices. |
| `docs/`, `eval/` | Documentation (contributors' docs in `docs/dev/`), and the model evaluation's data. |

Tests that need no GPU (`test_capacity.py` needs numpy and scipy; its eSpeak
NG case is skipped without `espeak-ng`):

```bash
python3 tests/test_stack_auth.py && python3 tests/test_stack_config.py
python3 tests/test_nonspeech.py && python3 tests/test_streaming.py
python3 tests/test_engines.py && python3 tests/test_licences.py
python3 tests/test_doc_links.py && python3 tests/test_capacity.py
python3 tests/test_profiles.py
python3 server/stack_config.py check
```

The protocol tests start the real `server/server.py` on CPU with stand-in
models (whisper tiny, t5-small, two Piper voices; ~0.6 GB downloaded once) and
check auth, limits, the hello message, frame sizes, `route=to`, `cands` and
concurrent connections. They run in CI (`.github/workflows/protocol.yml`) and
take about a minute once the models are cached:

```bash
pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-test.txt
python3 -m pytest tests/test_protocol.py -v
```

On a GPU, after any model or dependency change: `tools/smoke.py`
([user guide](user-guide.md#verify-with-the-smoke-test)).
