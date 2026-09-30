# Lessons learned

What building and running the stack taught us, from the first CPU smoke test in
August 2026 to the 25-language production stack of late September 2026. Most
of it was found the hard way: a pod billing all night, a language serving
fluent nonsense, a threshold that ate scripture. Each entry gives the
**symptom** you would see, the **cause**, and **what the code does now**, with
the file where the fix lives, so the next person recognises the failure
instead of rediscovering it.

This is not a manual. How to run the stack is in the [user guide](../user-guide.md)
and the [reference](../reference.md); which model won and by how much is
in [model-evaluation.md](model-evaluation.md); the wire protocol is in
[protocol.md](protocol.md); licences are in [licences.md](../licences.md).

**Contents**

1. [Timeline](#1-timeline)
2. [Environment and dependency pins](#2-environment-and-dependency-pins)
3. [Speech recognition, language ID and VAD](#3-speech-recognition-language-id-and-vad)
4. [Translation](#4-translation)
5. [Voices](#5-voices)
6. [Latency and throughput](#6-latency-and-throughput)
7. [Running on RunPod](#7-running-on-runpod)
8. [Security](#8-security)
9. [Protocol and client gotchas](#9-protocol-and-client-gotchas)
10. [How problems were found](#10-how-problems-were-found)

---

## 1. Timeline

- **Late August 2026: the test rig.** Built inside the Lithos Live Translation
  repository as a single WebSocket server (Silero VAD, faster-whisper,
  MADLAD-400 3B, Piper), first smoke-tested on a Mac CPU with tiny stand-in
  models, then run on a RunPod RTX 4090. Then a week of live testing through the Live
  Translation app: shared room pipeline, Omnilingual for low-resource sources,
  adaptive endpointing, simultaneous mode, Kokoro voices, Haitian Creole off
  MMS, and a long series of hallucination, latency and audio-quality fixes.
- **26-27 September: the model evaluation.** 20+ models against Gemini Live,
  graded blind. Hy-MT2 7B (4-bit) became the main translator, MADLAD 7B the
  fallback; German, Kokoro Japanese and Mandarin added.
- **28 September: production.** VoxCPM2 voices for Khmer, Lao and Tagalog;
  signed tokens and connection limits; `/health`; `route=to` and `cands` for
  Lithos Talk; 24 languages; a working Docker image and `languages.toml`; the
  RunPod idle stop fixed twice.
- **29 September: stand-alone.** Romanian (25 languages), a speech detector per
  connection, extraction into this repository, the licence audit, and the
  `server/ scripts/ tests/ tools/` layout.
  Then the engines split: every recogniser, translator and voice moved out of
  `server/server.py` into its own file in `server/engines/`, chosen per
  language in `languages.toml` ([architecture.md](architecture.md)). The
  lessons below point at the new files; the behaviour did not change.

---

## 2. Environment and dependency pins

Three of this project's worst days were environment, not code. The rule that
came out of them: **one install script** (`scripts/install-deps.sh`) for both
the pods and the Docker image, **loud failures** instead of silent fallbacks,
and a **build-time import gate** (`Dockerfile`).

| Pin | What breaks without it | Where |
|---|---|---|
| `transformers==4.57.6` (any 4.x ≥ 4.49 works; never 5.x) | MADLAD degenerate output; Omnilingual can't import | `scripts/install-deps.sh`, `Dockerfile` asserts `4.` |
| `torchaudio==2.8.0` | must match torch minor for minor; fairseq2 repins torch | `install-deps.sh` |
| `scipy==1.13.1` (with Omnilingual, in one pip pass) | `module 'numpy' has no attribute 'long'` | `install-deps.sh` |
| Base image `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` (torch 2.8, CUDA 12.8) | Blackwell (`sm_120`) needs CUDA 12.8; the CUDA/torch/CTranslate2 triple breaks silently | `Dockerfile` (asserts torch 2.8) |
| `voxcpm==2.0.3` in its own venv | VoxCPM2 pins library versions the stack must not inherit | `scripts/prepare-voices.sh` |
| Model revisions (Whisper, language ID, Silero, Hy-MT2, MADLAD 7B/3B, Kokoro, VoxCPM2) | a floating `main` changes the model under you (Silero's master moved on 2026-09-29, the day it was pinned) | `languages.toml` `[models]`, read by `server/stack_config.py` |

**transformers 5 breaks MADLAD** (reproduced 2026-08-28 on 5.16.1).
*Symptom:* translations like "ll ll ll ll…" or "ty u u e je je ij…". *Cause:*
unidentified. v5 declines to tie `shared.weight` to `decoder.embed_tokens.weight`
(the checkpoint holds both, differing by up to 253), but tying them by hand only
changes which garbage comes out. It is not fp16 (bf16 is identical) and not the
tokenizer (`<2es>` tokenizes identically on 4.46.3 and 4.57.6). v5 also pulls
`huggingface_hub` 1.x, which fairseq2 0.6 rejects (`~=0.32`), taking Omnilingual
with it. *Now:* pinned to 4.57.6. The pin sat at 4.46.3 for weeks on evidence that
only ever covered v5; a proper bisect showed 4.49.0 and 4.57.6 both correct.
Raising it removed two workarounds: the CTranslate2 converter needs a newer
transformers (it passes `dtype=`, which 4.46.3 rejects), and `coqui-tts` needs
≥ 4.49. Transformers is off the hot path anyway: MADLAD decodes through
CTranslate2.

**fairseq2 (Omnilingual) rearranges the environment.** *Symptom:*
`module 'numpy' has no attribute 'long'` at T5 import, two packages away from the
cause. *Cause:* fairseq2 downgrades numpy to ~1.26, stranding a numpy-2 scipy,
and repins torch, breaking the torchaudio pairing. *Now:*
`pip install omnilingual-asr 'torchaudio==2.8.0' 'scipy==1.13.1'` in one pass.
`coqui-tts` pulls the other way (numpy 1.26 → 2.5, scipy 1.13 → 1.18, against
fairseq2's declared `numpy~=1.23`); Omnilingual was verified to still
*transcribe* on that combination. Install order matters and is fixed in
`install-deps.sh`: Coqui before Omnilingual, the order the measured pods used.

**Omnilingual silently missing, so Khmer served nonsense** (August 2026).
*Symptom:* Khmer → English came back as "The 1000-year-old hill of the hill of
the hill…", with or without `src=km`. *Cause:* `--omni` was passed but the
provisioner never installed `omnilingual-asr`; the server logged
"Omnilingual unavailable — ht/km/lo/sw fall back to whisper (poor)" and Whisper
produced fluent, confident nonsense. *Now:* installed by `install-deps.sh` with
a loud warning on failure, and `STRICT=1` in the image build fails the build.

**Import success is not proof.** A clean import has misled this project
before. Omnilingual compatibility was always verified by running a
transcription, and the Docker build gate (`Dockerfile`) checks every runtime
import plus `spacy.load('en_core_web_sm')`. Things that have been missing from an
image or pod at some point: `speechbrain` (that *is* `src=auto`; without it the
server starts and mis-routes every guest), `onnxruntime` (only present
transitively via piper-tts, but imported directly for the thread fix),
`coqui-tts` (in a comment only, so Haitian silently fell back to MMS),
`server/stack_auth.py` (would have refused every connection).

**PEP 668 on the pod image.** *Symptom:* `pip install` refuses. *Now:*
`--break-system-packages` everywhere (`$PIP` in `install-deps.sh`). A venv is the
wrong answer on a disposable container that already carries CUDA torch. The one
line that missed it, `spacy download` (which shells out to pip), now sets
`PIP_BREAK_SYSTEM_PACKAGES=1`.

**Packages installed at first use.** Kokoro's English G2P pip-installs a spaCy
model inside the server process at the first English sentence, which dies on
PEP 668 and takes startup with it; without the model, English fails at
*synthesis*, not at start. *Now:* `en_core_web_sm` is fetched at install time.
A service must not install packages while someone is speaking.

**Other install traps:**

- MeCab's dictionary (`python -m unidic download`): without it Kokoro Japanese and
  Coqui fail with "Failed initializing MeCab".
- Japanese Piper needs `pyopenjtalk`, not espeak-ng; without it the voice loads and
  throws at synthesis.
- `kenlm` (pulled by Omnilingual) compiles from source. A plain
  `nvidia/cuda` runtime image has no compiler, and `--no-install-recommends` also
  strips `python3-dev` (`Python.h` missing). Found on the first real image build;
  the image now builds from the RunPod PyTorch base, which has
  the build tools.
- piper-tts 1.3 renamed the synthesis entry point; the 1.2-style call crashed the
  connection on the first utterance (now `synthesize_wav`).
- On macOS the piper wheel's espeak-ng aborts the whole process looking for
  phoneme data at a path baked in at build time. It is a native abort, so no Python
  `except` catches it. The local workaround is a directory shaped to satisfy both
  of espeak's probes, passed as `ESPEAK_DATA_PATH`. Linux wheels are unaffected.
- VoxCPM2's `from_pretrained` has no revision argument: `voxcpm_service.py`
  resolves the pinned snapshot with `snapshot_download` and loads it by path,
  with `HF_HUB_OFFLINE=1`.

---

## 3. Speech recognition, language ID and VAD

### Whisper invents text into silence and noise

This took four rounds; the order matters, because each fix was partial.

1. **Idle microphone** (Aug 2026). *Symptom:* "hello thank you for coming today"
   came back as "Subtitulado Societe Radio-Canada gracias", late. *Cause:* bench
   clips start speaking immediately, but a live mic idles; the endpoint fired on
   silence alone, so ever-growing silence buffers were transcribed in a loop,
   hallucinated subtitle credits were translated, and real speech queued behind
   them. *Now:* an utterance requires Silero to have fired since the last cut; an
   idle mic keeps only a 0.5 s pre-roll (`server/server.py`).
2. **Trailing silence.** *Symptom:* Spanish ending in "gracias por su comentario".
   *Now:* the pause that ended the utterance is trimmed to 250 ms;
   `condition_on_previous_text=False` (one invented sign-off could otherwise
   condition the next utterance into repeating it); `no_speech_threshold=0.6`.
3. **Room tone.** Still "Thank you" appended. A room is never digitally silent,
   and the sign-offs come back *confident*, so thresholds don't catch them. *Now:*
   `vad_filter=True`: Whisper only sees what Silero calls speech. **This is the
   fix that worked.** (Synthetic white noise at -40 and -34 dBFS never reproduced
   the hallucination; real room tone differs.)
4. **The gate that ate scripture.** A segment drop at `no_speech_prob > 0.5`
   discarded real speech: quiet, evenly read scripture scores 0.53-0.65 while being
   transcribed confidently. *Now:* a segment is dropped only when
   `no_speech_prob > 0.9` **and** `avg_logprob < -1.0`.

### Coughs

*Symptom:* a cough into the mic produced 3.65 s of Spanish "Tos, tos, tos. Abre -
¡Ha, ha!". Eight recorded coughs (ESC-50) were transcribed as "Cough, cough,
cough.", "ぷっぷっ", "ご視聴ありがとうございました". *Cause:* confidence can't
separate them: coughs arrive at `no_speech_prob` 0.50-0.75 and logprob -0.59 to
-1.50, while "Amen." is -0.660 and "Yas." -1.008. *Now* (`is_nonspeech()` and
constants in `server/engines/common.py`, the segment gates in
`server/engines/whisper.py`, replayed by `tests/test_nonspeech.py`):

- drop by **content**: annotations (`[music]`, `(coughing)`, ♪), caption
  sign-offs, a non-lexical token repeated. The repetition rule checks a
  noise-word set first; an earlier version dropped "Holy, holy, holy." and
  "Amen, amen.";
- `no_speech_prob` only as a secondary gate, on segments of one or two units;
- units counted script-aware: Khmer, Lao, Thai, Chinese and Japanese have no
  spaces, so `split()` returned 1 for a whole sentence;
- the Omnilingual path needed the same filter (it returns before the segment
  gates);
- a cough identified confidently as Khmer was poisoning the room's sticky
  language; the language is now committed only after a pass proves to be speech.

Result: eight coughs → silence, with 98/98 words of a reading kept and "Amen.",
"Yes.", "Hallelujah.", "Praise the Lord." still spoken.

**Never drop speech for being short.** A guard dropped utterances under 1.5 s
with fewer than 3 words. *Symptom:* "Great." (1.1 s) and "Thank you." (0.8 s)
vanished. The cough test passed only because synthetic "Amen." landed at 1.5-2.0 s.
Brevity never caught the noise; content and confidence did. Removed, with a
comment at the constant.

### Recognisers

- **distil-large-v3 is English-only.** It mis-transcribes other languages with
  confidence, and drops proper nouns and casing even in English ("town of cintra",
  "a romantic" against large-v3's "town of Sintra", "the romantic"). `run.sh` uses
  `--asr-model large-v3` for everything: +0.20 s, and one model instead of two, so
  GPU memory goes *down*.
- **Whisper can't do Khmer or Lao** (character error 99-173% in the evaluation;
  on 2026-08-27 a Khmer clip produced "Qt::Create_A_Client 1000000…"). Omnilingual
  ASR 300M gives coherent Khmer and Lao; its weakness is proper nouns ("john
  smith" for Brzezinski). It takes **file paths, not arrays** (the server writes a
  temp WAV per utterance) and returns **no word timings**, so its languages can't
  use sentence-end cuts or streaming trims. On a Mac CPU it took 46 s for a 16 s
  clip. Routing is by resource level, not geography: Omnilingual for ht km lo sw
  and, since 2026-09-28, hi fa bn ur (Bengali 34.9% → 3.1% word error on FLEURS).
- v2 Omnilingual models print "⁇" for several Lao vowel signs; v1 300M stays
  (see [model-evaluation.md](model-evaluation.md#33-recognition)).

### Language identification (VoxLingua107)

- **Constrain the argmax to the languages you expect.** On the synthetic corpus
  (Aug 2026) unconstrained accuracy was 67.6%, constrained to the eight configured
  languages 88.2%; on real FLEURS speech 95% → 100% (140 clips). Every
  unconstrained error was a language nobody asked about (Esperanto, Maltese,
  Tibetan…). This is why `SRCS` exists, and why Lithos Talk sends `cands`.
- **`cands` for two-person conversations** (2026-09-28). *Symptom:* Talk read
  Spanish as Russian, Tagalog and Indonesian, and English as French, Vietnamese and
  Bengali. *Cause:* detection chose among all 24 languages. *Now:* `?cands=en,es`
  limits it to the conversation's languages.
- **Short speech doesn't carry the language, and it fails toward English.**
  Measured on Spanish: 1.5 s fragments → "en" at 0.45-0.52 confidence (wrong every
  time); 3 s → "es" at 0.99-1.00. *Now* (`server/server.py`): relaying the
  microphone untranslated needs ≥ 0.75 of the constrained mass **and** ≥ 2 s
  (`PASSTHROUGH_MIN_CONF`, `PASSTHROUGH_MIN_S`); a room remembers its last
  confident language instead of falling back to "en"; a language *switch* on a
  fragment under 5 s needs 0.90 (`SWITCH_MIN_CONF`, `SWITCH_FREE_S`). The window was
  2.5 s until a 2.5 s English turn went through the Portuguese model: the
  comparison is strictly-less-than.
- Known confusions: Ukrainian with Russian (once); Urdu is detected as Hindi from
  speech. Set the room's source language when it is known.

### Silero VAD

- **v5 requires 512-sample frames.** A short final chunk crashed the connection.
  Short frames are padded everywhere now (the solo path missed it until
  2026-09-29).
- **State shared across connections** (2026-09-29). *Symptom:* with four solo
  connections at once, English lost its first words or produced nothing; one at a
  time was fine. *Cause:* one Silero model served every connection, and its
  recurrent state and frame context carry from call to call. *Now:*
  `Pipeline.new_vad()` gives each connection and each room its own copy, reset at
  the start. Retested on an A100: 12 of 12 whole over three rounds of four.

### Endpointing and long speech

- **Readers don't pause for 700 ms.** A paragraph read aloud was one 21.9 s
  utterance, delivered as one block at the end. *Now:* adaptive: a full pause
  (700 ms default, 900 in `run.sh`) under 5 s of speech; a 280 ms clause gap after
  that; a forced cut at `--max-utterance-s` (9 s default, 12 in `run.sh`). A forced
  cut keeps `speech_seen` set so the next chunk doesn't trim its own opening as
  idle-mic pre-roll.
- **Where the forced cut lands.** On the stopwatch it fell mid-word: the ASR
  invented the rest and the TTS spoke it with a falling contour. First fix: cut at
  the quietest 20 ms frame in the last 2 s (never in the final 300 ms), carrying
  the remainder forward. Since 2026-09-27: run the recogniser with word timings and
  cut after the last **sentence end**, carrying the unfinished sentence (+1 to +4
  points on a 78 s pause-free reading; es 90.3 → 93.1%). Omnilingual sources keep
  the quietest-point cut. `LITHOS_SENTENCE_CUT=0` restores it.

### Simultaneous (streaming) mode

- **LocalAgreement-2:** re-transcribe the turn every ~0.9 s, commit words two
  passes agree on, speak each clause. Per connection it would re-transcribe the
  same mic once per language, so it lives in the room (`?stream=1`, fixed by the
  first connection).
- **Align commits by text, not index.** *Symptom:* "it's adding lines" while
  reading. *Cause:* `words[translated_n:]` assumes the turn's prefix never changes;
  it does ("my beloved brother" → "my beloved brethren"), so words were repeated or
  skipped. *Now:* `resume_point()` anchors on the tail of what was actually spoken
  (`tests/test_streaming.py`). It can't fix a wholesale rewrite: audio can't be
  un-said.
- **Pass time climbs through a turn** (0.15 s → 0.76 s in one live 10.7 s turn)
  because the whole turn is re-decoded. Buffer trimming (`LITHOS_TRIM=1`, cut at
  the second-to-last Whisper segment past `LITHOS_TRIM_S`, 8 s) makes the committed
  prefix immutable, as whisper_streaming and HF speech-to-speech do. It is off by
  default and only fires when Whisper returns ≥ 2 segments; GPU-validated at
  `LITHOS_TRIM_S=3` (8 trims, 115/115 words).
- **The clause gate is the pause people hear.** With no punctuation the turn waits
  for `STREAM_MAX_WORDS`: 12 words was ~4.5 s of silence (worst gap 4.58 s). Set to
  8 on 2026-08-30 **by ear**; comma boundaries need 6 pending words; a clause under
  4 words waits (single-word utterances like "a" sounded worse than utterance
  mode). All three are `LITHOS_STREAM_*` variables.
- The trade stays real: on a 37 s reading, first audio 3.2 s against 6.55 s for
  utterance mode, but the translator sees a clause, and endings still garble. It is
  off by default.

---

## 4. Translation

**Current:** Hy-MT2 7B (4-bit NF4) for its 36 languages, MADLAD-400 7B
(CTranslate2 int8) for the rest, with non-Hy-MT2 sources pivoting through English
(`server/engines/hymt.py`, `server/engines/madlad.py`; the routing, pivot and
fallbacks in `server/engines/manager.py`).
The numbers are in [model-evaluation.md](model-evaluation.md#32-translation);
the lessons behind them:

- **MADLAD must load in bfloat16, never float16** (the first GPU session, Aug
  2026). *Symptom:* "ue ue ue ue" to `max_new_tokens`, no error. *Cause:* T5-family,
  trained in bf16; fp16 activations overflow silently. Invisible on CPU. Now moot
  on the hot path (CTranslate2), but the bf16 load remains for the no-CT2 fallback.
- **Don't load MADLAD twice.** With `--mt-ct2`, the bf16 HF copy was also loaded and
  never used: ~6 GB of a 20.1 GB footprint. Only the tokenizer is needed now.
- **Bound `max_new_tokens` by input length.** A flat 256 let one degenerate
  generation burn 12 s. But size it for the script: Hy-MT2's cap is 10× the source
  tokens because Khmer took 136 tokens for an 18-token English sentence, and 3×
  truncated every Khmer line.
- **Translate sentence by sentence (in one batch).** Given two sentences as one
  input, MADLAD dropped one (2026-09-26: Ukrainian kept only the first, Japanese
  only the second).
- **Ukrainian drifts into Russian** with MADLAD and OPUS-MT. M2M100 1.2B fixed
  English→Ukrainian but produced garbage from other sources ("Previous article: How
  to open a museum on Sunday") and was retired a day later for Hy-MT2.
- **4-bit costs nothing.** Hy-MT2 4-bit 92.7% (13 critical), FP8 92.2% (15), bf16
  93.0% (13); 7.5 GB instead of 16 GB and faster (352 ms against 548 ms per
  sentence). Built once from a pinned revision (`scripts/prepare-mt.sh`); the
  server loads it with `local_files_only`.
- **Greedy vs beam.** In August `num_beams=4` made a long sentence worse ("los
  sustantivos que se usan en el mundo" → "los sustantivos junto al mundo") for
  +0.11 s. Later, greedy was caught in a local trap on short courtesies: "Thank
  you." → "Gracias por tu comentario." (after "Gracias", "por" scored just above
  "."). Beam 4 is the default now (`LITHOS_MT_BEAM`, +4 ms per phrase), with a known
  cost: subtitle-corpus artefacts on some short phrases ("Grazie." → "- Grazie,
  signore.").
- **Don't translate a language into itself.** es → es through MADLAD read the
  speaker's sentence back as a fluent paraphrase in a stranger's voice. Members
  whose language is the spoken one get the microphone audio (0.70 s against
  2.07 s, and the real voice), subject to the confidence rule in §3.
- **Clause fragments translate wrongly, not partially.** MADLAD reorders across a
  clause, so half a clause is a wrong translation. This drives `--endpoint-ms 900`,
  the sentence-end cut, and the streaming clause gate.
- **Output quirks to know:** a literal `&#160;` in Khmer output (cleaned up);
  Tagalog is `<2fil>` to MADLAD; MADLAD sometimes drops Romanian diacritics
  entirely and mixes cedilla (ş ţ) and comma-below (ș ț) forms; Swahili clock times
  go wrong (Swahili time counts from 6 am); MADLAD says "5 in the morning" for "5
  o'clock"; idioms go literal (pt "na casa dos 20 anos" → "in the house of 20
  years").
- **MT is the latency.** In August it was 60-75% of the pipeline. See §6 for
  CTranslate2 and priority decoding.

---

## 5. Voices

**Current:** Kokoro (GPU) for en es fr it pt ja zh hi; VoxCPM2 (GPU, its own
service on :8791) for km lo tl; Piper (CPU) for the rest and as fallback; Coqui
OpenBible or MMS for Haitian Creole by edition. See
[the reference, "Voices"](../reference.md#voices).

- **Piper's choppiness is the model, not the pipeline.** Waveforms show no clicks
  (worst step-to-local-RMS 4.6-7.6, where a real click reads 20×+). Kokoro was
  chosen by ear for its languages. It emits 24 kHz, the pipeline's rate, so no
  resampling. It runs ~98× real time on GPU but only 2× on CPU, so don't run it
  without a GPU. End to end it changed latency by nothing (first audio 0.33-0.37 s
  either way).
- **Seams between sentences click.** Synthesis streams per sentence, and segments
  were butt-joined raw: a step of 17181 against a 1857 maximum elsewhere in the
  signal, plus resampler ringing at each short segment's edges. *Now:* pad before
  resampling and a 3 ms ramp at each end (one shared helper, `to_pcm16` in
  `server/engines/common.py`, that every voice engine uses).
  Clipping was measured and ruled out: resampling overshoots to 1.003-1.006, one
  or two samples per sentence.
- **Voice models are not thread-safe** (Aug 2026). Removing the single GPU TTS lock
  made Spanish (Kokoro) and Haitian (Coqui) develop "robotic tremors": several
  sentences of one utterance ran through the *same* model at once. It measured
  faster and sounded worse, and only a listener caught it. *Now:* one lock per
  voice model (`EngineSet.voice_lock` in `server/engines/manager.py`; a voice engine's
  `lock_policy`), 8 TTS workers (`LITHOS_TTS_WORKERS`); a 4-worker pool
  had hidden the benefit of removing the lock. `--serial-tts` restores one global
  lock for a small card.
- **Where the voices live:** one file each in `server/engines/` (`kokoro.py`,
  `voxcpm.py`, `coqui.py`, `piper.py`, `mms.py`); the level fix below is
  `peak_normalise` in `server/engines/common.py`.
- **MMS quirks.** Its tokenizers are script-specific: Latin text (numerals,
  borrowed words) into the Khmer or Lao model maps to an empty tensor and crashes
  VITS (`narrow(): length must be non-negative`), now guarded. It renders ~11 dB
  quieter (Haitian RMS -25.5 dBFS against -14 to -15), inaudible on a phone in a
  room; output is now peak-normalised to -1 dBFS with gain capped at 4×.
- **Piper voices trained on raw letters only know lowercase.** Ukrainian silently
  dropped every capital, so each sentence lost its first sound. Text is lowercased
  for voices whose `phoneme_type` is `text` (`server/engines/piper.py`).
- **Coqui OpenBible (Haitian) pads about a second of dead air at each end**: 3.86 s
  of audio for 1.68 s of speech. The path trims before normalising.
- **Voice names are exact.** The Japanese Piper fallback was configured as
  `ja_JA-hi_fi_captain-medium`, which doesn't exist; it is `ja_JP-…`. An earlier
  comment also claimed Piper had no ja/ko voices, which left them text-only for no
  reason. Check the [catalogue](https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json).
  Japanese Piper runs at 2.4× real time against Korean's 37×.
- **onnxruntime threads.** See §6: it was the largest single performance fix.

### VoxCPM2

- **Measured in August against MMS** (RTX PRO 4500): works in Khmer, Lao and
  Swahili at 48 kHz, but RTF 0.46 (advertised 0.3 for a 4090), 109 s and 4.7 GB to
  load, and a 3:1 level spread between languages (peaks 0.22-0.78). In service it
  takes 6.2-7.1 GB and sustains **about two real-time voices per GPU**, so it only
  serves languages with no other voice.
- **A new speaker every sentence** (2026-09-28). *Symptom:* Lao switched voice,
  even from a man to a woman, mid-phrase. *Cause:* without a reference VoxCPM2
  invents a speaker per call, and the stack voices each sentence separately.
  *Now:* the service clones `voices/voxcpm/<lang>.wav` for every call. References
  were chosen from four random voices by round-trip clarity (Khmer 9.7% → 7.0%, Lao
  11.8% → 3.7%), are committed in `voices/voxcpm/` and copied to the volume
  without overwriting (`scripts/prepare-voices.sh`). They were only on the RunPod
  volumes at first, so a fresh setup got a new speaker every sentence again.
- **Streaming** (2026-09-28): Khmer audio starts ~0.1 s after its text instead of
  1.5 s. The 48 kHz output is halved to 24 kHz with a *stateful* FIR, because
  resampling each chunk on its own rings at every edge. A stream can't know its
  peak, so it gets a fixed gain of 1.5 (1.8 clipped louder sentences) and a
  per-sample soft limiter above 0.9 (`server/voxcpm_service.py`).
- **Don't cut diffusion steps.** 4 steps instead of 10 saves 9% of the work and
  takes Khmer error from 9.7% to 24.2%, as unclear as MMS.
- **Capacity: queue in the stack, not in the service** (2026-09-30). Commercial
  routes ten languages to VoxCPM2, so there is one instance per GPU and the
  server balances them (`server/engines/voxcpm.py`). A service makes one voice
  at a time (RTF 0.28 on an A100: a 5 s sentence is ~1.4 s of GPU, so ~3
  real-time listeners per GPU, ~2 at RTF 0.46). A pre-release audit found three
  faults in the first version:
  - *A cap of 3 per instance was a hidden queue.* The service's model lock ran
    one and parked two, which the balancer could not see (another GPU could be
    idle), and it sent headers only after the lock: a sentence queued past
    `VOXCPM_TIMEOUT_S` (30 s) made the client mark a healthy instance down and
    was still generated later, for nobody. *Now:* cap 1
    (`VOXCPM_MAX_INFLIGHT`), the service answers 503 if busy for more than 1 s,
    sends headers as soon as it holds the model, drops a request whose client
    has gone before any GPU work, and stops generating when a write fails. The
    server holds the queue: a sentence waits for the first free instance up to
    `VOXCPM_QUEUE_S` (2 s: hidden behind the previous sentence still playing,
    since audio is made ~3.5x faster than it plays), then goes to eSpeak NG; up
    to `VOXCPM_WAIT_S` (15 s) when nothing follows VoxCPM2.
  - *Waiting on the shared pool starved it.* `send_speech` ran each stream's
    `next()` on `TTS_POOL` (8 workers). Waiters for a slot took every worker, so
    the streams holding the slots could not advance and Piper/Kokoro for every
    other language stalled: 1 instance, cap 3, 11 Khmer listeners -> all 15 s,
    5 silent. *Now:* each stream is iterated on its own thread, which only ever
    waits for itself (regression test in `tests/test_capacity.py`).
  - *Leaked slots.* A malformed `X-Sample-Rate` raised outside the `try`, and a
    stream closed from another pool thread while running raised "generator
    already executing" and never released. *Now:* one `try/finally` covers
    every exit after the slot is taken, and close() runs on the stream's own
    thread, after any `next()` in progress.

---

## 6. Latency and throughput

**Where it stands** (evaluation, 2026-09-27): first translated audio ~0.8 s after
the speaker stops. In late August, with MADLAD 3B: first audio 0.36 s, five
languages done in 0.72 s.

**The biggest wins, in the order they were found:**

| Fix | Before → after | Where |
|---|---|---|
| **Shared room pipeline**: VAD, ASR once, one batched MT, parallel TTS (`?room=`) | 7 languages, one 10.6 s clip, RTX 4090, 2026-08-27: median **9.45 s → 0.10 s** first audio after end of speech (worst 19.61 s); all 7 within ~90 ms | `server/server.py` (`Room`) |
| **Warm-up before "ready"** | the first listener's first utterance paid ~3 s of CUDA compilation | server start |
| **onnxruntime thread pool bounded** | the host showed 96 cores, the container's quota was ~10: Piper at 0.7× real time, audio falling further behind the longer someone spoke. Threads 1/2/4/8: 10.1×/14.3×/19.8×/23.7×. One utterance: TTS 4.71 s → 0.17 s, first audio 3.96 s → 0.25 s | `intra_op_num_threads` in `server/engines/piper.py` |
| **Per-sentence synthesis and a worker queue** | the room used to await the whole pipeline inline, so the socket wasn't read during synthesis; the queue sheds the oldest past depth 3, and says so | `server/server.py`, `server/engines/manager.py` (`synthesise_futures`) |
| **MADLAD through CTranslate2 int8** | MT was 60-75% of the pipeline (1.25-1.97 s of 2.0-2.6 s) | `--mt-ct2`, `scripts/prepare-mt.sh` |
| **Priority decode for the room's language** (`?priority=1`) | a batched decode waits for the *longest* output (Khmer, Haitian); the PA language now gets its own small decode first and leaves at ~0.28 s | `server/server.py` |
| **Same-language passthrough** | 2.07 s → 0.70 s, and the real voice | §4 |

**Trading latency for accuracy** (RTX 4090, three FLEURS clips, August 2026).
Accuracy here comes from giving the models **whole sentences**, not from more
compute per sentence. `scripts/run.sh` carries the result:

| Knob | Cost | Verdict |
|---|---|---|
| `--asr-model large-v3` | +0.20 s | **yes**: names and casing; replaces the second model, so less VRAM |
| `--endpoint-ms 900` | +0.20 s | **yes**: fewer sentences cut mid-thought, the biggest lever on MT quality |
| `--max-utterance-s 12` | 0 normally | **yes**: bites only on unbroken speech |
| ASR `beam_size=5` | none | no: identical to greedy on all three clips |
| MT `num_beams=4` | +0.11 s | no on long sentences then; later adopted for short courtesies (§4) |
| Simultaneous mode | halves first audio (6.55 → 3.20 s) | accuracy cost; off by default |

With those three flags the August pipeline ran 2.0-2.6 s from end of speech to
audio out for five languages.

**Other measurements worth keeping:**

- A streaming re-transcribe pass on the pod cost 0.12-0.27 s, nearly constant with
  buffer length because Whisper's encoder pads to 30 s: one room ≈ 25% of the GPU.
- TTS lock and pool: with a 4-worker pool, first audio after MT was staggered
  +0.05/+0.10/+0.14/+0.18 s; with per-model locks and 8 workers, +0.10 to +0.12 s,
  and the five-language turn went 0.76 → 0.71 s. VRAM barely moved (19.2 → 19.3 GB
  of 32 GB): the models were already resident.
- X→English through Whisper large-v3 (Aug 2026): median 6.2 s over six sources,
  and hallucinated Khmer. That led to Omnilingual.

**GPU memory, as it grew:**

| Date | Configuration | Measured |
|---|---|---|
| Aug 2026 | MADLAD 3B CT2 plus an unused bf16 copy | 20.1 GB (~6 GB of it the unused copy) |
| 2026-09-27 | eval stack without VoxCPM2 | 24.8 GB ready, 26 GB serving four rooms |
| 2026-09-28 | everything incl. VoxCPM2, RTX PRO 4500 | 31.8 of 32.6 GB |
| 2026-09-28 | 24 languages, L40, `expandable_segments` | 32.8 GB idle (25.7 server + 7.1 VoxCPM2): needs a 48 GB card |
| 2026-09-29 | 25 languages, RTX 6000 Ada | server 26.0 GB (Romanian's voice is on the CPU) |

`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` is set in `run.sh`; the ways to
fit 32 GB (`MADLAD=3b`, `VOXCPM=0`) are in the README.

---

## 7. Running on RunPod

**Why RunPod.** No quota gate, and a prepaid balance, which is also the best
cost guard: a pod can't spend credits you haven't loaded (when the balance runs
out, pods can't start, and running ones may be stopped). You pay only while a
pod runs, plus a small monthly fee for the network volume; prices change, so
check RunPod's current rates. The whole model evaluation took about 14 hours
of one 32 GB GPU.

**Idle stop: three bugs, all of which kept a pod billing** (`scripts/idle-stop.sh`):

1. **`ss` prints a header line** (2026-09-28). `ss … | grep -q .` matched the
   header, so the pod always looked busy. An idle RTX PRO 6000 kept billing an hour
   after its last client; only the 8-hour ceiling would have stopped it. *Now:*
   `ss -H`.
2. **`kill 1` doesn't stop a pod** (September 2026). RunPod restarts an exited
   container on the same GPU and keeps billing: a pod "stopped" every ~15 minutes
   and billed for hours. *Now:* `runpodctl stop pod $RUNPOD_POD_ID` with the pod's
   own scoped key; `kill 1` only if the API call fails or the container is still up 5 minutes later.
3. **`/proc/uptime` is the host's**, not the pod's. The uptime ceiling counts from
   the script's own start time.

The rules now: 15 idle minutes (`STACK_IDLE_MIN`), counted from **ready**
(`/health`), not from boot, so model loading doesn't count; and a hard 8-hour
ceiling (`STACK_MAX_UPTIME_H`) so an open connection can't keep a pod up forever.
`runpod-start.sh` starts the idle stop on every boot (a prebuilt image skips the
provisioner, which used to write it).

**Network volumes.**

- Hugging Face caches to `/root/.cache` on the **container disk**, which dies with
  the pod: 16 GB and ~15 minutes re-downloaded per launch. `HF_HOME=/workspace/hf-cache`
  puts it on the volume.
- A volume can only be attached **when the pod is created**, and only to a pod in
  its own data center. A running pod's cache can't be salvaged. Storage bills with
  or without a pod.
- A venv built *on* the network volume imported so slowly it wasted most of an
  hour; build throwaway environments on local disk. The translator build's
  full-precision downloads (~45 GB) also go to the container disk
  (`MT_SCRATCH`), hence the 80 GB container disk.
- The container disk is wiped on every stop, so the stock image reinstalls Python
  packages each boot (~3 minutes); the Docker image skips that.
- The Lithos launcher keeps a volume in several data centers (each a copy of
  the same files) and tries them in order, because 48 GB stock varies by
  region. A stopped pod can fail to start when its host's GPU was rented out
  meanwhile ("not enough free GPUs"): terminate it and deploy a new one; the volume
  has everything.

**Pod hygiene.**

- **A stale server keeps serving old code.** A second server binds nothing, logs
  "address already in use", and every check looks healthy. `run.sh` refuses to
  start when 8790 is taken. A stale process cost two rounds of diagnosis in the
  first GPU session.
- **Never hand-edit the deployed copy.** The pod's `server.py` carried a local fix
  for the voices path; a redeploy reverted it, and the server printed "ready" and
  ran text-only. Every launch path now passes `--voices-dir /workspace/voices`.
- **The first GPU session** (105 minutes) found one real bug (bf16) and no
  benchmark. Every other failure was environmental: PEP 668, IPv6 localhost, stdout
  buffering, a stale process. None needed a GPU. Hence `tools/dev-cpu.sh`: the
  whole stack on CPU with stand-in models plus the concurrent bench, before
  renting anything. The bench's first "green" was false (it always exited 0 while
  1 of 13 runs produced audio); its exit code is the verdict now.
- **Addresses.** Exposing **HTTP** 8790 gives `https://<pod-id>-8790.proxy.runpod.net`,
  which passes WebSockets and provides TLS. The earlier TCP exposure remapped both
  host and port.
- **`/health`** answers 200 only after warm-up (the port opens after the models
  load), so launchers can tell "booted" from "ready" without a token.
  `runpod-start.sh` reports ready/failed to the Lithos server, signed.
- The Docker image is ~23 GB; building it on every push burned CI minutes, so the
  image workflow is manual only.

---

## 8. Security

The stack has no accounts; the token is the only lock (`server/stack_auth.py`).

- **A pod URL is public.** `runpod-start.sh` and `docker-entrypoint.sh` refuse to
  start without `STACK_TOKEN` or `STACK_SIGNING_KEY` (Docker allows `STACK_OPEN=1`
  for a trusted LAN).
- **Short-lived signed tokens** (2026-09-28): `<payload>.<HMAC-SHA256>`,
  `{sub, exp}`, 2 h for Lithos Talk, 12 h for Live Translation. The stack holds only
  the key, a leaked token dies on its own, and every connection is attributable.
  Lithos's own RunPod volumes carry only the signing key, no static token.
- **Tokens go in `Authorization: Bearer`**, because URLs end up in proxy logs. The
  URL forms (`/<token>/translate`, `?key=`) still work for old clients, with a
  logged warning.
- **Limits:** 30 connections per subject (a room opens one per language), 60 in
  total, 6 h per connection; refusals close with 4401 (auth), 4429 (limits),
  4408 (session time).
- **Billing is a security boundary too:** the 8-hour pod ceiling means a valid
  credential holding a connection open can't keep a pod billing indefinitely.
  The launcher's RunPod key is restricted, and a pod stops itself with its own
  scoped key.
- `/health` needs no token and reveals only "ok".
- **The release audit** (2026-09-30) closed what one valid credential could
  still do to others. *Rooms* are keyed by token subject and room id, so two
  tokens that both say `room=main` get separate rooms; room ids must match
  `[A-Za-z0-9_-]{1,64}` (they reach the log). *Input* is bounded: every query
  parameter is checked before `hello` (close 4400), a WebSocket message is at
  most 256 KB (1009), and audio faster than 2x real time beyond a 60 s backlog
  closes with 4413 (before, a client could post 40 x 4 MB frames, a 58-minute
  "utterance", into one buffer). Solo connections are cut at
  `--max-utterance-s` like rooms. *Tokens* carry an audience (`aud`: `stack`
  for connections, `report` for the pod's ready report, which is signed with
  the same key and could otherwise open a connection), must expire, and live at
  most 24 hours; pre-audience tokens only with `STACK_ACCEPT_LEGACY_TOKENS=1`.
  *The report URL* has no default: a pod reports only where `STACK_REPORT_URL`
  (or `/workspace/.stack-report-url`) says. Details:
  [the reference, "Access, rooms and limits"](../reference.md#access-rooms-and-limits).
- Privacy scope: a marketplace GPU is fine for test clips; for real congregation
  audio it is a third party like any provider.

---

## 9. Protocol and client gotchas

The contract is in [protocol.md](protocol.md). What clients got wrong:

- **Audio arrives faster than real time** (synthesis streams per sentence), so
  pace it before playback. Unpaced, the Live Translation phone listener's 5 s
  queue cap jumped to the live edge and cut "Hola a todos, gracias por venir hoy"
  to "gracias". Three pacer lessons from that app:
  - **Credit elapsed clock time, not timer ticks.** A `setInterval(25)` fired every
    ~28 ms under load; crediting 25 ms drained at 0.89×, ~7 s of lag per minute.
  - **Copy the bytes you hold.** Node's `ws` can hand back a view into a buffer it
    reuses; frames held for seconds were overwritten (words breaking off).
  - **Size the lead for the transport.** A 2.5 s lead suited the WebSocket
    listener but made an iPhone's WebRTC NetEq time-compress playback; the app uses
    400 ms. RTP sent as fast as encoded did the same; 60 ms of pacing slack
    under-buffered over WiFi; 200 ms is the conventional jitter target.
- **Check the WiFi band first.** A phone on 2.4 GHz with the host on 5 GHz lost
  16-39% of packets; WebRTC is UDP, so NetEq concealment sounded exactly like a
  codec or pacing bug. Two pacing "fixes" went in against a packet-loss problem.
  The WebSocket path (TCP) was clean throughout, which already pointed at the
  transport.
- **`transcript` is a delta**: append, don't replace.
- **Audio frames are at most 64 KB** (2026-09-28). One runaway sentence went out as
  a single frame over iOS `URLSessionWebSocketTask`'s 1 MB limit ("Message too
  long") and dropped the session. `send_speech()` splits.
- **Always pass `room=`.** Without it N language sessions each run their own ASR and
  queue MT single-file: the measured 9.45 s median. The Live Translation provider
  pins `room=main&src=auto` in a test.
- **A room's mode is fixed by its first connection.** Toggling simultaneous mode
  against live sessions did nothing until they were reopened; the app now reopens
  them when the setting changes (and applies it on change, not on Save).
- **The primary can leave.** A room processes audio from one connection; when it
  dropped, the room went deaf while the other sessions stayed connected ("stops
  translating after 20-30 seconds"). A survivor is promoted now, and the read loop
  checks `room.primary` rather than a flag captured at join.
- The same symptom had a second, app-side cause: the echo mute's virtual playhead
  advanced for *every* language's audio, not just the one the room speaker plays,
  so with six languages the mic was always muted. The stack's heartbeat
  (`LITHOS_ROOM_HEARTBEAT=1`) showed Silero hearing no speech for 36 s: the engine
  was feeding it silence.
- **Two-way conversations need `route=to`.** With `src=auto`, PA routing (English
  in → target out, anything else → English) made Talk's into-English direction echo
  English and both directions translate the other side. `route=to` translates into
  `lang` and skips speech already in `lang`.
- A server without `--xeng` downgrades `src=auto` to English (logged) rather than
  refusing, so one client shape works against every server.

---

## 10. How problems were found

A few patterns repeated often enough to be rules:

- **Timing harnesses can't hear.** The TTS data race measured *faster*. The fix was
  a corruption metric in the app's WebRTC listener harness (sample step against
  local RMS: healthy voices 4.6-7.6, threshold 12). A localhost harness can't see
  WiFi or NetEq. Coverage needs its own test: `tools/coverage-test.py` diffs what
  the stack heard against a known passage (first run 115/115 words), and
  `tools/cough-test.py` feeds recorded coughs.
- **Loud beats silent.** The silent fallbacks (Omnilingual missing, Coqui
  missing, the voices path wrong) all served degraded output with one line in a
  log nobody read. The loud warning (`spaCy model missing`) was caught on the
  first provisioning run. Hence warnings on every optional install and `STRICT=1`
  in the image build.
- **Log per-stage timings.** The onnxruntime problem took three wrong guesses
  before one log line
  (`lid 0.25s asr 0.32s mt 0.87s tts1 4.71s`) showed it. They stay in the log.
- **A switch that silently does nothing is a bug.** It happened repeatedly on the
  app side (a stream toggle that needed reopening, a setting that didn't persist,
  a provider coerced to Gemini). If a setting can't take effect now, say so.
- **Synthetic tests mislead, in both directions.** Synthetic "Amen." landed just over a length
  threshold that real speech missed; synthetic noise never reproduced the
  room-tone hallucination; the LID synthetic corpus *under*-stated real accuracy.
  Every model-evaluation result is still on synthetic speech: real speakers are the
  next test.
