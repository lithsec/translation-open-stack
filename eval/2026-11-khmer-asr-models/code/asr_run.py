# Hears the 24 Khmer FLEURS test sentences of ../../2026-11-khmer-table-talk with one open Khmer recogniser, on this
# Mac (Apple M2 Pro, 16 GB), one sentence at a time (a phone's utterance), and times each call (model already loaded,
# one warm-up call first).
#   python3 -I asr_run.py KIND MODEL_DIR DATA OUT.json [DEVICE]
#   KIND: whisper (Thareah/Tha-ASR: beam 5, language km, as its card measured), ctc (nphearum/PsarAI-ASR-1B: greedy,
#   as its card's own output), qwen (seanghay/Qwen3-ASR-0.6B-Khmer through qwen-asr). DATA: set.json and km/*.raw
#   (16 kHz mono PCM16). Output: [{file, hyp, s}].
import json, sys, time
import numpy as np, torch
KIND, MD, D, OUT = sys.argv[1:5]
DEV = sys.argv[5] if len(sys.argv) > 5 else ("mps" if torch.backends.mps.is_available() else "cpu")
S = json.load(open(f"{D}/set.json"))
def audio(f): return np.frombuffer(open(f"{D}/km/{f.replace('.wav', '.raw')}", "rb").read(), dtype="<i2").astype(np.float32) / 32768
t0 = time.time()
if KIND == "whisper":
    from transformers import WhisperForConditionalGeneration, WhisperProcessor
    proc = WhisperProcessor.from_pretrained(MD); model = WhisperForConditionalGeneration.from_pretrained(MD, dtype=torch.float32).to(DEV).eval()
    def hear(a):
        x = proc(a, sampling_rate=16000, return_tensors="pt").input_features.to(DEV)
        with torch.inference_mode():
            ids = model.generate(x, language="km", task="transcribe", num_beams=int(__import__("os").environ.get("BEAMS", "5")), max_new_tokens=440)
        return proc.batch_decode(ids, skip_special_tokens=True)[0].strip()
elif KIND == "ctc":
    from transformers import AutoProcessor, Wav2Vec2ForCTC
    proc = AutoProcessor.from_pretrained(MD); model = Wav2Vec2ForCTC.from_pretrained(MD, dtype=torch.float32).to(DEV).eval()
    def hear(a):
        x = proc(a, sampling_rate=16000, return_tensors="pt").input_values.to(DEV)
        with torch.inference_mode():
            logits = model(x).logits
        return proc.decode(logits.argmax(-1)[0].cpu()).strip()
elif KIND == "qwen":
    from qwen_asr import Qwen3ASRModel
    model = Qwen3ASRModel.from_pretrained(MD, dtype=torch.float32, device_map=DEV, max_inference_batch_size=1, max_new_tokens=256)
    def hear(a):
        return model.transcribe(audio=(a, 16000))[0].text.strip()
else:
    sys.exit(f"unknown kind {KIND}")
print(f"loaded {KIND} on {DEV} in {time.time() - t0:.1f} s", flush=True)
hear(audio(S[0]["km_file"]))  # warm-up
rows = []
for s in S:
    a = audio(s["km_file"]); t = time.time()
    try: h, err = hear(a), None
    except Exception as e: h, err = "", str(e)[:200]  # noqa: BLE001
    rows.append({"file": s["km_file"], "hyp": h, "s": round(time.time() - t, 2), "audio_s": round(len(a) / 16000, 2), "device": DEV} | ({"error": err} if err else {}))
    print(len(rows), rows[-1]["s"], "s", len(h), "chars", err or "", flush=True)
json.dump(rows, open(OUT, "w"), ensure_ascii=False, indent=1)
