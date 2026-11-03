"""
The models every connection shares, and the turn rules they are driven by.

    Pipeline     Silero VAD, VoxLingua107 language ID, and the EngineSet(s) that
                 recognise, translate and speak (server/engines/), per edition.
    endpointing  when a pause ends a turn (--endpoint-ms and the rest, or the
                 language's own rules in languages.toml), and the other tunables
                 the solo and room handlers read (STREAM_*, PASSTHROUGH_*, ...).
    forced_cut   where to cut a buffer that never paused (quietest_cut and
                 Pipeline.sentence_cut).

Part of the server (server/server.py is the entry point). main() sets
ENDPOINT_MS, LONG_UTTERANCE_S and MAX_UTTERANCE_S here, on this module, from
its flags: read them as pipeline.X, never copy them with `from pipeline import`.
"""
import asyncio, copy, os
from concurrent.futures import ThreadPoolExecutor

import stack_config
from engines.base import Context, VAD_RATE
from engines.manager import EngineSet
from engines.common import hf_snapshot

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


def endpointing(src):
    """(endpoint_ms, long_utterance_s, long_endpoint_ms, max_utterance_s) for
    speech in `src`. The flags above, unless languages.toml gives the language
    its own turn rules (stack_config.TURN_KEYS). endpoint_ms / max_utterance_s
    alone: that pause always ends a turn (no shorter clause gap on long ones)
    and that length forces a cut. Lao and Khmer wait 700 ms and up to 15 s:
    Omnilingual mishears short pieces of them far more than whole sentences
    (eval/2026-10-omni-sizes). long_utterance_s / long_endpoint_ms keep the
    clause gap, at the language's own length and pause (eval/2026-10-pauses).
    src=auto is not known until a turn is over, so it keeps the flags."""
    t = _T.get("ENDPOINTING", {}).get(src) or {}
    ep = t.get("endpoint_ms", ENDPOINT_MS)
    max_s = t.get("max_utterance_s", MAX_UTTERANCE_S)
    if "long_utterance_s" in t or "long_endpoint_ms" in t:
        return ep, t.get("long_utterance_s", LONG_UTTERANCE_S), t.get("long_endpoint_ms", LONG_ENDPOINT_MS), max_s
    if "endpoint_ms" in t or "max_utterance_s" in t:
        return ep, max_s, ep, max_s
    return ENDPOINT_MS, LONG_UTTERANCE_S, LONG_ENDPOINT_MS, MAX_UTTERANCE_S


# A pause doesn't end a turn holding less than the language's min_speech_ms of
# speech (languages.toml; 0 = any) until the quiet has lasted this long: the
# piece waits for the rest of its sentence, but a speaker who said only that
# much and stopped is still answered.
SHORT_TURN_HOLD_MS = 1500


def min_speech_ms(src):
    return (_T.get("ENDPOINTING", {}).get(src) or {}).get("min_speech_ms", 0)


def short_turn(buf_s, quiet_ms, need_ms, min_ms):
    """True when a pause that would end the turn should wait: the buffer
    (buf_s seconds, the last quiet_ms of them quiet) holds under min_ms of
    speech and the quiet hasn't reached max(need_ms, SHORT_TURN_HOLD_MS)."""
    return buf_s * 1000 - quiet_ms < min_ms and quiet_ms < max(need_ms, SHORT_TURN_HOLD_MS)


