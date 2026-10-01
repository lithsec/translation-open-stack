"""faster-whisper: the default recogniser, for every source language that does
not name another one (asr = "whisper", or nothing).

Two slots: `model` for English, and `multi_model` for other sources, loaded
only with --xeng. distil-large-v3 (the server's bare default) is distilled for
English and mis-transcribes everything else with confidence, so the
multilingual slot must be a full model; scripts/run.sh loads large-v3 once and
shares it (languages.toml [models.whisper], multi_model = "").

On a Mac ([devices] whisper = "mps", profiles/mac.toml) the same engine runs
an MLX build on the Apple GPU instead ([models.whisper_mlx]; large-v3-turbo):
one model for every source, the same speech-only input (faster-whisper's own
Silero VAD, as vad_filter does) and the same segment gates below.

MIT (weights, faster-whisper and mlx-whisper).
"""
import os
from types import SimpleNamespace

from engines import register
from engines.base import Recognizer
from engines.common import is_nonspeech, content_units, ct2_device, SHORT_NOISE_P, SHORT_NOISE_UNITS

# LITHOS_SEG_STATS=1 prints every segment's confidence numbers (the data the
# gates below were tuned on).
SEG_STATS = bool(os.environ.get("LITHOS_SEG_STATS"))


@register
class Whisper(Recognizer):
    name = "whisper"
    title = "faster-whisper"
    licence = "MIT"
    mlx = None            # the MLX model path, when [devices] whisper = "mps"

    @classmethod
    def enabled(cls, ctx):
        return True   # the default recogniser, and every other one's fallback

    def supports(self, lang):
        return True

    def load(self):
        self.mlx = None
        if self.device == "mps":
            return self._load_mlx()
        from faster_whisper import WhisperModel
        o = self.ctx.options
        asr_model = o.get("asr_model") or "distil-large-v3"
        asr_multi_model = o.get("asr_multi_model") or "large-v3"
        asr_revision = o.get("asr_revision")
        asr_multi_revision = o.get("asr_multi_revision")
        kind, index = ct2_device(self.device)
        compute = "float16" if kind == "cuda" else "int8"
        print(f"[stack] loading faster-whisper {asr_model}{f' @ {asr_revision}' if asr_revision else ''} on {self.device}…")
        self.asr = WhisperModel(asr_model, device=kind, device_index=index, revision=asr_revision or None,
                                compute_type=compute)
        # X->eng needs the FULL multilingual model: distil-large-v3 is distilled
        # for English and mis-transcribes everything else with confidence.
        self.asr_multi = None
        if o.get("xeng"):
            if asr_multi_model == asr_model:
                # One model for every source. distil is the better English
                # default (2x faster, half the VRAM, WER parity — and a
                # sermon-only deployment loads nothing else), but on a
                # memory-tight box `--asr-model large-v3 --asr-multi-model
                # large-v3` shares a single instance instead of loading the
                # same weights twice.
                print(f"[stack] sharing {asr_model} for English and --xeng sources")
                self.asr_multi = self.asr
            else:
                pin = f" @ {asr_multi_revision}" if asr_multi_revision else " (UNPINNED: set [models.whisper] multi_revision)"
                print(f"[stack] loading whisper {asr_multi_model}{pin} (multilingual, for --xeng)…")
                self.asr_multi = WhisperModel(asr_multi_model, device=kind, device_index=index,
                                              revision=asr_multi_revision or None, compute_type=compute)
        self.available = True

    def _load_mlx(self):
        import mlx_whisper  # noqa: F401  (fails here, at start, if it is missing)
        from engines.common import hf_snapshot
        m = self.ctx.models["whisper_mlx"]
        print(f"[stack] loading Whisper (MLX, Apple GPU) {m['repo']} @ {m['revision'][:12] or 'unpinned'}…")
        self.mlx = hf_snapshot(m["repo"], m["revision"] or None)
        self.asr = "mlx"
        # One multilingual model serves English and every other source.
        self.asr_multi = "mlx" if self.ctx.options.get("xeng") else None
        self.available = True

    def _mlx_segments(self, pcm16k, language, word_timestamps=False):
        """mlx-whisper over the speech in pcm16k only (what vad_filter does for
        faster-whisper), as segment objects with the same fields, times mapped
        back onto the original audio."""
        import numpy as np
        import mlx_whisper
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        audio = np.asarray(pcm16k, dtype=np.float32)
        spans = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300))
        if not spans:
            return []
        parts, where, at = [], [], 0          # (start in the cut audio, start in the original)
        for sp in spans:
            parts.append(audio[sp["start"]:sp["end"]])
            where.append((at, sp["start"]))
            at += sp["end"] - sp["start"]
        cut = np.concatenate(parts)

        def orig(t):
            n = int(t * 16000)
            base = max((w for w in where if w[0] <= n), default=where[0])
            return (base[1] + n - base[0]) / 16000

        from engines.common import mlx_run
        # On the MLX thread (engines.common.mlx_run), which also serialises decodes.
        out = mlx_run(mlx_whisper.transcribe, cut, path_or_hf_repo=self.mlx, language=language,
                      temperature=0.0, condition_on_previous_text=False, no_speech_threshold=0.6,
                      word_timestamps=word_timestamps, verbose=None)
        segs = []
        for sg in out.get("segments", []):
            words = [SimpleNamespace(word=w["word"], end=orig(w["end"])) for w in sg.get("words") or []]
            segs.append(SimpleNamespace(text=sg["text"], start=orig(sg["start"]), end=orig(sg["end"]),
                                        no_speech_prob=sg.get("no_speech_prob", 0.0),
                                        avg_logprob=sg.get("avg_logprob", 0.0),
                                        compression_ratio=sg.get("compression_ratio", 0.0), words=words))
        return segs

    @property
    def multilingual(self):
        return self.asr_multi is not None

    def words(self, pcm16k, lang):
        # The same model and language choice as transcribe(). This used to pick the
        # language by model identity, so when the English and multilingual slots
        # share one model (scripts/run.sh) every source was decoded as English:
        # Spanish came back as English-ish words with no sentence ends, and a
        # forced cut fell back to the quietest point, mid-sentence (fixed 2026-09-29).
        if lang == "en" or self.asr_multi is None:
            model, language = self.asr, "en"
        else:
            model, language = self.asr_multi, lang
        if self.mlx:
            return [(w.word, w.end) for sg in self._mlx_segments(pcm16k, language, word_timestamps=True)
                    for w in sg.words]
        segs, _ = model.transcribe(pcm16k, language=language, beam_size=1,
                                   condition_on_previous_text=False, temperature=0, vad_filter=True,
                                   vad_parameters=dict(min_silence_duration_ms=300), word_timestamps=True)
        return [(w.word, w.end) for sg in segs for w in (sg.words or [])]

    def transcribe(self, pcm16k, lang="en", want_segments=False):
        # condition_on_previous_text=False: with it on, one hallucinated
        # sign-off conditions the next utterance and the model keeps saying it.
        # no_speech_threshold drops segments the model itself rates as silence,
        # which is where the invented filler lives.
        # vad_filter: whisper only sees the parts Silero calls speech. Trimming
        # the pause before the endpoint was not enough, because a room is never
        # digitally silent — mains hum and HVAC are audio, and whisper fills
        # audio it cannot parse with the polite sign-offs it learned from
        # captioned video ("Thank you", "gracias por su comentario"). Those come
        # back CONFIDENT, so no_speech_threshold never catches them; the fix is
        # to stop handing it the noise in the first place.
        opts = dict(beam_size=1, condition_on_previous_text=False,
                    no_speech_threshold=0.6, temperature=0,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=300))
        if self.mlx:
            segs = self._mlx_segments(pcm16k, "en" if lang == "en" or self.asr_multi is None else lang)
        elif lang == "en" or self.asr_multi is None:
            segs, _ = self.asr.transcribe(pcm16k, language="en", **opts)
        else:
            segs, _ = self.asr_multi.transcribe(pcm16k, language=lang, **opts)
        kept = []
        for sg in segs:
            # Drop a segment only when BOTH signals agree it is not speech: the
            # model thinks there was silence AND it had low confidence in the
            # words. Either alone is not enough — this gate was p>0.5 for one
            # afternoon and ate real scripture reading at p=0.53-0.65, because
            # a confident transcription of quiet speech looks "non-speech" by
            # that measure. A hallucination is the case where the model is
            # unsure AND heard nothing; that is what these two together catch.
            no_speech = getattr(sg, "no_speech_prob", 0.0)
            logprob = getattr(sg, "avg_logprob", 0.0)
            if SEG_STATS:
                print("[segstat] p=%.3f logprob=%.3f dur=%.2f comp=%.2f | %s" % (
                    no_speech, logprob,
                    getattr(sg, "end", 0.0) - getattr(sg, "start", 0.0),
                    getattr(sg, "compression_ratio", 0.0),
                    sg.text.strip()[:60]), flush=True)
            if no_speech > 0.9 and logprob < -1.0:
                print(f"[stack] dropped non-speech segment (p={no_speech:.2f}, "
                      f"logprob={logprob:.2f}): {sg.text.strip()[:50]}", flush=True)
                continue
            # The content gate, for the case the confidence gate cannot see: a
            # cough transcribed as "Cough, cough, cough." is CONFIDENT, and it
            # reached the Spanish listeners as "Tos, tos, tos."
            if is_nonspeech(sg.text):
                print(f"[stack] dropped annotation (p={no_speech:.2f}): "
                      f"{sg.text.strip()[:50]}", flush=True)
                continue
            if (content_units(sg.text) <= SHORT_NOISE_UNITS
                    and no_speech > SHORT_NOISE_P):
                print(f"[stack] dropped short noise (p={no_speech:.2f}): "
                      f"{sg.text.strip()[:50]}", flush=True)
                continue
            kept.append((sg.text.strip(), float(getattr(sg, "end", 0.0))))
        text = " ".join(t for t, _ in kept).strip()
        return (text, kept) if want_segments else text
