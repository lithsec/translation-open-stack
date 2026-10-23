# Get every candidate as fp32 ONNX, quantise to int8 (dynamic, weights int8), and check
# int8 against fp32 (cosine of embeddings on 20 FLEURS clips) plus single-thread timing of one
# 1 s and one 1.5 s window (front end and network separately).
#   python export.py FLEURS_DIR OUT.json
import glob, json, os, sys, time, wave
import numpy as np
import torch
from huggingface_hub import hf_hub_download
from onnxruntime.quantization import quantize_dynamic, QuantType
import models as MD

FD, OUT = sys.argv[1:3]
M = MD.M
os.makedirs(M, exist_ok=True)
info = {}
# speechbrain ECAPA -> ONNX (the embedding network; the front end stays outside)
sb = MD.sb_ecapa()
net = sb.mods.embedding_model.eval()
dummy = torch.randn(1, 150, 80)
torch.onnx.export(net, (dummy,), f"{M}/sb_ecapa_fp32.onnx", input_names=["feats"], output_names=["embs"],
                  dynamic_axes={"feats": {0: "B", 1: "T"}, "embs": {0: "B"}}, opset_version=17)
info["sb_ecapa"] = {"repo": "speechbrain/spkrec-ecapa-voxceleb", "licence": "Apache-2.0", "train": "VoxCeleb1+2"}
for name, (repo, fn, lic) in MD.WESPEAKER.items():
    p = hf_hub_download(repo, fn, cache_dir=f"{M}/hf")
    os.system(f"cp '{p}' {M}/{name}_fp32.onnx")
    info[name] = {"repo": repo, "licence": lic, "train": "CN-Celeb1+2" if name.startswith("cn_") else "VoxCeleb2 dev"}
for name in info:
    src, dst = f"{M}/{name}_fp32.onnx", f"{M}/{name}_int8.onnx"
    try:
        quantize_dynamic(src, dst, weight_type=QuantType.QInt8, op_types_to_quantize=["Conv", "MatMul", "Gemm"])
        info[name]["int8_ops"] = "Conv+MatMul+Gemm"
    except Exception as e:
        print(name, "conv quantise failed:", e)
        quantize_dynamic(src, dst, weight_type=QuantType.QInt8, op_types_to_quantize=["MatMul", "Gemm"])
        info[name]["int8_ops"] = "MatMul+Gemm"
    info[name]["fp32_mb"] = round(os.path.getsize(src) / 1e6, 1)
    info[name]["int8_mb"] = round(os.path.getsize(dst) / 1e6, 1)
    info[name]["params_m"] = round(sum(int(np.prod(i.dims)) for i in __import__("onnx").load(src).graph.initializer) / 1e6, 2)
# 20 clips for the int8 check
clips = []
for lang in ["en", "es", "fr", "ja"]:
    for f in sorted(glob.glob(f"{FD}/{lang}/0[0-4]*.wav"))[:5]:
        with wave.open(f) as w:
            clips.append(np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768)
for name in info:
    a, b = MD.load(f"{name}_fp32"), MD.load(f"{name}_int8")
    ea, eb = a.embed(clips), b.embed(clips)
    cos = (ea * eb).sum(1)
    info[name]["int8_vs_fp32_cos_min"] = round(float(cos.min()), 4)
    info[name]["int8_vs_fp32_cos_mean"] = round(float(cos.mean()), 4)
    # timing, one thread
    for prec in ("fp32", "int8"):
        m = MD.load(f"{name}_{prec}", threads=1)
        torch.set_num_threads(1)
        for w in (1.0, 1.5):
            x = clips[0][:int(w * 16000)]
            for _ in range(3):
                F = m.feats([x]); m.embed_feats(F)
            tf, tn = [], []
            for _ in range(20):
                t0 = time.perf_counter(); F = m.feats([x]); t1 = time.perf_counter(); m.embed_feats(F); t2 = time.perf_counter()
                tf.append(t1 - t0); tn.append(t2 - t1)
            info[name][f"ms_{prec}_{w}s_front"] = round(1000 * float(np.median(tf)), 2)
            info[name][f"ms_{prec}_{w}s_net"] = round(1000 * float(np.median(tn)), 2)
    torch.set_num_threads(8)
    print(name, info[name], flush=True)
json.dump(info, open(OUT, "w"), indent=1)
