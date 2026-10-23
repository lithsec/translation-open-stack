# Dynamic int8 (ConvInteger) came out slower than fp32 on CPU and below 0.98 cosine for CAM++ and
# ECAPA-512, so also try static QDQ int8 (per-channel weights, activations calibrated on 200 1.5 s
# windows from FLEURS files 48-59, never used in a test), and record the same checks.
#   python export_static.py FLEURS_DIR export.json OUT.json
import glob, json, os, sys, time, wave
import numpy as np
import torch
from onnxruntime.quantization import quantize_static, QuantType, QuantFormat, CalibrationDataReader, CalibrationMethod
from onnxruntime.quantization.shape_inference import quant_pre_process
import models as MD

FD, PREV, OUT = sys.argv[1:4]
M = MD.M
info = json.load(open(PREV))
R = 16000


def rd(f):
    with wave.open(f) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768


cal_x = []
for lang in ["en", "es", "fr", "pt", "ja", "lo", "km"]:
    for f in sorted(glob.glob(f"{FD}/{lang}/*.wav"))[48:60]:
        x = rd(f)
        for a in range(0, len(x) - int(1.5 * R), int(1.5 * R))[:3]:
            cal_x.append(x[a:a + int(1.5 * R)])
cal_x = cal_x[:200]
clips = []
for lang in ["en", "es", "fr", "ja"]:
    for f in sorted(glob.glob(f"{FD}/{lang}/0[0-4]*.wav"))[:5]:
        clips.append(rd(f))


class Reader(CalibrationDataReader):
    def __init__(self, name, feats):
        self.it = iter([{name: f[None].astype(np.float32)} for f in feats])

    def get_next(self):
        return next(self.it, None)


for name in info:
    src = f"{M}/{name}_fp32.onnx"
    pre = f"{M}/{name}_pre.onnx"
    dst = f"{M}/{name}_qdq.onnx"
    # speechbrain ECAPA's pooling breaks on other lengths after pre-processing: quantise it as exported
    if name == "sb_ecapa":
        pre = src
    else:
        try:
            quant_pre_process(src, pre, skip_symbolic_shape=True)
        except Exception as e:
            print(name, "preprocess skipped:", e); pre = src
    fp = MD.load(f"{name}_fp32")
    feats = fp.feats(cal_x)
    try:
        quantize_static(pre, dst, Reader(fp.inp, feats), quant_format=QuantFormat.QDQ, per_channel=True,
                        weight_type=QuantType.QInt8, activation_type=QuantType.QUInt8,
                        calibrate_method=CalibrationMethod.Percentile,
                        extra_options={"CalibPercentile": 99.99})
    except Exception as e:
        print(name, "static quantise failed:", e); continue
    try:
        q = MD.OnnxModel(dst, fp.front)
        ea, eb = fp.embed(clips), q.embed(clips)
    except Exception as e:
        print(name, "quantised model fails:", e); continue
    cos = (ea * eb).sum(1)
    info[name]["qdq_mb"] = round(os.path.getsize(dst) / 1e6, 1)
    info[name]["qdq_vs_fp32_cos_min"] = round(float(cos.min()), 4)
    info[name]["qdq_vs_fp32_cos_mean"] = round(float(cos.mean()), 4)
    q1 = MD.OnnxModel(dst, fp.front, threads=1)
    torch.set_num_threads(1)
    for w in (1.0, 1.5):
        F = q1.feats([clips[0][:int(w * R)]])
        for _ in range(3):
            q1.embed_feats(F)
        tn = []
        for _ in range(20):
            t0 = time.perf_counter(); q1.embed_feats(F); tn.append(time.perf_counter() - t0)
        info[name][f"ms_qdq_{w}s_net"] = round(1000 * float(np.median(tn)), 2)
    torch.set_num_threads(8)
    print(name, {k: v for k, v in info[name].items() if "qdq" in k}, flush=True)
json.dump(info, open(OUT, "w"), indent=1)
