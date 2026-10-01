"""MADLAD-400 (Google, Apache 2.0): the translator for every language no other
translator takes, the fallback when another one fails or leaves a language out,
and the English pivot for sources another translator does not know.

translator = "madlad", and `madlad = "<tag>"` where MADLAD's target tag differs
from the language code (Tagalog is <2fil>). Always loaded.

Two decode paths, one prompt format (`<2xx> text`):
  --mt-ct2 DIR   a CTranslate2 int8 conversion (scripts/prepare-mt.sh; every
                 real deployment). Only the tokenizer comes from transformers.
  otherwise      the transformers T5 model named by --mt-model, in bfloat16 on
                 the GPU (t5-small in the CPU tests: a plumbing stand-in that
                 ignores the language tags and emits junk on purpose).
"""
import os

from engines import register
from engines.base import Translator
from engines.common import ct2_device, is_gpu, join_sentences

# Beam width for MT. Greedy decoding took a local trap on short courtesies:
# "Thank you." came out "Gracias por tu comentario." because after "Gracias"
# the token "por" scored fractionally above ".", and "tu comentario" is glued
# to it in MADLAD's web-scraped training data. Scored over the WHOLE sequence
# the model prefers "Muchas gracias." -- greedy just never got to compare.
# Measured on an L4-class GPU, batch of 9: 11ms/phrase greedy -> 15ms at
# beam 4, and beam 8 changed no output. It also stopped "Yes." doubling into
# "Si, si." A length penalty made no difference.
MT_BEAM = int(os.environ.get("LITHOS_MT_BEAM", 4))


@register
class Madlad(Translator):
    name = "madlad"
    title = "MADLAD-400"
    lang_key = str            # madlad = "<tag>": MADLAD's target tag, when it differs
    licence = "Apache-2.0"

    @classmethod
    def enabled(cls, ctx):
        return True   # the fallback translator: always there

    def __init__(self, ctx):
        super().__init__(ctx)
        # MADLAD's target tag per language, where it differs from the code (tl -> fil).
        self.tags = dict(ctx.tables.get("LANG_TO_MADLAD", {}))
        self.ct2 = None
        self.mt = None

    def tag(self, lang):
        return self.tags.get(lang, lang)

    def load(self):
        """The tokenizer, then CTranslate2 or the transformers model."""
        from transformers import T5Tokenizer
        o = self.ctx.options
        mt_ct2 = o.get("mt_ct2")
        mt_model = o.get("mt_model") or "google/madlad400-3b-mt"
        device = self.device
        # MADLAD's SentencePiece vocabulary is the same at every size; prepare-mt.sh
        # copies it next to the converted model so no hub download is needed.
        tok_src = mt_ct2 if mt_ct2 and os.path.exists(os.path.join(mt_ct2, "spiece.model")) else mt_model
        print(f"[stack] loading MADLAD tokenizer from {tok_src}…")
        self.mt_tok = T5Tokenizer.from_pretrained(tok_src)
        # A converted CTranslate2 copy replaces the HF decode path; the
        # tokenizer is still the HF one, so the prompt format is unchanged.
        #   ct2-transformers-converter --model google/madlad400-3b-mt \
        #     --output_dir /workspace/madlad-ct2 --quantization int8
        if mt_ct2:
            import ctranslate2
            kind, index = ct2_device(device)
            self.ct2 = ctranslate2.Translator(
                mt_ct2, device=kind, device_index=index,
                compute_type="int8_float16" if kind == "cuda" else "int8")
            print(f"[stack] MT via CTranslate2: {mt_ct2}", flush=True)
        # Only when CTranslate2 is NOT carrying MT. The decode goes through
        # CTranslate2 whenever it exists, so with --mt-ct2 set this bf16 copy
        # was never once used -- it just sat in VRAM. Measured on the deployed
        # config: ~6GB of a 20.1GB footprint, about 30%, for a model on no code
        # path. run.sh passes --mt-ct2 whenever the converted model exists,
        # which is every real deployment.
        #
        # bfloat16 (T5 was trained in bf16; fp16 risks overflow) — but the
        # "ue ue ue" garbage first blamed on fp16 was actually a transformers
        # 5.x regression in T5 weight loading, fixed by the pin in the
        # provisioners. Keep bf16 anyway; it is the safe dtype here.
        if self.ct2 is None:
            import torch
            from transformers import T5ForConditionalGeneration
            self.mt = T5ForConditionalGeneration.from_pretrained(
                mt_model,
                torch_dtype=torch.bfloat16 if is_gpu(device) else None,
            ).to(device).eval()
        else:
            print("[stack] MT is CTranslate2 only — bf16 copy not loaded", flush=True)
        self.available = True

    # ------------------------------------------------------------ the interface

    def translate(self, sentences, src, targets, text=None):
        """Sentence by sentence, still in ONE batch: given two sentences as one
        input, MADLAD dropped one of them for some languages (measured
        2026-09-26: uk kept only the first, ja only the second, of "Could you
        tell me where the train station is? I need to catch the 5 o'clock
        train to the airport."). One sentence goes in as the text it was heard."""
        if len(sentences) > 1:
            outs = self.generate([f"<2{self.tag(lg)}> {x}" for lg in targets for x in sentences])
            n = len(sentences)
            return {lg: join_sentences([o.strip() for o in outs[i * n:(i + 1) * n]], lg)
                    for i, lg in enumerate(targets)}
        whole = text if text is not None else sentences[0]
        return dict(zip(targets, self.generate([f"<2{self.tag(lg)}> {whole}" for lg in targets])))

    def translate_text(self, text, lang):
        """One text into one language, whole (the fallback for a language
        another translator did not return)."""
        return self.generate([f"<2{self.tag(lang)}> {text}"])[0]

    def to_english(self, sentences):
        """The English pivot, sentence by sentence (MADLAD's strongest direction)."""
        return [o.strip() for o in self.generate([f"<2en> {x}" for x in sentences])]

    # ------------------------------------------------------------ decoding

    def _translate_ct2(self, prompts, max_new):
        """MADLAD through CTranslate2 — the engine that makes faster-whisper
        fast, pointed at the T5 family. int8 on GPU, and MT is 60-75% of this
        pipeline's latency, so it is the only stage left where the money is."""
        srcs = [self.mt_tok.convert_ids_to_tokens(self.mt_tok.encode(pr)) for pr in prompts]
        res = self.ct2.translate_batch(srcs, max_decoding_length=max_new,
                                       beam_size=MT_BEAM, replace_unknowns=False)
        out = []
        for r in res:
            ids = self.mt_tok.convert_tokens_to_ids(r.hypotheses[0])
            out.append(self.mt_tok.decode(ids, skip_special_tokens=True))
        return out

    def generate(self, prompts):
        """MADLAD over a batch of prompts, one output per prompt."""
        import torch
        inp = self.mt_tok(prompts, return_tensors="pt", padding=True).to(self.device)
        # Bounded by the input: translation is roughly length-preserving, and a
        # flat 256 let a degenerate generation burn 12s before giving up.
        max_new = min(160, int(inp["input_ids"].shape[1] * 2) + 24)
        if self.ct2 is not None:
            return self._translate_ct2(prompts, max_new)
        with torch.inference_mode():
            out = self.mt.generate(**inp, max_new_tokens=max_new,
                                   num_beams=MT_BEAM)
        return [self.mt_tok.decode(o, skip_special_tokens=True) for o in out]
