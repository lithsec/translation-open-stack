# Character error rate of speech recognisers on known sentences.
#   python asr_eval.py whisper|omni   (system python)     venv_asr/bin/python asr_eval.py qwen
import glob, json, os, sys, unicodedata, re
import jiwer
which = sys.argv[1]
SPACELESS = {"km", "zh", "ja"}
def norm(t, L):
    t = unicodedata.normalize("NFC", t).lower()
    t = "".join(c for c in t if not unicodedata.category(c).startswith("P"))
    t = re.sub(r"\s+", " " if L not in SPACELESS else "", t).strip()
    # Khmer zero-width spaces / joiners
    return t.replace("​", "").replace("‌", "").replace("‍", "")
def refs(L): return json.load(open("en.json" if L == "en" else f"src_{L}.json"))
# (audio set, language) pairs this recogniser is asked about
SETS = {"whisper": [(d, L) for d in ["voxcpm", "stack", "mms", "mmsraw"] for L in ["km","es","pt","fr","en","de","ru","zh","ja","ht"]],
        "omni": [(d, L) for d in ["voxcpm", "stack", "mms", "mmsraw"] for L in ["km", "ht"]],
        "qwen": [(d, L) for d in ["voxcpm", "stack", "mmsraw"] for L in ["km"]]}[which]
if which == "whisper":
    from faster_whisper import WhisperModel
    m = WhisperModel("large-v3", device="cuda", compute_type="float16")
    def tr(path, L):
        segs, _ = m.transcribe(path, language=L, beam_size=1, condition_on_previous_text=False, temperature=0)
        return " ".join(s.text for s in segs)
elif which == "omni":
    from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline
    p = ASRInferencePipeline(model_card="omniASR_LLM_300M")
    code = {"km": "khm_Khmr", "ht": "hat_Latn"}
    def tr(path, L): return (p.transcribe([path], lang=[code[L]], batch_size=1) or [""])[0]
else:
    import torch
    from qwen_asr import Qwen3ASRModel
    m = Qwen3ASRModel.from_pretrained("seanghay/Qwen3-ASR-0.6B-Khmer", dtype=torch.bfloat16, device_map="cuda:0", max_new_tokens=256)
    def tr(path, L): return m.transcribe(audio=path)[0].text
out = {}
for d, L in SETS:
    files = sorted(glob.glob(f"tts/{d}/{L}_*.wav"))
    if not files: continue
    R = refs(L); hyps, rs, samples = [], [], []
    for f in files:
        i = int(f.rsplit("_", 1)[1][:2]); h = tr(f, L)
        hyps.append(norm(h, L)); rs.append(norm(R[i], L)); samples.append(h)
    cer = jiwer.cer(rs, hyps)
    out[f"{d}/{L}"] = {"cer": round(cer, 3), "n": len(files), "sample": samples[:2]}
    print(which, d, L, f"CER {cer:.1%}", flush=True)
json.dump(out, open(f"asr_{which}.json", "w"), ensure_ascii=False, indent=1)
