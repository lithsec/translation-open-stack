#!/usr/bin/env python3
"""
The English→X open-weight translation stack, as one WebSocket server.

    python3 server/server.py --langs es,fr,pt,sw --port 8790

Protocol (deliberately the shape of the app's provider sessions, so a future
LocalProvider is a thin client):

    client connects  ws://host:8790/translate?lang=es
    server sends     {"type":"hello","lang":"es","rate":24000}
    client sends     binary 24 kHz mono PCM16 (the app's canonical format)
    server sends     {"type":"inputTranscript","text":"..."}    per utterance
                     {"type":"transcript","delta":"..."}         translation text
                     binary 24 kHz mono PCM16                    translated speech

Pipeline per utterance (the original design, Lithos Live Translation's local-pipeline notes):

    Silero VAD  ->  faster-whisper (English)  ->  MADLAD-400-3B  ->  Piper

  --streaming     translate WHILE the speaker talks instead of after the
                  pause. LocalAgreement policy: the growing utterance is
                  re-transcribed every second, words that came back identical
                  in two consecutive passes are committed, and committed text
                  is translated and spoken clause by clause. Chosen over
                  attention-based wait-k because it needs no model surgery and
                  degrades to the utterance path on unstable audio. First
                  audio lands mid-sentence; the translation arrives in clause
                  chunks. Compare both modes with the same WAV — that A/B is
                  the whole reason the flag exists next to the default.

  --mms           synthesise ht/km/lo with Meta MMS-TTS instead of returning
                  text-only. CC-BY-NC — Lithos ships none of it; the operator
                  running this instance downloads the weights, which is the
                  operator-supplied pattern (see docs/licences.md). Off
                  by default for exactly that reason.

OPTIONAL EXTRAS, so one g6 session can test every experiment:

  --xeng          also accept NON-English source audio: connect with
                  ?lang=en&src=ru and the pipeline becomes
                  whisper large-v3 (multilingual) -> MADLAD -> English voice.
                  Loads the full large-v3 alongside distil (~3 GB more VRAM):
                  distil-large-v3 is DISTILLED FOR ENGLISH and cannot
                  transcribe other languages, so this cannot share the model.

  --srcs en,ru,ht   with --xeng: the SOURCE languages to expect. Connecting
                  with ?src=auto makes the server identify the spoken language
                  per utterance — the same VoxLingua107 model, and the same
                  constrained-argmax trick, as the app's own LID sidecar
                  (in the app's repository, not this one; 100% on FLEURS constrained) — and
                  route: English in -> translate to ?lang; anything else in ->
                  translate to ENGLISH, which is the app's actual PA behaviour
                  (roomMicOrOtherLang). In production the APP makes this call
                  and passes ?src= explicitly; auto exists so the rig can be
                  tested without the app.

  --omni          with --xeng: transcribe low-resource sources (ht/km/lo/sw)
                  with Meta's Omnilingual ASR instead of whisper large-v3 —
                  whisper simply does not cover Haitian Creole, and it is weak
                  on the other three. Needs `pip install omnilingual-asr`
                  (fairseq2-based, its own heavy dependency tree, which is why
                  it is a flag and not the default).

  --clone ref.wav route es/fr/pt through CosyVoice2 zero-shot cloning of the
                  reference voice instead of Piper. The one capability no
                  provider offers — the translation in the preacher's own
                  timbre. es/fr/pt ride CosyVoice2's CROSS-LINGUAL mode (its
                  strong languages are zh/en/ja/ko), which is exactly where
                  its quality is least proven: that is what the A/B against
                  Piper is for. Falls back to Piper per-utterance on any error.

The models are ENGINES (server/engines/, one file each; docs/dev/architecture.md):
languages.toml says which recogniser, translator and voice serve a language,
and this file only runs the pipeline around them. Adding one:
docs/dev/adding-an-engine.md.

One ASR and one MT serve every connection; each connection only picks its
decode language and its Piper voice. This is why the GPU bill does not scale
with language count, which is the entire economic argument.

HONESTY
-------
This is an utterance-level cascade, not a streaming one: it waits for the VAD
to close an utterance before translating. Expect first-audio 1.5-3 s after the
speaker pauses. A wait-k streaming policy is the known next step and is not
built. Measure this version first — if utterance-level latency is tolerable in
a real room, the streaming work may not be needed.
"""
import argparse, asyncio, copy, json, os, re, time
from concurrent.futures import ThreadPoolExecutor

import stack_config
from engines.base import Context, AudioStream, RATE, VAD_RATE  # noqa: F401
from engines.manager import EngineSet
# The shared helpers moved into engines/common.py with the engines; these names
# stay importable from server.py (tests/test_nonspeech.py uses them).
from engines.common import (  # noqa: F401
    hf_snapshot, is_nonspeech, content_units, split_sentences, NO_SPACE_JOIN,
    NONSPEECH_ANNOTATION, NONSPEECH_PHRASES, SHORT_NOISE_P, SHORT_NOISE_UNITS)
from engines.hymt import HYMT_NAMES  # noqa: F401  (tests/test_stack_config.py)
from engines.madlad import MT_BEAM  # noqa: F401
from engines.piper import TTS_THREADS  # noqa: F401

# Per-language model choices (voice chain, recogniser, translator): the defaults
# in stack_config.py, overridden by languages.toml / $STACK_CONFIG. Nothing below
# names a model for a language directly; see those files to change one. The
# engines themselves (Whisper, MADLAD, Kokoro, ...) are in server/engines/, one
# file each; docs/dev/adding-an-engine.md explains how to add one.
LANG_CONFIG, LANG_CONFIG_SRC = stack_config.load()
_T = stack_config.tables(LANG_CONFIG)
# The models every language shares, with their pinned revisions: languages.toml
# [models] (Silero, language ID, Omnilingual, Kokoro here; Whisper, the
# translators and VoxCPM2 arrive as flags from scripts/run.sh).
MODELS, _ = stack_config.load_models()
# Which device each model loads on: [devices] in languages.toml, the profile
# (STACK_PROFILE), STACK_DEVICES. Unset: everything on the first GPU, as always.
DEVICES = stack_config.load_devices()
# [licence_review]: unclear (❓) items the operator reviewed and admits in
# EDITION=commercial (docs/licences.md §2). The EngineSet enforces the edition.
LICENCE_REVIEW = stack_config.load_reviews()

# Utterance endpoint: silence that ends a turn. The app tunes its own
# equivalents from the operator page; here a flag (--endpoint-ms).
ENDPOINT_MS = 700
# Reading aloud does not pause for 700ms between sentences, so an endpoint
# that only fires on a full stop lets one utterance run the length of a
# paragraph — nothing reaches the listener until the reader finally breathes.
# Past LONG_UTTERANCE_S a much shorter dip is accepted (a clause gap is
# usually enough), and past MAX_UTTERANCE_S the buffer is cut wherever it is.
LONG_UTTERANCE_S = 5.0
LONG_ENDPOINT_MS = 280
MAX_UTTERANCE_S = 9.0
# Forced cuts land after the last sentence end (LITHOS_SENTENCE_CUT=0: quietest point, the old way).
SENTENCE_CUT = os.environ.get("LITHOS_SENTENCE_CUT", "1") != "0"
# Confidence and length a language guess must clear before the microphone is
# relayed untranslated. Routing a translation needs neither.
PASSTHROUGH_MIN_CONF = 0.75
PASSTHROUGH_MIN_S = 2.0
# Simultaneous mode: how often the turn so far is re-transcribed, and how many
# uncommitted words force a clause out even with no punctuation in sight.
STREAM_PASS_MS = 900
# Tunable, because this is what a listener experiences as a PAUSE. With no
# punctuation in sight the turn waits for this many words before speaking.
#
# Was 12, which is ~4.5s of silence at reading pace -- measured as 12 gaps
# over 0.35s, worst 4.58s, in a 47s passage, and reported from a live service
# as "there are pauses now when I read". Lowered to 8 and judged BY EAR in a
# live session on 2026-08-30: "sounds better", with no reported loss of
# Spanish quality. The trade is real -- MADLAD reorders across a clause
# boundary, so a shorter clause carries less context -- which is why this was
# settled by listening rather than by measurement.
STREAM_MAX_WORDS = int(os.environ.get("LITHOS_STREAM_MAX_WORDS", 8))
# Shortest clause worth speaking by itself, unless the turn is over.
STREAM_MIN_WORDS = int(os.environ.get("LITHOS_STREAM_MIN_WORDS", 4))
# Words that must pile up before a mere comma is accepted as a boundary.
STREAM_COMMA_WORDS = int(os.environ.get("LITHOS_STREAM_COMMA_WORDS", 6))
# Buffer trimming (LITHOS_TRIM=1): once a turn's buffer passes this, cut it at
# the end of the SECOND-to-last whisper segment -- the last one is still
# liable to move -- and carry the cut segments forward as fixed text. This is
# what whisper_streaming and HF speech-to-speech both do, and what we did not:
# without it every pass re-decodes the whole turn, so pass time climbs
# (0.15s -> 0.76s across one live turn) and a committed prefix can still be
# rewritten by a later pass (measured in Lithos Live Translation's streaming notes).
STREAM_TRIM = os.environ.get("LITHOS_TRIM") == "1"
STREAM_TRIM_S = float(os.environ.get("LITHOS_TRIM_S", "8"))

# The non-speech filter (what whisper says when it hears a cough, and the
# no_speech_prob gate for one- or two-word fragments) is engines/common.py's
# is_nonspeech() and SHORT_NOISE_*, used by the recognisers.
#
# A language switch is real but rare mid-service, and a short fragment is weak
# evidence for one. Noise -- and plain English -- gets identified CONFIDENTLY
# as the wrong language, so a short utterance that would CHANGE the room's
# language needs more than the standard bar.
#
# The window was 2.5s until a live session put a 2.5s English turn through the
# PORTUGUESE model: the comparison is strictly-less-than, so the one duration
# that mattered fell on the wrong side of it. Widened to 5s -- a real speaker
# changing language keeps talking, so the cost of waiting is small and the
# cost of being wrong is a whole turn transcribed by the wrong model.
SWITCH_MIN_CONF = 0.90
SWITCH_FREE_S = 5.0
# Trailing quiet kept on an utterance, so a final consonant is not clipped.
TRAILING_KEEP_MS = 250

