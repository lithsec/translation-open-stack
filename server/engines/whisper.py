"""faster-whisper: the default recogniser, for every source language that does
not name another one (asr = "whisper", or nothing).

Two slots: `model` for English, and `multi_model` for other sources, loaded
only with --xeng. distil-large-v3 (the server's bare default) is distilled for
English and mis-transcribes everything else with confidence, so the
multilingual slot must be a full model; scripts/run.sh loads large-v3 once and
shares it (languages.toml [models.whisper], multi_model = "").

MIT (weights and faster-whisper).
"""
import os

from engines import register
from engines.base import Recognizer
from engines.common import is_nonspeech, content_units, SHORT_NOISE_P, SHORT_NOISE_UNITS

# LITHOS_SEG_STATS=1 prints every segment's confidence numbers (the data the
# gates below were tuned on).
SEG_STATS = bool(os.environ.get("LITHOS_SEG_STATS"))


@register
class Whisper(Recognizer):
    name = "whisper"
    title = "faster-whisper"
    licence = "MIT"

    @classmethod
    def enabled(cls, ctx):
        return True   # the default recogniser, and every other one's fallback

    def supports(self, lang):
        return True

    def load(self):
        from faster_whisper import WhisperModel
        o = self.ctx.options
        asr_model = o.get("asr_model") or "distil-large-v3"
        asr_multi_model = o.get("asr_multi_model") or "large-v3"
        asr_revision = o.get("asr_revision")
        asr_multi_revision = o.get("asr_multi_revision")
        device = self.ctx.device
        print(f"[stack] loading faster-whisper {asr_model}{f' @ {asr_revision}' if asr_revision else ''}…")
        self.asr = WhisperModel(asr_model, device=device, revision=asr_revision or None,
                                compute_type="float16" if device == "cuda" else "int8")
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
                self.asr_multi = WhisperModel(asr_multi_model, device=device, revision=asr_multi_revision or None,
                                              compute_type="float16" if device == "cuda" else "int8")
        self.available = True

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
        if lang == "en" or self.asr_multi is None:
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
