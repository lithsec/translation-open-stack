# Adding an engine

A speech recogniser, a translator or a voice is an **engine**: one Python file
in `server/engines/` (or in a directory of your own, see
[Out of tree](#8-out-of-tree)), named in `languages.toml`. You do not edit
`server/server.py`. The pipeline around the engines (speech detection,
endpointing, language ID, rooms, streaming, the protocol) is unchanged by an
engine and does not need to know about it.

How the pieces fit: [architecture.md](architecture.md). The interfaces, with
their full contracts: [`server/engines/base.py`](../../server/engines/base.py).
A working example to copy: [`server/engines/_template.py`](../../server/engines/_template.py).

**Contents**

1. [The three interfaces](#1-the-three-interfaces)
2. [A worked example: a translator in one file](#2-a-worked-example-a-translator-in-one-file)
3. [Naming it in languages.toml](#3-naming-it-in-languagestoml)
4. [Lifecycle](#4-lifecycle)
5. [Threads and locks](#5-threads-and-locks)
6. [Audio: sample rates, levels, seams](#6-audio-sample-rates-levels-seams)
7. [Where settings go](#7-where-settings-go)
8. [Out of tree](#8-out-of-tree)
9. [Testing it](#9-testing-it)
10. [Licences](#10-licences)

---

## 1. The three interfaces

Subclass one of these (from `engines.base`) and decorate it with `@register`
(from `engines`). `name` is what `languages.toml` calls it: lowercase letters,
digits and `_`, unique across all three kinds, and not one of the table keys
`asr`, `translator`, `voice`, `models`, `commercial`, `licence_review`.

| Kind | Named by | You implement | Returns |
|---|---|---|---|
| `Recognizer` | `asr = "<name>"` or `"<name>:<arg>"` for a **source** language | `transcribe(pcm16k, lang, want_segments=False)`; optionally `words(pcm16k, lang)` | text (`""` for non-speech); with `want_segments`, `(text, [(segment_text, end_s), ...])`; `words` gives `[(word, end_s), ...]` or `None` |
| `Translator` | `translator = "<name>"` for a **target** language | `translate(sentences, src, targets, text=None)`; optionally `supports_source(lang)` | `{lang: translation}` |
| `Voice` | `<name> = <value>` in a language, and/or `voice = ["<name>", ...]` | `synthesise(text, lang)`; optionally `stream(text, lang, fallback)` | 24 kHz mono PCM16 `bytes`, or `None` to let the next voice try |

Every engine may also set or override:

| Attribute / method | Default | Meaning |
|---|---|---|
| `title` | `None` | human name for log lines |
| `licence` | `""` | shown by `stack_config.py engines`; see [§10](#10-licences) |
| `lang_key` | `None` | the type (`str`, `bool`, ...) of the engine's per-language value `<name> = ...`; `None` = the engine takes none |
| `check_lang(lang, value)` (classmethod) | accepts | return an error string to reject a per-language value at `stack_config.py check` |
| `models` | `{}` | keys and defaults accepted under `[models.<name>]` |
| `enabled(ctx)` (classmethod) | a served language names the engine | whether to load it at all |
| `load()` | sets `available` | load weights; see [§4](#4-lifecycle) |
| `supports(lang)` | a language names it | whether to serve this language (a recogniser: this *source*) |

Kind-specific:

- **Recognizer** `arg`: `"none"` (default), `"optional"` or `"required"`, for
  `asr = "<name>:<arg>"` (Omnilingual's is its language code, `omni:khm_Khmr`);
  `self.arg_for(lang)` reads it. Without `words()`, a long unbroken speech is
  cut at its quietest point instead of after a sentence (as Omnilingual's
  languages are). Filter noise with `engines.common.is_nonspeech()`: Whisper
  invents captions ("Thanks for watching") and annotations ("Cough, cough.")
  in noise, and so may yours ([lessons-learned §3](lessons-learned.md#3-speech-recognition-language-id-and-vad)).
- **Translator** `languages`: the target codes it can do, or `None` for any;
  checked by `stack_config.py check`. `supports_source(lang) -> False` makes
  MADLAD pivot the sentences into English first (Hy-MT2 does this for Haitian
  Creole speakers).
- **Voice** `priority` (place in the default chain, lowest first; the built-ins
  are kokoro 10, voxcpm 20, coqui 30, piper 40, mms 50; a new voice defaults
  to 0, first), `lock_policy` ([§5](#5-threads-and-locks)), `streaming`
  (`stream()` implemented; see VoxCPM2).

What the pipeline does around them (`server/engines/manager.py`):

- **Recognition**: the source language's `asr` engine if it is running and
  `supports(lang)`, else Whisper.
- **Translation**: targets are grouped by their `translator` (default `hymt`);
  each engine gets **one batched call** with all its targets. A target whose
  engine is not running or does not support it goes to MADLAD. A target the
  engine leaves out of its answer, or maps to `""`, is translated by MADLAD
  (whole utterance); an exception does that for every target of that call
  (logged). Sentences are pre-split (`engines.common.split_sentences`:
  MADLAD dropped sentences when given several at once), and `text` is the
  utterance as heard for engines that prefer it whole.
- **Voices**: the chain is tried in order, the first non-`None` answer is
  spoken. Returning `None` means "not me, try the next"; raising means "this
  sentence fails" (logged, nothing spoken for it). Empty or punctuation-only
  text never reaches a voice.

## 2. A worked example: a translator in one file

[`server/engines/_template.py`](../../server/engines/_template.py) is a
complete translator that needs no download: MADLAD with a different prompting
strategy (the whole utterance in one prompt, instead of sentence by sentence).
It reuses the MADLAD the server has already loaded (`ctx.engine("translator",
"madlad")`), so it costs no memory. The heart of it:

```python
from engines import register
from engines.base import Translator


@register
class MadladWhole(Translator):
    name = "madlad_whole"                 # translator = "madlad_whole"
    title = "MADLAD, whole utterance"
    licence = "Apache-2.0 (MADLAD's)"
    models = {"max_words": "60"}          # [models.madlad_whole] max_words = "..."

    def load(self):
        self.madlad = self.ctx.engine("translator", "madlad")
        if self.madlad is None:
            return                        # not available: MADLAD serves its languages
        self.max_words = int(self.model("max_words", "60"))
        self.available = True

    def translate(self, sentences, src, targets, text=None):
        whole = text if text is not None else " ".join(sentences)
        if len(whole.split()) > self.max_words:
            return self.madlad.translate(sentences, src, targets, text=text)
        outs = self.madlad.generate([f"<2{self.madlad.tag(lg)}> {whole}" for lg in targets])
        return dict(zip(targets, (o.strip() for o in outs)))
```

To use it:

```bash
cp server/engines/_template.py server/engines/madlad_whole.py   # files starting "_" are never loaded
```

```toml
# languages.toml: Romanian through it
[ro]
piper = "ro_RO-mihai-medium"
asr = "whisper"
translator = "madlad_whole"
madlad = "ro"
```

```bash
python3 server/stack_config.py check      # ro ... mt=madlad_whole
python3 server/stack_config.py engines    # lists it, with its file
# restart the stack (docker compose up -d --force-recreate, or scripts/run.sh)
STACK_TOKEN=... python3 tools/smoke.py --langs ro
```

The server log says `[stack] loading translator madlad_whole (engines.madlad_whole)…`
at start. A real model follows the same shape: import its library inside
`load()`, keep the model on `self`, and decode in `translate()`. For a
translator wrapping, say, NLLB, `languages` would be the codes you map to
NLLB's `xxx_Latn` tags, and `models = {"repo": "...", "revision": "..."}` would
pin the weights ([§7](#7-where-settings-go)).

A voice or a recogniser is the same pattern; the bottom of `_template.py`
sketches both, and `engines/piper.py` (a simple voice),
`engines/omnilingual.py` (a recogniser with an argument) and
`engines/voxcpm.py` (a streaming voice over HTTP) are real ones to read.
`tests/engines_fixture/shout.py` has a translator and a voice small enough to
read in a minute.

## 3. Naming it in languages.toml

The existing keys keep working exactly as before. What is new:

```toml
[de]
translator = "nllb"             # any registered translator (was: hymt | madlad)
asr = "qwen3"                   # any registered recogniser (was: whisper | omni:<code>)
myvoice = "speaker-3"           # a voice's per-language value, under its own name
voice = ["myvoice", "piper"]    # optional: the chain, in this order
piper = "de_DE-thorsten-high"
```

- A **translator** or **recogniser** is picked by name. If it isn't running
  (not loaded, failed to load, or `supports()` says no), MADLAD or Whisper
  serves that language, and the server says so once at start
  (`[stack] translator nllb not running — madlad serves de`).
- A **voice** joins a language's chain when the language names it, either with
  its key (`myvoice = "..."`, which is how `kokoro`, `piper`, `coqui`, `mms` and
  `voxcpm` always worked) or in `voice = [...]`. Without `voice`, the chain is
  every running voice that supports the language, by `priority`: the built-ins
  in their old order (kokoro, voxcpm, coqui, piper, mms), a new voice first.
  With `voice`, exactly that order (CosyVoice cloning, `--clone`, still goes in
  front of it). A streaming voice in the chain takes the sentence in streaming
  mode, with the rest of the chain as its fallback: that is how VoxCPM2 has
  always behaved.
- Unknown names are errors at `stack_config.py check` (and at every start),
  never a silently text-only language:
  `[de] translator: unknown translator 'nlb' (registered: echo, hymt, madlad, nllb)`.

A language section **replaces** that language's defaults, as before, so keep
every key you still want.

## 4. Lifecycle

1. **Import.** At start, and whenever `stack_config.py` runs, every
   `server/engines/*.py` not starting with `_` is imported in name order, then
   every `*.py` in each `STACK_ENGINES_PATH` directory. `stack_config.py` runs
   on machines without torch (the macOS system Python, CI's checks job), so a
   module's top level may import only the standard library and `engines`;
   import `torch`, `transformers` and your model's library inside `load()` or
   the method that needs them. An import error names the file and stops
   everything.
2. **Enable.** `enabled(ctx)` decides whether this server instance loads the
   engine. The default is "a language this server serves (`--langs` for voices
   and translators, `--srcs` for recognisers) names it". The built-ins follow
   their flags instead (`--kokoro`, `--hymt DIR`, `--omni`, ...), so
   `scripts/run.sh` still decides what a deployment runs.
3. **Load.** `load()` runs once, before the server says "ready", in a fixed
   order: the built-ins as they always loaded (Whisper, then language ID, then
   Omnilingual, CosyVoice, Coqui, VoxCPM2, Hy-MT2, Kokoro, MADLAD, Piper, MMS),
   then new engines by name. Load onto `self.device` (`"cuda"`, `"cuda:1"`,
   `"mps"` or `"cpu"`: its `[devices]` entry, else the default; see
   [Profiles and devices](../reference.md#profiles-and-devices)), not a fixed
   `"cuda"`. It gets `self.ctx`: `models` (the merged `[models]`), `table` (the language tables),
   `langs`, `srcs`, `options` (the server's flags) and `engine(kind, name)`
   (another loaded engine). Set `self.available = True` when ready. Raise to
   stop the server when the engine is essential; for an optional one, catch,
   print why (`[stack] X unavailable (...) — Y instead`), and leave `available`
   False: the pipeline then falls back. *Loud beats silent*: a fallback nobody
   hears about served degraded audio for days more than once
   ([lessons-learned §10](lessons-learned.md#10-how-problems-were-found)).
4. **Warm-up.** Before "ready" the server transcribes a second of silence and
   translates and speaks one sentence in every language, so CUDA compilation is
   paid at start, not by the first listener. Lazy per-language loading (as
   Kokoro, Coqui and MMS do) happens there too.
5. **Serve.** Methods are called from worker threads for as long as the server
   runs. There is no unload.
   An engine whose backend starts in its own process beside the server (as
   VoxCPM2's services do) can also define `wait_ready()`: it runs once every
   engine has loaded, before warm-up and "ready", so that start overlaps the
   other engines' loading instead of coming before it.

## 5. Threads and locks

Recognition and translation run in the event loop's default executor;
synthesis in a pool of `LITHOS_TTS_WORKERS` threads (8). An utterance is split
into **sentences, each synthesised on its own thread**, and several rooms and
connections run at once. So:

- **Voices**: `lock_policy = "language"` (the default) gives each language one
  lock; hold it around the model call only, with `with self.lock(lang):`
  (not around downloads or resampling). Use it unless you *know* your model is
  thread-safe: removing the old global lock made Kokoro Spanish and Coqui
  Haitian sound like "robotic tremors" because two sentences went through the
  same model at once; it *measured faster* and only a listener caught it
  ([lessons-learned §5](lessons-learned.md#5-voices)). `"none"` is for engines
  that are safe as they are (Piper's ONNX sessions, VoxCPM2's HTTP client).
  `--serial-tts` turns every `"language"` lock into one global lock.
- **Translators and recognisers** are called concurrently too (a room's
  priority decode overlaps the rest; solo connections overlap each other). If
  the model is not safe to call from two threads, hold a lock of your own for
  the decode (`engines/hymt.py` does). Keep no per-call state on `self`.
- Anything built lazily on first use (a per-language pipeline) can race on its
  first two calls; build it in `load()` if that matters.

## 6. Audio: sample rates, levels, seams

- **In**: recognisers get 16 kHz mono float32 in [-1, 1] (Silero's and
  Whisper's rate; `engines.base.VAD_RATE`).
- **Out**: voices return **24 kHz mono PCM16** bytes (`engines.base.RATE`, the
  protocol's rate). Return your model's float32 samples through
  `engines.common.to_pcm16(pcm, native_rate)`: it resamples with padding (so
  short segments don't ring at their edges) and ramps 3 ms at each end (so
  sentences butt-joined in simultaneous mode don't click). A model that emits
  24 kHz natively (Kokoro) skips the resample, not the helper.
- **Level**: `engines.common.peak_normalise(pcm)` brings the peak to -1 dBFS
  (gain capped at 4×). Use it unless the model is already mastered like Piper:
  a room hears a language switch as a level jump, and MMS was 11 dB quieter
  than the rest.
- **Dead air**: trim leading and trailing silence if the model pads (Coqui's
  OpenBible voice padded a second at each end; `engines/coqui.py`).
- **Streaming voices** yield 24 kHz PCM16 chunks of whole samples. A stream
  can't know its peak, so it can't normalise; VoxCPM2 uses a fixed gain and a
  soft limiter in its service (`server/voxcpm_service.py`). If `stream()`
  cannot start, call `fallback()` and yield its bytes.
- **Text**: a voice gets one sentence at a time, split on `. ! ? ; :`. Watch
  for characters outside the model's script (MMS crashed on Latin digits in
  Khmer text) and for case (Piper's letter-trained voices drop capitals;
  `engines/piper.py` lowercases for them).

## 7. Where settings go

| Setting | Where | Read with |
|---|---|---|
| which engine serves a language | the language's table: `asr`, `translator`, `voice` | the pipeline |
| a per-language value (a voice name, a speaker, a code) | the language's table, under the engine's `name`; declare `lang_key` | `self.setting(lang)` |
| model repo, revision, sizes | `[models.<name>]`; declare `models = {key: default}` | `self.model(key)` |
| server-wide switches | an existing flag in `self.ctx.options`, or an environment variable (`LITHOS_*`) | `self.ctx.options`, `os.environ` |

`[models.<name>]` merges key by key over your declared defaults, like the
built-in models; unknown keys and non-string values are errors. Pin a
revision (a commit hash) for anything downloaded: a floating `main` changed
Silero under the stack the day it was pinned. Use `engines.common.hf_snapshot(repo,
revision)` to fetch a pinned Hugging Face snapshot. Weights that must be
converted or quantised once belong in `scripts/prepare-mt.sh` (or a script
like it) writing to `/workspace`, with a `PROVENANCE.txt`, not in `load()`.

## 8. Out of tree

To keep an engine outside this repository (a private model, an experiment),
put its file in a directory and list the directory in `STACK_ENGINES_PATH`
(several are separated by `:`), in the environment of both the server and
`stack_config.py`:

```bash
STACK_ENGINES_PATH=/workspace/my-engines python3 server/stack_config.py engines
STACK_ENGINES_PATH=/workspace/my-engines bash scripts/run.sh
```

The files load after the built-in ones, and the same rules apply (a name may be
registered once; files starting with `_` are skipped). A directory that does
not exist is an error. Docker: mount the directory and set the variable in
`.env`.

## 9. Testing it

1. `python3 server/stack_config.py check` and `... engines`: the file imports,
   the name is registered, `languages.toml` validates.
2. **Unit tests** without models: `tests/test_engines.py` shows how. Build an
   `EngineSet` with your class plus fakes for the rest, and check routing and
   fallbacks; `tests/engines_fixture/` is loaded through `STACK_ENGINES_PATH`
   in a subprocess. Run all of them:
   ```bash
   python3 tests/test_engines.py && python3 tests/test_stack_config.py
   ```
3. **CPU plumbing**: `tests/test_protocol.py` and `tools/dev-cpu.sh` start the
   real server with stand-in models; a CPU-capable engine can be configured in
   through `STACK_CONFIG` and `STACK_ENGINES_PATH`.
4. **GPU, end to end**: start the stack with your engine configured for a
   language and run the smoke test against it
   ([the user guide, "Verify with the smoke test"](../user-guide.md#verify-with-the-smoke-test)):
   ```bash
   STACK_TOKEN=... python3 tools/smoke.py --langs <lang>
   STACK_TOKEN=... python3 tools/smoke.py          # everything else still passes
   ```
   Watch the log for your engine's load line, `[stack] utterance ... mt ...s tts1[<lang>] ...s`
   stage timings, and GPU memory at idle (`nvidia-smi`) against the numbers in
   [lessons-learned §6](lessons-learned.md#6-latency-and-throughput).
5. **Quality** is not what the smoke test measures. Compare against the
   current engine the way [model-evaluation.md](model-evaluation.md) did, blind,
   before switching a language in production. Listen to it: timing harnesses
   can't hear.

## 10. Licences

Before an engine serves anyone, classify its model in
[`server/licences.py`](../../server/licences.py): an `ENGINES` entry (or, when the
licence depends on the per-language value, like Piper's voices, an `ITEMS`
table), with the class (`permissive`, `attribution`, `share-alike`,
`noncommercial`, `unclear`), the licence as stated, why, the upstream link and,
for attribution or share-alike, the credit it needs. An out-of-tree engine can
declare its own instead: `licence_class = "permissive"` (and `licence`,
`licence_url`, `licence_obligation`) on the class. **An engine with neither is
unclear, and `EDITION=commercial` refuses to construct it**; the tests fail
when `languages.toml` names an item without an entry. Add the library to
[licences.md](../licences.md) §8 too. Set `licence` on the class so
`stack_config.py engines` shows it. Non-commercial weights (CC-BY-NC, like MMS) belong only in the
non-profit edition and must be downloaded by the operator, never shipped: make
such an engine opt-in (an `enabled()` that follows a flag, as `engines/mms.py`
follows `--mms`), not merely named in the default `languages.toml`.
