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
        return bool(ctx.options.get("hymt"))

    def __init__(self, ctx):
        super().__init__(ctx)
        self.hymt = None
        self._lock = threading.Lock()

    def supports(self, lang):
        return self.available and lang in HYMT_NAMES

    def supports_source(self, lang):
        return lang in HYMT_NAMES

    def load(self):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        path = self.ctx.options["hymt"]
        print(f"[stack] loading Hy-MT2 from {path}…", flush=True)
        tok = AutoTokenizer.from_pretrained(path, local_files_only=True)
        tok.padding_side = "left"
        model = AutoModelForCausalLM.from_pretrained(path, local_files_only=True,
                                                     device_map=self.ctx.device).eval()
        self.hymt = (tok, model)
        self.available = True

    def translate(self, sentences, src, targets, text=None):
        """Hy-MT2 over every (language, sentence) pair in one left-padded batch;
        {lang: joined translation}, or {} on failure (MADLAD then serves)."""
        import torch
        try:
            tok, model = self.hymt
            pairs = [(lg, x) for lg in targets for x in sentences]
            prompts = [tok.apply_chat_template([{"role": "user", "content":
                f"Translate the following text into {HYMT_NAMES[lg]}. Note that you should only output "
                f"the translated result without any additional explanation:\n\n{x}"}],
                tokenize=False, add_generation_prompt=True) for lg, x in pairs]
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
