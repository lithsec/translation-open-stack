# The configurations this round runs, written beside this script from the repo's languages.toml:
#   G1  as shipped on this branch (German speakers: the default turns, a 700 ms pause, cut at 9 s)
#   G5  German speakers on long turns cut at 12 s (PR #83: 900 ms pause, 500 ms after 8 s, 2.5 s of speech)
#   python3 -I make_configs.py ../../languages.toml configs
import os, re, sys

src, out = sys.argv[1], sys.argv[2]
base = open(src, encoding="utf-8").read()
m = re.search(r"^\[de\]\n(.*?)(?=^\[|\Z)", base, flags=re.S | re.M)
assert m and "max_utterance_s" not in m.group(1)
keys = "endpoint_ms = 900\nlong_utterance_s = 8\nlong_endpoint_ms = 500\nmax_utterance_s = 12\nmin_speech_ms = 2500\n"
g5 = base[:m.start(1)] + m.group(1).replace('asr = "whisper"\n', 'asr = "whisper"\n' + keys, 1) + base[m.end(1):]
os.makedirs(out, exist_ok=True)
for name, text in {"G1": base, "G5": g5}.items():
    open(os.path.join(out, f"{name}.toml"), "w", encoding="utf-8").write(text)
    print(name, "written")