# What one connection may send (docs/dev/protocol.md, "Limits and close codes"). A 100 ms
# frame at 24 kHz PCM16 is 4.8 KB; a bigger WebSocket message is refused by the
# websockets library itself (close 1009). Audio faster than AUDIO_MAX_SPEED x
# real time, beyond AUDIO_BURST_S of it in hand (the backlog a client builds
# while the server is busy with an utterance and not reading), is not a
# microphone: close CLOSE_TOO_FAST. Before these a client could post 40 x 4 MB
# frames, a 58-minute "utterance", into one buffer.
MAX_FRAME_BYTES = 256 * 1024
AUDIO_MAX_SPEED = 2.0
AUDIO_BURST_S = 60.0
# Close codes this server uses besides 4401 (token), 4429 (connection limits)
# and 4408 (session time limit), which guarded() sends.
CLOSE_BAD_REQUEST = 4400   # a query parameter the server does not accept
CLOSE_TOO_FAST = 4413      # audio faster than AUDIO_MAX_SPEED x real time
# ?room= ids: a name, not free text (they reach the log).
ROOM_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
# ?cands=: at most this many conversation languages.
MAX_CANDS = 8


def clean(value, n=64):
    """Anything a client chose, made safe to print: at most n characters, no
    newlines or control characters (which could forge or hide log lines)."""
    return "".join(c if c.isprintable() else "?" for c in str(value)[:n])


class AudioMeter:
    """How fast one connection sends audio: a token bucket that refills at
    AUDIO_MAX_SPEED seconds of audio per second and holds AUDIO_BURST_S."""

    def __init__(self, speed=None, burst_s=None, clock=time.monotonic):
        self.speed = speed or AUDIO_MAX_SPEED
        self.burst = burst_s or AUDIO_BURST_S
        self.clock = clock
        self.credit = self.burst
        self.t = clock()

    def take(self, nbytes):
        """Account for a message of nbytes (PCM16 at RATE); False once over the limit."""
        t = self.clock()
        self.credit = min(self.burst, self.credit + (t - self.t) * self.speed)
        self.t = t
        self.credit -= nbytes / 2 / RATE
        return self.credit >= 0


async def too_fast(ws, who):
    print(f"[stack] {who}: audio faster than {AUDIO_MAX_SPEED:g}x real time, closing", flush=True)
    await ws.close(code=CLOSE_TOO_FAST, reason=f"audio faster than {AUDIO_MAX_SPEED:g}x real time")

# The lookup tables the engines read (derived from languages.toml; kept here
# under their old names for anyone reading or scripting against server.py).
LANG_TO_MADLAD = _T["LANG_TO_MADLAD"]   # MADLAD's target tag, where it differs (tl -> fil)
KOKORO_VOICES = _T["KOKORO_VOICES"]     # lang -> (Kokoro lang_code, voice)
VOXCPM_LANGS = _T["VOXCPM_LANGS"]       # km, lo, tl (tl: no Piper or Kokoro voice exists)
COQUI_VOICES = _T["COQUI_VOICES"]       # ht: multilingual-tts/VITS-OpenBible-Haitian-Creole
PIPER_VOICES = _T["PIPER_VOICES"]
MMS_VOICES = _T["MMS_VOICES"]           # Meta MMS-TTS (CC-BY-NC) for ht/km/lo/tl, with --mms only
MADLAD_ONLY = _T["MADLAD_ONLY"]         # kept on MADLAD even where Hy-MT2 supports them (none by default)


class Pipeline:
    """The models one server shares across every connection: the speech
    detector and language ID here, and the recognisers, translators and voices
    through an EngineSet (server/engines/). Which engine serves a language is
    languages.toml's business; this class only asks."""

    def __init__(self, langs, xeng=False, clone_ref=None, srcs=None, omni=False, mms=False,
                 asr_model="distil-large-v3", mt_model="google/madlad400-3b-mt",
                 mt_ct2=None, kokoro=False, coqui=False, serial_tts=False,
                 asr_multi_model="large-v3", voices_dir=None, hymt=None, voxcpm=None, voxcpm_langs=None,
                 asr_revision=None, edition="nonprofit", voxcpm_max_inflight=None, espeak=False,
                 asr_multi_revision=None):
        # Imported here, first, in the order the server always has: the
        # heavyweight libraries (fairseq2, coqui) rearrange the environment,
        # and import order is part of what was measured.
        import torch
        from faster_whisper import WhisperModel  # noqa: F401
        from transformers import T5ForConditionalGeneration, T5Tokenizer  # noqa: F401

        self.langs = list(langs)   # the target languages a client may ask for (?lang=)
        from engines.common import resolve_device
        devices = {k: resolve_device(v) for k, v in DEVICES.items()}
        self.device = devices.pop("default")
        n_gpu = torch.cuda.device_count() if torch.cuda.is_available() else 0
        for name, dev in [("default", self.device)] + sorted(devices.items()):
            kind, _, idx = dev.partition(":")
            # Loud: a model placed on a card that isn't there would otherwise
            # fail deep inside a library, or land on the CPU unnoticed.
            if kind == "cuda" and int(idx or 0) >= n_gpu:
                raise SystemExit(f"[stack] [devices] {name} = {dev}, but this machine has {n_gpu} GPU(s)")
            if kind == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
                raise SystemExit(f"[stack] [devices] {name} = mps, but PyTorch sees no Apple GPU")
        print(f"[stack] device={self.device}" + "".join(f", {k}={v}" for k, v in sorted(devices.items())))
        vad = MODELS["vad"]
        hub = f"{vad['repo']}:{vad['ref']}" if vad["ref"] else vad["repo"]
        print(f"[stack] loading Silero VAD ({hub})…")
        self.vad, utils = torch.hub.load(hub, "silero_vad", trust_repo=True)
        self.get_speech_ts = utils[0]
        self.srcs = srcs or ["en"]

        # One voice set per edition this server serves (EDITION=both: two, see
        # build_voice_sets). The first set also owns recognition and translation.
        self.edition = edition
        self.editions = stack_config.editions_of(edition)
        # The edition of a connection whose token names none: the stricter one.
        self.default_edition = "commercial" if "commercial" in self.editions else self.editions[0]
        voxcpm_shared = {}

        def ctx_for(ed):
            return Context(
                device=self.device, devices=devices, models=MODELS, table=copy.deepcopy(LANG_CONFIG), tables=_T,
                langs=langs, srcs=self.srcs,
                options=dict(xeng=xeng, clone_ref=clone_ref, omni=omni, mms=mms, asr_model=asr_model,
                             asr_multi_model=asr_multi_model, asr_revision=asr_revision,
                             asr_multi_revision=asr_multi_revision, mt_model=mt_model,
                             mt_ct2=mt_ct2, kokoro=kokoro, coqui=coqui, voices_dir=voices_dir, hymt=hymt,
                             voxcpm=voxcpm, voxcpm_langs=voxcpm_langs, edition=ed,
                             voxcpm_max_inflight=voxcpm_max_inflight, espeak=espeak,
                             licence_review=LICENCE_REVIEW, voxcpm_shared=voxcpm_shared))
        self._ctx_for, self._serial_tts = ctx_for, serial_tts
        self.engines = EngineSet(ctx_for(self.editions[0]), serial_tts=serial_tts)
        self.voice_sets = {self.editions[0]: self.engines}
        # Whisper first (it decides whether other sources work at all), then
        # language ID, then everything else: the order the stack always loaded in.
        self.engines.load(["whisper"])
        self.whisper = self.engines.engines["recognizer"]["whisper"]

        # Spoken-language ID for ?src=auto — the same model, and the same
        # constrained-argmax, as the app's sidecar. Loaded only with --xeng:
        # a fixed-source connection never needs it.
        self.lid = None
        self.lid_keep = []
        if xeng:
            try:
                from speechbrain.inference.classifiers import EncoderClassifier
                lid = MODELS["lid"]
                # On the CPU unless [devices] lid names a device (as before: it is small,
                # and one classification per utterance).
                lid_opts = {"device": devices["lid"]} if "lid" in devices else None
                pin = f" @ {lid['revision']}" if lid["revision"] else ""
                print(f"[stack] loading {lid['repo']}{pin} for src=auto…")
                if lid["revision"]:
                    # Pinned: fetch that snapshot and load it by path. The model's
                    # hyperparams.yaml names the repo again (pretrained_path) for
                    # its checkpoints, so point that at the snapshot too.
                    local = hf_snapshot(lid["repo"], lid["revision"])
                    self.lid = EncoderClassifier.from_hparams(
                        source=local, savedir="/tmp/voxlingua-ecapa", overrides={"pretrained_path": local},
                        run_opts=lid_opts)
                else:
                    self.lid = EncoderClassifier.from_hparams(source=lid["repo"], savedir="/tmp/voxlingua-ecapa",
                                                              run_opts=lid_opts)
                enc = self.lid.hparams.label_encoder
                for lg in self.srcs:
                    for k in enc.lab2ind:
                        if k.split(":")[0].strip().lower() == lg:
                            self.lid_keep.append((lg, enc.lab2ind[k]))
                            break
                print(f"[stack] auto-routing among: {[k for k, _ in self.lid_keep]}")
            except Exception as e:
                # Fatal, not a warning: without language ID every src=auto client (all of
                # Lithos Talk, Live Translation's auto rooms) is silently served as English,
                # which looks like bad translation rather than a broken stack. Refusing to
                # start makes the launcher report "failed" instead of "ready".
                raise SystemExit(f"[stack] language ID failed to load ({e}); fix it or drop --xeng")

        self.engines.load()
        for ed in self.editions[1:]:
            self.voice_sets[ed] = self.build_voice_set(ed)
            self.voice_sets[ed].load()

    def build_voice_set(self, ed):
        """The voice set for a second edition (EDITION=both): recognisers and
        translators from the first set, and every voice engine whose settings
        are the same in both editions' tables (Kokoro, eSpeak NG) shared with
        it; the rest (Piper's per-edition voices, Coqui, MMS, VoxCPM2's language
        list) its own. VoxCPM2 shares its services' slots across both sets."""
        first = self.engines
        mine = stack_config.apply_edition(LANG_CONFIG, ed, first.reviews, first.unclear_ok)[0]
        names = first.shareable_voices(mine)
        print(f"[stack] {ed} voices: sharing {', '.join(sorted(names)) or 'none'} with {first.edition}", flush=True)
        return EngineSet(self._ctx_for(ed), serial_tts=self._serial_tts, share_from=first, share_voices=names)

    def voices(self, edition=None):
        """The EngineSet that speaks for a connection in `edition` (None: the default)."""
        return self.voice_sets[edition or self.default_edition]

    @property
    def asr_multi(self):
        """The multilingual Whisper (None without --xeng): whether this server
        takes sources other than English at all."""
        return self.whisper.asr_multi

    def new_vad(self):
        """A speech detector for ONE audio stream. Silero carries state from call
        to call (its recurrent state and the previous frame's context), so a
        detector shared by several connections mixes their audio: with four
        callers at once, English lost its first words or came out empty
        (2026-09-29). Each connection, and each room, gets its own copy."""
        vad = copy.deepcopy(self.vad)
        vad.reset_states()
        return vad

    def identify(self, pcm16k, only=None):
        """The spoken language of this utterance, constrained to --srcs (and to
        `only`, the client's conversation languages, when it names any of them)."""
        return self.identify_conf(pcm16k, only)[0]

    def identify_conf(self, pcm16k, only=None):
        """As identify(), plus how sure it is — a share of the constrained
        mass, 0..1.

        Callers that only route translation can ignore the score: guessing
        wrong there costs a bad translation. Passthrough cannot ignore it.
        Sending the microphone to a member because it "matches" the detected
        language means a misread puts UNTRANSLATED speech on that member's
        output — and if that member feeds the PA, the room hears the raw
        microphone instead of the translation. That is not a degraded
        translation, it is no translation, so passthrough demands confidence
        while routing does not.
        """
        if not self.lid or not self.lid_keep:
            return None, 0.0
        import math, torch
        with torch.inference_mode():
            pred = self.lid.classify_batch(torch.tensor(pcm16k).unsqueeze(0))
        probs = pred[0].squeeze()
        keep = self.lid_keep
        if only:
            # A two-person conversation: choosing among its own languages instead of all
            # 24 stops a quiet or distant voice being read as Hindi, Vietnamese, Russian...
            narrowed = [(c, i) for c, i in keep if c in only]
            keep = narrowed or keep
        scores = {code: float(probs[idx]) for code, idx in keep}
        # SpeechBrain hands back log-probabilities; older/other heads hand back
        # plain ones. Normalising the wrong space silently flattens every score
        # to 1/N and would disable passthrough for good, so check which it is.
        mx = max(scores.values())
        if mx <= 0.0:
            weights = {c: math.exp(v - mx) for c, v in scores.items()}
        else:
            weights = dict(scores)
        total = sum(weights.values()) or 1.0
        best = max(weights, key=weights.get)
        return best, weights[best] / total

    def sentence_cut(self, pcm16k, src="en"):
        """Where to cut a buffer that hit MAX_UTTERANCE_S with no pause: just after
        the last word that ends a sentence, so the translation gets whole
        sentences and the unfinished one carries into the next utterance. Falls
        back to a clause comma past 4 s. None when there is neither, or when
        the recogniser has no word timings (Omnilingual), and the caller cuts
        at the quietest point."""
        rec = self.engines.recognizer_for(src)
        try:
            words = rec.words(pcm16k, src)
        except Exception as e:
            print(f"[stack] sentence cut: ASR failed ({e})", flush=True)
            return None
        if words is None:
            return None
        total = len(pcm16k) / VAD_RATE
        best = None
        for word, end in words:
            t = word.strip()
            # Leave at least 2 s in the utterance and 0.2 s of speech to carry.
            if not t or end < 2.0 or end > total - 0.2:
                continue
            if t[-1] in ".?!。？！؟":
                best = ("sentence", end)
            elif t[-1] in ",;:，、،" and end >= 4.0 and (best is None or best[0] != "sentence"):
                best = ("clause", end)
        if best is None:
            return None
        # Cut in the gap after the word, not on its last sample.
        return min(len(pcm16k), int((best[1] + 0.08) * VAD_RATE)), best[0]

    def transcribe(self, pcm16k, src="en", want_segments=False):
        """Text heard, by the recogniser languages.toml names for `src`
        (asr = ...; Whisper when it names none, or its engine is not running)."""
        return self.engines.transcribe(pcm16k, src, want_segments=want_segments)

    def translate(self, text, lang, src=None):
        return self.translate_batch(text, [lang], src)[0]

    def translate_batch(self, text, langs, src=None):
        """Every target language at once, one batch per translator (engines/manager.py)."""
        return self.engines.translate_batch(text, langs, src)

    def synthesise_futures(self, text, lang, edition=None):
        """This utterance's audio, one future per sentence, in order (engines/manager.py),
        in the connection's edition."""
        return self.voices(edition).synthesise_futures(text, lang, TTS_POOL)

    def synthesise(self, text, lang, edition=None):
        """24 kHz mono PCM16 bytes, or None when this language is text-only."""
        return self.voices(edition).synthesise(text, lang)


