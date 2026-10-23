"""An LLM translator served beside the stack by an OpenAI-compatible server
(vLLM), for languages Hy-MT2 does not have: Haitian Creole and Lao.

MADLAD-400 7B translates them today. On correct text (eval/2026-10-ht-lo-translators)
Gemma 4 31B scored en->ht 90 / ht->en 86 / en->lo 94 against MADLAD's 78 / 77 / 80,
and MiLMMT-46 12B (Lao, not Haitian Creole) en->lo 94 / lo->en 98. Both are
chat or completion LMs too large to load inside the stack's process next to
everything else, so this engine talks HTTP to a server started beside it:

    vllm serve google/gemma-4-31B-it-qat-w4a16-ct --port 8101 --gpu-memory-utilization 0.3 ...

A language names its server in languages.toml as "<style> <base url> <model id>":

    [ht]
    translator = "llmmt"
    llmmt = "chat http://127.0.0.1:8101/v1 google/gemma-4-31B-it-qat-w4a16-ct"

    [lo]
    translator = "llmmt"
    llmmt = "milmmt http://127.0.0.1:8102/v1 xiaomi-research/MiLMMT-46-12B-v0.1"

The stack picks a translator by the TARGET language. For ht -> en the target is
English, so [en] can say translator = "llmmt" too: a pair is sent to the server
its non-English side names (the source's, else the target's), and any pair
neither side names goes to Hy-MT2 as before (MADLAD if Hy-MT2 can't).

Styles: "chat" (the shootout's prompt as one user message, temperature 0) and
"milmmt" (MiLMMT's model-card completion prompt). One request per sentence,
all of an utterance's sentences at once; vLLM batches them.

Context (?context=1, server/translation_context.py): as for Hy-MT2, the pieces
before this one (at most two) and the newest translation into the target go
ABOVE the instruction, marked as context only; the sentence to translate stays
last. MiLMMT's completion prompt takes the previous pair as one earlier
"{source}: ... / {target}: ..." exchange instead, and only when there is a
previous translation to pair with. No context: exactly the prompts above.

Licence: the served model's, not this file's. Gemma 4 is Apache-2.0; MiLMMT-46
is under the Gemma terms. The commercial edition refuses an engine it can't
classify, so it needs the operator's review ([licence_review]).
"""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from engines import register
from engines.base import Translator
from engines.common import join_sentences

NAMES = {
    "en": "English", "ht": "Haitian Creole", "lo": "Lao", "km": "Khmer", "es": "Spanish", "fr": "French",
    "pt": "Portuguese", "ja": "Japanese", "zh": "Chinese", "de": "German", "it": "Italian", "ru": "Russian",
    "uk": "Ukrainian", "ar": "Arabic", "hi": "Hindi", "vi": "Vietnamese", "ko": "Korean", "tl": "Filipino",
    "fa": "Persian", "id": "Indonesian", "tr": "Turkish", "bn": "Bengali", "ur": "Urdu", "sw": "Swahili",
    "ro": "Romanian",
}
TIMEOUT_S = 30


def parse_server(value):
    """"<style> <url> <model>" -> (style, url, model), or ValueError."""
    parts = str(value).split()
    if len(parts) != 3 or parts[0] not in ("chat", "milmmt") or not parts[1].startswith("http"):
        raise ValueError(f"want \"chat|milmmt <base url> <model id>\", got {value!r}")
    return parts[0], parts[1].rstrip("/"), parts[2]


CONTEXT_PIECES = ("The {a} text before this one, for context only. Do not translate it and do not "
                  "repeat it:\n\n{pieces}\n\n")
CONTEXT_TRANSLATION = ("How the text before this one was translated into {b}, for context only. "
                       "Do not repeat it:\n\n{translation}\n\n")


def _context(context, tgt):
    """(pieces, previous translation into tgt) from the stack's context dict."""
    if not context:
        return [], None
    pieces = [p.strip() for p in (context.get("pieces") or []) if p and p.strip()][-2:]
    previous = ((context.get("translations") or {}).get(tgt) or "").strip() or None
    return pieces, previous


