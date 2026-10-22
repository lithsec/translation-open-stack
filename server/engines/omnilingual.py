"""Meta Omnilingual ASR, for the sources Whisper cannot serve (ht) or serves
badly (km lo sw, and hi fa bn ur): asr = "omni:<code>" in languages.toml,
where <code> is Omnilingual's own language code (e.g. khm_Khmr).

Measured on FLEURS human speech (2026-09-28, CER Whisper large-v3 ->
Omnilingual 300M): bn 34.9% -> 3.1%, hi 9.5 -> 4.4, fa 7.8 -> 5.0,
sw 8.8 -> 5.3, ur 7.7 -> 6.7. (tl stays on Whisper: 4.6 vs 8.5.)

Loaded with --omni. The adapter is deliberately thin and failure-loud: the
package is young and its pipeline call may drift. It returns no word timings,
so its languages keep the quietest-point forced cut and no streaming trims.

A language may ask for the larger card ([models.omnilingual_large], the 7B)
with `omni = "large"`. It loads only with --omni-large (OMNI_LARGE=1, set by the
profiles with room for it: ~20 GB more); without it those languages stay on
[models.omnilingual]. Lao and Khmer ask for it: one sentence at a time Lao goes
from 15.6% of characters wrong to 8.5%, Khmer from 14.1% to 12.6%; live, the
stack's English from Lao went from 22% to 47% (eval/2026-10-lao-khmer-7b). Every text from this engine passes the
repetition guard (engines/common.py), which the 7B needs most: its decoder
loops on Lao fragments.

Apache 2.0 (weights), fairseq2-based (its own heavy dependency tree:
docs/dev/lessons-learned.md §2).
"""
import os

from engines import register
from engines.base import Recognizer, VAD_RATE
from engines.common import is_nonspeech, on_device, repetition_guard


