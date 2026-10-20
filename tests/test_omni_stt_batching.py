#!/usr/bin/env python3
"""services/omni-stt's repetition guard and GPU micro-batcher, without models:
fake batch models stand in for Omnilingual and VoxLingua107.

    python3 tests/test_omni_stt_batching.py   (or python3 -m pytest tests/test_omni_stt_batching.py)

Needs numpy and scipy (server.py's imports), nothing else.
"""
import asyncio
import contextlib
import io
import json
import os
import sys
import threading
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "omni-stt"))
import server as stt  # noqa: E402
import numpy as np  # noqa: E402

LID = {"en", "fr", "ht", "km", "lo", "es"}


# ---------------------------------------------------------------- repetition guard

def test_guard_leaves_speech_alone():
    s = "Bondye beni nou, e li toujou la avèk nou nan tout sa nou fè."
    assert stt.repetition_guard(s, 4.0, 30, 6) == (s, None)
    assert stt.repetition_guard("", 0.5, 30, 6) == ("", None)
    assert stt.repetition_guard("wi", 0.3, 30, 6) == ("wi", None)          # a lone word on a short clip
    # Sung or said a few times is speech, not a loop.
    s = "alelouya alelouya alelouya alelouya"
    assert stt.repetition_guard(s, 3.0, 30, 6) == (s, None)
    assert stt.repetition_guard("mèsi mèsi", 1.0, 30, 6) == ("mèsi mèsi", None)
    assert stt.repetition_guard("1000000 dola", 2.0, 30, 6) == ("1000000 dola", None)   # one character is no unit


def test_guard_drops_a_looping_fragment():
    # The failure seen on the fine-tuned card: under a second, ~200 characters.
    s = " ".join(["ba"] * 70)
    assert stt.repetition_guard(s, 0.8, 30, 6) == ("", "dropped")
    s = "ka" * 90                                                        # no spaces
    assert stt.repetition_guard(s, 0.6, 30, 6) == ("", "dropped")
    assert stt.repetition_guard("a" * 40, 0.5, 30, 6) == ("", "dropped")


def test_guard_truncates_a_loop_after_real_words():
    words = "nou pral li yon pasaj nan Bib la"
    s = words + " " + " ".join(["ansanm"] * 30)
    out, action = stt.repetition_guard(s, 3.0, 30, 6)
    assert (out, action) == (words + " ansanm", "truncated")
    # A loop of a two-word unit.
    s = "mwen di " + "bonjou tout " * 12
    assert stt.repetition_guard(s.strip(), 6.0, 30, 6) == ("mwen di bonjou tout", "truncated")
    # A loop short enough to pass the rate is still cut.
    s = "wi " + "la " * 8
    assert stt.repetition_guard(s.strip(), 5.0, 30, 6) == ("wi la", "truncated")


def test_guard_rate_without_a_loop():
    # 120 characters of varied text on half a second: an invention, dropped whole.
    s = "Tanpri chita epi louvri liv chan nou yo nan paj karant, apre sa n ap chante ansanm avèk koral la jodi a."
    assert stt.repetition_guard(s, 0.5, 30, 6) == ("", "dropped")
    assert stt.repetition_guard(s, 5.0, 30, 6) == (s, None)
    # The thresholds are the caller's (the env vars' defaults otherwise).
    assert stt.repetition_guard(s, 5.0, 10, 6) == ("", "dropped")
    assert stt.repetition_guard(" ".join(["ba"] * 70), 30.0, 0, 0) == (" ".join(["ba"] * 70), None)  # both off


def test_guard_logs_lengths_only():
    class Omni:
        def transcribe_batch(self, items):
            return ["sekrè " * 40, "Bonjou tout moun."]
    m = stt.Models.__new__(stt.Models)
    m.omni = Omni()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = m.transcribe_batch([(np.zeros(8000, np.float32), "ht"), (np.zeros(32000, np.float32), "ht")])
    assert out == ["", "Bonjou tout moun."]
    log = buf.getvalue()
    assert "repetition guard: dropped 240 -> 0 chars (0.5s of audio)" in log, log
    assert "sekrè" not in log and "Bonjou" not in log


# ---------------------------------------------------------------- batcher

