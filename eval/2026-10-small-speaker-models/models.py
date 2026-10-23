# Speaker-embedding models for the small-model test: one interface, embed(list of float32 16 kHz
# arrays) -> L2-normalised (N, D). Front ends:
#   speechbrain ECAPA: its own Fbank + sentence mean norm (torch), then the embedding network
#   WeSpeaker ONNX:    Kaldi fbank 80 (torchaudio.compliance.kaldi, 25/10 ms, no dither) minus its
#                      time mean, as WeSpeaker's own runtime does
import os
import numpy as np
import onnxruntime as ort
import torch
import torchaudio

torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "8")))
M = os.environ.get("MDIR", "/w/models")

WESPEAKER = {   # name -> (HF repo, onnx file, licence)
    "campplus": ("Wespeaker/wespeaker-voxceleb-campplus", "voxceleb_CAM++.onnx", "Apache-2.0"),
    "ecapa512": ("Wespeaker/wespeaker-voxceleb-ecapa-tdnn512", "voxceleb_ECAPA512.onnx", "Apache-2.0"),
    "resnet34": ("Wespeaker/wespeaker-voxceleb-resnet34", "voxceleb_resnet34.onnx", "Apache-2.0"),
    "cn_resnet34": ("Wespeaker/wespeaker-cnceleb-resnet34", "cnceleb_resnet34.onnx", "Apache-2.0"),
}


def kaldi_fbank(x):
    w = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))[None] * 32768
    f = torchaudio.compliance.kaldi.fbank(w, num_mel_bins=80, frame_length=25, frame_shift=10, dither=0.0,
                                          energy_floor=0.0, sample_frequency=16000, window_type="hamming")
    return (f - f.mean(dim=0, keepdim=True)).numpy()


def _norm(e):
    return e / np.linalg.norm(e, axis=1, keepdims=True).clip(1e-9)


class OnnxModel:
    def __init__(self, path, front, threads=None):
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads or int(os.environ.get("ORT_THREADS", "8"))
        so.inter_op_num_threads = 1
        self.s = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
        self.inp = self.s.get_inputs()[0].name
        self.front = front

    def feats(self, xs):
        return [self.front(x) for x in xs]

    def embed_feats(self, F):
        # equal-length windows batch together; otherwise one by one
        if len({f.shape[0] for f in F}) == 1:
            out = []
            for i in range(0, len(F), 64):
                out.append(self.s.run(None, {self.inp: np.stack(F[i:i + 64]).astype(np.float32)})[0])
            return _norm(np.concatenate(out).reshape(len(F), -1))
        return _norm(np.concatenate([self.s.run(None, {self.inp: f[None].astype(np.float32)})[0].reshape(1, -1) for f in F]))

    def embed(self, xs):
        return self.embed_feats(self.feats(xs))


_sb = {}


def sb_ecapa():
    if "m" not in _sb:
        from speechbrain.inference.speaker import EncoderClassifier
        _sb["m"] = EncoderClassifier.from_hparams("speechbrain/spkrec-ecapa-voxceleb", savedir=f"{M}/sb_ecapa", run_opts={"device": "cpu"})
        _sb["m"].eval()
    return _sb["m"]


def sb_front(x):
    m = sb_ecapa()
    with torch.no_grad():
        w = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))[None]
        f = m.mods.compute_features(w)
        f = m.mods.mean_var_norm(f, torch.ones(1))
    return f[0].numpy()


class SBTorch:
    """The baseline exactly as in eval/2026-10-switch-detection: EncoderClassifier.encode_batch."""
    def embed(self, xs):
        m = sb_ecapa()
        out = []
        if len({len(x) for x in xs}) == 1:
            for i in range(0, len(xs), 64):
                with torch.no_grad():
                    out.append(m.encode_batch(torch.from_numpy(np.stack(xs[i:i + 64])).float()).squeeze(1).numpy())
        else:
            for x in xs:
                with torch.no_grad():
                    out.append(m.encode_batch(torch.from_numpy(x[None]).float()).squeeze(1).numpy())
        return _norm(np.concatenate(out))


def load(name, threads=None):
    """name: sb_ecapa_torch | sb_ecapa_fp32 | sb_ecapa_int8 | <wespeaker>_fp32 | <wespeaker>_int8"""
    if name == "sb_ecapa_torch":
        return SBTorch()
    base, prec = name.rsplit("_", 1)
    path = f"{M}/{base}_{prec}.onnx"
    return OnnxModel(path, sb_front if base == "sb_ecapa" else kaldi_fbank, threads)
