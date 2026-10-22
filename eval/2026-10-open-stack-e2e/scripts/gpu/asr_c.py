"""Addition to A: stronger English (and es/fr) recognisers on the e2e-stack clips, one sentence at a time.
  python asr_c.py <clips dir with en/es/fr .wav+.json> <out.json> <model: canary|parakeet|whisper>
canary   nvidia/canary-qwen-2.5b (NeMo SALM, ASR mode prompt from the model card), en only
parakeet nvidia/parakeet-tdt-0.6b-v3 (NeMo ASRModel), en es fr
whisper  faster-whisper large-v3 @ the stack's pinned revision, float16, the stack's transcribe options
Per sentence: text, decode seconds; RTF and peak GPU memory per model.
"""
import json, os, sys, tempfile, time
import numpy as np, soundfile as sf, torch

clips, out, which = sys.argv[1], sys.argv[2], sys.argv[3]
langs = ["en"] if which == "canary" else ["en", "es", "fr"]
tmp = tempfile.mkdtemp()
torch.cuda.reset_peak_memory_stats()
t0 = time.time()
if which == "canary":
    from nemo.collections.speechlm2.models import SALM
    m = SALM.from_pretrained("nvidia/canary-qwen-2.5b").bfloat16().eval().cuda()

    def run(path, lang):
        ids = m.generate(prompts=[[{"role": "user", "content": f"Transcribe the following: {m.audio_locator_tag}", "audio": [path]}]],
                         max_new_tokens=256)
        return m.tokenizer.ids_to_text(ids[0].cpu())
elif which == "parakeet":
    import nemo.collections.asr as nemo_asr
    m = nemo_asr.models.ASRModel.from_pretrained(model_name="nvidia/parakeet-tdt-0.6b-v3").eval().cuda()

    def run(path, lang):
        r = m.transcribe([path], batch_size=1, verbose=False)[0]
        return getattr(r, "text", r)
else:
    from faster_whisper import WhisperModel
    m = WhisperModel("large-v3", device="cuda", compute_type="float16", revision="edaa852ec7e145841d8ffdb056a99866b5f0a478")
    opts = dict(beam_size=1, condition_on_previous_text=False, no_speech_threshold=0.6, temperature=0,
                vad_filter=True, vad_parameters=dict(min_silence_duration_ms=300))

    def run(path, lang):
        segs, _ = m.transcribe(sf.read(path, dtype='float32')[0], language=lang, **opts)
        return " ".join(s.text.strip() for s in segs)
load_s = time.time() - t0
res = {"model": which, "load_s": round(load_s, 1), "gpu": torch.cuda.get_device_name(0), "langs": {}}
dec = aud = 0.0
for lang in langs:
    wav, sr = sf.read(f"{clips}/{lang}.wav", dtype="float32")
    rows = []
    marks = json.load(open(f"{clips}/{lang}.json"))["sentences"]
    for k, mk in enumerate([marks[0]] + marks):  # first one again as warm-up (dropped)
        u = wav[int(mk["start"] * sr):int(mk["end"] * sr)]
        p = os.path.join(tmp, f"{lang}_{mk['i']}.wav"); sf.write(p, u, sr)
        torch.cuda.synchronize(); a = time.time()
        with torch.inference_mode():
            text = run(p, lang)
        torch.cuda.synchronize(); s = time.time() - a
        if k == 0:
            continue
        dec += s; aud += len(u) / sr
        rows.append({"i": mk["i"], "text": (text or "").strip(), "decode_s": round(s, 3), "audio_s": round(len(u) / sr, 2)})
    res["langs"][lang] = rows
    print(which, lang, "done", flush=True)
res["rtf"] = round(dec / aud, 4)
res["mem_peak_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)
print("DONE", which, res["rtf"], res["mem_peak_gb"], flush=True)