def quietest_cut(buf, window_s=2.0, frame_ms=20):
    """Index of the quietest frame in the last `window_s` of the buffer.

    A forced cut has to land SOMEWHERE, and landing mid-word is audible twice
    over: the ASR gets a fragment ending mid-syllable and invents the rest,
    and the clause it produces is spoken with a falling contour that sounds
    like the speaker gave up. Real speech has micro-gaps between words even
    when it never pauses long enough to endpoint, so cut at the quietest one
    in range instead of at the arbitrary instant the limit expired.
    """
    import numpy as np
    frame = max(1, int(VAD_RATE * frame_ms / 1000))
    start = max(0, len(buf) - int(VAD_RATE * window_s))
    tail = buf[start:]
    n = len(tail) // frame
    if n < 2:
        return len(buf)
    energies = np.abs(tail[: n * frame].reshape(n, frame)).mean(axis=1)
    # Never cut inside the last 300ms: that audio is the live edge and the
    # speaker is still in it.
    keep = max(1, int(0.3 * 1000 / frame_ms))
    if n <= keep:
        return len(buf)
    return start + int(np.argmin(energies[: n - keep])) * frame


def common_prefix_words(a, b):
    """Words that two consecutive ASR passes agree on — the LocalAgreement
    commit rule. Case-folded compare, original-case keep."""
    aw, bw = a.split(), b.split()
    out = []
    for x, y in zip(aw, bw):
        if x.lower().strip(".,;:!?") != y.lower().strip(".,;:!?"):
            break
        out.append(y)
    return out


