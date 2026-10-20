import json, os, time, numpy as np, soundfile as sf, torch, warnings
warnings.filterwarnings("ignore")
from huggingface_hub import hf_hub_download
from TTS.utils.synthesizer import Synthesizer
from transformers import AutoTokenizer, VitsModel
sents = json.load(open(os.path.expanduser("~/dev/translation-open-stack/eval/2026-10-real-voices/sentences/ht.json")))
repo = "multilingual-tts/VITS-OpenBible-Haitian-Creole"
syn = Synthesizer(tts_checkpoint=hf_hub_download(repo, "model_last.pth"), tts_config_path=hf_hub_download(repo, "config.json"), use_cuda=False)
tok = AutoTokenizer.from_pretrained("facebook/mms-tts-hat"); mms = VitsModel.from_pretrained("facebook/mms-tts-hat").eval()
def coqui(t):
    pcm = np.asarray(syn.tts(t), dtype="float32").squeeze()
    idx = np.where(np.abs(pcm) > 0.01)[0]
    if len(idx): pcm = pcm[max(0, idx[0]-int(.05*syn.output_sample_rate)): idx[-1]+int(.05*syn.output_sample_rate)]
    return pcm, syn.output_sample_rate
def mmsf(t):
    with torch.no_grad(): pcm = mms(**tok(t, return_tensors="pt")).waveform[0].numpy()
    return pcm, mms.config.sampling_rate
samples = json.load(open("samples.json"))
samples = [s for s in samples if s["v"] not in ("coqui", "mms")]
for name, f in (("coqui", coqui), ("mms", mmsf)):
    times = []
    for i in range(12):
        t0 = time.time(); pcm, sr = f(sents[i]); dt = time.time() - t0
        pcm = pcm / max(1e-6, np.abs(pcm).max()) * 0.89  # peak-normalise like the stack
        if i < 6:
            sf.write(f"{name}__{i}.wav", pcm, sr); samples.append({"v": name, "i": i, "file": f"{name}__{i}.wav", "text": sents[i], "secs": len(pcm)/sr})
        else: times.append((dt, len(pcm)/sr))
    print(name, "CPU synth s per sentence (median)", sorted(t for t, _ in times)[3], "audio s", sorted(a for _, a in times)[3])
json.dump(samples, open("samples.json", "w"), indent=1)
print(len(samples), "samples")
