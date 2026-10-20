"""Batched Omnilingual decoding with every utterance's prompt aligned at the end.

omnilingual-asr 0.1.0's own batched path (ASRInferencePipeline.transcribe with
batch_size > 1) right-pads the decoder prompts (audio frames, language token,
BOS), prefills only the shortest one, and then feeds the rest of every longer
prompt through the decoder ONE POSITION PER STEP, each as costly as generating a
token. A 2 s and a 12 s utterance in one batch cost ~500 extra decoder steps;
on the L4 that made mixed-length batches slower than decoding one at a time
(omni-stt-00018-raw, 2026-10-20).

Here the prompts are LEFT-padded instead: every row's prompt ends at the same
position, one prefill covers all of them, and generation starts together. The
padding is masked out of every self-attention call (KeyMaskSDPA). RoPE scores
depend only on the distance between a query and a key, so shifting a row right
by its padding changes nothing it attends to: each row decodes as it would
alone (up to float rounding in the batched kernels). The loop is the library's
for nbest = 1 (greedy, which is what the pipeline's default beam search config
is): the same end-of-sequence handling, the same compression-ratio stop every
250 positions (counted per row from its own prompt, as a lone decode counts),
the same token filter.

Used by services/omni-stt (server.py Models.transcribe_batch); anything this
does not cover (a CTC card, a zero-shot card, nbest > 1, length_norm) goes
through the library's own batched call instead.
"""
import contextvars
import zlib

import numpy as np
import torch
from torch.nn.functional import scaled_dot_product_attention

# (N, S_kv) bool, True = a real key, while an aligned decode runs.
KEY_MASK = contextvars.ContextVar("omni_batch_key_mask", default=None)


class KeyMaskSDPA(torch.nn.Module):
    """Wraps a decoder layer's SDPA: passes through unless KEY_MASK is set; then
    attends causally (queries are the last S positions of the S_kv keys) over
    the real keys only. A padding query attends to itself alone, so it stays
    finite (its output is never used, and its key is masked from real rows)."""

    def __init__(self, inner):
        super().__init__()
        self.inner = inner

    def forward(self, q, q_layout, k, k_layout, v, bias_cache, *, needs_weights=False):
        mask = KEY_MASK.get()
        if mask is None or needs_weights:
            return self.inner(q, q_layout, k, k_layout, v, bias_cache, needs_weights=needs_weights)
        s, s_kv = q.size(1), k.size(1)
        k_pos = torch.arange(s_kv, device=q.device)
        q_pos = k_pos[s_kv - s:]
        causal = k_pos[None, :] <= q_pos[:, None]                     # (S, S_kv)
        own = k_pos[None, :] == q_pos[:, None]
        allowed = causal[None] & (mask[:, None, :s_kv] | own[None])   # (N, S, S_kv)
        attns = scaled_dot_product_attention(
            q.transpose(-2, -3), k.transpose(-2, -3), v.transpose(-2, -3), attn_mask=allowed[:, None])
        return attns.transpose(-2, -3), None


def install(model):
    """Wrap the LLM decoder's attention once (a no-op outside aligned_generate)."""
    from fairseq2.models.transformer.sdpa.base import SDPA
    n = 0
    for m in model.llama_decoder.modules():
        sdpa = getattr(m, "sdpa", None)
        if isinstance(sdpa, SDPA) and not isinstance(sdpa, KeyMaskSDPA):
            m.sdpa = KeyMaskSDPA(sdpa)
            n += 1
        elif isinstance(sdpa, KeyMaskSDPA):
            n += 1
    return n


def supported(pipeline):
    """Whether aligned_generate reproduces this pipeline's decoding."""
    try:
        from omnilingual_asr.models.wav2vec2_llama.config import ModelType
        from omnilingual_asr.models.wav2vec2_llama.model import Wav2Vec2LlamaModel
    except ImportError:
        return False
    model = getattr(pipeline, "model", None)
    gen = getattr(pipeline, "beam_search_generator", None)
    return (isinstance(model, Wav2Vec2LlamaModel) and gen is not None
            and model.model_type != ModelType.ZERO_SHOT
            and gen.config.nbest == 1 and not gen.config.length_norm)


def _compression_ratio(tokens):
    # As the library computes it: zlib over numpy's printed form of the window.
    text = np.array_str(tokens).replace("\n", "").encode("utf-8")
    return len(text) / len(zlib.compress(text))


