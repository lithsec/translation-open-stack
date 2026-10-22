"""Experiment A on the pod: Omnilingual LLM 300M vs 7B (bf16) through omni-stt's own code.
  STACK=/root/a/stack OMNI_MMAP=1 python3 asr_a.py --card omniASR_LLM_7B --out /root/a/out
1. per sentence: rv/<lang>.wav cut at rv/<lang>.json marks (30 FLEURS sentences), one decode each
   (the service's engine path), raw text and repetition_guard(text, audio_s) (the service's guard:
   STT_MAX_CHARS_PER_S 30, STT_MAX_REPEATS 6).
2. segmented: e2e/<lang>.wav (the 20-sentence e2e-stack clip, as streamed) as 100 ms PCM16 messages
   through AudioIn, Silero per 32 ms window (vad_windows) and omni-stt's Segmenter at each setting,
   each segment decoded + guarded, as Models.transcribe_batch does for one utterance.
"""
import argparse, importlib.util, json, os, time
from pathlib import Path
import numpy as np
import soundfile as sf


def stt_module():
    path = Path(os.environ["STACK"]) / "services" / "omni-stt" / "server.py"
    spec = importlib.util.spec_from_file_location("omni_stt_server", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--root", default="/root/a")
    ap.add_argument("--settings", default="200:10,700:15")
    args = ap.parse_args()
    import torch
    stt = stt_module()
    t0 = time.time()
    omni = stt.load_omni("cuda", args.card)
    res = {"card": args.card, "gpu": torch.cuda.get_device_name(0), "load_s": round(time.time() - t0, 1),
           "mem_load_gb": round(torch.cuda.memory_allocated() / 2**30, 2),
           "guard": {"max_cps": stt.MAX_CHARS_PER_S, "max_repeats": stt.MAX_REPEATS},
           "segmenter": {"min_speech_ms": stt.MIN_SPEECH_MS, "cut_window_s": stt.CUT_WINDOW_S,
                         "cut_endpoint_ms": stt.CUT_ENDPOINT_MS, "cut_early_s": stt.CUT_EARLY_S},
           "per_sentence": {}, "segmented": {}}
    torch.cuda.reset_peak_memory_stats()
    dec = aud = 0.0

    def decode(u, lang):
        nonlocal dec, aud
        torch.cuda.synchronize(); a = time.time()
        raw = omni.transcribe(u, lang) if len(u) >= 400 else ""
        torch.cuda.synchronize(); s = time.time() - a
        dec += s; aud += len(u) / 16000
        kept, action = stt.repetition_guard(raw, len(u) / 16000)
        return raw, kept, action, round(s, 3)

    for lang in ("km", "lo"):
        wav, sr = sf.read(f"{args.root}/rv/{lang}.wav", dtype="float32")
        assert sr == 16000
        rows = []
        for m in json.load(open(f"{args.root}/rv/{lang}.json"))["sentences"]:
            u = wav[int(m["start"] * 16000):int(m["end"] * 16000)]
            raw, kept, action, s = decode(u, lang)
            rows.append({"i": m["i"], "raw": raw, "text": kept, "guard": action, "decode_s": s, "audio_s": round(len(u) / 16000, 2)})
        res["per_sentence"][lang] = rows
        print(lang, "per sentence done", sum(1 for r in rows if r["guard"]), "guarded", flush=True)

    for lang in ("km", "lo"):
        pcm, sr = sf.read(f"{args.root}/e2e/{lang}.wav", dtype="int16")
        assert sr == 16000 and pcm.ndim == 1
        raw_bytes = pcm.tobytes()
        for setting in args.settings.split(","):
            ep, mx = setting.split(":")
            vad = stt.load_vad(); vad.reset_states()
            conn_in = stt.audio_input(16000, "eval")
            seg = stt.Segmenter(endpoint_ms=int(ep), max_s=float(mx))
            utts = []
            for off in range(0, len(raw_bytes), 3200):
                for block in conn_in.feed(raw_bytes[off:off + 3200]):
                    utts += seg.feed(block, stt.vad_windows(vad, block))
            utts += seg.flush()
            out = []
            for u, s_ms, e_ms in utts:
                raw, kept, action, s = decode(u, lang)
                out.append({"start_ms": s_ms, "end_ms": e_ms, "raw": raw, "text": kept, "guard": action, "decode_s": s})
            res["segmented"][f"{lang}:{setting}"] = out
            print(lang, setting, len(out), "segments", sum(1 for r in out if r["guard"]), "guarded", flush=True)
    res["rtf_batch1"] = round(dec / aud, 4)
    res["mem_peak_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    (Path(args.out) / f"{args.card}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("done", args.card, res["rtf_batch1"], res["mem_peak_gb"], flush=True)


if __name__ == "__main__":
    main()
