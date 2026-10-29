# ../2026-10-complete-thought-ht-km-lo/words.py with Japanese added. That file:
# Words for Khmer and Lao, which write no spaces between words (spaces mark phrases, if anything): ICU's word
# break, through Node's Intl.Segmenter (one long-lived node process, cached). Punctuation sticks to the word
# before it; zero-width spaces are dropped. Text is joined back without spaces, except between two Latin or digit
# words (names, numbers). Other languages: whitespace, as before.
import json, re, subprocess, threading

NOSPACE = {"km", "lo", "ja"}
_JS = r"""
const rl = require('readline').createInterface({input: process.stdin});
const seg = {km: new Intl.Segmenter('km', {granularity: 'word'}), lo: new Intl.Segmenter('lo', {granularity: 'word'}), ja: new Intl.Segmenter('ja', {granularity: 'word'})};
rl.on('line', (l) => { const j = JSON.parse(l); const out = [];
  for (const s of seg[j.lang].segment(j.text)) out.push([s.segment, !!s.isWordLike]);
  process.stdout.write(JSON.stringify(out) + '\n'); });
"""
_lock, _cache, _proc = threading.Lock(), {}, [None]
LATIN = re.compile(r"[A-Za-z0-9]")


def _segments(text, lang):
    k = (lang, text)
    with _lock:
        if k not in _cache:
            if _proc[0] is None:
                _proc[0] = subprocess.Popen(["node", "-e", _JS], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            p = _proc[0]
            p.stdin.write(json.dumps({"lang": lang, "text": text}) + "\n")
            p.stdin.flush()
            _cache[k] = json.loads(p.stdout.readline())
        return _cache[k]


def toks(text, lang):
    if lang not in NOSPACE:
        return text.split()
    out = []
    for s, wordlike in _segments(text, lang):
        s = s.replace("​", "").strip()
        if not s:
            continue
        if not wordlike and out and not LATIN.match(s):
            out[-1] += s
        else:
            out.append(s)
    return out


def joined(ts, lang):
    if lang not in NOSPACE:
        return " ".join(ts)
    s = ""
    for t in ts:
        if s and LATIN.search(s[-1]) and LATIN.match(t):
            s += " "
        s += t
    return s