@torch.no_grad()
def aligned_generate(model, config, ctx, ctx_lens):
    """ctx: (B, L, D) decoder prompts, right-padded, real lengths ctx_lens (each
    ending with BOS). -> a list of B token lists (no pad/BOS/EOS), as the
    library's generate_hypotheses would give each row decoded alone."""
    vocab = model.target_vocab_info
    pad, eos, bos = vocab.pad_idx, vocab.eos_idx, vocab.bos_idx
    window, threshold = config.compression_window, config.compression_threshold
    B, _, D = ctx.shape
    device, dtype = ctx.device, ctx.dtype
    lens = [int(x) for x in ctx_lens]
    L = max(lens)
    pads = [L - n for n in lens]
    max_len = model.max_generation_length

    # Left-align: row i's prompt occupies [pads[i], L).
    prompt = torch.zeros(B, L, D, device=device, dtype=dtype)
    for i, n in enumerate(lens):
        prompt[i, pads[i]:] = ctx[i, :n]
    steps = max_len - L + 4  # room for the mask; the loop stops long before
    real = torch.ones(B, L + steps, dtype=torch.bool, device=device)
    for i, p in enumerate(pads):
        real[i, :p] = False

    from fairseq2.nn import BatchLayout, IncrementalStateBag
    state_bag = IncrementalStateBag(max_num_steps=max_len)
    # Equal prompts need no mask: the library's own attention (and its fast
    # kernels) then runs unchanged.
    token = KEY_MASK.set(real if any(pads) else None)
    try:
        if L > 1:
            pre = prompt[:, : L - 1]
            model.llama_decoder(seqs=pre, seqs_layout=BatchLayout.of(pre), state_bag=state_bag)
            state_bag.increment_step_nr(L - 1)
        x = prompt[:, L - 1: L]            # every row's BOS
        out = []                           # per step: (B,) tokens
        done = torch.zeros(B, dtype=torch.bool, device=device)
        s = 0
        while True:
            dec = model.llama_decoder(seqs=x, seqs_layout=BatchLayout.of(x), state_bag=state_bag)
            state_bag.increment_step_nr(1)
            logits = model.final_proj(dec).squeeze(1)
            tok = torch.log_softmax(logits, dim=-1).argmax(dim=-1)
            tok = torch.where(done, torch.full_like(tok, eos), tok)
            out.append(tok)
            done = done | (tok == eos)
            # The library's stop: at positions t = (prompt length - 1) + s that
            # are multiples of 250, a row whose last `window` tokens compress too
            # well (a loop) ends; only once t > prompt length + window.
            for i in range(B):
                t = lens[i] - 1 + s
                if t % 250 == 0 and t > lens[i] + window and not bool(done[i]):
                    # out[k] is the token at position lens[i] - 1 + k; the
                    # window is positions [t - window, t), all generated ones
                    # (t > prompt length + window).
                    lo = t - window - (lens[i] - 1)
                    win = torch.stack(out[lo:s], dim=0)[:, i].to(torch.int).cpu().numpy()
                    if _compression_ratio(win) > threshold:
                        done[i] = True
            # The library's cap: a lone decode ends at position max_len - 4. The
            # shared cache here ends where the LONGEST prompt's row reaches it,
            # which cuts the others too: only past ~max_len - prompt tokens
            # (8192 - ~760 for 15 s of audio), which no utterance here reaches.
            for i in range(B):
                if lens[i] - 1 + s == max_len - 4:
                    done[i] = True
            if bool(done.all()) or L - 1 + s >= max_len - 4:
                break
            x = model.embed_text(tok.unsqueeze(1), dtype=dtype)
            s += 1
    finally:
        KEY_MASK.reset(token)
    toks = torch.stack(out, dim=1).tolist() if out else [[] for _ in range(B)]
    return [[t for t in row if t not in (pad, eos, bos)] for row in toks]


def transcribe(pipeline, wavs, langs):
    """The pipeline's transcribe(wavs, lang=langs, batch_size=len(wavs)), decoded
    with aligned_generate: same inputs, same batch building, same text decoder."""
    from fairseq2.data.data_pipeline import DataPipeline, read_sequence
    install(pipeline.model)
    builder = DataPipeline.zip([
        pipeline._build_audio_wavform_pipeline(wavs).and_return(),
        read_sequence(list(langs)).and_return(),
    ])
    items = list(builder.and_return())
    with torch.inference_mode():
        batch = pipeline._create_batch_simple(items)
        ctx, layout = pipeline.model(batch, return_decoder_inputs=True)
        rows = aligned_generate(pipeline.model, pipeline.beam_search_generator.config, ctx, layout.seq_lens)
        texts = [pipeline.token_decoder(torch.tensor(r, dtype=torch.int64, device=ctx.device)) for r in rows]
    if pipeline.device.type == "cuda":
        torch.cuda.empty_cache()
    return texts