# Forced cuts land after the last sentence end (LITHOS_SENTENCE_CUT=0: quietest point, the old way).
SENTENCE_CUT = os.environ.get("LITHOS_SENTENCE_CUT", "1") != "0"
# Confidence and length a language guess must clear before the microphone is
# relayed untranslated. Routing a translation needs neither.
PASSTHROUGH_MIN_CONF = 0.75
PASSTHROUGH_MIN_S = 2.0
# Simultaneous mode: how often the turn so far is re-transcribed, and how many
# uncommitted words force a clause out even with no punctuation in sight.
STREAM_PASS_MS = 900
# With no punctuation in sight the turn waits for this many words before
# speaking: what a listener hears as a PAUSE. 12 left ~4.5 s gaps at reading
# pace; 8 was judged better by ear in a live session (2026-08-30). Shorter
# clauses give the translator less context, hence a tunable.
STREAM_MAX_WORDS = int(os.environ.get("LITHOS_STREAM_MAX_WORDS", 8))
# Shortest clause worth speaking by itself, unless the turn is over.
STREAM_MIN_WORDS = int(os.environ.get("LITHOS_STREAM_MIN_WORDS", 4))
# Words that must pile up before a mere comma is accepted as a boundary.
STREAM_COMMA_WORDS = int(os.environ.get("LITHOS_STREAM_COMMA_WORDS", 6))
# The commit policy when a client names none (?policy=): "clause", the rules above, or "agree", where the
# translator decides (agree.py). Agree runs only on the directions Gemma serves and agree.eligible() takes.
STREAM_POLICY = os.environ.get("LITHOS_STREAM_POLICY", "clause")
# Buffer trimming (LITHOS_TRIM=1): once a turn's buffer passes STREAM_TRIM_S,
# cut it at the end of the SECOND-to-last whisper segment (the last may still
# move) and carry the cut segments forward as fixed text, as whisper_streaming
# does. Without it every pass re-decodes the whole turn (0.15 s -> 0.76 s per
# pass across one live turn) and a later pass can rewrite a committed prefix.
STREAM_TRIM = os.environ.get("LITHOS_TRIM") == "1"
STREAM_TRIM_S = float(os.environ.get("LITHOS_TRIM_S", "8"))

# The non-speech filter (what whisper says when it hears a cough, and the
# no_speech_prob gate for one- or two-word fragments) is engines/common.py's
# is_nonspeech() and SHORT_NOISE_*, used by the recognisers.
#
# A language switch is rare mid-service and a short fragment is weak evidence
# for one (noise and plain English get identified CONFIDENTLY as the wrong
# language), so an utterance shorter than SWITCH_FREE_S that would CHANGE the
# room's language must clear SWITCH_MIN_CONF. 2.5 s let a 2.5 s English turn
# through the Portuguese model in a live session; a real speaker changing
# language keeps talking, so waiting costs little.
SWITCH_MIN_CONF = 0.90
SWITCH_FREE_S = 5.0
# Trailing quiet kept on an utterance, so a final consonant is not clipped.
TRAILING_KEEP_MS = 250

# The lookup tables the engines read (derived from languages.toml; kept under
# their old names, and re-exported by server.py, for anyone reading or
# scripting against it).
LANG_TO_MADLAD = _T["LANG_TO_MADLAD"]   # MADLAD's target tag, where it differs (tl -> fil)
KOKORO_VOICES = _T["KOKORO_VOICES"]     # lang -> (Kokoro lang_code, voice)
VOXCPM_LANGS = _T["VOXCPM_LANGS"]       # km, lo, tl (tl: no Piper or Kokoro voice exists)
COQUI_VOICES = _T["COQUI_VOICES"]       # ht: multilingual-tts/VITS-OpenBible-Haitian-Creole
PIPER_VOICES = _T["PIPER_VOICES"]
MMS_VOICES = _T["MMS_VOICES"]           # Meta MMS-TTS (CC-BY-NC) for ht/km/lo/tl, with --mms only
MADLAD_ONLY = _T["MADLAD_ONLY"]         # kept on MADLAD even where Hy-MT2 supports them (none by default)

