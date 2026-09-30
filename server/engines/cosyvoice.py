"""CosyVoice2 0.5B zero-shot cloning (Apache 2.0), with --clone REF_WAV only:
en/es/fr/pt spoken in the reference voice (the preacher's own timbre). es/fr/pt
ride CosyVoice2's CROSS-LINGUAL mode (its strong languages are zh/en/ja/ko),
which is exactly where its quality is least proven. No script here installs it
(the server looks for pretrained_models/CosyVoice2-0.5B).

Not named in languages.toml: the flag puts it at the front of those four
languages' chains, and every failure falls back to the rest of the chain.
"""
from engines import register
from engines.base import Voice
from engines.common import to_pcm16

CLONE_LANGS = ("en", "es", "fr", "pt")


@register
class CosyVoice(Voice):
    name = "cosyvoice"
    title = "CosyVoice2"
    priority = -100           # ahead of everything, as --clone always was
    front = True              # ...even of a language's own `voice = [...]` list
    # Never locked, as before: cloning is an experiment on one listener.
    lock_policy = "none"
    licence = "Apache-2.0"

    @classmethod
    def enabled(cls, ctx):
        return bool(ctx.options.get("clone_ref"))

    def __init__(self, ctx):
        super().__init__(ctx)
        self.clone = None
        self.clone_ref = None

    def supports(self, lang):
        return self.clone is not None and lang in CLONE_LANGS

    def load(self):
        clone_ref = self.ctx.options.get("clone_ref")
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice2
            import torchaudio
            print("[stack] loading CosyVoice2-0.5B…")
            self.clone = CosyVoice2("pretrained_models/CosyVoice2-0.5B")
            ref, sr = torchaudio.load(clone_ref)
            if sr != 16000:
                ref = torchaudio.transforms.Resample(sr, 16000)(ref)
            self.clone_ref = ref.mean(0)  # mono
            print(f"[stack] cloning voice from {clone_ref}")
            self.available = True
        except Exception as e:
            print(f"[stack] CosyVoice2 unavailable ({e}) — cloned routes fall back to Piper")
            self.clone = None

    def synthesise(self, text, lang):
        """The reference voice speaking `text`. None on any failure — the
        chain then continues, so a cloning bug can never cost the room its
        translation."""
        try:
            import numpy as np
            chunks = []
            for out in self.clone.inference_cross_lingual(text, self.clone_ref, stream=False):
                chunks.append(out["tts_speech"].squeeze().cpu().numpy())
            if not chunks:
                return None
            pcm = np.concatenate(chunks)
            return to_pcm16(pcm, int(self.clone.sample_rate))
        except Exception as e:
            print(f"[stack] clone failed ({e}) — Piper fallback")
            return None
