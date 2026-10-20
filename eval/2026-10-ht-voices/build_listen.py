import json, base64, os, sys
D = sys.argv[1]; out = sys.argv[2]
scores = json.load(open(sys.argv[3])) if len(sys.argv) > 3 and os.path.exists(sys.argv[3]) else {}
sents = json.load(open(os.path.expanduser("~/dev/translation-open-stack/eval/2026-10-real-voices/sentences/ht.json")))[:6]
voices = [
 ("gemini-flash", "Gemini 3.8 Flash TTS", "Google", "What Talk uses for Haitian Creole now", "cloud"),
 ("gemini-lite", "Gemini 3.8 Flash Lite TTS", "Google", "Talk's old Haitian voice (sounded French)", "cloud"),
 ("oai-coral", "gpt-4o-mini-tts, coral", "Microsoft (Azure eastus2)", "No accent instruction", "ms"),
 ("oai-coral-instr", "gpt-4o-mini-tts, coral + accent", "Microsoft (Azure eastus2)", "Told to use a native Haitian accent", "ms"),
 ("oai-sage-instr", "gpt-4o-mini-tts, sage + accent", "Microsoft (Azure eastus2)", "Told to use a native Haitian accent", "ms"),
 ("coqui", "Coqui VITS OpenBible", "Open, self-hosted", "Commercial edition of the stack (CC-BY-SA). Drops digits", "open"),
 ("mms", "Meta MMS-TTS", "Open, self-hosted", "Non-profit edition of the stack (CC-BY-NC)", "open"),
]
audio = {v[0]: [ "data:audio/mpeg;base64," + base64.b64encode(open(f"{D}/{v[0]}__{i}.mp3","rb").read()).decode() for i in range(6)] for v in voices}
data = {"sents": sents, "voices": [dict(id=a,name=b,host=c,note=d,kind=e, score=scores.get(a)) for a,b,c,d,e in voices], "audio": audio}
html = open(os.path.join(os.path.dirname(__file__), "listen_template.html")).read().replace("__DATA__", json.dumps(data, ensure_ascii=False))
open(out, "w").write(html); print(len(html)//1024, "KB")