def request(style, model, sentence, src, tgt, context=None):
    """(path, body) for one sentence. `context` as in engines/base.py; None
    gives exactly the prompt the engine has always sent."""
    a, b = NAMES.get(src, src), NAMES.get(tgt, tgt)
    pieces, previous = _context(context, tgt)
    if style == "milmmt":   # the model card's prompt, the previous pair as one earlier exchange
        head = f"{a}: {' '.join(pieces)}\n{b}: {previous}\n" if pieces and previous else ""
        return "/completions", {"model": model,
                                "prompt": f"Translate this from {a} to {b}:\n{head}{a}: {sentence.strip()}\n{b}:",
                                "temperature": 0, "max_tokens": 600, "stop": ["\n"]}
    head = ""
    if pieces:
        head += CONTEXT_PIECES.format(a=a, pieces="\n".join(pieces))
    if previous:
        head += CONTEXT_TRANSLATION.format(b=b, translation=previous)
    text = (head + f"Translate this {a} sentence into natural {b}. Keep numbers, names and negation exact. "
            f"Output only the {b}.\n\n{sentence.strip()}")
    return "/chat/completions", {"model": model, "messages": [{"role": "user", "content": text}],
                                 "temperature": 0, "max_tokens": 600,
                                 "chat_template_kwargs": {"enable_thinking": False}}


def answer(style, reply):
    choice = (reply.get("choices") or [{}])[0]
    if style == "milmmt":   # a completion: its first line (the stop sequence, should a server ignore it)
        return (choice.get("text") or "").strip().split("\n")[0].strip()
    return ((choice.get("message") or {}).get("content") or "").strip()


@register
class LlmMT(Translator):
    name = "llmmt"
    title = "LLM translator (OpenAI-compatible server)"
    lang_key = str
    licence = "the served model's (see each language's llmmt = ...)"
    takes_context = True      # prompted LMs: see request() and the module docstring

    @classmethod
    def check_lang(cls, lang, value):
        try:
            parse_server(value)
        except ValueError as e:
            return str(e)
        return None

    def load(self):
        self.pool = ThreadPoolExecutor(max_workers=16)
        self.available = True

    def supports_source(self, lang):
        return True   # reads Haitian Creole and Lao itself: no English pivot

    def server_for(self, src, tgt):
        """The server the pair's non-English side names, or None."""
        for lang in (src, tgt):
            value = self.setting(lang)
            if value:
                return parse_server(value)
        return None

    def call(self, server, sentence, src, tgt, context=None):
        style, url, model = server
        path, body = request(style, model, sentence, src, tgt, context)
        req = urllib.request.Request(url + path, data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return answer(style, json.loads(r.read()))

    def translate(self, sentences, src, targets, text=None, context=None):
        out, others = {}, []
        for tgt in targets:
            server = self.server_for(src, tgt)
            if server is None:
                others.append(tgt)
                continue
            try:
                got = list(self.pool.map(lambda s: self.call(server, s, src, tgt, context), sentences))
            except Exception as e:   # this target only: MADLAD translates it whole
                print(f"[stack] llmmt {src}->{tgt} failed ({e}) — MADLAD instead", flush=True)
                continue
            if all(got):
                prev = _context(context, tgt)[1]
                if prev:   # a repeat of the previous translation is dropped, as for Hy-MT2 (exact prefix only)
                    got = [g[len(prev):].strip() or g if g.startswith(prev) else g for g in got]
                out[tgt] = join_sentences(got, tgt)
        if others:   # pairs no server is named for: Hy-MT2, as without this engine
            hymt = self.ctx.engine("translator", "hymt")
            if hymt is not None and hymt.available and hymt.supports_source(src):
                kw = {"context": context} if context and getattr(hymt, "takes_context", False) else {}
                out.update({k: v for k, v in (hymt.translate(sentences, src, others, text=text, **kw) or {}).items()
                            if k in others})
        return out
