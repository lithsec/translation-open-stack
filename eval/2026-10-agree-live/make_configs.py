# The configurations this round runs, written beside this script from the repo's languages.toml:
#   G1  as shipped (German: the default turns, a 700 ms pause, cut at 9 s)
#   G3  German on LONG_TURNS as in ../2026-10-de-ru-ro (900 ms pause, 500 ms after 8 s, cut at 15 s, 2.5 s of speech)
#   G4  G3 with the cut at 10 s
#   G5  G3 with the cut at 12 s
#   S   Spanish and French into English on Gemma too, so every simultaneous policy (and utterance mode) has the
#       same translator both ways; agree runs only where Gemma translates
#   python3 -I make_configs.py ../../languages.toml configs
import os, re, sys

src, out = sys.argv[1], sys.argv[2]
base = open(src, encoding="utf-8").read()


def section(text, lang, edit):
    m = re.search(rf"^\[{lang}\]\n(.*?)(?=^\[|\Z)", text, flags=re.S | re.M)
    assert m, lang
    return text[:m.start(1)] + edit(m.group(1)) + text[m.end(1):]


def long_turns(cut):
    keys = f"endpoint_ms = 900\nlong_utterance_s = 8\nlong_endpoint_ms = 500\nmax_utterance_s = {cut}\nmin_speech_ms = 2500\n"
    return lambda body: body.replace('asr = "whisper"\n', 'asr = "whisper"\n' + keys, 1)


def to_en_gemma(body):
    return re.sub(r'^translator_to_en = .*$', 'translator_to_en = ["llmmt", "hymt"]', body, count=1, flags=re.M)


cfg = {"G1": base, "G3": section(base, "de", long_turns(15)), "G4": section(base, "de", long_turns(10)),
       "G5": section(base, "de", long_turns(12)),
       "S": section(section(base, "es", to_en_gemma), "fr", to_en_gemma)}
os.makedirs(out, exist_ok=True)
for name, text in cfg.items():
    open(os.path.join(out, f"{name}.toml"), "w", encoding="utf-8").write(text)
    print(name, "written")
