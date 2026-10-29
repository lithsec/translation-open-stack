# Recognition, one read sentence at a time (language given, no language ID), on the pod:
#   whisper   faster-whisper large-v3, float16, the stack's transcribe options (server/engines/whisper.py)
#   omni300m  Omnilingual LLM 300M through omni-stt's own engine path (load_omni, repetition_guard)
#   omni7b    Omnilingual LLM 7B, the same way
#   STACK=/workspace/tos python3 -I asr.py WORK whisper|omniASR_LLM_300M|omniASR_LLM_7B
# Writes WORK/asr/<system>.json: {lang: [{"id": "a00", "text", "decode_s", "audio_s"}]}.
import importlib.util, json, os, sys, time
from pathlib import Path
import soundfile as sf

WORK, SYS = sys.argv[1], sys.argv[2]
LANGS = ("de", "ru", "ro")


def sentences(lang):
    d = Path(WORK) / "sent" / lang
    for p in sorted(d.glob("*.wav")):
        wav, sr = sf.read(p, dtype="float32")
        assert sr == 16000
        yield p.stem, wav


def main():
    import torch
    out = {"system": SYS, "gpu": torch.cuda.get_device_name(0)}
    if SYS == "whisper":
        from faster_whisper import WhisperModel
        m = WhisperModel("large-v3", device="cuda", compute_type="float16")
        opts = dict(beam_size=1, condition_on_previous_text=False, no_speech_threshold=0.6, temperature=0,
                    vad_filter=True, vad_parameters=dict(min_silence_duration_ms=300))

        def run(wav, lang):
            segs, _ = m.transcribe(wav, language=lang, **opts)
            return " ".join(s.text.strip() for s in segs).strip()
    else:
        path = Path(os.environ["STACK"]) / "services" / "omni-stt" / "server.py"
        sys.path.insert(0, str(path.parent))   # its own modules (partials, ...)
        spec = importlib.util.spec_from_file_location("omni_stt_server", path)
        stt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stt)
        omni = stt.load_omni("cuda", SYS)

        def run(wav, lang):
            raw = omni.transcribe(wav, lang) if len(wav) >= 400 else ""
            return stt.repetition_guard(raw, len(wav) / 16000)[0]
    for lang in LANGS:
        rows = []
        for sid, wav in sentences(lang):
            torch.cuda.synchronize(); t = time.time()
            text = run(wav, lang)
            torch.cuda.synchronize()
            rows.append({"id": sid, "text": text, "decode_s": round(time.time() - t, 3), "audio_s": round(len(wav) / 16000, 2)})
        out[lang] = rows
        print(SYS, lang, len(rows), flush=True)
    os.makedirs(Path(WORK) / "asr", exist_ok=True)
    name = {"omniASR_LLM_300M": "omni300m", "omniASR_LLM_7B": "omni7b"}.get(SYS, SYS)
    json.dump(out, open(Path(WORK) / "asr" / f"{name}.json", "w"), ensure_ascii=False, indent=1)


main()
