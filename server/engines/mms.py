"""Meta MMS-TTS: mms = "<hugging face repo>", e.g. "facebook/mms-tts-khm".
CC-BY-NC: Lithos ships none of it; the operator running the instance downloads
the weights (the operator-supplied pattern, docs/licences.md). Loaded with
--mms only (EDITION=nonprofit). Lazy per language: each model is ~150 MB and a
session usually needs one of them. Last in the chain, behind Piper.
"""
from engines import register
from engines.base import Voice
from engines.common import peak_normalise, to_pcm16


@register
class MMS(Voice):
    name = "mms"
    title = "MMS-TTS"
    lang_key = str
    priority = 50
    licence = "CC-BY-NC-4.0"

    @classmethod
    def enabled(cls, ctx):
        return bool(ctx.options.get("mms"))

    def __init__(self, ctx):
        super().__init__(ctx)
        self.ids = dict(ctx.tables.get("MMS_VOICES", {}))
        self.cache = {}

    def supports(self, lang):
        return self.available and lang in self.ids

    def synthesise(self, text, lang):
        """MMS-TTS (CC-BY-NC, operator-downloaded). None when unmapped."""
        mid = self.ids.get(lang)
        if not mid:
            return None
        try:
            import torch
            if lang not in self.cache:
                from transformers import VitsModel, AutoTokenizer
                print(f"[stack] loading {mid}…")
                self.cache[lang] = (AutoTokenizer.from_pretrained(mid),
                                    VitsModel.from_pretrained(mid).eval().to(self.ctx.device))
            tok, model = self.cache[lang]
            inputs = tok(text, return_tensors="pt").to(self.ctx.device)
            # MMS tokenizers are script-specific (Khmer, Lao…): text in the
            # wrong script maps to NOTHING, and an empty id tensor crashes
            # VITS with "narrow(): length must be non-negative". Skip instead
            # — with real MADLAD output this is rare, but numerals and
            # borrowed Latin words can still produce it.
            if inputs["input_ids"].numel() == 0:
                return None
            with self.lock(lang):
                with torch.inference_mode():
                    pcm = model(**inputs).waveform[0].float().cpu().numpy()
            native = int(model.config.sampling_rate)
            # MMS renders about 11dB below Piper (Haitian RMS -25.5 dBFS against
            # -14 to -15 for the Piper voices), so a listener on that language
            # has to turn the phone up and may still lose it in a room.
            return to_pcm16(peak_normalise(pcm), native)
        except Exception as e:
            print(f"[stack] MMS {lang} failed ({e}) — text only")
            return None
