"""Kokoro 82M (hexgrad, Apache 2.0): kokoro = "<lang_code>:<voice>", e.g.
"a:am_michael". Loaded with --kokoro; [models.kokoro] pins the release.

Picked over Piper by ear on identical sentences. Three things beyond how it
sounds: it emits 24kHz, which IS the pipeline rate, so the resample step and
its edge-ringing disappear; one model covers several languages instead of a
63-114MB file each; and unlike MMS the licence is permissive.

It is a GPU model. Warm: 98x real time on the GPU against Piper's 30x on CPU,
but only 2.0x on CPU — so this moves TTS onto the GPU deliberately, using the
device that sits idle between utterances rather than the CPU Piper competes
for. Piper stays behind it as the fallback.
"""
import os

from engines import register
from engines.base import Voice, RATE
from engines.common import hf_snapshot, peak_normalise, to_pcm16


@register
class Kokoro(Voice):
    name = "kokoro"
    title = "Kokoro"
    lang_key = str
    priority = 10
    licence = "Apache-2.0"

    @classmethod
    def enabled(cls, ctx):
        return bool(ctx.options.get("kokoro"))

    @classmethod
    def check_lang(cls, lang, value):
        if len(value.split(":")) != 2:
            return "kokoro must be \"<lang_code>:<voice>\", e.g. \"a:am_michael\""
        return None

    def __init__(self, ctx):
        super().__init__(ctx)
        self.voices = dict(ctx.tables.get("KOKORO_VOICES", {}))  # lang -> (Kokoro lang_code, voice)
        self.pipelines = {}     # lang_code -> (KPipeline, voices dir), built on first use

    def supports(self, lang):
        return self.available and lang in self.voices

    def load(self):
        try:
            from kokoro import KPipeline  # noqa: F401
            self.available = True
            print("[stack] Kokoro TTS enabled (24kHz native, GPU)", flush=True)
        except Exception as e:
            print(f"[stack] Kokoro unavailable ({e}) — falling back to Piper", flush=True)

    def synthesise(self, text, lang):
        """Kokoro at the pipeline's own 24kHz — no resample, so no edge ringing."""
        code, voice = self.voices[lang]
        try:
            import numpy as np
            if code not in self.pipelines:
                self.pipelines[code] = self._pipeline(code)
            pipe, voices = self.pipelines[code]
            # Kokoro's pipeline is not thread-safe: one language's sentences go
            # through it one at a time (lock_policy "language").
            with self.lock(lang):
                chunks = [a for _, _, a in pipe(text, voice=os.path.join(voices, f"{voice}.pt") if voices else voice)]
            if not chunks:
                return None
            pcm = np.concatenate([
                c.detach().cpu().numpy() if hasattr(c, "detach") else np.asarray(c)
                for c in chunks
            ]).astype("float32")
            # Kokoro peaks around 0.4-0.7 where Piper masters to 1.0. Left alone
            # a room switching languages would hear the level jump, which is the
            # same defect measured on MMS (Haitian was 11dB down).
            return to_pcm16(peak_normalise(pcm), RATE)
        except Exception as e:
            print(f"[stack] Kokoro {lang} failed ({e}) — falling back", flush=True)
            return None

    def _pipeline(self, code):
        """(KPipeline, voices dir or None) for one Kokoro language code, from
        languages.toml [models.kokoro]. Pinned: the model, its config and the
        voices come from that snapshot (KPipeline itself has no revision
        argument, so it gets them as paths); one model per pipeline, as before."""
        from kokoro import KModel, KPipeline
        repo, rev = self.ctx.models["kokoro"]["repo"], self.ctx.models["kokoro"]["revision"]
        device = self.device
        if not rev:
            return KPipeline(lang_code=code, repo_id=repo, device=device), None
        weights = KModel.MODEL_NAMES.get(repo, "kokoro-v1_0.pth")
        local = hf_snapshot(repo, rev, allow_patterns=["config.json", weights] +
                            [f"voices/{v}.pt" for _, v in self.voices.values()])
        model = KModel(repo_id=repo, config=os.path.join(local, "config.json"),
                       model=os.path.join(local, weights)).to(device).eval()
        return KPipeline(lang_code=code, repo_id=repo, model=model, device=device), os.path.join(local, "voices")
