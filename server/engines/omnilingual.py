"""Meta Omnilingual ASR, for the sources Whisper cannot serve (ht) or serves
badly (km lo sw, and hi fa bn ur): asr = "omni:<code>" in languages.toml,
where <code> is Omnilingual's own language code (e.g. khm_Khmr).

Measured on FLEURS human speech (2026-09-28, CER Whisper large-v3 ->
Omnilingual 300M): bn 34.9% -> 3.1%, hi 9.5 -> 4.4, fa 7.8 -> 5.0,
sw 8.8 -> 5.3, ur 7.7 -> 6.7. (tl stays on Whisper: 4.6 vs 8.5.)

Loaded with --omni. The adapter is deliberately thin and failure-loud: the
package is young and its pipeline call may drift. It returns no word timings,
so its languages keep the quietest-point forced cut and no streaming trims.

Apache 2.0 (weights), fairseq2-based (its own heavy dependency tree:
docs/dev/lessons-learned.md §2).
"""
import os

from engines import register
from engines.base import Recognizer, VAD_RATE
from engines.common import is_nonspeech


@register
class Omnilingual(Recognizer):
    name = "omni"
    title = "Omnilingual ASR"
    arg = "required"          # asr = "omni:<code>"
    licence = "Apache-2.0"

    @classmethod
    def enabled(cls, ctx):
        return bool(ctx.options.get("omni"))

    def __init__(self, ctx):
        super().__init__(ctx)
        # (asr = "omni:<code>" in languages.toml) -> {lang: code}
        self.codes = dict(ctx.tables.get("OMNI_LANGS", {}))
        self.omni = None

    def supports(self, lang):
        return self.available and lang in self.codes

    def load(self):
        try:
            from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline
            card = self.ctx.models["omnilingual"]["card"]
            print(f"[stack] loading Omnilingual ASR ({card})…")
            self.omni = ASRInferencePipeline(model_card=card)
            self.available = True
        except Exception as e:
            print(f"[stack] Omnilingual unavailable ({e}) — ht/km/lo/sw fall back to whisper (poor)")

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
            out = self.omni.transcribe([path], lang=[self.codes[lang]], batch_size=1)
        finally:
            os.unlink(path)
        text = (out[0] if out else "").strip()
        # This path has no segment gates of its own, so it needs the content
        # filter: a cough that language ID sends to Khmer came back as
        # "ភ្អាក់ ها ها" and reached the Spanish listeners as "Abre - ¡Ha, ha!".
        if is_nonspeech(text):
            print(f"[stack] dropped annotation (omni): {text[:50]}", flush=True)
            return ("", []) if want_segments else ""
        # No per-segment timestamps from this path, so no trimming either.
        return (text, []) if want_segments else text
