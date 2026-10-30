# Per-sentence output and latency for every run of this round: ../2026-10-unseen/analyze_e2e.py, with two changes.
#   1. ORDER: the directions run here.
#   2. Turns: in simultaneous mode a turn's translation is spoken before its inputTranscript (the stack sends
#      that at the turn's end), so a turn opens at the stack's "route" message instead, and inputTranscript
#      names what it heard. Without "route" (utterance mode sends one too) an inputTranscript opens the turn as before.
#   python3 -I analyze.py work     -> work/e2e_*/out/latency.json, sentences.json
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
W = sys.argv[1]
src = open(os.path.join(HERE, "..", "2026-10-unseen", "analyze_e2e.py"), encoding="utf-8").read()
old_utt = src[src.index("def utterances(events):"):src.index("def assign(")]
new_utt = '''def utterances(events):
    us = []
    for e in events:
        if e["kind"] == "route":
            us.append({"t": e["t"], "heard": None, "texts": [], "auds": []})
        elif e["kind"] == "input":
            if us and us[-1]["heard"] is None:
                us[-1]["heard"], us[-1]["t"] = e["text"], e["t"]
            else:
                us.append({"t": e["t"], "heard": e["text"], "texts": [], "auds": []})
        elif e["kind"] == "text" and us:
            us[-1]["texts"].append(e)
        elif e["kind"] == "audio" and us:
            us[-1]["auds"].append(e)
    return [u for u in us if u["heard"] is not None]


'''
src = src.replace(old_utt, new_utt)
src = src.replace('ORDER = ["en-es", "es-en", "en-ja", "ja-en", "en-fr", "fr-en", "en-km", "km-en", "ht-en", "en-ht", "lo-en", "en-lo", "en-pt", "pt-en"]',
                  'ORDER = ["en-de", "de-en"]')
assert "def utterances(events):\n    us = []\n    for e in events:\n        if e[\"kind\"] == \"route\"" in src and '"de-en"]' in src
tmp = os.path.join(HERE, ".analyze_agree.py")
open(tmp, "w", encoding="utf-8").write(src)
for d in sorted(os.listdir(W)):
    if d.startswith("e2e_") and os.path.isdir(os.path.join(W, d, "out", "runs")):
        print("==", d, flush=True)
        subprocess.run([sys.executable, "-I", tmp, os.path.join(W, d)], check=False)
