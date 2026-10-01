"""Hy-MT2 7B (Tencent, Apache 2.0), 4-bit NF4: the main translator, for the
36 languages it supports (translator = "hymt", the default). Loaded from the
LOCAL directory scripts/prepare-mt.sh builds from the pinned revision
(--hymt DIR); nothing is fetched at runtime.

Measured 2026-09-27, 24 sentences x 20 directions through this stack's own
ASR, graded blind: Hy-MT2 95% with 13 critical errors, MADLAD 7B 87% / 23,
MADLAD 3B 82% / 26, Gemini Live 79% / 38. Hy-MT2 does not support ht (10%,
answers partly in French).

A source it does not know (a Haitian Creole speaker) is pivoted through
English by MADLAD first; a target it fails on falls back to MADLAD.

On a Mac ([devices] hymt = "mps", profiles/mac.toml) the same model runs as
an MLX 4-bit build on the Apple GPU ([models.hymt_mlx], downloaded at start;
nothing to build), with the same prompt, greedy decoding and repetition penalty.
"""
import threading

from engines import register
from engines.base import Translator
from engines.common import join_sentences

# Code -> the language name its prompt uses (the model card's 36 plus English).
HYMT_NAMES = {
    "en": "English", "zh": "Chinese", "fr": "French", "pt": "Portuguese", "es": "Spanish", "ja": "Japanese",
    "tr": "Turkish", "ru": "Russian", "ar": "Arabic", "ko": "Korean", "th": "Thai", "it": "Italian",
    "de": "German", "vi": "Vietnamese", "ms": "Malay", "id": "Indonesian", "tl": "Filipino", "hi": "Hindi",
    "pl": "Polish", "cs": "Czech", "nl": "Dutch", "km": "Khmer", "my": "Burmese", "fa": "Persian",
    "gu": "Gujarati", "ur": "Urdu", "te": "Telugu", "mr": "Marathi", "he": "Hebrew", "bn": "Bengali",
    "ta": "Tamil", "uk": "Ukrainian", "bo": "Tibetan", "kk": "Kazakh", "mn": "Mongolian", "ug": "Uyghur",
    "yue": "Cantonese",
}


@register
class HyMT(Translator):
    name = "hymt"
    title = "Hy-MT2"
    languages = frozenset(HYMT_NAMES)
    licence = "Apache-2.0"

    @classmethod
    def enabled(cls, ctx):
        # The NF4 build (--hymt DIR, CUDA), or the MLX build on a Mac's GPU.
        return bool(ctx.options.get("hymt")) or ctx.device_for(cls.name) == "mps"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.hymt = None
        self.mlx = None
        self._lock = threading.Lock()

    def supports(self, lang):
        return self.available and lang in HYMT_NAMES

    def supports_source(self, lang):
        return lang in HYMT_NAMES

    def load(self):
        self.mlx = None
        if self.device == "mps":
            from engines.common import hf_snapshot, mlx_run
            m = self.ctx.models["hymt_mlx"]
            print(f"[stack] loading Hy-MT2 (MLX, Apple GPU) {m['repo']} @ {m['revision'][:12] or 'unpinned'}…",
                  flush=True)
            self.mlx = mlx_run(self._mlx_load, hf_snapshot(m["repo"], m["revision"] or None))
            self.available = True
            return
        from transformers import AutoModelForCausalLM, AutoTokenizer
        path = self.ctx.options["hymt"]
        print(f"[stack] loading Hy-MT2 from {path}…", flush=True)
        tok = AutoTokenizer.from_pretrained(path, local_files_only=True)
        tok.padding_side = "left"
        model = AutoModelForCausalLM.from_pretrained(path, local_files_only=True,
                                                     device_map=self.device).eval()
        self.hymt = (tok, model)
        self.available = True

    @staticmethod
    def _mlx_load(path):
        """(model, tokenizer) of an MLX build. The tokenizer is loaded as the
        class tencent/Hy-MT2-7B names (PreTrainedTokenizerFast): mlx-community's
        conversion was saved by transformers 5 and names "TokenizersBackend",
        which the pinned transformers 4.57 lacks. Same files, and checked to give
        the original's token ids and chat template (2026-09-30)."""
        import logging
        from pathlib import Path
        from transformers import PreTrainedTokenizerFast
        from mlx_lm.tokenizer_utils import TokenizerWrapper
        from mlx_lm.utils import load_model
        # Its "incorrect regex pattern" warning is a check for Mistral tokenizers.
        logging.getLogger("transformers.tokenization_utils_base").setLevel(logging.ERROR)
        tok = PreTrainedTokenizerFast.from_pretrained(path)
        model, _ = load_model(Path(path))
        return model, TokenizerWrapper(tok)

    @staticmethod
    def _prompt(lg, x):
        return [{"role": "user", "content":
                 f"Translate the following text into {HYMT_NAMES[lg]}. Note that you should only output "
                 f"the translated result without any additional explanation:\n\n{x}"}]

    def _translate_mlx(self, sentences, targets):
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_logits_processors, make_sampler
        model, tok = self.mlx
        n = len(sentences)
        out = {}
        with self._lock:
            for lg in targets:
                parts = []
                for x in sentences:
                    prompt = tok.apply_chat_template(self._prompt(lg, x), tokenize=False, add_generation_prompt=True)
                    longest = len(tok.encode(x, add_special_tokens=False))
                    parts.append(generate(model, tok, prompt, max_tokens=min(1024, longest * 10 + 64),
                                          sampler=make_sampler(temp=0.0),
                                          logits_processors=make_logits_processors(repetition_penalty=1.05),
                                          verbose=False).strip())
                out[lg] = join_sentences(parts[:n], lg)
        return out

    def translate(self, sentences, src, targets, text=None):
        """Hy-MT2 over every (language, sentence) pair in one left-padded batch;
        {lang: joined translation}, or {} on failure (MADLAD then serves)."""
        if self.mlx:
            from engines.common import mlx_run
            try:
                return mlx_run(self._translate_mlx, sentences, targets)
            except Exception as e:
                print(f"[stack] Hy-MT2 (MLX) failed ({e}) — MADLAD instead", flush=True)
                return {}
        import torch
        try:
            tok, model = self.hymt
            pairs = [(lg, x) for lg in targets for x in sentences]
            prompts = [tok.apply_chat_template(self._prompt(lg, x), tokenize=False, add_generation_prompt=True)
                       for lg, x in pairs]
            with self._lock, torch.inference_mode():
                inp = tok(prompts, return_tensors="pt", padding=True, add_special_tokens=False).to(model.device)
                inp.pop("token_type_ids", None)
                # Generous on purpose: the cap only matters for a runaway, but some
                # scripts need far more tokens than the English source: Khmer took
                # 136 for an 18-token sentence, and a 3x cap cut every one short.
                longest = max(len(tok.encode(x, add_special_tokens=False)) for x in sentences)
                gen = model.generate(**inp, max_new_tokens=min(1024, longest * 10 + 64), do_sample=False,
                                     repetition_penalty=1.05)
            texts = [tok.decode(g[inp["input_ids"].shape[1]:], skip_special_tokens=True).strip() for g in gen]
            n = len(sentences)
            return {lg: join_sentences(texts[i * n:(i + 1) * n], lg) for i, lg in enumerate(targets)}
        except Exception as e:
            print(f"[stack] Hy-MT2 failed ({e}) — MADLAD instead", flush=True)
            return {}
