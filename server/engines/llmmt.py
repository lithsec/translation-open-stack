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

The stack picks a translator per direction: into a language, that language's
translator; into English, the source's translator_to_en when it names one (else
[en]'s). A list is tried in order, so translator = ["llmmt", "hymt"] means this
engine while its server answers and Hy-MT2 otherwise. A pair is sent to the
server its non-English side names (the source's, else the target's), and any
pair neither side names goes to Hy-MT2 as before (MADLAD if Hy-MT2 can't).

Health: at load, and every HEALTH_EVERY_S after, each named server is asked for
/models (HEALTH_TIMEOUT_S). Any HTTP answer counts as up; a refused or timed-out
connection as down, and while a server is down supports_pair() says no for its
pairs, so the stack uses the next translator in the list. Each change is logged.
LLMMT_HEALTH=0 skips the checks and treats every named server as up.

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
import os
import threading
import time
import urllib.error
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
HEALTH_EVERY_S = 30
HEALTH_TIMEOUT_S = 2


def server_answers(url, timeout=HEALTH_TIMEOUT_S):
    """Does an HTTP server answer at this base url? Any status counts."""
    try:
        with urllib.request.urlopen(url + "/models", timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


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
        self._up = {}
        self._servers = self._configured()
        self._checks = os.environ.get("LLMMT_HEALTH", "1") != "0"
        self.check_servers()
        if self._checks and self._servers:
            threading.Thread(target=self._watch, daemon=True, name="llmmt-health").start()
        self.available = True

    def _configured(self):
        """{server: [languages naming it]}, for the served languages (all when none are given)."""
        served = set(self.ctx.langs) | set(self.ctx.srcs)
        out = {}
        for lang, entry in self.ctx.table.items():
            value = entry.get(self.name) if isinstance(entry, dict) else None
            if value and (not served or lang in served):
                try:
                    out.setdefault(parse_server(value), []).append(lang)
                except ValueError:
                    pass
        return out

    def _set(self, server, up):
        before = self._up.get(server)
        self._up[server] = up
        if before is up:
            return
        style, url, model = server
        langs = ",".join(sorted(self._servers.get(server, [])))
        if up:
            print(f"[stack] llmmt: {url} ({model}) answering — {langs} use it", flush=True)
        else:
            print(f"[stack] llmmt: {url} ({model}) not answering — {langs} use their next translator "
                  f"(checking every {HEALTH_EVERY_S} s)", flush=True)

    def check_servers(self):
        for server in self._servers:
            self._set(server, server_answers(server[1]) if self._checks else True)

    def _watch(self):
        while True:
            time.sleep(HEALTH_EVERY_S)
            self.check_servers()

    def supports_pair(self, src, tgt):
        """Only while the server this pair goes to answers (and one is named)."""
        server = self.server_for(src, tgt)
        checks = getattr(self, "_checks", False)
        return server is not None and getattr(self, "_up", {}).get(server, not checks)

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
                if isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError):
                    self._set(server, False)   # unreachable: the next translator until it answers again
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