class BatchModels:
    """identify_batch / transcribe_batch that record each call's size. Language
    by the audio's level (< 0.45 ht, else en); text says whose audio it was."""

    def __init__(self, delay=0.0, gate=None, fail_level=None):
        self.calls = []
        self.delay = delay
        self.gate = gate
        self.fail_level = fail_level
        self.lock = threading.Lock()
        self.entered = threading.Event()     # set once a transcribe_batch call has begun

    def identify_batch(self, items):
        with self.lock:
            self.calls.append(("lid", len(items)))
        return [("ht" if p.max() < 0.45 else "en", 0.9) if len(l) > 1 else (l[0], 1.0) for p, l in items]

    def transcribe_batch(self, items):
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(5)
        with self.lock:
            self.calls.append(("asr", len(items)))
        time.sleep(self.delay)
        out = []
        for p, lang in items:
            if self.fail_level is not None and abs(p.max() - self.fail_level) < 1e-6:
                raise ValueError("bad utterance")
            out.append(f"{lang} {p.max():.3f} {len(p)}")
        return out


def _utt(level, n=16000):
    return np.full(n, level, dtype=np.float32)


def test_batcher_routes_every_result_to_its_caller():
    gate = threading.Event()
    models = BatchModels(gate=gate)
    b = stt.Batcher(models, max_batch=8, wait_ms=0)

    async def run():
        # The worker takes the first item alone and blocks on the gate. Only
        # once it is inside that call do the other eleven queue (submitting
        # them at once let the worker wake early and take a few, so whether a
        # batch of 8 formed depended on thread timing); then they go 8 and 3.
        futs = [b.submit("asr", _utt(0.01, 16000), "ht")]
        assert await asyncio.to_thread(models.entered.wait, 5)
        futs += [b.submit("asr", _utt(0.01 * (i + 1), 16000 + i), "ht") for i in range(1, 12)]
        gate.set()
        return await asyncio.gather(*futs)
    got = asyncio.run(run())
    assert got == [f"ht {0.01 * (i + 1):.3f} {16000 + i}" for i in range(12)], got
    sizes = [n for kind, n in models.calls if kind == "asr"]
    assert sizes == [1, 8, 3], sizes


def test_batcher_runs_each_kind_in_one_call():
    gate = threading.Event()
    models = BatchModels(gate=gate)
    b = stt.Batcher(models, max_batch=8, wait_ms=0)

    async def run():
        first = b.submit("asr", _utt(0.2), "ht")           # holds the worker
        await asyncio.sleep(0.05)
        lids = [b.submit("lid", _utt(0.3 if i % 2 else 0.6), ["ht", "en"]) for i in range(4)]
        asrs = [b.submit("asr", _utt(0.1 * (i + 1)), "en") for i in range(3)]
        gate.set()
        return await first, await asyncio.gather(*lids), await asyncio.gather(*asrs)
    first, lids, asrs = asyncio.run(run())
    assert first == "ht 0.200 16000"
    assert lids == [("en", 0.9), ("ht", 0.9), ("en", 0.9), ("ht", 0.9)]
    assert asrs == ["en 0.100 16000", "en 0.200 16000", "en 0.300 16000"]
    # Language ID before recognition, each kind in one call.
    assert models.calls == [("asr", 1), ("lid", 4), ("asr", 3)], models.calls