@register
class Omnilingual(Recognizer):
    name = "omni"
    title = "Omnilingual ASR"
    arg = "required"          # asr = "omni:<code>"
    lang_key = str            # omni = "large": this language uses [models.omnilingual_large]
    licence = "Apache-2.0"

    @classmethod
    def check_lang(cls, lang, value):
        if value not in ("large", "base"):
            return f'omni must be "large" or "base" (got {value!r})'
        return None

    @classmethod
    def enabled(cls, ctx):
        return bool(ctx.options.get("omni"))

    def __init__(self, ctx):
        super().__init__(ctx)
        # (asr = "omni:<code>" in languages.toml) -> {lang: code}
        self.codes = dict(ctx.tables.get("OMNI_LANGS", {}))
        self.omni = None
        # The languages that asked for the large card, and that card's pipeline
        # (None: not loaded, so they use self.omni).
        self.large_langs = {l for l, e in ctx.table.items()
                            if e.get("omni") == "large" and l in self.codes
                            and (not ctx.srcs or l in ctx.srcs)}   # only the sources this server takes
        self.large = None

    def supports(self, lang):
        return self.available and lang in self.codes

    def load(self):
        try:
            card = self.ctx.models["omnilingual"]["card"]
            self.omni = self._pipeline(card)
            self.available = True
        except Exception as e:
            print(f"[stack] Omnilingual unavailable ({e}) — ht/km/lo/sw fall back to whisper (poor)")
            return
        if not self.large_langs:
            return
        large = self.ctx.models.get("omnilingual_large", {}).get("card", "")
        if not self.ctx.options.get("omni_large"):
            print(f"[stack] {', '.join(sorted(self.large_langs))}: Omnilingual {card}, not {large or 'the large card'} "
                  "(OMNI_LARGE=1, or a profile with room for it, loads that)")
            return
        try:
            self.large = self._pipeline(large)
        except Exception as e:
            print(f"[stack] Omnilingual {large} unavailable ({e}) — "
                  f"{', '.join(sorted(self.large_langs))} stay on {card}")

    def _pipeline(self, card):
        from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline
        print(f"[stack] loading Omnilingual ASR ({card}) on {self.device}…")
        # The configured device, passed explicitly: the pipeline moves its
        # inputs to its own `device`, and left to itself that is "cuda", read
        # as card 0, while the weights followed the current card (a 2-GPU pod
        # failed every Khmer utterance that way, 2026-09-30). on_device covers
        # fairseq2 code that still says plain "cuda".
        import inspect
        kw = {}
        params = inspect.signature(ASRInferencePipeline).parameters
        if "device" in params:
            kw["device"] = self.device
        # The pipeline defaults to bfloat16, which a CPU emulates: on an M2
        # Pro a 13 s Haitian sentence took 34 s in bf16 and 13.5 s in
        # float32 (2026-10-17, services/omni-stt). GPUs keep the default.
        if "dtype" in params and str(self.device).startswith("cpu"):
            import torch
            kw["dtype"] = torch.float32
        with on_device(self.device):
            return ASRInferencePipeline(model_card=card, **kw)

    def pipeline_for(self, lang):
        """The large card for a language that asked for it, when it loaded."""
        return self.large if self.large is not None and lang in self.large_langs else self.omni

    def transcribe(self, pcm16k, lang, want_segments=False):
        # The real API (verified against omnilingual-asr 0.1.0) takes file
        # paths, not arrays — write a temp wav. Adapter guessed right on
        # everything else: model_card init, transcribe(inp, lang=[...]).
        import tempfile, wave as _wave
        import numpy as _np
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as fh:
                with _wave.open(fh, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(VAD_RATE)
                    w.writeframes((_np.clip(pcm16k, -1, 1) * 32767).astype("<i2").tobytes())
            with on_device(self.device):
                out = self.pipeline_for(lang).transcribe([path], lang=[self.codes[lang]], batch_size=1)
        finally:
            os.unlink(path)
        text = self._guarded((out[0] if out else "").strip(), len(pcm16k) / VAD_RATE)
        # No per-segment timestamps from this path, so no trimming either.
        return (text, []) if want_segments else text

    def transcribe_batch(self, items):
        """[(pcm16k, lang), ...] -> [text, ...] in the same order, in ONE batched
        pipeline call (services/omni-stt's micro-batcher). Each item keeps its own
        language code; the pipeline zero-pads the audio to the longest and passes
        the true lengths (seq_lens) to the encoder and the decoder, so an item's
        text does not depend on its neighbours beyond float rounding. The audio
        goes in as in-memory 16-bit wav bytes: the same AudioDecoder path as the
        temp file in transcribe(), without the file."""
        if not items:
            return []
        # One call per card: the large one for its languages, the base for the rest.
        out = [None] * len(items)
        groups = {}
        for i, (_, lang) in enumerate(items):
            groups.setdefault(id(self.pipeline_for(lang)), (self.pipeline_for(lang), []))[1].append(i)
        for pipe, idx in groups.values():
            wavs = [wav_bytes(items[i][0]) for i in idx]
            with on_device(self.device):
                texts = pipe.transcribe(wavs, lang=[self.codes[items[i][1]] for i in idx], batch_size=len(idx))
            if len(texts) != len(idx):
                raise RuntimeError(f"Omnilingual returned {len(texts)} texts for {len(idx)} utterances")
            for i, t in zip(idx, texts):
                out[i] = self._guarded((t or "").strip(), len(items[i][0]) / VAD_RATE)
        return out

    def _guarded(self, text, audio_s):
        text = self._filtered(text)
        kept, action = repetition_guard(text, audio_s)
        if action:
            # Lengths only: the text is the speaker's, and is not logged.
            print(f"[stack] repetition guard (omni): {action} {len(text)} -> {len(kept)} chars "
                  f"({audio_s:.1f}s of audio)", flush=True)
        return kept

    @staticmethod
    def _filtered(text):
        # This path has no segment gates of its own, so it needs the content
        # filter: a cough that language ID sends to Khmer came back as
        # "ភ្អាក់ ها ها" and reached the Spanish listeners as "Abre - ¡Ha, ha!".
        if is_nonspeech(text):
            print(f"[stack] dropped annotation (omni): {text[:50]}", flush=True)
            return ""
        return text


def wav_bytes(pcm16k):
    """float [-1, 1] at 16 kHz -> a mono 16-bit wav file's bytes (as transcribe() writes)."""
    import io, wave as _wave
    import numpy as _np
    buf = io.BytesIO()
    with _wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(VAD_RATE)
        w.writeframes((_np.clip(pcm16k, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()