# Sentences decode independently; Piper releases the GIL in onnxruntime.
# Sized above the usual language count on purpose: at 4 workers a fifth
# language could not START until another finished, which hid the benefit of
# running the voices concurrently and made that look like a dead end.
TTS_POOL = ThreadPoolExecutor(max_workers=int(os.environ.get("LITHOS_TTS_WORKERS", "8")))


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
                 asr_multi_revision=None, omni_large=False):
        # Imported here, first, in the order the server always has: the
        # heavyweight libraries (fairseq2, coqui) rearrange the environment,
        # and import order is part of what was measured.
        import torch
        from faster_whisper import WhisperModel  # noqa: F401
        from transformers import T5ForConditionalGeneration, T5Tokenizer  # noqa: F401

        self.langs = list(langs)   # the target languages a client may ask for (?lang=)
        from engines.common import is_gpu, resolve_device
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
        if n_gpu == 0 and not any(is_gpu(d) for d in [self.device, *devices.values()]):
            # Not an error (a CPU-only test is legitimate), but rarely what anyone meant.
            print("[stack] WARNING: PyTorch sees no GPU, so every model runs on the CPU. Check, in this shell: "
                  "the virtualenv is active; python -c \"import torch; print(torch.cuda.is_available())\" "
                  "prints True (on AMD: your user is in the render and video groups); "
                  "STACK_PROFILE is exported if you use one.")
        vad = MODELS["vad"]
        hub = f"{vad['repo']}:{vad['ref']}" if vad["ref"] else vad["repo"]
        print(f"[stack] loading Silero VAD ({hub})…")
        self.vad, _ = torch.hub.load(hub, "silero_vad", trust_repo=True)
        self.srcs = srcs or ["en"]

        # One engine set per edition this server serves (EDITION=both: two, see
        # build_voice_set). The first set owns recognition, shared by both; each
        # set translates and speaks by its own edition's table, sharing every
        # model configured the same in both (engines/manager.py).
        self.edition = edition
        self.editions = stack_config.editions_of(edition)
        # The edition of a connection whose token names none: the stricter one.
        self.default_edition = "commercial" if "commercial" in self.editions else self.editions[0]
        voxcpm_shared = {}

        def ctx_for(ed):
            return Context(
                device=self.device, devices=devices, models=MODELS, table=copy.deepcopy(LANG_CONFIG), tables=_T,
                langs=langs, srcs=self.srcs,
                options=dict(xeng=xeng, clone_ref=clone_ref, omni=omni, omni_large=omni_large, mms=mms,
                             asr_model=asr_model,
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
        """The engine set for a second edition (EDITION=both): recognisers from
        the first set; translators from it where configured the same in both
        tables (Hy-MT2, MADLAD; llmmt's own client where a server line differs,
        so a commercial connection's Lao never reaches MiLMMT-46); every voice
        engine whose settings are the same in both editions' tables (Kokoro,
        eSpeak NG) shared with it; the rest (Piper's per-edition voices, Coqui,
        MMS, VoxCPM2's language list) its own. VoxCPM2 shares its services'
        slots across both sets."""
        first = self.engines
        mine = stack_config.apply_edition(LANG_CONFIG, ed, first.reviews, first.unclear_ok)[0]
        names = first.shareable_voices(mine)
        print(f"[stack] {ed} voices: sharing {', '.join(sorted(names)) or 'none'} with {first.edition}", flush=True)
        vs = EngineSet(self._ctx_for(ed), serial_tts=self._serial_tts, share_from=first, share_voices=names)
        own = sorted(n for n, e in vs.engines["translator"].items() if first.engines["translator"].get(n) is not e)
        print(f"[stack] {ed} translators: sharing "
              f"{', '.join(sorted(set(vs.engines['translator']) - set(own))) or 'none'} with {first.edition}"
              + (f"; its own {', '.join(own)} (configured differently)" if own else ""), flush=True)
        return vs

    def voices(self, edition=None):
        """The EngineSet that translates and speaks for a connection in `edition`
        (None: the default edition)."""
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

    def translate(self, text, lang, src=None, context=None, edition=None):
        return self.translate_batch(text, [lang], src, context, edition)[0]

    def translate_batch(self, text, langs, src=None, context=None, edition=None):
        """Every target language at once, one batch per translator (engines/manager.py),
        by the translators of the connection's `edition` (voices(): EDITION=both
        routes each edition by its own table). `context`: TranslationMemory.before(src),
        the previous pieces for a client that asked (?context=1); None, and nothing
        changes, otherwise."""
        return self.voices(edition).translate_batch(text, langs, src, context=context)

    def agree_turn(self, src, lang, context=None, edition=None):
        """An agree.AgreeTurn for src -> lang when that direction may agree (agree.eligible) and Gemma
        (llmmt, a chat server) is the translator serving it now in `edition`; None, and the clause
        rule, otherwise."""
        import agree
        from engines import llmmt
        if not src or not agree.eligible(src, lang):
            return None
        eng = self.voices(edition).translator_for(lang, src)
        if getattr(eng, "name", None) != "llmmt" or (eng.server_for(src, lang) or ("",))[0] != "chat":
            return None
        names = llmmt.NAMES
        return agree.AgreeTurn(lambda prompt: eng.ask(src, lang, prompt), names.get(src, src),
                               names.get(lang, lang), llmmt.context_head(context, src, lang))

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
