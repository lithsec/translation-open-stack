"""python3 tests/test_mlx_backends.py  (no Mac needed: MLX and the VAD are stand-ins)

The Apple GPU paths ([devices] whisper/hymt = "mps"): Whisper feeds MLX only
the speech, maps the times back onto the original audio and applies the same
gates as faster-whisper; Hy-MT2 uses the same prompt and greedy decoding."""
import os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
import numpy as np  # noqa: E402
import stack_config as c  # noqa: E402
from engines.base import Context  # noqa: E402

CALLS = {}


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


class VadOptions:
    def __init__(self, **kw):
        self.kw = kw


# Speech at 1.0-1.5 s and 2.5-3.0 s of a 3 s clip.
_stub("faster_whisper")
_stub("faster_whisper.vad", VadOptions=VadOptions,
      get_speech_timestamps=lambda audio, opts: [{"start": 16000, "end": 24000}, {"start": 40000, "end": 48000}])


def fake_transcribe(audio, **kw):
    CALLS["whisper"] = (len(audio), kw)
    return {"segments": [
        # Ends 0.9 s into the cut audio = 0.4 s into the second span = 2.9 s in the original.
        {"text": " Hello there.", "start": 0.0, "end": 0.9, "no_speech_prob": 0.1, "avg_logprob": -0.2,
         "words": [{"word": " Hello", "start": 0.0, "end": 0.3}, {"word": " there.", "start": 0.6, "end": 0.9}]},
        {"text": " Thank you for watching.", "start": 0.9, "end": 1.0, "no_speech_prob": 0.95,
         "avg_logprob": -1.5, "words": []},           # the confidence gate drops it
        {"text": " (coughing)", "start": 0.9, "end": 1.0, "no_speech_prob": 0.2, "avg_logprob": -0.3,
         "words": []},                                 # the content gate drops it
    ]}


_stub("mlx_whisper", transcribe=fake_transcribe)

import engines.common  # noqa: E402
engines.common.hf_snapshot = lambda repo, rev, **kw: f"/models/{repo}@{rev}"
from engines.whisper import Whisper  # noqa: E402
from engines.hymt import HyMT  # noqa: E402

MODELS = c.model_defaults()


def _ctx(**devices):
    return Context(device="cpu", devices=devices, models=MODELS, options={"xeng": True})


def test_whisper_mlx_transcribes_speech_only_with_the_same_gates():
    w = Whisper(_ctx(whisper="mps"))
    w.load()
    assert w.available and w.multilingual and w.mlx.startswith("/models/mlx-community/whisper-large-v3-turbo@")
    text, kept = w.transcribe(np.zeros(48000, dtype=np.float32), "es", want_segments=True)
    n, kw = CALLS["whisper"]
    assert n == 16000                                      # the two speech spans only
    assert kw["language"] == "es" and kw["temperature"] == 0.0 and not kw["condition_on_previous_text"]
    assert text == "Hello there." and len(kept) == 1
    assert abs(kept[0][1] - 2.9) < 1e-6                    # mapped back onto the original audio
    words = w.words(np.zeros(48000, dtype=np.float32), "en")
    assert [x for x, _ in words] == [" Hello", " there."] and abs(words[0][1] - 1.3) < 1e-6
    assert CALLS["whisper"][1]["language"] == "en" and CALLS["whisper"][1]["word_timestamps"]


def test_whisper_without_mps_is_untouched():
    w = Whisper(_ctx())
    assert w.device == "cpu" and w.mlx is None


def test_hymt_mlx_is_enabled_by_the_device_and_uses_the_same_prompt():
    assert not HyMT.enabled(_ctx())                        # no NF4 build, no mps: off
    assert HyMT.enabled(_ctx(hymt="mps"))

    class Tok:
        def apply_chat_template(self, msgs, tokenize, add_generation_prompt):
            return "<prompt>" + msgs[0]["content"]

        def encode(self, x, add_special_tokens=False):
            return x.split()

    seen = []

    def generate(model, tok, prompt, max_tokens, sampler, logits_processors, verbose):
        seen.append((prompt, max_tokens))
        return f" [{prompt.split(':')[-1].strip()}] "

    _stub("mlx_lm", generate=generate)
    HyMT._mlx_load = staticmethod(lambda path: ("model", Tok()))
    _stub("mlx_lm.sample_utils", make_sampler=lambda temp: ("greedy", temp),
          make_logits_processors=lambda repetition_penalty: [repetition_penalty])
    h = HyMT(_ctx(hymt="mps"))
    h.load()
    assert h.available
    out = h.translate(["Good morning.", "See you soon."], "en", ["es", "ja"])
    assert out == {"es": "[Good morning.] [See you soon.]", "ja": "[Good morning.][See you soon.]"}
    assert "into Spanish" in seen[0][0] and "only output the translated result" in seen[0][0]
    assert seen[0][1] == 2 * 10 + 64


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
