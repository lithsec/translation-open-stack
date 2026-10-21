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

Context (?context=1, server/translation_context.py): Hy-MT2 is a chat-prompted
causal LM, so earlier text can go into the prompt where a tagged-sentence
model (MADLAD) has no room for it. prompt() puts the previous pieces, and the
previous translation into the target, BEFORE the instruction, each under a
line that says it is context only and must not be translated or repeated,
and the piece to translate last, under the stack's usual instruction, so the
answer is still that piece's translation alone. Each sentence of a piece gets
the same context (the pieces before it, not its own earlier sentences).
only_new() drops the one failure mode that can be told from the outside, an
answer that begins by repeating the previous translation. The output cap is
still set by the sentence, not the prompt. UNMEASURED: whether this helps
Hy-MT2 as it helped a cloud LLM (judge 2.15-2.21 -> 2.52-2.67 on short
pieces, eval/2026-10-continuous-ht) is not known until a GPU run compares the
two prompts; docs/dev/protocol.md says how.
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

# The stack's instruction (the model card's), unchanged since the first run.
INSTRUCTION = ("Translate the following text into {lang}. Note that you should only output "
               "the translated result without any additional explanation:\n\n{text}")
# Context goes ABOVE it. The piece to translate stays last, under the usual
# instruction, so the model's job reads the same as without context.
CONTEXT_PIECES = ("The text before this one, for context only. Do not translate it and do not "
                  "repeat it:\n\n{pieces}\n\n")
CONTEXT_TRANSLATION = ("How the text before this one was translated into {lang}, for context only. "
                       "Do not repeat it:\n\n{translation}\n\n")


def prompt(lang, text, context=None):
    """The user message for one (target language, sentence) pair. With no
    context it is exactly the prompt the stack has always sent."""
    body = INSTRUCTION.format(lang=HYMT_NAMES[lang], text=text)
    if not context:
        return body
    pieces = [p for p in (context.get("pieces") or []) if p]
    previous = (context.get("translations") or {}).get(lang)
    head = ""
    if pieces:
        head += CONTEXT_PIECES.format(pieces="\n".join(pieces))
    if previous:
        head += CONTEXT_TRANSLATION.format(lang=HYMT_NAMES[lang], translation=previous)
    return head + body


def only_new(answer, lang, context=None):
    """The answer without the previous translation, should the model have
    repeated it before (or instead of) translating the new piece. Exact
    prefix only: anything subtler is a guess about the model's output."""
    previous = ((context or {}).get("translations") or {}).get(lang)
    if previous and answer.startswith(previous):
        rest = answer[len(previous):].strip()
        return rest if rest else answer
    return answer


@register
class HyMT(Translator):
    name = "hymt"
    title = "Hy-MT2"
    languages = frozenset(HYMT_NAMES)
    licence = "Apache-2.0"
    takes_context = True      # a prompted LM: see prompt() and the module docstring

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
                                                     device_map=self.device).eval()
        self.hymt = (tok, model)
        self.available = True

    def translate(self, sentences, src, targets, text=None, context=None):
        """Hy-MT2 over every (language, sentence) pair in one left-padded batch;
        {lang: joined translation}, or {} on failure (MADLAD then serves).
        `context` (engines/base.py), when given, goes into each prompt as
        context only; the answer is still each sentence's own translation."""
        import torch
        try:
            tok, model = self.hymt
            pairs = [(lg, x) for lg in targets for x in sentences]
            prompts = [tok.apply_chat_template([{"role": "user", "content": prompt(lg, x, context)}],
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
            if context:
                texts = [only_new(t, lg, context) for (lg, _), t in zip(pairs, texts)]
            n = len(sentences)
            return {lg: join_sentences(texts[i * n:(i + 1) * n], lg) for i, lg in enumerate(targets)}
        except Exception as e:
            print(f"[stack] Hy-MT2 failed ({e}) — MADLAD instead", flush=True)
            return {}