def test_batcher_one_bad_utterance_fails_alone():
    gate = threading.Event()
    models = BatchModels(gate=gate, fail_level=0.5)
    b = stt.Batcher(models, max_batch=8, wait_ms=0)

    async def run():
        first = b.submit("asr", _utt(0.1), "ht")
        await asyncio.sleep(0.05)
        futs = [b.submit("asr", _utt(level), "ht") for level in (0.2, 0.5, 0.3)]
        gate.set()
        await first
        return await asyncio.gather(*futs, return_exceptions=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        got = asyncio.run(run())
    assert got[0] == "ht 0.200 16000" and got[2] == "ht 0.300 16000"
    assert isinstance(got[1], ValueError)
    assert "retrying one by one" in buf.getvalue()


def test_batcher_skips_jobs_whose_client_left():
    gate = threading.Event()
    models = BatchModels(gate=gate)
    b = stt.Batcher(models, max_batch=8, wait_ms=0)

    async def run():
        first = b.submit("asr", _utt(0.1), "ht")             # holds the worker
        assert await asyncio.to_thread(models.entered.wait, 5)
        futs = [b.submit("asr", _utt(level), "ht") for level in (0.2, 0.3, 0.4)]
        lid = b.submit("lid", _utt(0.3), ["ht", "en"])
        futs[1].cancel()                                     # that client left
        lid.cancel()
        gate.set()
        await first
        return await asyncio.gather(futs[0], futs[2])
    assert asyncio.run(run()) == ["ht 0.200 16000", "ht 0.400 16000"]
    # The cancelled ones never reached a model: no language ID call at all.
    assert models.calls == [("asr", 1), ("asr", 2)], models.calls


def test_batcher_retry_skips_jobs_whose_client_left():
    gate = threading.Event()

    class FailOnce(BatchModels):
        def transcribe_batch(self, items):
            if len(items) > 1:
                self.entered.set()
                gate.wait(5)
                with self.lock:
                    self.calls.append(("asr-failed", len(items)))
                raise RuntimeError("batch failed")
            return super().transcribe_batch(items)
    models = FailOnce()
    # Three streams and a long wait: the worker takes all three at once.
    b = stt.Batcher(models, max_batch=8, wait_ms=5000)
    for _ in range(3):
        b.opened()

    async def run():
        futs = [b.submit("asr", _utt(level), "ht") for level in (0.2, 0.3, 0.4)]
        assert await asyncio.to_thread(models.entered.wait, 5)
        futs[0].cancel()                                     # left while the batch ran
        gate.set()
        return await asyncio.gather(futs[1], futs[2])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        got = asyncio.run(run())
    assert got == ["ht 0.300 16000", "ht 0.400 16000"]
    # The batch of three failed; only the two still wanted were retried.
    assert models.calls == [("asr-failed", 3), ("asr", 1), ("asr", 1)], models.calls


def test_batcher_waits_only_for_streams_that_exist():
    models = BatchModels()
    b = stt.Batcher(models, max_batch=8, wait_ms=300)

    async def one():
        t0 = time.monotonic()
        await b.submit("asr", _utt(0.1), "ht")
        return time.monotonic() - t0
    b.opened()
    assert asyncio.run(one()) < 0.2          # one stream: nothing to wait for
    b.opened()
    b.opened()

    async def three():
        t0 = time.monotonic()
        futs = [b.submit("asr", _utt(0.1 * (i + 1)), "ht") for i in range(3)]
        await asyncio.gather(*futs)
        return time.monotonic() - t0
    assert asyncio.run(three()) < 0.2        # all three streams' items are in: go
    assert models.calls[-1] == ("asr", 3), models.calls

    async def late():
        t0 = time.monotonic()
        a = b.submit("asr", _utt(0.1), "ht")
        await asyncio.sleep(0.05)
        c = b.submit("asr", _utt(0.2), "ht")      # joins the first within the wait
        await asyncio.gather(a, c)
        return time.monotonic() - t0
    took = asyncio.run(late())
    assert models.calls[-1] == ("asr", 2), models.calls
    assert 0.25 < took < 1.0, took            # waited (3 streams, 2 items) until the deadline


def test_pick_group_keeps_lengths_together():
    s = 16000  # samples a second
    # Similar lengths go together, up to the cap.
    assert stt.pick_group([10 * s, 9 * s, 12 * s, 11 * s], 8, gen=0.3) == [0, 1, 2, 3]
    assert stt.pick_group([10 * s] * 12, 8, gen=0.3) == list(range(8))
    # A short one beside long ones would add more decoder steps (its missing
    # prompt, one step a frame) than it costs alone: it waits for the next batch.
    assert stt.pick_group([10 * s, 2 * s, 9 * s, 15 * s], 8, gen=0.3) == [0, 2]
    # The oldest always goes, even alone.
    assert stt.pick_group([1 * s, 14 * s, 13 * s], 8, gen=0.3) == [0]
    assert stt.pick_group([], 8) == []
    # Short clips differ by few frames: they batch.
    assert stt.pick_group([int(0.8 * s), 1 * s, int(1.1 * s)], 8, gen=0.3) == [0, 1, 2]


def test_batcher_groups_by_length_and_serves_the_rest_next():
    gate = threading.Event()
    models = BatchModels(gate=gate)
    b = stt.Batcher(models, max_batch=8, wait_ms=0)

    async def run():
        first = b.submit("asr", _utt(0.01, 16000), "ht")         # holds the worker
        await asyncio.sleep(0.05)
        lens = [160000, 32000, 150000, 30000, 170000, 34000]     # 10 s, 2 s, ... mixed
        futs = [b.submit("asr", _utt(0.1 * (i + 1), n), "ht") for i, n in enumerate(lens)]
        gate.set()
        await first
        return lens, await asyncio.gather(*futs)
    lens, got = asyncio.run(run())
    assert got == [f"ht {0.1 * (i + 1):.3f} {n}" for i, n in enumerate(lens)], got
    assert [n for _, n in models.calls] == [1, 3, 3], models.calls   # long ones, then short ones


def test_batcher_falls_back_to_one_at_a_time_models():
    class Plain:
        def identify(self, pcm, langs):
            return langs[-1], 0.5

        def transcribe(self, pcm, lang):
            return f"{lang}:{len(pcm)}"
    b = stt.Batcher(Plain(), max_batch=4, wait_ms=0)

    async def run():
        return await b.submit("lid", _utt(0.1), ["ht", "en"]), await b.submit("asr", _utt(0.1, 320), "ht")
    assert asyncio.run(run()) == (("en", 0.5), "ht:320")


# ---------------------------------------------------------------- the models' batch methods

def test_identify_batch_pads_and_passes_lengths():
    try:
        import torch
    except ImportError:  # requirements-test.txt installs it; a bare numpy env skips this one
        print("skip: no torch")
        return

    class Lid:
        def __init__(self):
            self.calls = []

        def classify_batch(self, wavs, wav_lens=None):
            self.calls.append((tuple(wavs.shape), None if wav_lens is None else [round(float(x), 3) for x in wav_lens]))
            # Row r: log-probs favouring label (r % 2): ht (0) or en (1).
            n = wavs.shape[0]
            probs = torch.full((n, 1, 3), -5.0)
            for r in range(n):
                probs[r, 0, r % 2] = -0.1
            return (probs,)
    m = stt.Models.__new__(stt.Models)
    m.lid = Lid()
    m.lid_index = {"ht": 0, "en": 1, "fr": 2}
    items = [(_utt(0.1, 16000), ["ht", "en"]), (_utt(0.1, 8000), ["ht"]),
             (_utt(0.1, 8000), ["ht", "en"]), (_utt(0.1, 4000), ["fr", "en"])]
    out = m.identify_batch(items)
    assert m.lid.calls == [((3, 16000), [1.0, 0.5, 0.25])], m.lid.calls      # the one-language item skipped
    assert out[1] == ("ht", 1.0)
    assert out[0][0] == "ht" and out[2][0] == "en" and out[3][0] == "fr"     # rows 0, 1, 2 -> ht, en, ht(not allowed) -> fr
    assert all(0.5 < c <= 1.0 for _, c in (out[0], out[2]))
    # A lone item takes identify()'s exact path (no wav_lens).
    m.lid.calls.clear()
    assert m.identify_batch([(_utt(0.1, 8000), ["ht", "en"])])[0][0] == "ht"
    assert m.lid.calls == [((1, 8000), None)]


def test_engine_transcribe_batch():
    sys.path.insert(0, os.path.join(ROOT, "server"))
    from engines.base import Context
    from engines.omnilingual import Omnilingual, wav_bytes

    class Pipe:
        def __init__(self):
            self.calls = []

        def transcribe(self, inp, lang=None, batch_size=2):
            self.calls.append((len(inp), list(lang), batch_size))
            out = []
            for b in inp:
                with wave.open(io.BytesIO(b)) as w:
                    assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
                    out.append(f" {w.getnframes()} " if w.getnframes() != 1600 else "[music]")
            return out
    ctx = Context(device="cpu", models={"omnilingual": {"card": "x"}}, tables={"OMNI_LANGS": stt.OMNI_CODES},
                  options={"omni": True})
    eng = Omnilingual(ctx)
    eng.omni = Pipe()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = eng.transcribe_batch([(_utt(0.1, 16000), "ht"), (_utt(0.1, 1600), "en"), (_utt(0.1, 4000), "km")])
    assert out == ["16000", "", "4000"], out                    # stripped; the annotation filtered
    assert eng.omni.calls == [(3, ["hat_Latn", "eng_Latn", "khm_Khmr"], 3)]
    assert eng.transcribe_batch([]) == []
    # The bytes are the 16-bit wav transcribe() writes to its temp file.
    b = wav_bytes(np.array([0.5, -2.0, 1.0], np.float32))
    with wave.open(io.BytesIO(b)) as w:
        assert np.frombuffer(w.readframes(3), "<i2").tolist() == [16383, -32767, 32767]


def test_identity_reorder_is_skipped():
    try:
        import torch
        from fairseq2.nn import IncrementalStateBag
    except ImportError:  # fairseq2 comes with omnilingual-asr (the image), not requirements-test.txt
        print("skip: no fairseq2")
        return
    calls = []

    class State:
        def reorder(self, order):
            calls.append(order.tolist())
    bag = IncrementalStateBag(max_num_steps=10)
    bag._module_states[object()] = State()
    stt.skip_identity_reorder()
    stt.skip_identity_reorder()                       # once is enough; twice is harmless
    bag.reorder(torch.arange(4))
    bag.reorder(torch.tensor([1, 0, 2, 3]))
    bag.reorder(torch.tensor([0, 0, 2, 3]))
    assert calls == [[1, 0, 2, 3], [0, 0, 2, 3]], calls


def _tiny_llm(vocab=24, dim=32, max_len=1200, seed=0, dtype=None):
    """A random 2-layer Omnilingual-style LLaMA decoder and the parts of
    Wav2Vec2LlamaModel the beam search touches."""
    import torch
    from types import SimpleNamespace
    from fairseq2.models.llama.config import LLaMAConfig
    from fairseq2.nn import Linear, StandardEmbedding
    from omnilingual_asr.models.wav2vec2_llama.factory import OmnilingualASRLLamaFactory
    torch.manual_seed(seed)
    cfg = LLaMAConfig(model_dim=dim, max_seq_len=max_len, vocab_size=vocab, pad_idx=1, num_layers=2,
                      num_attn_heads=4, num_key_value_heads=2, ffn_inner_dim=64, ffn_inner_dim_multiple_of=8)
    dec = OmnilingualASRLLamaFactory(cfg).create_decoder()
    proj = Linear(dim, vocab, bias=False)
    emb = StandardEmbedding(num_embeddings=vocab + 1, embed_dim=dim)
    for m in (dec, proj, emb):
        m.to(dtype=dtype or torch.float32).eval()
    with torch.no_grad():
        proj.weight[2] *= 1.6            # eos a little likelier, so rows end at different steps

    class M(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.llama_decoder, self.final_proj, self.text_frontend = dec, proj, emb
            self.max_generation_length = max_len
            self.model_dim = dim
            self.target_vocab_info = SimpleNamespace(pad_idx=1, eos_idx=2, bos_idx=0)

        def embed_text(self, seqs, dtype):
            return self.text_frontend(seqs).to(dtype)
    return M()


def test_aligned_generate_matches_one_at_a_time():
    try:
        import torch
        import omni_batch
        from fairseq2.nn import BatchLayout
        from omnilingual_asr.models.wav2vec2_llama.beamsearch import Wav2Vec2LlamaBeamSearchSeq2SeqGenerator
        from omnilingual_asr.models.wav2vec2_llama.config import Wav2Vec2LlamaBeamSearchConfig
    except ImportError:  # omnilingual-asr is in the image, not requirements-test.txt
        print("skip: no omnilingual_asr")
        return
    model = _tiny_llm()
    assert omni_batch.install(model) == 2 and omni_batch.install(model) == 2
    config = Wav2Vec2LlamaBeamSearchConfig(nbest=1, length_norm=False)
    gen = Wav2Vec2LlamaBeamSearchSeq2SeqGenerator(model=model, config=config)
    torch.manual_seed(1)
    lens = [37, 5, 120, 64, 64, 9, 251]          # prompts (audio frames + lang + BOS) of mixed length
    ctx = torch.zeros(len(lens), max(lens), 32)
    for i, n in enumerate(lens):
        ctx[i, :n] = torch.randn(n, 32)
        ctx[i, n - 1] = model.embed_text(torch.tensor([[0]]), torch.float32)[0, 0]   # BOS last
    with torch.inference_mode():
        alone = []
        for i, n in enumerate(lens):
            one = ctx[i:i + 1, :n]
            try:
                toks, lay = gen.generate_hypotheses(one, BatchLayout.of(one, [n]))
                alone.append(toks[0, :lay.seq_lens[0]].tolist())
            except ValueError:  # EOS first: the library cannot build an empty layout; here it is []
                alone.append([])
        together = omni_batch.aligned_generate(model, config, ctx, lens)
    assert together == alone, (together, alone)
    assert len({len(t) for t in alone}) > 2          # rows really ended at different steps
    # Equal prompts (no padding, no mask) give the same rows too.
    with torch.inference_mode():
        same = omni_batch.aligned_generate(model, config, ctx[3:5, :64], [64, 64])
    assert same == [alone[3], alone[4]]
    # Outside aligned_generate the wrapped attention is the library's own.
    with torch.inference_mode():
        one = ctx[2:3, :lens[2]]
        toks, lay = gen.generate_hypotheses(one, BatchLayout.of(one, [lens[2]]))
    assert toks[0, :lay.seq_lens[0]].tolist() == alone[2]


def test_key_mask_sdpa_masks_padding():
    try:
        import torch
        import omni_batch
    except ImportError:
        print("skip: no torch")
        return

    class Inner(torch.nn.Module):
        def forward(self, *a, **k):
            return "inner", None
    w = omni_batch.KeyMaskSDPA(Inner())
    q = torch.randn(2, 1, 2, 4)
    k = torch.randn(2, 5, 2, 4)
    v = torch.randn(2, 5, 2, 4)
    assert w(q, None, k, None, v, None)[0] == "inner"            # no mask set: the library's path
    mask = torch.tensor([[False, False, True, True, True], [True] * 5])
    tok = omni_batch.KEY_MASK.set(mask)
    try:
        v2 = v.clone()
        v2[0, :2] = 1e6                                          # padding values must not leak
        a, _ = w(q, None, k, None, v2, None)
    finally:
        omni_batch.KEY_MASK.reset(tok)
    ref = torch.nn.functional.scaled_dot_product_attention(
        q[:1].transpose(1, 2), k[:1, 2:].transpose(1, 2), v[:1, 2:].transpose(1, 2)).transpose(1, 2)
    assert torch.allclose(a[:1], ref, atol=1e-5)


# ---------------------------------------------------------------- the protocol, batched

def _pcm(seconds, level, rate=16000):
    return (np.full(int(seconds * rate), level) * 32767).astype("<i2").tobytes()


def _speech(level):
    audio = _pcm(0.5, 0.0) + _pcm(2.0, level) + _pcm(1.2, 0.0)
    step = 3200
    return [audio[i:i + step] for i in range(0, len(audio), step)]


class FakeWS:
    def __init__(self, path, messages):
        self.request = type("R", (), {"path": path, "headers": {}})()
        self.messages = list(messages)
        self.sent = []
        self.done = asyncio.Event()

    async def send(self, data):
        self.sent.append(json.loads(data))
        if self.sent[-1]["type"] == "flushed":
            self.done.set()

    async def close(self, code=1000, reason=""):
        self.done.set()

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self.messages:
            yield m
            await asyncio.sleep(0)
        await asyncio.wait_for(self.done.wait(), 10)


class ProtoModels(BatchModels):
    serve = {"listen"}
    voices = None

    def __init__(self):
        super().__init__(delay=0.02)
        self.lid_index = {c: i for i, c in enumerate(sorted(LID))}

    def new_vad(self):
        return object()


def test_many_streams_batched_and_unmixed():
    import audio_in
    audio_in.vad_block = lambda vad, block: 1.0 if np.abs(block).max() > 0.05 else 0.0
    models = ProtoModels()
    flush = json.dumps({"type": "flush"})
    levels = [0.11, 0.62, 0.23, 0.74, 0.35, 0.86, 0.17, 0.98]
    wss = []
    for i, lv in enumerate(levels):
        langs = "ht,en" if i % 3 else "ht"
        wss.append(FakeWS(f"/listen?langs={langs}", _speech(lv) + _speech(lv + 0.01) + [flush]))

    async def all_at_once():
        await asyncio.gather(*(stt.handle(ws, models) for ws in wss))
    asyncio.run(all_at_once())
    for i, (ws, lv) in enumerate(zip(wss, levels)):
        tx = [m for m in ws.sent if m["type"] == "inputTranscript"]
        want_lang = "ht" if i % 3 == 0 or lv < 0.45 else "en"
        assert [t["text"].split()[:2] for t in tx] == [[want_lang, f"{lv:.3f}"], [want_lang, f"{lv + 0.01:.3f}"]], (i, tx)
        assert [m["type"] for m in ws.sent][-1] == "flushed"
    asr = [n for kind, n in models.calls if kind == "asr"]
    assert sum(asr) == 16 and max(asr) > 1, models.calls       # batched, and nothing lost
    assert stt.batcher_for(models).streams == 0                # every stream let go


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
