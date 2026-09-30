# Clarity of VoxCPM2 at fewer diffusion steps: Omnilingual 300M round trip on the
# Khmer and Lao clips from voxcpm_speed.py (same recogniser as the published scores).
import glob, json, re, unicodedata, jiwer
from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline
p = ASRInferencePipeline(model_card="omniASR_LLM_300M")
CODE = {"km": "khm_Khmr", "lo": "lao_Laoo"}
REF = {"km": json.load(open("/workspace/b4/src_km.json")), "lo": json.load(open("/workspace/lao/src_lo.json"))}
def norm(t):
    t = unicodedata.normalize("NFC", t).lower()
    t = "".join(c for c in t if not unicodedata.category(c).startswith("P"))
    return re.sub(r"\s+", "", t).replace("​", "").replace("‌", "").replace("‍", "")
out = {}
for T in (10, 6, 4):
    for L in ("km", "lo"):
        files = sorted(glob.glob(f"tts/voxT{T}/{L}_*.wav"))
        hyps = [(p.transcribe([f], lang=[CODE[L]], batch_size=1) or [""])[0] for f in files]
        cer = jiwer.cer([norm(REF[L][int(f[-6:-4])]) for f in files], [norm(h) for h in hyps])
        out[f"T{T}/{L}"] = round(cer, 3); print(T, L, f"CER {cer:.1%}", flush=True)
json.dump(out, open("asr_steps.json", "w"), indent=1)
