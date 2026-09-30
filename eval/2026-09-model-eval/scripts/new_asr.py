# Recognition for the new languages. (1) Voice clarity: round trip of every candidate voice. (2) Real speech:
# FLEURS test clips (human readers), Whisper large-v3 vs Omnilingual 300M, for the languages where Whisper is
# not known to be strong — decides which recogniser the stack routes each language to.
import csv, glob, io, json, os, re, sys, tarfile, unicodedata, urllib.request
import jiwer
from faster_whisper import WhisperModel
wh = WhisperModel("large-v3", device="cuda", compute_type="float16")
from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline
omni = ASRInferencePipeline(model_card="omniASR_LLM_300M")
OMNI = {"hi": "hin_Deva", "tl": "tgl_Latn", "fa": "pes_Arab", "bn": "ben_Beng", "ur": "urd_Arab", "sw": "swh_Latn",
        "ar": "arb_Arab", "vi": "vie_Latn", "ko": "kor_Hang", "id": "ind_Latn", "tr": "tur_Latn", "it": "ita_Latn"}
SPACELESS = set()
def norm(t):
    t = unicodedata.normalize("NFC", t).lower()
    t = "".join(c for c in t if not unicodedata.category(c).startswith("P"))
    return re.sub(r"\s+", " ", t).strip()
def w_tr(p, L): return " ".join(s.text for s in wh.transcribe(p, language=L, beam_size=1, condition_on_previous_text=False, temperature=0)[0])
def o_tr(p, L):
    try: return (omni.transcribe([p], lang=[OMNI[L]], batch_size=1) or [""])[0]
    except Exception as e: return f"<err {e}>"
res = {"clarity": {}, "fleurs": {}}
# (1) clarity of each candidate voice (Whisper; Omnilingual too where Whisper is weak)
for d in sorted(glob.glob("tts/*")):
    for L in sorted({os.path.basename(f)[:2] for f in glob.glob(f"{d}/*.wav")}):
        files = sorted(glob.glob(f"{d}/{L}_*.wav")); S = json.load(open(f"src_{L}.json"))
        refs = [norm(S[int(f[-6:-4])]) for f in files]
        r = {"whisper": round(jiwer.cer(refs, [norm(w_tr(f, L)) for f in files]), 3)}
        if L in ("hi", "tl", "fa", "bn", "ur", "sw"): r["omni"] = round(jiwer.cer(refs, [norm(o_tr(f, L)) for f in files]), 3)
        res["clarity"][f"{os.path.basename(d)}/{L}"] = r; print("clarity", os.path.basename(d), L, r, flush=True)
# (2) real speech
FLEURS = {"hi": "hi_in", "tl": "fil_ph", "fa": "fa_ir", "bn": "bn_in", "ur": "ur_pk", "sw": "sw_ke"}
base = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
os.makedirs("/root/fleurs", exist_ok=True)
for L, code in FLEURS.items():
    tsv = urllib.request.urlopen(f"{base}/{code}/test.tsv").read().decode()
    rows = list(csv.reader(io.StringIO(tsv), delimiter="\t"))[:25]
    want = {r[1]: r[2] for r in rows}
    tf = f"/root/fleurs/{code}.tar.gz"
    if not os.path.exists(tf): urllib.request.urlretrieve(f"{base}/{code}/audio/test.tar.gz", tf)
    with tarfile.open(tf) as t:
        for m in t.getmembers():
            if os.path.basename(m.name) in want:
                m.name = os.path.basename(m.name); t.extract(m, f"/root/fleurs/{code}")
    files = [f"/root/fleurs/{code}/{n}" for n in want if os.path.exists(f"/root/fleurs/{code}/{n}")]
    refs = [norm(want[os.path.basename(f)]) for f in files]
    r = {"n": len(files), "whisper": round(jiwer.cer(refs, [norm(w_tr(f, L)) for f in files]), 3),
         "omni": round(jiwer.cer(refs, [norm(o_tr(f, L)) for f in files]), 3)}
    res["fleurs"][L] = r; print("fleurs", L, r, flush=True)
json.dump(res, open("new_asr.json", "w"), ensure_ascii=False, indent=1)
