# VoxCPM2: the 24 sentences in each language it supports; per-sentence WAVs + real-time factor.
import json, os, time, numpy as np, soundfile as sf, torch
from voxcpm import VoxCPM
LANGS = ["km", "es", "pt", "fr", "en", "de", "ru", "zh", "ja"]
model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
sr = model.tts_model.sample_rate
os.makedirs("tts/voxcpm", exist_ok=True)
stats = {}
model.generate(text="Hello.", cfg_value=2.0, inference_timesteps=10)  # warm up
for L in LANGS:
    sents = json.load(open("en.json" if L == "en" else f"src_{L}.json"))
    gen_s = audio_s = 0.0
    for i, s in enumerate(sents):
        t = time.time(); wav = model.generate(text=s, cfg_value=2.0, inference_timesteps=10); torch.cuda.synchronize()
        gen_s += time.time() - t; audio_s += len(wav) / sr
        sf.write(f"tts/voxcpm/{L}_{i:02d}.wav", wav, sr)
    stats[L] = {"rtf": round(gen_s / audio_s, 3), "audio_s": round(audio_s, 1)}
    print(L, stats[L], flush=True)
stats["vram_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 1)
json.dump(stats, open("tts/voxcpm_stats.json", "w"), indent=1)
