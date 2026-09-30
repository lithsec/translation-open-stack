# One recogniser over the Lao, Khmer and Haitian Creole test sets; character error rate + transcripts.
#   python3 asr_one.py <name>     (writes res/<name>.json)
import glob, json, os, re, sys, unicodedata, time
import jiwer, numpy as np, soundfile as sf, torch
from scipy.signal import resample_poly
name = sys.argv[1]
SETS = {  # (language, voice) -> file glob, reference sentences
    ("lo", "voxcpm"): ("/workspace/lao/tts/voxcpm/lo_*.wav", "/workspace/lao/src_lo.json"),
    ("lo", "mms"):    ("/workspace/lao/tts/mms/lo_*.wav",    "/workspace/lao/src_lo.json"),
    ("km", "voxcpm"): ("/workspace/b4/tts/voxcpm/km_*.wav",  "/workspace/b4/src_km.json"),
    ("km", "mms"):    ("/workspace/b4/tts/mmsraw/km_*.wav",  "/workspace/b4/src_km.json"),
    ("ht", "mms"):    ("/workspace/b4/tts/mms/ht_*.wav",     "/workspace/b4/src_ht.json"),
    ("ht", "coqui"):  ("/workspace/b4/tts/stack/ht_*.wav",   "/workspace/b4/src_ht.json"),
}
OMNI = {"lo": "lao_Laoo", "km": "khm_Khmr", "ht": "hat_Latn"}
MMS = {"lo": "lao", "km": "khm", "ht": "hat"}
def norm(t, L):
    t = unicodedata.normalize("NFC", t).lower()
    t = "".join(c for c in t if not unicodedata.category(c).startswith("P")).replace("​", "")
    return re.sub(r"\s+", "" if L in ("lo", "km") else " ", t).strip()
def load16(p):
    w, sr = sf.read(p, dtype="float32")
    if w.ndim > 1: w = w.mean(1)
    return resample_poly(w, 16000, sr).astype(np.float32) if sr != 16000 else w
langs = None
if name.startswith("omniASR"):
    from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline
    pipe = ASRInferencePipeline(model_card=name)
    llm = "_LLM_" in name
    def tr(p, L):
        return (pipe.transcribe([p], lang=[OMNI[L]], batch_size=1) if llm else pipe.transcribe([p], batch_size=1) or [""])[0]
elif name == "whisper-lao":
    from transformers import pipeline
    asr = pipeline("automatic-speech-recognition", model="Phonepadith/whisper-large-lao-finetuned-v1", device=0, torch_dtype=torch.float16)
    langs = {"lo"}
    def tr(p, L): return asr(load16(p), generate_kwargs={"language": "lao", "task": "transcribe"})["text"]
elif name == "mms-1b-all":
    from transformers import Wav2Vec2ForCTC, AutoProcessor
    proc = AutoProcessor.from_pretrained("facebook/mms-1b-all"); model = Wav2Vec2ForCTC.from_pretrained("facebook/mms-1b-all").to("cuda").eval()
    cur = [None]
    def tr(p, L):
        if cur[0] != L:
            proc.tokenizer.set_target_lang(MMS[L]); model.load_adapter(MMS[L]); cur[0] = L
        inp = proc(load16(p), sampling_rate=16000, return_tensors="pt").to("cuda")
        with torch.inference_mode(): ids = model(**inp).logits.argmax(-1)[0]
        return proc.decode(ids)
out = {"name": name, "vram_gb": None, "sets": {}}
for (L, voice), (pat, ref) in SETS.items():
    if langs and L not in langs: continue
    files = sorted(glob.glob(pat)); R = json.load(open(ref))
    t = time.time(); hyps = [tr(f, L) for f in files]
    cer = jiwer.cer([norm(R[int(os.path.basename(f)[3:5])], L) for f in files], [norm(h, L) for h in hyps])
    out["sets"][f"{L}/{voice}"] = {"cer": round(cer, 3), "secs": round(time.time() - t, 1), "hyps": hyps}
    print(name, L, voice, f"CER {cer:.1%}", flush=True)
out["vram_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 1)
os.makedirs("res", exist_ok=True); json.dump(out, open(f"res/{name}.json", "w"), ensure_ascii=False, indent=1)
