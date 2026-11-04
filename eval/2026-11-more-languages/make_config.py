# configs: A = languages.toml as it is; B = the same with the seven Hy-MT2-only languages (it ko id tr bn ur hi)
# routed as the Gemma languages are: translator = ["llmmt", "hymt"], Gemma's llmmt line, translator_to_en the same.
#   python3 -I make_config.py <languages.toml> <out dir>
import re, sys
src, out = sys.argv[1], sys.argv[2]
text = open(src).read()
open(f"{out}/A.toml", "w").write(text)
GEMMA = 'llmmt = "chat http://127.0.0.1:8101/v1 google/gemma-4-31B-it-qat-w4a16-ct"'
for lang in ("it", "ko", "id", "tr", "bn", "ur", "hi"):
    pat = re.compile(rf'(^\[{lang}\]\n(?:(?!^\[).*\n)*?)translator = "hymt"\n', re.M)
    text, n = pat.subn(rf'\1translator = ["llmmt", "hymt"]\n{GEMMA}\ntranslator_to_en = ["llmmt", "hymt"]\n', text, count=1)
    assert n == 1, lang
open(f"{out}/B.toml", "w").write(text)
