# Lao speech recognition: Omnilingual vs Whisper large-v3, character error rate on both voices.
import glob, json, re, unicodedata, jiwer
S = json.load(open("src_lo.json"))
def norm(t):
    t = unicodedata.normalize("NFC", t)
    t = "".join(c for c in t if not unicodedata.category(c).startswith("P"))
    return re.sub(r"\s+", "", t).replace("​", "")
from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline
omni = ASRInferencePipeline(model_card="omniASR_LLM_300M")
from faster_whisper import WhisperModel
wh = WhisperModel("large-v3", device="cuda", compute_type="float16")
def t_omni(p): return (omni.transcribe([p], lang=["lao_Laoo"], batch_size=1) or [""])[0]
def t_wh(p): return " ".join(s.text for s in wh.transcribe(p, language="lo", beam_size=1, condition_on_previous_text=False, temperature=0)[0])
out = {}
for voice in ["voxcpm", "mms"]:
    files = sorted(glob.glob(f"tts/{voice}/lo_*.wav"))
    for name, f in [("omni", t_omni), ("whisper", t_wh)]:
        hyps = [f(p) for p in files]
        cer = jiwer.cer([norm(S[int(p[-6:-4])]) for p in files], [norm(h) for h in hyps])
        out[f"{name}/{voice}"] = {"cer": round(cer, 3), "hyps": hyps}
        print(name, voice, f"CER {cer:.1%}", flush=True)
json.dump(out, open("asr_lo.json", "w"), ensure_ascii=False, indent=1)
