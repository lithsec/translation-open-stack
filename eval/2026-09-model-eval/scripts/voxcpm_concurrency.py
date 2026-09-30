# Throughput with N simultaneous streams: N processes, each synthesising the same Spanish sentences.
import sys, json, time, torch, multiprocessing as mp
def worker(q, n):
    from voxcpm import VoxCPM
    m = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False); sr = m.tts_model.sample_rate
    m.generate(text="Hola.", cfg_value=2.0, inference_timesteps=10)
    sents = json.load(open("src_es.json"))[:6]
    q.put("ready"); q.get() if False else None
    t = time.time(); a = 0.0
    for s in sents:
        a += len(m.generate(text=s, cfg_value=2.0, inference_timesteps=10)) / sr
    q.put((time.time() - t, a))
if __name__ == "__main__":
    mp.set_start_method("spawn")
    res = {}
    for n in [1, 2, 4]:
        q = mp.Queue(); ps = [mp.Process(target=worker, args=(q, n)) for _ in range(n)]
        [p.start() for p in ps]; [p.join() for p in ps]
        out = [x for x in [q.get() for _ in range(2 * n)] if x != "ready"]
        wall = max(o[0] for o in out); audio = sum(o[1] for o in out)
        res[n] = {"streams": n, "audio_s": round(audio, 1), "wall_s": round(wall, 1), "rtf_per_stream": round(wall / (audio / n), 3),
                  "realtime_capacity": round(audio / wall, 2)}
        print(res[n], flush=True)
    json.dump(res, open("tts/voxcpm_concurrency.json", "w"), indent=1)
