# SimulStreaming (ufal/SimulStreaming, AlignAtt on Whisper large-v3) over several clips in
# one process: the model is loaded once and each clip is run with the tool's own
# real-time, computationally aware simulation loop (whisper_online_main.py
# main_simulation_from_file, "online = simultaneous mode", copied here unchanged in
# substance: wait for min_chunk of new audio, feed everything that has arrived, process,
# print the output with its emission time). The language is switched between clips by
# rebuilding the tokenizer (what the tool does after language detection). One stream at
# a time: three processes at once fell behind real time on the shared GPU.
# Afterwards one computationally unaware pass (the clock stops while the model computes)
# over the first clip gives the real-time factor.
#
#   OMP_NUM_THREADS=8 python simul_run.py SIMULSTREAMING_DIR CLIPS_ROOT OUT_DIR [tool args...]
#   tool args used here: --vac --min-chunk-size 0.5 --model_path large-v3.pt -l WARNING
# Writes OUT_DIR/simul_<pattern>_<lang>.jsonl (the tool's JSONL) and OUT_DIR/simul_cost.json
import argparse, json, os, sys, time

SS, ROOT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, SS)
import torch  # noqa: E402
from simulstreaming_whisper import simul_asr_factory, simulwhisper_args, SimulWhisperOnline  # noqa: E402
from simulstreaming.whisper.whisper_streaming import whisper_online_main as wom  # noqa: E402
from simulstreaming.whisper.whisper_streaming.vac_online_processor import VACOnlineASRProcessor  # noqa: E402

parser = argparse.ArgumentParser()
wom.processor_args(parser)
simulwhisper_args(parser)
args = parser.parse_args(["--task", "transcribe", "--lan", "en"] + sys.argv[4:])
wom.set_logging(args, wom.logger)
asr, _ = simul_asr_factory(args)
M = asr.model
asr.warmup(wom.load_audio_chunk(os.path.join(ROOT, "clips_reg", "en.wav"), 0, 1))
torch.cuda.reset_peak_memory_stats()


def set_language(lang):
    M.cfg.language = lang
    M.decode_options = M.decode_options.__class__(language=lang, without_timestamps=True, task=M.cfg.task)
    M.create_tokenizer(lang)
    M.detected_language = lang


def new_online():
    online = SimulWhisperOnline(asr)
    return VACOnlineASRProcessor(args.min_chunk_size, online) if args.vac else online


def run_online(path, out):
    """The tool's simultaneous mode."""
    duration = len(wom.load_audio(path)) / 16000
    online = new_online()
    min_chunk = args.vac_chunk_size if args.vac else args.min_chunk_size
    lines = []

    def emit(o, now):
        if o:
            o["emission_time"] = now
            lines.append(json.dumps(o))
    beg, end = 0.0, 0.0
    start = time.time()
    while True:
        now = time.time() - start
        if now < end + min_chunk:
            time.sleep(min_chunk + end - now)
        end = time.time() - start
        online.insert_audio_chunk(wom.load_audio_chunk(path, beg, end))
        beg = end
        try:
            o = online.process_iter()
        except AssertionError:
            pass
        else:
            emit(o, time.time() - start)
        if end >= duration:
            break
    emit(online.finish(), time.time() - start)
    open(out, "w").write("\n".join(lines) + "\n")
    return duration


def run_unaware(path):
    """Computationally unaware: the compute time of the whole clip, chunk by chunk."""
    duration = len(wom.load_audio(path)) / 16000
    online = new_online()
    min_chunk = args.vac_chunk_size if args.vac else args.min_chunk_size
    beg, end, busy = 0.0, min_chunk, 0.0
    while True:
        a = wom.load_audio_chunk(path, beg, end)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        online.insert_audio_chunk(a)
        try:
            online.process_iter()
        except AssertionError:
            pass
        torch.cuda.synchronize()
        busy += time.perf_counter() - t0
        if end >= duration:
            break
        beg, end = end, min(duration, end + min_chunk)
    online.finish()
    return busy, duration


langs = os.environ.get("LANGS", "en,es,fr").split(",")
for lang in langs:
    set_language(lang)
    for pattern in ["reg", "irr"]:
        path = os.path.join(ROOT, f"clips_{pattern}", f"{lang}.wav")
        d = run_online(path, os.path.join(OUT, f"simul_{pattern}_{lang}.jsonl"))
        print("simul", pattern, lang, round(d, 1), "s", flush=True)
set_language(langs[0])
busy, dur = run_unaware(os.path.join(ROOT, "clips_reg", f"{langs[0]}.wav"))
json.dump({"model": "whisper large-v3 (openai large-v3.pt, sha256 e5b1a55b...)", "policy": "AlignAtt",
           "frame_threshold": args.frame_threshold, "min_chunk_size": args.min_chunk_size, "vac": args.vac, "beams": args.beams,
           "rtf_one_stream": round(busy / dur, 4), "rtf_clip": f"reg/{langs[0]}",
           "peak_allocated_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2), "gpu": torch.cuda.get_device_name(0)},
          open(os.path.join(OUT, "simul_cost.json"), "w"), indent=1)
print("done", flush=True)
