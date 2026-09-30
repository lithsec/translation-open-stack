"""Piper (CPU, ONNX): piper = "<voice name>", e.g. "de_DE-thorsten-high".
Download list: https://huggingface.co/rhasspy/piper-voices (scripts/fetch-voices.sh
downloads what languages.toml names). Why each voice was chosen: languages.toml.

Always on: every served language with a Piper voice loads it at start, and it
is the fallback behind Kokoro. The voices' licences vary (docs/licences.md §7);
piper-tts itself is GPL-3.0-or-later since 1.3.
"""
import io
import wave
from pathlib import Path

from engines import register
from engines.base import Voice
from engines.common import to_pcm16

# Threads per Piper inference. ONNX Runtime sizes its pool from the cores it
# can SEE, not the container's cgroup quota (see load()).
TTS_THREADS = 4


@register
class Piper(Voice):
    name = "piper"
    title = "Piper"
    lang_key = str
    priority = 40
    # One ONNX session per language; onnxruntime's run() is thread-safe and
    # releases the GIL, so a language's sentences synthesise in parallel.
    lock_policy = "none"
    licence = "per voice (docs/licences.md §7); piper-tts GPL-3.0-or-later"

    @classmethod
    def enabled(cls, ctx):
        return True

    def __init__(self, ctx):
        super().__init__(ctx)
        self.names = dict(ctx.tables.get("PIPER_VOICES", {}))
        self.tts = {}

    def supports(self, lang):
        return lang in self.tts

    def load(self):
        # Script-relative, not CWD-relative: a CWD-relative "voices/" worked on
        # the pod only because the CWD happened to be the script dir, and cost
        # a whole CPU bench run locally when it was not. The repository's
        # voices/ is two levels up from server/engines/.
        voices_dir = self.ctx.options.get("voices_dir")
        voices_dir = Path(voices_dir) if voices_dir else Path(__file__).resolve().parent.parent.parent / "voices"
        for lang in self.ctx.langs:
            voice = self.names.get(lang)
            if not voice:
                print(f"[stack] {lang}: no Piper voice mapped — text only")
                continue
            try:
                from piper import PiperVoice
                model = str(voices_dir / f"{voice}.onnx")
                v = PiperVoice.load(model)
                # ONNX Runtime sizes its thread pool from the cores it can SEE
                # — 96 on this host — while the container's cgroup quota is
                # ~10. Ninety-six threads contending for ten cores ran this
                # voice at 0.7x real time; bounding the pool gives ~20x. That
                # one line was the whole latency problem: text was ready in
                # 0.9s and the operator waited seconds for audio behind it.
                import onnxruntime as ort
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = TTS_THREADS
                opts.inter_op_num_threads = 1
                v.session = ort.InferenceSession(
                    model, opts, providers=["CPUExecutionProvider"])
                self.tts[lang] = v
                print(f"[stack] {lang}: {voice} (intra_op={TTS_THREADS})")
            except Exception as e:
                print(f"[stack] {lang}: Piper voice unavailable ({e}) — text only")
        self.available = True

    def synthesise(self, text, lang):
        """Always audio for a language it has (a failure raises: nothing
        behind Piper would do better with the same text)."""
        voice = self.tts[lang]
        import numpy as np
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            # piper-tts >= 1.3: synthesize() returns chunks; synthesize_wav
            # writes a complete file (and found by the CPU smoke, not on GPU
            # money — the old 1.2 call form crashed the connection here).
            # Voices trained on raw letters (phoneme_type "text", e.g. Ukrainian)
            # only know lowercase: a capital is silently dropped, so every
            # sentence lost its first letter. Lowercase costs them nothing.
            pt = getattr(getattr(voice, "config", None), "phoneme_type", "")
            if getattr(pt, "value", pt) == "text":
                text = text.lower()
            voice.synthesize_wav(text, w)
        buf.seek(0)
        with wave.open(buf, "rb") as w:
            native = w.getframerate()
            pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32") / 32768
        return to_pcm16(pcm, native)
