# VoxCPM2 speed-ups: fewer diffusion steps (inference_timesteps 10 -> 6 -> 4) and
# streaming (time to the first audio chunk). Writes WAVs for the clarity round trip.
#   /workspace/venv_voxcpm/bin/python voxcpm_speed.py      (in /workspace/vbench)
import json, os, time, numpy as np, soundfile as sf, torch
from voxcpm import VoxCPM
model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
sr = model.tts_model.sample_rate
SENTS = {"km": json.load(open("/workspace/b4/src_km.json")), "lo": json.load(open("/workspace/lao/src_lo.json"))}
model.generate(text="Hello.", cfg_value=2.0, inference_timesteps=10)
for T in (6, 4):  # warm each step count's compiled graph
    model.generate(text="Hello there.", cfg_value=2.0, inference_timesteps=T)
stats = {}
for T in (10, 6, 4):
    for L, sents in SENTS.items():
        d = f"tts/voxT{T}"; os.makedirs(d, exist_ok=True)
        gen = aud = 0.0; first = []
        for i, s in enumerate(sents):
            # Streaming: time to the first chunk, then the rest; the concatenation is the clip.
            t = time.time(); chunks = []
            for c in model.generate_streaming(text=s, cfg_value=2.0, inference_timesteps=T):
                if not chunks: torch.cuda.synchronize(); first.append(time.time() - t)
                chunks.append(np.asarray(c, dtype=np.float32))
            torch.cuda.synchronize(); gen += time.time() - t
            wav = np.concatenate(chunks); aud += len(wav) / sr
            sf.write(f"{d}/{L}_{i:02d}.wav", wav, sr)
        stats[f"T{T}/{L}"] = {"rtf": round(gen / aud, 3), "first_chunk_ms_median": int(np.median(first) * 1000),
                              "first_chunk_ms_p90": int(np.percentile(first, 90) * 1000), "chunks_per_s": None}
        print(T, L, stats[f"T{T}/{L}"], flush=True)
# Non-streaming at the same settings, for comparison with how the service works today.
for T in (10, 6, 4):
    t = time.time(); aud = 0.0
    for s in SENTS["km"][:8]:
        w = model.generate(text=s, cfg_value=2.0, inference_timesteps=T); aud += len(w) / sr
    torch.cuda.synchronize(); stats[f"T{T}/km/whole"] = {"rtf": round((time.time() - t) / aud, 3)}
    print(T, "whole", stats[f"T{T}/km/whole"], flush=True)
stats["vram_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 1)
json.dump(stats, open("speed.json", "w"), indent=1)
