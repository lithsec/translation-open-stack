"""Coqui VITS checkpoints: coqui = "<hugging face repo>", for languages neither
Kokoro nor Piper covers. Loaded with --coqui (EDITION=commercial).

Haitian Creole is the case that matters: it had no voice outside MMS, whose
CC-BY-NC licence is the one thing preventing this stack being redistributed.
OpenBible (multilingual-tts/VITS-OpenBible-Haitian-Creole) is CC-BY-SA — an
obligation, but a redistributable one.
"""
from engines import register
from engines.base import Voice
from engines.common import is_gpu, on_device, peak_normalise, to_pcm16


@register
class Coqui(Voice):
    name = "coqui"
    title = "Coqui VITS"
    lang_key = str
    priority = 30
    licence = "per checkpoint (OpenBible Haitian Creole: CC-BY-SA-4.0)"

    @classmethod
    def enabled(cls, ctx):
        return bool(ctx.options.get("coqui"))

    def __init__(self, ctx):
        super().__init__(ctx)
        self.repos = dict(ctx.tables.get("COQUI_VOICES", {}))
        self.synths = {}          # lang -> Synthesizer, built on first use

    def supports(self, lang):
        return self.available and lang in self.repos

    def load(self):
        try:
            from TTS.utils.synthesizer import Synthesizer  # noqa: F401
            self.available = True
            print(f"[stack] Coqui voices enabled for {sorted(self.repos)}", flush=True)
        except Exception as e:
            print(f"[stack] Coqui unavailable ({e}) — those languages fall back", flush=True)

    def synthesise(self, text, lang):
        """A Coqui VITS checkpoint (currently Haitian Creole)."""
        try:
            import numpy as np
            from huggingface_hub import hf_hub_download
            from TTS.utils.synthesizer import Synthesizer
            if lang not in self.synths:
                repo = self.repos[lang]
                cfg = hf_hub_download(repo, "config.json")
                ckpt = hf_hub_download(repo, "model_last.pth")
                try:
                    spk = hf_hub_download(repo, "speakers.pth")
                except Exception:
                    spk = None
                # Coqui only ever says "cuda": on_device makes that the configured card.
                with on_device(self.device):
                    self.synths[lang] = Synthesizer(
                        tts_checkpoint=ckpt, tts_config_path=cfg,
                        tts_speakers_file=spk, use_cuda=is_gpu(self.device))
                print(f"[stack] {lang}: {repo}", flush=True)
            syn = self.synths[lang]
            with self.lock(lang), on_device(self.device):
                pcm = np.asarray(syn.tts(text), dtype="float32").squeeze()
            # This model pads roughly a SECOND of dead air onto each end —
            # measured 3.86s of audio for 1.68s of speech. Left in, every
            # Haitian utterance would arrive a second late and hold the line
            # open a second after it finished. Trim to the speech, keeping 50ms
            # so no onset or release is clipped.
            idx = np.where(np.abs(pcm) > 0.01)[0]
            if len(idx):
                keep = int(syn.output_sample_rate * 0.05)
                pcm = pcm[max(0, idx[0] - keep):min(len(pcm), idx[-1] + keep)]
            return to_pcm16(peak_normalise(pcm), int(syn.output_sample_rate))
        except Exception as e:
            print(f"[stack] Coqui {lang} failed ({e}) — falling back", flush=True)
            return None
