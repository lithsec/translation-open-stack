# Join utterance wavs into one 16 kHz PCM16 clip: each utterance levelled to the same speech RMS
# (-26 dBFS over its loud frames), gaps from the source clamped to 0.35-1.2 s. Writes
# <out>/<lang>.wav, <lang>.json {"sentences":[{start,end}]}, <lang>.txt.json (the dataset transcript per utterance).
import sys, json, os, wave, numpy as np
lang, items_p, out = sys.argv[1:4]
items=json.load(open(items_p))   # [{"wav":..., "text":..., "gap":...}]
os.makedirs(out, exist_ok=True)
def read(p):
    import struct
    with open(p,"rb") as f: data=f.read()
    # parse RIFF chunks (IEEE float or PCM16)
    pos=12; fmt=None; pcm=None
    while pos<len(data):
        cid=data[pos:pos+4]; n=struct.unpack("<I",data[pos+4:pos+8])[0]; body=data[pos+8:pos+8+n]
        if cid==b"fmt ": fmt=struct.unpack("<HHIIHH",body[:16])
        if cid==b"data": pcm=body
        pos+=8+n+(n&1)
    tag,ch,sr,_,_,bits=fmt; assert sr==16000 and ch==1, fmt
    return np.frombuffer(pcm, "<f4").astype(np.float64) if tag==3 else np.frombuffer(pcm,"<i2")/32768.0
x_all=[]; sents=[]; t=0.5; x_all.append(np.zeros(8000))
for k,it in enumerate(items):
    x=read(it["wav"])
    n=len(x)//320; fr=np.sqrt((x[:n*320].reshape(n,320)**2).mean(1)) if n else np.array([1e-4])
    loud=fr[fr>=0.1*np.percentile(fr,90)] if n else fr
    g=10**(-26/20)/max(np.sqrt((loud**2).mean()),1e-5)
    x=np.clip(x*min(g,30),-1,1)
    if k: 
        gap=min(1.2,max(0.35,it.get("gap",0.5))); x_all.append(np.zeros(int(gap*16000))); t+=gap
    sents.append({"start":round(t,3),"end":round(t+len(x)/16000,3)}); x_all.append(x); t+=len(x)/16000
x_all.append(np.zeros(16000))
y=(np.concatenate(x_all)*32767).astype("<i2")
with wave.open(os.path.join(out,f"{lang}.wav"),"wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(y.tobytes())
json.dump({"sentences":sents}, open(os.path.join(out,f"{lang}.json"),"w"), indent=1)
json.dump([it["text"] for it in items], open(os.path.join(out,f"{lang}.txt.json"),"w"), ensure_ascii=False, indent=1)
print(lang, len(items), "utts", round(len(y)/16000,1), "s")