async def handle_streaming(ws, pipe, src, lang, edition=None):
    """Translate WHILE the speaker talks.

    Every second the whole current utterance is re-transcribed; words identical
    in two consecutive passes are COMMITTED (ASR flicker never reaches the
    room); committed text past the last translation point is translated and
    spoken when a clause completes (punctuation, or 12 words of nothing).
    The re-transcribe grows with the utterance, so cost rises within a turn —
    distil at ~10x realtime keeps that fine for sermon-length turns; the
    utterance reset on silence bounds it.
    """
    import numpy as np
    import torch
    from scipy.signal import resample_poly

    buf = np.zeros(0, dtype=np.float32)
    quiet_ms = 0.0
    speech_seen = False
    last_pass = ""
    committed_n = 0      # words already committed
    translated_n = 0     # words already translated+spoken
    since_asr_ms = 0.0
    vad = pipe.new_vad()
    meter = AudioMeter()
    loop = asyncio.get_running_loop()

    async def flush(words, force=False):
        nonlocal translated_n
        pending = words[translated_n:]
        if not pending:
            return
        clause_end = 0
        for i, w in enumerate(pending):
            if w and w[-1] in ".,;:!?":
                clause_end = i + 1
        if not clause_end and (force or len(pending) >= 12):
            clause_end = len(pending)
        if not clause_end:
            return
        segment = " ".join(pending[:clause_end])
        translated_n += clause_end
        translated = await loop.run_in_executor(None, pipe.translate, segment, lang, src)
        await ws.send(json.dumps({"type": "transcript", "delta": translated + " "}))
        await speak_to(ws, pipe, translated, lang, edition)

    async for msg in ws:
        if not meter.take(len(msg)):
            await too_fast(ws, "streaming client")
            return
        if not isinstance(msg, bytes):
            continue
        pcm = np.frombuffer(msg, "<i2").astype(np.float32) / 32768
        pcm16 = resample_poly(pcm, VAD_RATE, RATE)
        buf = np.concatenate([buf, pcm16])
        chunk_ms = len(pcm16) / VAD_RATE * 1000
        prob = vad_prob(vad, pcm16)
        quiet_ms = 0.0 if prob > 0.5 else quiet_ms + chunk_ms
        since_asr_ms += chunk_ms

        # The turn ends on a pause, or at MAX_UTTERANCE_S whatever the speaker
        # does (the buffer is re-transcribed every pass, so it must stay short).
        forced = len(buf) / VAD_RATE >= MAX_UTTERANCE_S
        if forced or (quiet_ms >= ENDPOINT_MS and len(buf) >= VAD_RATE // 2):
            # Turn over: everything not yet committed is now final.
            cut = quietest_cut(buf) if forced else len(buf)
            text = await loop.run_in_executor(None, pipe.transcribe, buf[:cut], src)
            words = text.split()
            if words:
                await ws.send(json.dumps({"type": "inputTranscript", "text": text}))
                await flush(words, force=True)
            buf = buf[cut:]
            last_pass, committed_n, translated_n, quiet_ms = "", 0, 0, 0.0
            continue

        if since_asr_ms < 1000 or len(buf) < VAD_RATE:
            continue
        since_asr_ms = 0.0
        text = await loop.run_in_executor(None, pipe.transcribe, buf, src)
        agreed = common_prefix_words(last_pass, text)
        last_pass = text
        if len(agreed) > committed_n:
            committed_n = len(agreed)
            await flush(agreed)


class Room:
    """Connections that share ONE audio source — the app's real shape: it
    streams the same microphone to a session per target language. Without
    this, the fanout bench transcribed the identical clip seven times and
    queued seven MT decodes single-file; the last language came back ~15s
    after the first. With it: VAD once, ASR once, ONE batched MT generate,
    TTS in parallel. The first connection in the room drives the audio;
    the rest have their (identical) audio drained and discarded.

    A room belongs to ONE token subject: ROOMS is keyed by (subject, ?room=),
    so two tenants who both say ?room=main get two rooms and never hear, drive
    or displace each other. Within a subject any number of connections may
    listen to the same language; each gets the output, and one leaving takes
    only itself out."""

    def __init__(self, edition=None):
        self.edition = edition     # whose voices the room speaks with (EDITION=both: per room)
        self.members = {}          # ws -> lang, in joining order
        self.primary = None        # the connection whose audio we process
        import numpy as np
        self.buf = np.zeros(0, dtype=np.float32)
        self.quiet_ms = 0.0
        self.vad = None  # the room's own speech detector (pipe.new_vad), made on first audio
        # No utterance until a human has actually spoken. The benches never
        # exposed this: their clips speak immediately. A LIVE microphone idles,
        # and without this gate silence alone satisfied the endpoint — the
        # server transcribed ever-growing silence buffers on a loop, whisper
        # hallucinated subtitle credits into them ("Subtitulado...",
        # "Société Radio-Canada" — its classic silence artifacts), MADLAD
        # translated the credits, and real speech queued behind it all.
        self.speech_seen = False
        # The reader must never block on the pipeline. It used to await the
        # whole of room_utterance inline, so while an utterance was being
        # synthesised the socket was not being drained and VAD saw nothing —
        # every slow utterance pushed the next one further behind.
        self.queue = None
        self.worker = None
        self.heartbeat = None
        # Last language we were CONFIDENT about, for utterances too short to
        # identify on their own.
        self.last_src = None
        # Detected language awaiting proof that the pass was speech, so a
        # cough cannot make itself the room's language.
        self.lid_commit = None
        # Simultaneous mode, decided by whoever opens the room (?stream=1).
        self.stream = False
        self.since_asr_ms = 0.0
        self.last_pass = ""       # previous pass's text, for LocalAgreement
        self.translated_n = 0     # words already translated AND spoken
        # The actual words spoken, for aligning the next pass by TEXT rather
        # than by a count that a re-transcription can invalidate.
        self.spoken_words = []
        # Buffer trimming (LITHOS_TRIM=1). fixed_words is transcription that
        # can no longer change because its audio has left the decode window;
        # trimmed_audio keeps the raw samples for the same-language relay at
        # turn end; turn_gen guards a trim landing after the buffer was reset.
        self.fixed_words = []
        self.trimmed_audio = []
        self.turn_gen = 0
        self.turn_src = None      # language of the turn in progress
        # Connections that said ?priority=1 — the room's PA feed. Their
        # languages are translated in their own decode, ahead of the batch.
        self.priority_ws = set()

    @property
    def priority(self):
        """Languages a ?priority=1 connection is listening to."""
        return {self.members[w] for w in self.priority_ws if w in self.members}

    def pairs(self):
        """(lang, ws) for every connection, several per language possible."""
        return [(lg, w) for w, lg in self.members.items()]

    def groups(self):
        """lang -> [ws]: each language once, with everyone listening to it."""
        out = {}
        for w, lg in self.members.items():
            out.setdefault(lg, []).append(w)
        return out


# (token subject, room id) -> Room. The subject is part of the key on purpose:
# see Room.
ROOMS = {}


class Fanout:
    """Everyone listening to one language as a single send() target, so a
    sentence is translated and synthesised once however many listen. A
    listener that has gone is dropped; with none left, send() raises and the
    caller stops making audio nobody will hear."""

    def __init__(self, targets):
        self.targets = list(targets)

    async def send(self, data):
        for w in list(self.targets):
            try:
                await w.send(data)
            except Exception:
                self.targets.remove(w)
        if not self.targets:
            raise ConnectionError("no listener left")


async def send_json(targets, obj):
    """One JSON message to each connection in targets, ignoring any that have gone."""
    data = json.dumps(obj)
    for w in targets:
        try:
            await w.send(data)
        except Exception:
            pass

# Sentences decode independently; Piper releases the GIL in onnxruntime.
# Sized above the usual language count on purpose: at 4 workers a fifth
# language could not START until another finished, which hid the benefit of
# running the voices concurrently and made that look like a dead end.
TTS_POOL = ThreadPoolExecutor(max_workers=int(os.environ.get("LITHOS_TTS_WORKERS", "8")))


def vad_prob(vad, pcm16):
    """Speech probability of the newest 512 samples (Silero v5 requires exactly
    512 at 16 kHz; a shorter final frame is padded, not passed through, which
    raised and dropped the connection)."""
    import numpy as np
    import torch
    tail = pcm16[-512:]
    if len(tail) < 512:
        tail = np.pad(tail, (512 - len(tail), 0))
    with torch.inference_mode():
        return vad(torch.tensor(tail, dtype=torch.float32), VAD_RATE).item()


async def send_speech(w, audio):
    """Send one sentence's audio: bytes, or an AudioStream chunk by chunk as it
    is generated (the listener hears the start while the rest is being made)."""
    if isinstance(audio, AudioStream):
        # On a thread of its own, NOT TTS_POOL: next() blocks (VoxCPM2 waits up to
        # VOXCPM_WAIT_S for a GPU slot, then for each chunk). In the shared pool the
        # waiters took every worker, the streams holding the slots could not get one
        # to advance, and Piper/Kokoro stalled for every other language: 11 Khmer
        # listeners on one instance, 8 workers -> 15 s stall, 5 of them silent
        # (2026-09-30 audit). One thread per stream: it only ever waits for itself.
        # One worker also orders close() after a next() still running (a listener that
        # hung up mid-wait), so the generator is never closed while it runs, and its
        # finally always releases the slot. Not awaited: a cancelled sender need not
        # wait for a slot it will never use.
        loop = asyncio.get_running_loop()
        own = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stream")
        it = audio.chunks
        try:
            while (chunk := await loop.run_in_executor(own, next, it, None)) is not None:
                await w.send(chunk)
        finally:
            own.submit(it.close)
            own.shutdown(wait=False)
    elif audio:
        # In pieces: a long sentence's audio in one frame can exceed the client's
        # message limit (iOS URLSessionWebSocketTask: 1 MB, "Message too long").
        for i in range(0, len(audio), 1 << 16):
            await w.send(audio[i:i + (1 << 16)])


async def speak_to(ws, pipe, text, lang, edition=None):
    """One listener: each sentence's audio the moment it is ready, in order."""
    for fut in pipe.synthesise_futures(text, lang, edition):
        try:
            audio = await asyncio.wrap_future(fut)
        except Exception as e:
            print(f"[stack] tts failed ({lang}): {e}", flush=True)
            continue
        await send_speech(ws, audio)
# Utterances waiting on the pipeline before we start shedding the oldest.
MAX_PENDING_UTTERANCES = 3


async def room_heartbeat(room, room_id):
    """Say what the room is doing every few seconds.

    A room can stop translating while every connection stays open and no error
    is raised — a wedged worker, a queue that never drains, a buffer that never
    endpoints, or no primary at all. From outside they are indistinguishable:
    captions simply stop. This prints the state that tells them apart.
    """
    import asyncio, time
    last = None
    while True:
        await asyncio.sleep(5)
        try:
            qsize = room.queue.qsize() if room.queue else -1
            state = (
                f"members={len(room.members)} primary={'yes' if room.primary else 'NONE'} "
                f"queue={qsize} buf={len(room.buf) / VAD_RATE:.1f}s "
                f"speech_seen={room.speech_seen} quiet={room.quiet_ms:.0f}ms "
                f"worker={'alive' if room.worker and not room.worker.done() else 'DEAD'}"
            )
            if state != last:
                print(f"[stack] room {room_id}: {state}", flush=True)
                last = state
        except Exception as e:
            print(f"[stack] heartbeat failed: {e}", flush=True)
            return


async def room_worker(pipe, room, src):
    """Process utterances in order, off the read path."""
    while True:
        job = await room.queue.get()
        if job is None:
            return
        try:
            kind, audio = job[0], job[1]
            if kind == "utt":
                await room_utterance(pipe, room, audio, src)
            else:
                await room_pass(pipe, room, audio, src, job[2],
                                job[3] if len(job) > 3 else None)
        except Exception as e:
            print(f"[stack] {job[0]} failed: {e}", flush=True)


async def room_utterance(pipe, room, utterance, src):
    """One utterance through the shared pipeline, fanned out to every member.

    src="auto" is the hybrid: identify THIS utterance's language, transcribe
    with the right engine (distil / whisper / Omnilingual by resource level),
    then translate to every member language as usual. A Spanish speaker's
    utterance therefore reaches the room's English session as English — the
    PA case — while the Spanish session hears Spanish, which is exactly the
    semantics the cloud providers give the app today.
    """
    import asyncio, json, time
    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()
    stage = {}
    # lang -> [ws]: each language is translated and synthesised once, and sent
    # to everyone listening to it.
    groups = room.groups()
    everyone = [w for ws_ in groups.values() for w in ws_]
    this_src = src
    lid_conf = 0.0
    lid_commit = None
    if src == "auto":
        detected, lid_conf = await loop.run_in_executor(None, pipe.identify_conf, utterance)
        switching = bool(room.last_src) and detected != room.last_src
        bar = (SWITCH_MIN_CONF
               if switching and len(utterance) / VAD_RATE < SWITCH_FREE_S
               else PASSTHROUGH_MIN_CONF)
        if detected and lid_conf >= bar:
            this_src = detected
            # Do NOT make it sticky yet. Noise can be identified CONFIDENTLY as
            # the wrong language -- a cough was read as Khmer at >=0.75 -- and
            # committing here poisoned room.last_src, so every following
            # utterance went to Khmer too. That is the "src ja / src km while
            # speaking English" in the service log. It sticks below, once the
            # utterance has proved to be speech.
            lid_commit = detected
        else:
            # Measured: 1.5s of Spanish is read as ENGLISH at ~0.5 confidence,
            # on every clip tried — short fragments do not carry the language.
            # Falling back to "en" made every "sí, gracias" an English
            # transcription; the speaker has not changed language since the
            # last utterance we were sure about, so stay there.
            this_src = room.last_src or detected or "en"
        # Known limit: per-utterance ID jitters on very short utterances (a
        # 2-3s fragment misread as a neighbour language in CPU testing).
        # Full-clip accuracy measured 100% constrained; a stickiness window
        # like the app's SourceLanguageTracker is the fix if it shows up on
        # real speech.
        await send_json(everyone, {"type": "route", "src": this_src})
    stage["lid"] = time.perf_counter() - t0
    text = await loop.run_in_executor(None, pipe.transcribe, utterance, this_src)
    stage["asr"] = time.perf_counter() - t0
    if not text:
        return
    if lid_commit:
        room.last_src = lid_commit      # speech, so the language may stick
    await send_json(everyone, {"type": "inputTranscript", "text": text})
    # A listener whose language is the one being SPOKEN does not want a
    # translation of it — that round trip put the speaker's own sentence
    # through MT and a synthetic voice to arrive back as the same words in a
    # stranger's voice. Send them the microphone instead: their own room, in
    # the real voice, with no model in the path at all.
    # Passthrough only on a language we are SURE of. A misread here does not
    # degrade a translation, it replaces one: the member gets the raw
    # microphone, and if that member feeds a PA the room hears untranslated
    # speech. Reported live — Spanish spoken, raw Spanish out of an English
    # PA, because LID read the utterance as English and "en" then matched.
    # Short fragments are where it jitters, and adaptive endpointing makes
    # more of them, so length is part of the test.
    sure = (src != "auto" or (lid_conf >= PASSTHROUGH_MIN_CONF
                              and len(utterance) / VAD_RATE >= PASSTHROUGH_MIN_S))
    same = [(lg, ws_) for lg, ws_ in groups.items() if lg == this_src] if sure else []
    others = [(lg, ws_) for lg, ws_ in groups.items() if lg != this_src] if sure else list(groups.items())
    if not sure and this_src in groups:
        stage["unsure"] = round(lid_conf, 2)
    if same:
        import numpy as np
        from scipy.signal import resample_poly
        pcm = resample_poly(utterance, RATE, VAD_RATE)
        passthrough = (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()
        for lg, ws_ in same:
            for w in ws_:
                try:
                    await w.send(json.dumps({"type": "transcript", "delta": text}))
                    await w.send(passthrough)
                except Exception:
                    pass
        stage["passthrough"] = time.perf_counter() - t0
    if not others:
        stage["done"] = time.perf_counter() - t0
        print("[stack] utterance %.1fs speech | " % (len(utterance) / VAD_RATE)
              + " ".join(f"{k} {v:.2f}s" for k, v in stage.items()), flush=True)
        return
    members = others      # (lang, [ws]), one entry per language
    async def stream_to(lg, w, tr):
        """Send each sentence the moment it is ready, in order, to everyone
        listening to lg (w: their connections)."""
        out = Fanout(w)
        for i, fut in enumerate(pipe.synthesise_futures(tr, lg, room.edition)):
            try:
                audio = await asyncio.wrap_future(fut)
            except Exception as e:
                print(f"[stack] tts failed ({lg}): {e}", flush=True)
                continue
            if audio:
                if i == 0:
                    stage[f"tts1[{lg}]"] = time.perf_counter() - t0
                try:
                    await send_speech(out, audio)
                except Exception:
                    return

    # One batched decode runs until the LONGEST output finishes, so a language
    # nobody in the room is listening to holds up the one they are. The
    # connection that feeds the PA marks itself (?priority=1); it gets its own
    # small decode first and starts speaking while the rest are still being
    # translated. Costs a little total GPU, buys the only latency the room
    # actually experiences.
    prio = room.priority
    order = sorted(range(len(members)), key=lambda i: members[i][0] not in prio)
    if prio and any(members[i][0] in prio for i in order):
        first = [i for i in order if members[i][0] in prio]
        rest = [i for i in order if members[i][0] not in prio]
        translations = [None] * len(members)
        got = await loop.run_in_executor(
            None, pipe.translate_batch, text, [members[i][0] for i in first], this_src)
        for i, tr in zip(first, got):
            translations[i] = tr
        stage["mt1"] = time.perf_counter() - t0
        for i in first:
            await send_json(members[i][1], {"type": "transcript", "delta": translations[i]})
        speaking = [asyncio.create_task(stream_to(*members[i], translations[i])) for i in first]
        if rest:
            got = await loop.run_in_executor(
                None, pipe.translate_batch, text, [members[i][0] for i in rest], this_src)
            for i, tr in zip(rest, got):
                translations[i] = tr
            for i in rest:
                await send_json(members[i][1], {"type": "transcript", "delta": translations[i]})
        stage["mt"] = time.perf_counter() - t0
        await asyncio.gather(*speaking,
                             *[stream_to(*members[i], translations[i]) for i in rest])
        stage["done"] = time.perf_counter() - t0
        print("[stack] utterance %.1fs speech | " % (len(utterance) / VAD_RATE)
              + " ".join(f"{k} {v:.2f}s" for k, v in stage.items()), flush=True)
        return
    langs = [lg for lg, _ in members]
    translations = await loop.run_in_executor(None, pipe.translate_batch, text, langs, this_src)
    stage["mt"] = time.perf_counter() - t0
    for (lg, w), tr in zip(members, translations):
        await send_json(w, {"type": "transcript", "delta": tr})

    await asyncio.gather(*[
        stream_to(lg, w, tr) for (lg, w), tr in zip(members, translations)
    ])
    stage["done"] = time.perf_counter() - t0
    spoken = len(utterance) / VAD_RATE
    print("[stack] utterance %.1fs speech | " % spoken
          + " ".join(f"{k} {v:.2f}s" for k, v in stage.items()), flush=True)


def trim_point(seg_ends, buf_s, trim_s):
    """Where to cut a long streaming buffer, or None.

    Cut at the end of the second-to-last segment: the most recent boundary is
    still liable to move on the next pass (both reference implementations use
    the same margin -- sents[-2] in whisper_streaming, a 2s sentence_buffer in
    HF speech-to-speech). Requires at least two segments and a buffer over
    trim_s; refuses cuts so early they would churn for no gain.
    """
    if buf_s <= trim_s or len(seg_ends) < 2:
        return None
    cut = seg_ends[-2]
    return cut if cut > 1.0 else None


def resume_point(spoken, words):
    """Where a new transcription continues past what was already SPOKEN.

    room_flush used to slice by index -- words[translated_n:] -- which assumes
    the prefix of the turn never changes. It does. A live read produced, over
    three consecutive passes:

        But behold, my beloved brother, in this kind of world,
        But behold, my beloved brother, and thus came the voice of t
        But behold, my beloved brethren, thus came the voice of the

    and the final pass hands room_flush the WHOLE re-transcription. Slicing
    that by a count derived from an earlier, differently-worded pass lands in
    the wrong place: words already spoken get said again (the reader sees
    lines being added) or a word is skipped.

    So align by text instead. Find where the tail of what was actually spoken
    occurs in the new transcription and continue from there; fall back to the
    old index only when no anchor is found.
    """
    if not spoken:
        return 0
    def key(w):
        return w.strip(".,!?;:\u2014-").lower()
    tail = [key(w) for w in spoken[-3:] if key(w)]
    if tail:
        low = [key(w) for w in words]
        for k in range(len(low) - len(tail), -1, -1):
            if low[k:k + len(tail)] == tail:
                return k + len(tail)
    return min(len(spoken), len(words))


async def room_flush(pipe, room, words, final):
    """Translate and speak the committed words that complete a clause.

    Audio cannot be un-said, so only COMMITTED words get here, and only whole
    clauses: MT reorders across a clause boundary, so half a clause is not
    half a translation, it is a wrong one.
    """
    import asyncio, json
    loop = asyncio.get_running_loop()
    pending = words[resume_point(room.spoken_words, words):]
    if not pending:
        return
    # Prefer a SENTENCE end. MADLAD reorders across a clause boundary, so a
    # comma-sized fragment is translated without the context that decides its
    # word order — measured against utterance mode, that is where "los
    # sustantivos que se usan en el mundo" degraded to "los nombres que el
    # mundo dice". Take a comma only once waiting costs more than the context
    # is worth.
    clause_end = 0
    for i, w in enumerate(pending):
        if w and w[-1] in ".!?":
            clause_end = i + 1
    if not clause_end and len(pending) >= STREAM_COMMA_WORDS:
        for i, w in enumerate(pending):
            if w and w[-1] in ",;:":
                clause_end = i + 1
    if not clause_end and (final or len(pending) >= STREAM_MAX_WORDS):
        clause_end = len(pending)
    # A comma two words in is not a clause worth speaking on its own. Measured
    # on a read-aloud: flushing at every punctuation mark produced fragments
    # like "letra mayúscula," and one utterance that was the single word "a",
    # each its own TTS call with its own silence around it. Wait for the next
    # break unless the turn has ended or the backlog is already long.
    if (clause_end and clause_end < STREAM_MIN_WORDS
            and not final and len(pending) < STREAM_MAX_WORDS):
        return
    if not clause_end:
        return
    segment = " ".join(pending[:clause_end])
    room.spoken_words.extend(pending[:clause_end])
    room.translated_n += clause_end
    # A member whose language is the one being spoken is served the microphone
    # at the turn boundary, not a clause-by-clause re-speak of their own words.
    members = [(lg, ws_) for lg, ws_ in room.groups().items() if lg != room.turn_src]
    if not members:
        return
    langs = [lg for lg, _ in members]
    translations = await loop.run_in_executor(None, pipe.translate_batch, segment, langs, room.turn_src)

    async def speak(lg, w, tr):
        out = Fanout(w)      # everyone listening to lg
        try:
            await out.send(json.dumps({"type": "transcript", "delta": tr + " "}))
        except Exception:
            return
        for fut in pipe.synthesise_futures(tr, lg, room.edition):
            try:
                audio = await asyncio.wrap_future(fut)
            except Exception as e:
                print(f"[stack] tts failed ({lg}): {e}", flush=True)
                continue
            if audio:
                try:
                    await send_speech(out, audio)
                except Exception:
                    return

    await asyncio.gather(*[speak(lg, w, tr) for (lg, w), tr in zip(members, translations)])


async def room_pass(pipe, room, audio, src, final, ctx=None):
    """One pass over the turn so far: re-transcribe, commit, speak.

    Words identical across two consecutive passes are committed — the same
    LocalAgreement-2 rule handle_streaming() uses, so ASR flicker never
    reaches the room. The buffer is not cleared between passes; the turn ends
    on the same endpoint rule utterance mode uses.
    """
    import asyncio, json, time
    loop = asyncio.get_running_loop()
    if len(audio) < VAD_RATE // 2:
        return
    members = room.pairs()     # (lang, ws), one per connection
    if not members:
        return
    t0 = time.perf_counter()

    if room.turn_src is None:
        if src != "auto":
            room.turn_src = src
        else:
            detected, conf = await loop.run_in_executor(None, pipe.identify_conf, audio)
            switching = bool(room.last_src) and detected != room.last_src
            bar = (SWITCH_MIN_CONF
                   if switching and len(audio) / VAD_RATE < SWITCH_FREE_S
                   else PASSTHROUGH_MIN_CONF)
            if (detected and conf >= bar
                    and len(audio) / VAD_RATE >= PASSTHROUGH_MIN_S):
                room.turn_src = detected
                # Deferred for the same reason as the utterance path: a noise
                # burst identified confidently as the wrong language must not
                # become the room's sticky source. Committed after the pass
                # proves to be speech.
                room.lid_commit = detected
            elif final:
                room.turn_src = room.last_src or detected or "en"
            else:
                # Too little audio to name the language, and committing words
                # transcribed by the wrong model is not recoverable once
                # spoken. Wait for the next pass.
                return
        for _, w in members:
            try:
                await w.send(json.dumps({"type": "route", "src": room.turn_src}))
            except Exception:
                pass

    fixed = (ctx or {}).get("fixed") or []
    text, segs = await loop.run_in_executor(
        None, lambda: pipe.transcribe(audio, room.turn_src, want_segments=True))
    # With trimming, `audio` is only the tail of the turn; the fixed words are
    # transcription whose audio has already left the window. Prepending them
    # keeps everything downstream -- LocalAgreement, the clause gate, the
    # spoken-word alignment -- working on the whole turn, unchanged.
    full_text = (" ".join(fixed) + " " + text).strip() if fixed else text
    words = full_text.split()
    if room.lid_commit:
        room.last_src = room.lid_commit
        room.lid_commit = None
    if final:
        committed = words          # the turn is over: everything is final
    else:
        committed = common_prefix_words(room.last_pass, full_text)
        room.last_pass = full_text
    if final and full_text:
        for _, w in members:
            try:
                await w.send(json.dumps({"type": "inputTranscript", "text": full_text}))
            except Exception:
                pass
    spoke = room.translated_n
    await room_flush(pipe, room, committed, final)

    # Trim AFTER speaking, so it never delays a commit. Only on an interim
    # pass, only in the turn the audio came from (gen), and only at the end of
    # the second-to-last segment -- the last is still liable to move.
    if (STREAM_TRIM and not final
            and (ctx or {}).get("gen") == room.turn_gen):
        cut = trim_point([e for _, e in segs], len(audio) / VAD_RATE,
                         STREAM_TRIM_S)
        if cut:
            n = int(cut * VAD_RATE)
            if n <= len(room.buf):
                room.trimmed_audio.append(audio[:n])
                room.buf = room.buf[n:]
                add = " ".join(t for t, _ in segs[:-1]).split()
                room.fixed_words.extend(add)
                print("[stack] trimmed %.1fs (%d words fixed, %.1fs left)" % (
                    cut, len(add), len(room.buf) / VAD_RATE), flush=True)

    if final:
        if room.turn_src and any(lg == room.turn_src for lg, _ in members):
            import numpy as np
            from scipy.signal import resample_poly
            # The relay is the WHOLE turn: trimming removed audio from the
            # decode window, not from what a same-language member is owed.
            raw = ((ctx or {}).get("raw") or []) + [audio]
            pcm = resample_poly(np.concatenate(raw) if len(raw) > 1 else audio,
                                RATE, VAD_RATE)
            relay = (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()
            for lg, w in members:
                if lg != room.turn_src:
                    continue
                try:
                    await w.send(json.dumps({"type": "transcript", "delta": full_text}))
                    await w.send(relay)
                except Exception:
                    pass
        turn_s = (sum(len(a) for a in (ctx or {}).get("raw") or [])
                  + len(audio)) / VAD_RATE
        print("[stack] turn %.1fs speech | %d words | pass %.2fs%s" % (
            turn_s, len(words), time.perf_counter() - t0,
            "" if room.turn_src is None else " | src " + room.turn_src), flush=True)
        room.last_pass = ""
        room.translated_n = 0
        room.spoken_words = []
        room.turn_src = None
    elif room.translated_n > spoke:
        print("[stack] commit %d->%d words at %.1fs buffered (%.2fs)" % (
            spoke, room.translated_n, len(audio) / VAD_RATE,
            time.perf_counter() - t0), flush=True)


async def forced_cut(pipe, buf, src, fallback_src="en", only=None):
    """Where to cut a buffer that reached MAX_UTTERANCE_S with no pause:
    (sample index, "sentence" | "clause" | "quietest"). After the last sentence
    the recogniser heard, so the translation gets whole sentences and the
    unfinished one carries into the next utterance; without one, the quietest
    instant (quietest_cut)."""
    loop = asyncio.get_running_loop()
    # The language of THIS buffer: the previous speaker may have used another
    # one, and a first long reading has no previous at all (it fell back to
    # English and decoded Spanish as English).
    src_now = src
    if src == "auto":
        src_now = (await loop.run_in_executor(None, pipe.identify, buf.copy(), only)
                   or fallback_src or "en")
    found = None
    if SENTENCE_CUT:
        found = await loop.run_in_executor(None, pipe.sentence_cut, buf.copy(), src_now)
    return (found[0], found[1]) if found else (quietest_cut(buf), "quietest")


async def handle_room(ws, pipe, key, lang, src, stream=False, priority=False):
    """One connection in the room `key`: (token subject, ?room= id, edition). The
    edition is part of the key, so a room's voices are always its members' edition."""
    import numpy as np
    import torch
    from scipy.signal import resample_poly

    room_id = f"{clean(key[0], 24)}/{key[1]}"   # for the log; the id itself is validated
    room = ROOMS.get(key)
    if room is None:
        room = ROOMS[key] = Room(key[2] if len(key) > 2 else None)
    room.members[ws] = lang
    if priority:
        room.priority_ws.add(ws)
    meter = AudioMeter()
    is_primary = room.primary is None
    if is_primary:
        room.primary = ws
        room.stream = stream
        room.queue = asyncio.Queue()
        room.worker = asyncio.create_task(room_worker(pipe, room, src))
        if os.environ.get("LITHOS_ROOM_HEARTBEAT") == "1":
            room.heartbeat = asyncio.create_task(room_heartbeat(room, room_id))
    print(f"[stack] room {room_id}: +{lang}"
          f"{' (primary, ' + ('simultaneous' if room.stream else 'utterance') + ')' if is_primary else ''}")

    try:
        async for msg in ws:
            # Every connection is metered, the discarded ones too: their
            # frames still cost a read.
            if not meter.take(len(msg)):
                await too_fast(ws, f"room {room_id}")
                return
            if not isinstance(msg, bytes):
                continue
            # Consult the CURRENT primary, not a flag captured at join: a
            # session promoted after the original primary left must start
            # driving the room immediately.
            if ws is not room.primary:
                continue  # same audio as the primary — drain and discard
            pcm = np.frombuffer(msg, "<i2").astype(np.float32) / 32768
            pcm16 = resample_poly(pcm, VAD_RATE, RATE)
            room.buf = np.concatenate([room.buf, pcm16])
            chunk_ms = len(pcm16) / VAD_RATE * 1000
            if room.vad is None:
                room.vad = pipe.new_vad()
            prob = vad_prob(room.vad, pcm16)
            if prob > 0.5:
                room.speech_seen = True
                room.quiet_ms = 0.0
            else:
                room.quiet_ms += chunk_ms
            if not room.speech_seen:
                # Idle mic: keep only a half-second pre-roll so the eventual
                # first word arrives with its onset, not with minutes of room
                # tone in front of it.
                room.buf = room.buf[-(VAD_RATE // 2):]
                room.turn_gen += 1   # origin moved: no stale trim may land
                continue
            if room.stream and room.speech_seen:
                room.since_asr_ms += chunk_ms
                # Coalesce: never stack passes behind a slow one, or the
                # commits fall further behind the speaker every second.
                if (room.since_asr_ms >= STREAM_PASS_MS
                        and len(room.buf) >= VAD_RATE and room.queue.empty()):
                    room.since_asr_ms = 0.0
                    room.queue.put_nowait(("pass", room.buf.copy(), False,
                                           {"gen": room.turn_gen,
                                            "fixed": list(room.fixed_words)}))
            buf_s = len(room.buf) / VAD_RATE
            # Long buffer -> settle for a clause gap; very long -> cut anyway.
            need_ms = ENDPOINT_MS if buf_s < LONG_UTTERANCE_S else LONG_ENDPOINT_MS
            forced = buf_s >= MAX_UTTERANCE_S
            if not forced and (room.quiet_ms < need_ms or len(room.buf) < VAD_RATE):
                continue
            if forced:
                # No pause for MAX_UTTERANCE_S (a speech, a reading): cut after the
                # last sentence the recogniser heard, carrying the unfinished one
                # into the next utterance, so the translation gets whole
                # sentences. Awaited here on purpose: audio arriving meanwhile
                # waits in the socket, so the carry stays in order. Without a
                # sentence or clause end, the least bad instant as before.
                cut, how = await forced_cut(pipe, room.buf, src, room.last_src)
                print(f"[stack] room {room_id}: forced cut at {cut / VAD_RATE:.1f}s of "
                      f"{len(room.buf) / VAD_RATE:.1f}s ({how})", flush=True)
                utterance, room.buf = room.buf[:cut], room.buf[cut:]
                room.quiet_ms = 0.0
            else:
                # Hand over the SPEECH, not the pause that ended it. Whisper
                # fills silence with polite filler it has seen at the end of
                # captioned video — "gracias por su comentario", "thanks for
                # watching" — and MADLAD dutifully translates the invention.
                # The endpoint already measured the trailing quiet; drop all
                # but a short tail so no word loses its release.
                trail = int(VAD_RATE * max(0.0, room.quiet_ms - TRAILING_KEEP_MS) / 1000)
                utterance = room.buf[:-trail] if 0 < trail < len(room.buf) else room.buf
                room.buf, room.quiet_ms = np.zeros(0, dtype=np.float32), 0.0
            room.speech_seen = forced  # still talking: keep listening, no pre-roll trim
            # The turn is over: snapshot what trimming carried for the final
            # pass, then start the next turn clean. The gen bump also voids
            # any in-flight interim pass's right to trim the new buffer.
            trim_ctx = {"gen": room.turn_gen, "fixed": room.fixed_words,
                        "raw": room.trimmed_audio}
            room.fixed_words, room.trimmed_audio = [], []
            room.turn_gen += 1
            if room.stream:
                room.queue.put_nowait(("pass", utterance, True, trim_ctx))
                room.since_asr_ms = 0.0
                continue
            if room.queue.qsize() >= MAX_PENDING_UTTERANCES:
                # Never silently: a drop here is the pipeline losing to a
                # talker, and the operator needs to see it in the log.
                dropped = await room.queue.get()
                print(f"[stack] room {room_id}: pipeline behind, dropped "
                      f"{len(dropped[1]) / VAD_RATE:.1f}s utterance", flush=True)
            room.queue.put_nowait(("utt", utterance))
    finally:
        # Only this connection leaves: another listener of the same language stays.
        room.members.pop(ws, None)
        room.priority_ws.discard(ws)
        if room.primary is ws:
            # PROMOTE a survivor. The primary is the only connection whose audio
            # is processed; when it dropped this used to set primary=None and
            # wait for a NEW joiner. The other sessions stayed connected and kept
            # streaming, every frame was discarded, and the room went deaf
            # permanently — reported as "after 20-30 seconds it stops
            # translating, no text no audio, everything else sounds fine".
            #
            # A room outlives any one connection: the app opens a session per
            # language and any of them can blip.
            survivor = next(iter(room.members), None)
            room.primary = survivor
            if survivor is None:
                if room.worker:
                    room.worker.cancel()
                    room.worker = None
                if room.heartbeat:
                    room.heartbeat.cancel()
                    room.heartbeat = None
            else:
                print(f"[stack] room {room_id}: primary left, promoted a survivor", flush=True)
                # That buffer belonged to the old connection's audio; a new
                # speaker's first words must not be glued onto its tail.
                room.buf = np.zeros(0, dtype=np.float32)
                room.fixed_words, room.trimmed_audio = [], []
                room.turn_gen += 1
                room.quiet_ms = 0.0
                room.speech_seen = False
        if not room.members and ROOMS.get(key) is room:
            ROOMS.pop(key, None)


class BadRequest(ValueError):
    """A query parameter this server does not accept; the message is for the client."""


def _code(value):
    """A language code as the engines name it: "pt-BR" -> "pt"."""
    return value.strip().replace("_", "-").split("-")[0].lower()


def parse_request(q, pipe):
    """The connection's parameters, validated against what this server serves.

    An unknown language used to go straight to the engines (each unknown ?lang
    one more translation and voice per utterance, or an exception deep in the
    pipeline), and every value reached the log verbatim. Now anything
    unexpected is refused up front with a BadRequest naming the parameter."""
    def arg(name, default=""):
        return q.get(name, [default])[0]

    served = list(getattr(pipe, "langs", None) or [])
    srcs = list(getattr(pipe, "srcs", None) or ["en"])
    known = set(served) | set(srcs) | {"en"}

    lang = arg("lang", "es")
    if served and lang not in served:
        if _code(lang) not in served:
            raise BadRequest(f"lang {clean(lang, 24)!r} is not served here; this server translates into: "
                             + ", ".join(served))
        lang = _code(lang)

    src = arg("src", "en")
    if src not in ("auto", "en") and src not in srcs:
        if _code(src) not in srcs and _code(src) != "en":
            raise BadRequest(f"src {clean(src, 24)!r} is not a source this server takes; use auto or one of: "
                             + ", ".join(["en"] + [c for c in srcs if c != "en"]))
        src = _code(src)

    route = arg("route")
    if route not in ("", "to"):
        raise BadRequest(f"route {clean(route, 24)!r} is not understood; the only value is 'to'")

    cands = None
    raw = [c for c in arg("cands").split(",") if c.strip()]
    if raw:
        if len(raw) > MAX_CANDS:
            raise BadRequest(f"cands names {len(raw)} languages; at most {MAX_CANDS}")
        cands = {_code(c) for c in raw}
        unknown = sorted(c for c in cands if c not in known)
        if unknown:
            raise BadRequest("cands has languages this server does not know: "
                             + ", ".join(clean(c, 12) for c in unknown[:MAX_CANDS]))

    room = arg("room") or None
    if room is not None and not ROOM_ID_RE.fullmatch(room):
        raise BadRequest("room must be 1-64 letters, digits, '-' or '_'")

    flag = lambda name: arg(name, "0") not in ("0", "", "false")  # noqa: E731
    return {"lang": lang, "src": src, "route_to": route == "to", "cands": cands, "room": room,
            "stream": flag("stream"), "priority": flag("priority")}


async def handle(ws, pipe, sub="open", edition=None):
    """One connection, from the subject guarded() admitted, served in `edition`
    (connection_edition: whose voices it hears)."""
    import numpy as np
    import torch
    from scipy.signal import resample_poly
    from urllib.parse import urlparse, parse_qs

    url = urlparse(ws.request.path)
    q = parse_qs(url.query)
    # Who may connect, and how many at once: guarded() (stack_auth.py).
    try:
        req = parse_request(q, pipe)
    except BadRequest as e:
        print(f"[stack] {clean(sub, 24)}: refused request: {clean(e, 200)}", flush=True)
        await ws.send(json.dumps({"type": "error", "detail": str(e)}))
        await ws.close(code=CLOSE_BAD_REQUEST, reason="bad request")
        return
    lang, src = req["lang"], req["src"]
    # The app always asks for src=auto (the hybrid: whoever speaks, route
    # them). A sermon-only deployment without --xeng cannot honour that —
    # DOWNGRADE to English rather than refuse, so one client works against
    # every server shape and the hello says what it actually got.
    if src == "auto" and (not pipe.lid or pipe.asr_multi is None):
        print("[stack] src=auto requested but LID/--xeng not loaded — serving src=en")
        src = "en"
    elif src != "en" and pipe.asr_multi is None:
        await ws.send(json.dumps({"type": "error", "detail": "server not started with --xeng"}))
        await ws.close()
        return
    await ws.send(json.dumps({"type": "hello", "lang": lang, "src": src, "rate": RATE,
                              "mode": "streaming" if getattr(pipe, "streaming", False) else "utterance",
                              "edition": edition or pipe.default_edition}))
    print(f"[stack] client: {src} -> {lang}")

    if req["room"]:
        # Shared-pipeline mode (see Room). src is fixed per room. The room is
        # this subject's: another token's ?room=main is a different room.
        await handle_room(ws, pipe, (sub, req["room"], edition), lang, src, req["stream"], req["priority"])
        return

    if getattr(pipe, "streaming", False):
        # Streaming needs a fixed source: LocalAgreement commits words from a
        # single ASR stream, and swapping models mid-utterance would reset the
        # agreement every pass. auto stays an utterance-mode feature.
        if src == "auto":
            await ws.send(json.dumps({"type": "error", "detail": "--streaming needs a fixed ?src"}))
            await ws.close()
            return
        await handle_streaming(ws, pipe, src, lang, edition)
        return

    # route=to (Lithos Talk): translate whatever is spoken INTO `lang`, and skip
    # speech already in `lang`. A two-way conversation runs one connection per
    # direction on the same microphone, so each must ignore its own language
    # rather than send it on to English (the PA routing below).
    route_to = req["route_to"]
    # ?cands=en,es: the only languages this conversation uses (Lithos Talk). Auto
    # detection chooses among these instead of every --srcs language.
    cands = req["cands"]
    buf = np.zeros(0, dtype=np.float32)
    quiet_ms = 0.0
    speech_seen = False
    vad = pipe.new_vad()
    meter = AudioMeter()

    async for msg in ws:
        if not meter.take(len(msg)):
            await too_fast(ws, clean(sub, 24))
            return
        if not isinstance(msg, bytes):
            continue
        pcm = np.frombuffer(msg, "<i2").astype(np.float32) / 32768
        pcm16 = resample_poly(pcm, VAD_RATE, RATE)
        buf = np.concatenate([buf, pcm16])
        # Endpoint on Silero: an utterance ends after 700 ms without speech.
        chunk_ms = len(pcm16) / VAD_RATE * 1000
        prob = vad_prob(vad, pcm16)
        if prob > 0.5:
            speech_seen = True
            quiet_ms = 0.0
        else:
            quiet_ms += chunk_ms
        if not speech_seen:
            buf = buf[-(VAD_RATE // 2):]  # idle mic: pre-roll only (see Room)
            continue
        # No pause for MAX_UTTERANCE_S: cut anyway, as rooms do. Without this
        # a client that never paused grew one buffer without limit.
        buf_s = len(buf) / VAD_RATE
        forced = buf_s >= MAX_UTTERANCE_S
        if not forced and (quiet_ms < ENDPOINT_MS or len(buf) < VAD_RATE):  # not ended, or under 1 s of audio
            continue

        if forced:
            cut, how = await forced_cut(pipe, buf, src, "en", cands)
            print(f"[stack] solo: forced cut at {cut / VAD_RATE:.1f}s of {buf_s:.1f}s ({how})", flush=True)
            utterance, buf, quiet_ms = buf[:cut], buf[cut:], 0.0   # still talking: speech_seen stays
        else:
            utterance, buf, quiet_ms = buf, np.zeros(0, dtype=np.float32), 0.0
            speech_seen = False
        loop = asyncio.get_running_loop()

        # Auto-route per utterance: English in -> the requested language out;
        # anything else in -> ENGLISH out. That is the app's PA behaviour
        # (roomMicOrOtherLang) expressed as routing.
        this_src, this_lang = src, lang
        if src == "auto":
            detected = await loop.run_in_executor(None, pipe.identify, utterance, cands)
            this_src = detected or "en"
            if route_to:
                await ws.send(json.dumps({"type": "route", "src": this_src, "lang": lang}))
                if this_src == lang:
                    continue  # already in this direction's language: the other direction's job
            else:
                this_lang = lang if this_src == "en" else "en"
                await ws.send(json.dumps({"type": "route", "src": this_src, "lang": this_lang}))

        text = await loop.run_in_executor(None, pipe.transcribe, utterance, this_src)
        if not text:
            continue
        await ws.send(json.dumps({"type": "inputTranscript", "text": text}))
        translated = await loop.run_in_executor(None, pipe.translate, text, this_lang, this_src)
        await ws.send(json.dumps({"type": "transcript", "delta": translated}))
        print(f"[stack] solo {this_src}->{this_lang}: {len(text)} chars heard, {len(translated)} out", flush=True)
        await speak_to(ws, pipe, translated, this_lang, edition)


LIMITS = None  # stack_auth.Limits, made in main()


# A token for an edition this stack doesn't serve (a commercial client on a
# non-profit-only stack): refused rather than served with voices it may not use.
CLOSE_EDITION = 4403


def connection_edition(served, claim):
    """The edition a connection is served in, or None to refuse it.

    served: the server's editions (["nonprofit"], ["commercial"] or both).
    claim: the token's "ed" (None for the static token, an open stack, or an
    issuer that doesn't say). No claim: the strictest edition served. A
    non-profit client on a commercial-only stack gets commercial voices (only
    stricter); a commercial client is never served by a non-profit-only stack."""
    if claim is None:
        return "commercial" if "commercial" in served else served[0]
    if claim in served:
        return claim
    return "commercial" if claim == "nonprofit" and "commercial" in served else None


async def guarded(ws, pipe):
    """One client's failure must never reach the serve loop.

    Found the hard way on a metered GPU: a bench client cancelling its receive
    task produced a keepalive-ping timeout that propagated out of the handler
    and killed the whole server — it had logged "ready", then refused every
    later connection with ECONNREFUSED, which reads exactly like a port
    problem and is not one.
    """
    from urllib.parse import urlparse, parse_qs
    import stack_auth
    url = urlparse(ws.request.path)
    sub, via, claim = stack_auth.credentials_for(ws.request.headers, url.path, parse_qs(url.query))
    if sub is None:
        print(f"[stack] refused: bad or missing token (via {clean(via, 12)})", flush=True)
        await ws.close(code=4401, reason="unauthorized")
        return
    who = clean(sub, 24)    # the subject comes from the token: printable, bounded
    edition = connection_edition(pipe.editions, claim)
    if edition is None:
        print(f"[stack] refused {who}: its token is for the {claim} edition; this stack serves "
              f"{'/'.join(pipe.editions)}", flush=True)
        await ws.close(code=CLOSE_EDITION, reason=f"this stack does not serve the {claim} edition")
        return
    why = LIMITS.admit(sub)
    if why:
        print(f"[stack] refused {who}: {why}", flush=True)
        await ws.close(code=4429, reason=why)
        return
    if via in ("path", "query"):
        print(f"[stack] {who} sent its token in the URL — clients should use the Authorization header", flush=True)
    try:
        await asyncio.wait_for(handle(ws, pipe, sub, edition), LIMITS.session_s)
    except asyncio.TimeoutError:
        print(f"[stack] {who}: session time limit reached", flush=True)
        await ws.close(code=4408, reason="session time limit")
    except Exception as e:
        print(f"[stack] client ended: {type(e).__name__}: {clean(e, 200)}")
    finally:
        LIMITS.release(sub)


def warmup(pipe, langs):
    """First calls compile CUDA kernels and build caches — measured as
    seconds of the FIRST utterance's latency (Spanish paid ~3s of it in the
    first bench). Pay it at boot instead, before "ready" is printed, so no
    listener ever does.

    The voices warm in parallel, one thread per voice ENGINE (the first in each
    language's chain), each going through its own languages in turn: every
    language is still warmed, but no engine is ever called by two warm-up
    threads at once (VoxCPM2 takes one sentence at a time, and a second would
    overflow to eSpeak). Sequentially this took ~34 s on a GPU with 25 languages.
    STACK_WARM_LANGS=en,es limits it to those languages (the rest then pay their
    first-call cost, a few seconds, on their first sentence)."""
    import numpy as np, time
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.time()
    only = [l.strip() for l in os.environ.get("STACK_WARM_LANGS", "").split(",") if l.strip()]
    langs = [l for l in langs if l in only] if only else list(langs)
    silence = np.zeros(VAD_RATE, dtype=np.float32)
    pipe.transcribe(silence, "en")
    if pipe.asr_multi is not None:
        pipe.transcribe(silence, "es")
    texts = pipe.translate_batch("Hello, welcome to the service.", langs) if langs else []
    # Grouped by the engine object, so a voice shared by both editions' sets
    # (EDITION=both) is one group, and each of its languages is warmed once.
    by_engine, seen = {}, set()
    for ed, vs in pipe.voice_sets.items():
        for lg, tr in zip(langs, texts):
            chain = vs.chain(lg)
            key = id(chain[0]) if chain else None
            if (key, lg) not in seen:
                seen.add((key, lg))
                by_engine.setdefault(key, []).append((lg, tr, ed))

    def warm(items):
        for lg, tr, ed in items:
            pipe.synthesise(tr, lg, ed)

    with ThreadPoolExecutor(max(1, len(by_engine)), thread_name_prefix="warm") as pool:
        for f in [pool.submit(warm, pairs) for pairs in by_engine.values()]:
            f.result()
    print(f"[stack] warm in {time.time() - t0:.1f}s ({len(langs)} languages, "
          f"{len(by_engine)} voice engines in parallel) — first utterance pays nothing")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", default="es,fr,pt")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--xeng", action="store_true",
                    help="also load multilingual whisper so ?src=<lang> works (X -> English)")
    ap.add_argument("--clone", metavar="REF_WAV", default=None,
                    help="CosyVoice2 zero-shot: en/es/fr/pt spoken in this reference voice")
    ap.add_argument("--srcs", default="en,ru,es",
                    help="with --xeng: source languages to expect / auto-route among")
    ap.add_argument("--asr-model", default="distil-large-v3",
                    help="faster-whisper model id; 'tiny' for a CPU plumbing smoke")
    ap.add_argument("--asr-revision", default="",
                    help="pin --asr-model to this revision of its repo (scripts/run.sh passes "
                         "languages.toml [models.whisper] revision); shared with --asr-multi-model "
                         "when both name the same model")
    ap.add_argument("--asr-multi-revision", default="",
                    help="pin --asr-multi-model to this revision when it differs from --asr-model "
                         "(languages.toml [models.whisper] multi_revision)")
    ap.add_argument("--asr-multi-model", default="large-v3",
                    help="multilingual whisper for --xeng; 'tiny' (which IS multilingual, "
                         "unlike distil) for a CPU plumbing smoke")
    ap.add_argument("--mt-model", default="google/madlad400-3b-mt",
                    help="T5-family MT model. Anything but MADLAD is a PLUMBING smoke: "
                         "other T5s ignore the <2xx> language tags and emit junk on purpose")
    ap.add_argument("--voices-dir", default=None, help="Piper voices dir (default: <script>/voices)")
    ap.add_argument("--serial-tts", action="store_true",
                    help="run GPU voices one at a time. Costs ~0.06s to the last "
                         "of five languages; use on a card that cannot hold "
                         "several voices' activations at once")
    ap.add_argument("--coqui", action="store_true",
                    help="use Coqui VITS checkpoints where mapped (Haitian Creole); "
                         "CC-BY-SA, and the way off MMS for that language")
    ap.add_argument("--kokoro", action="store_true",
                    help="use Kokoro (GPU, 24kHz native) for en/es/fr/it/pt; "
                         "Piper still serves everything else")
    ap.add_argument("--mt-ct2", default=None,
                    help="directory of a CTranslate2-converted MT model; replaces "
                         "the HF decode path (see README for the convert command)")
    ap.add_argument("--voxcpm", default=None,
                    help="URL(s) of voxcpm_service.py, comma-separated (e.g. http://127.0.0.1:8791,"
                         "http://127.0.0.1:8792; scripts/run.sh starts one per GPU it may use): VoxCPM2 voices "
                         "for --voxcpm-langs, each sentence to the least-loaded instance; when all are busy or "
                         "down, the next voice in the chain speaks it")
    ap.add_argument("--voxcpm-max-inflight", type=int,
                    default=int(os.environ.get("VOXCPM_MAX_INFLIGHT") or 1),
                    help="sentences one VoxCPM2 instance takes at once before overflow goes to the next voice "
                         "(default: $VOXCPM_MAX_INFLIGHT or 1: a service makes one voice at a time)")
    ap.add_argument("--espeak", action="store_true",
                    help="eSpeak NG (the espeak-ng program, GPL-3.0, run as a separate process) as the last "
                         "voice of every language it speaks: VoxCPM2's overflow, and fa/ro in commercial")
    ap.add_argument("--voxcpm-langs", default="",
                    help="languages VoxCPM2 speaks (it sustains ~2 real-time voices per GPU); default: the "
                         "`voxcpm = true` languages of the edition (languages.toml)")
    ap.add_argument("--edition", default=os.environ.get("EDITION") or "nonprofit",
                    choices=stack_config.EDITIONS,
                    help="nonprofit: every configured voice; commercial: only voices and models licensed for "
                         "commercial use (server/licences.py, docs/licences.md); both: each connection in the "
                         "edition its token names (claim \"ed\"), commercial when it names none. "
                         "Default: $EDITION or nonprofit")
    ap.add_argument("--hymt", default=None,
                    help="directory of the 4-bit Hy-MT2 7B built by prepare-mt.sh; translates into "
                         "the 36 languages it supports, MADLAD the rest")
    ap.add_argument("--long-utterance-s", type=float, default=5.0,
                    help="past this much buffered speech, accept a clause-length "
                         "gap as an endpoint instead of a full pause")
    ap.add_argument("--max-utterance-s", type=float, default=9.0,
                    help="cut an utterance here even if the speaker never pauses")
    ap.add_argument("--endpoint-ms", type=int, default=700,
                    help="silence that ends an utterance (lower = faster, riskier mid-sentence)")
    ap.add_argument("--streaming", action="store_true",
                    help="LocalAgreement streaming: translate while they talk, clause by clause")
    ap.add_argument("--mms", action="store_true",
                    help="synthesise ht/km/lo with MMS-TTS (CC-BY-NC, downloaded by YOU, not shipped)")
    ap.add_argument("--omni", action="store_true",
                    help="with --xeng: Omnilingual ASR for ht/km/lo/sw sources (pip install omnilingual-asr)")
    args = ap.parse_args()
    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    # X->eng needs an English voice on the way out.
    if args.xeng and "en" not in langs:
        langs.append("en")

    srcs = [l.strip() for l in args.srcs.split(",") if l.strip()]
    print(f"[stack] language config: {LANG_CONFIG_SRC}")
    print(f"[stack] edition: {args.edition}", flush=True)
    if args.edition in ("commercial", "both"):
        # The shared models (and the Whisper flags, which can differ from
        # [models.whisper]) must be commercially licensed, or nothing starts.
        models = copy.deepcopy(MODELS)
        models["whisper"]["model"] = args.asr_model
        if args.xeng and args.asr_multi_model != args.asr_model:
            models["whisper_multi"] = {"model": args.asr_multi_model, "revision": args.asr_multi_revision}
        if not args.hymt:
            models.pop("hymt", None)
        bad = stack_config.commercial_problems(models, LICENCE_REVIEW)
        if bad:
            raise SystemExit("[licence] EDITION=commercial refuses to start:\n  " + "\n  ".join(bad))
    pipe = Pipeline(langs, xeng=args.xeng, clone_ref=args.clone, srcs=srcs, omni=args.omni, mms=args.mms,
                    asr_model=args.asr_model, mt_model=args.mt_model,
                    mt_ct2=args.mt_ct2, kokoro=args.kokoro, coqui=args.coqui, serial_tts=args.serial_tts,
                    asr_multi_model=args.asr_multi_model, asr_multi_revision=args.asr_multi_revision or None,
                    voices_dir=args.voices_dir, hymt=args.hymt,
                    voxcpm=args.voxcpm, voxcpm_langs=[l for l in args.voxcpm_langs.split(",") if l],
                    asr_revision=args.asr_revision, edition=args.edition,
                    voxcpm_max_inflight=args.voxcpm_max_inflight, espeak=args.espeak)
    pipe.streaming = args.streaming
    global ENDPOINT_MS, LONG_UTTERANCE_S, MAX_UTTERANCE_S
    ENDPOINT_MS = args.endpoint_ms
    LONG_UTTERANCE_S = args.long_utterance_s
    MAX_UTTERANCE_S = args.max_utterance_s

    warmup(pipe, langs)
    global LIMITS
    import stack_auth
    LIMITS = stack_auth.Limits()
    print(f"[stack] access: {'signed tokens' if os.environ.get('STACK_SIGNING_KEY') else ''}"
          f"{' + ' if os.environ.get('STACK_SIGNING_KEY') and os.environ.get('STACK_TOKEN') else ''}"
          f"{'static token' if os.environ.get('STACK_TOKEN') else ''}{'OPEN (LAN only)' if not stack_auth.auth_required() else ''}"
          f"; limits {LIMITS.per_client}/client, {LIMITS.total} total, {LIMITS.session_s // 60} min/session", flush=True)

    import websockets
    from http import HTTPStatus

    def health(connection, request):
        # Plain GET /health answers 200 once models are loaded (the port only
        # opens after warm-up), so a launcher can tell "pod up" from "ready"
        # without a token or a WebSocket. It reveals nothing else.
        if request.path == "/health":
            return connection.respond(HTTPStatus.OK, "ok\n")
        return None

    async with websockets.serve(lambda ws: guarded(ws, pipe), "0.0.0.0", args.port,
                                max_size=MAX_FRAME_BYTES, ping_interval=None, process_request=health):
        print(f"[stack] ready on :{args.port} for {langs}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
