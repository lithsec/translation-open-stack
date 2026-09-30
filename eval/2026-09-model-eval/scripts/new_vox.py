# VoxCPM2 for the new languages it supports: one voice per language (sentence 0 generated freely, then cloned
# for sentences 1-7 — how the stack runs it), so the samples are one consistent speaker.
import json, os, time, numpy as np, soundfile as sf, torch
from voxcpm import VoxCPM
model = VoxCPM.from_pretrained("/workspace/hf-cache/hub/models--openbmb--VoxCPM2/snapshots/32279effe8c19989596f05d353d1447f51d9e915", load_denoiser=False)
sr = model.tts_model.sample_rate
model.generate(text="Hello.", cfg_value=2.0, inference_timesteps=10)
stats = {}
for L in ["ar", "hi", "vi", "ko", "tl", "id", "tr", "it", "sw"]:
    S = json.load(open(f"src_{L}.json")); d = "tts/voxcpm"; os.makedirs(d, exist_ok=True)
    ref = f"{d}/{L}_00.wav"; t = time.time(); aud = 0
    w = np.asarray(model.generate(text=S[0], cfg_value=2.0, inference_timesteps=10), dtype=np.float32); sf.write(ref, w, sr); aud += len(w) / sr
    for i in range(1, 8):
        w = np.asarray(model.generate(text=S[i], reference_wav_path=ref, cfg_value=2.0, inference_timesteps=10), dtype=np.float32)
        sf.write(f"{d}/{L}_{i:02d}.wav", w, sr); aud += len(w) / sr
    stats[L] = round((time.time() - t) / aud, 3); print(L, "rtf", stats[L], flush=True)
json.dump(stats, open("new_vox_stats.json", "w"), indent=1)
