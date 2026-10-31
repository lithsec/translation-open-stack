"""server/engines/llmmt.py against a stand-in OpenAI-compatible server: which
pairs go to which server, the two prompt styles, and what a failure leaves for
MADLAD. Standard library only.

    python3 tests/test_llmmt.py
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from engines.base import Context  # noqa: E402
from engines import llmmt  # noqa: E402

SEEN = []


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        SEEN.append((self.server.server_port, self.path, body))
        if "SLOW" in json.dumps(body):
            time.sleep(0.4)
        if "FAIL" in json.dumps(body):
            self.send_response(500)
            self.end_headers()
            return
        if self.path.endswith("/completions") and "prompt" in body:
            src = body["prompt"].split("\n")[-2].split(": ", 1)[1]   # the last source line
            reply = {"choices": [{"text": f" <{src}>\nignored"}]}
        else:
            src = body["messages"][0]["content"].rsplit("\n\n", 1)[1]   # the sentence comes last
            reply = {"choices": [{"message": {"content": f"[{src}]"}}]}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class Server(ThreadingHTTPServer):
    request_queue_size = 64   # llmmt sends every target at once; the default backlog of 5 refuses some


def serve():
    srv = Server(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_port


class FakeHyMT:
    available = True

    def supports_source(self, lang):
        return lang != "ht"

    takes_context = True
    got_context = None

    def translate(self, sentences, src, targets, text=None, context=None):
        FakeHyMT.got_context = context
        return {t: f"hymt:{' '.join(sentences)}" for t in targets}


def engine():
    a, b = serve(), serve()
    ctx = Context(table={"ht": {"translator": "llmmt", "llmmt": f"chat http://127.0.0.1:{a}/v1 g4"},
                         "lo": {"translator": "llmmt", "llmmt": f"milmmt http://127.0.0.1:{b}/v1 mi"},
                         "en": {"translator": "llmmt"}})
    ctx.engine = lambda kind, name: FakeHyMT() if name == "hymt" else None
    e = llmmt.LlmMT(ctx)
    e.load()
    return e, a, b


def test_a_pair_goes_to_the_server_its_non_english_side_names():
    e, a, b = engine()
    SEEN.clear()
    assert e.translate(["Bonjou.", "Mèsi."], "ht", ["en"]) == {"en": "[Bonjou.] [Mèsi.]"}
    assert {p for p, _, _ in SEEN} == {a}
    SEEN.clear()
    assert e.translate(["Hello."], "en", ["lo"]) == {"lo": "<Hello.>"}   # MiLMMT: the card's prompt, first line
    port, path, body = SEEN[0]
    assert port == b and path == "/v1/completions" and body["stop"] == ["\n"]
    assert body["prompt"] == "Translate this from English to Lao:\nEnglish: Hello.\nLao:"


def test_chat_style_sends_the_shootout_prompt_at_temperature_0():
    e, a, _ = engine()
    SEEN.clear()
    e.translate(["One dose, not two."], "en", ["ht"])
    _, path, body = SEEN[0]
    assert path == "/v1/chat/completions" and body["model"] == "g4" and body["temperature"] == 0
    assert body["messages"][0]["content"].startswith("Translate this English sentence into natural Haitian Creole.")


def test_a_pair_no_server_names_stays_with_hymt():
    e, _, _ = engine()
    SEEN.clear()
    assert e.translate(["Hola."], "es", ["en"]) == {"en": "hymt:Hola."}
    assert SEEN == []


def test_every_target_goes_to_the_server_at_once():
    a = serve()
    table = {t: {"translator": "llmmt", "llmmt": f"chat http://127.0.0.1:{a}/v1 g4"} for t in ("ht", "es", "fr", "de")}
    e = llmmt.LlmMT(Context(table=table))
    e.load()
    t0 = time.monotonic()
    got = e.translate(["SLOW one.", "SLOW two."], "en", ["ht", "es", "fr", "de"])
    took = time.monotonic() - t0
    assert set(got) == {"ht", "es", "fr", "de"}
    assert took < 1.2, took      # 8 calls of 0.4 s: about 0.4 s at once, 3.2 s one after another


def test_a_failed_sentence_leaves_the_target_to_madlad():
    e, _, _ = engine()
    assert e.translate(["fine", "FAIL"], "en", ["ht"]) == {}   # nothing half-translated


def test_a_bad_server_line_is_refused_by_the_config_check():
    assert llmmt.LlmMT.check_lang("ht", "chat not-a-url m")
    assert llmmt.LlmMT.check_lang("ht", "chat http://127.0.0.1:8101/v1 some/model") is None



CTX = {"pieces": ["Bonjou.", "Kijan ou ye?"], "translations": {"en": "Hello. How are you?", "lo": "ສະບາຍດີ"}}


def test_no_context_sends_exactly_the_old_prompts():
    for style in ("chat", "milmmt"):
        assert llmmt.request(style, "m", "Hi.", "en", "ht") == llmmt.request(style, "m", "Hi.", "en", "ht", None)
        assert llmmt.request(style, "m", "Hi.", "en", "ht", {}) == llmmt.request(style, "m", "Hi.", "en", "ht")


def test_chat_context_goes_above_the_instruction_and_the_sentence_stays_last():
    e, a, _ = engine()
    SEEN.clear()
    assert e.translate(["Mwen byen."], "ht", ["en"], context=CTX) == {"en": "[Mwen byen.]"}
    content = SEEN[0][2]["messages"][0]["content"]
    assert content.startswith("The Haitian Creole text before this one, for context only.")
    assert "Bonjou.\nKijan ou ye?" in content and "Hello. How are you?" in content
    assert content.index("Translate this Haitian Creole sentence") > content.index("Hello. How are you?")
    assert content.rsplit("\n\n", 1)[1] == "Mwen byen."


def test_context_keeps_at_most_two_pieces():
    _, body = llmmt.request("chat", "m", "x", "ht", "en", {"pieces": ["alpha", "beta", "gamma"]})
    content = body["messages"][0]["content"]
    assert "alpha" not in content and "beta\ngamma" in content


def test_milmmt_takes_the_previous_pair_as_one_earlier_exchange():
    _, body = llmmt.request("milmmt", "mi", "Thank you.", "en", "lo",
                            {"pieces": ["Hello."], "translations": {"lo": "ສະບາຍດີ"}})
    assert body["prompt"] == ("Translate this from English to Lao:\nEnglish: Hello.\nLao: ສະບາຍດີ\n"
                              "English: Thank you.\nLao:")
    _, body = llmmt.request("milmmt", "mi", "Thank you.", "en", "lo", {"pieces": ["Hello."]})   # nothing to pair
    assert body["prompt"] == "Translate this from English to Lao:\nEnglish: Thank you.\nLao:"


def test_a_repeated_previous_translation_is_dropped():
    class Rep(llmmt.LlmMT):
        def call(self, server, sentence, src, tgt, context=None):
            return "Hello. How are you? I am fine."
    e, _, _ = engine()
    r = Rep(e.ctx)
    r.load()
    assert r.translate(["Mwen byen."], "ht", ["en"], context=CTX) == {"en": "I am fine."}


def test_pairs_left_to_hymt_get_the_context_too():
    e, _, _ = engine()
    FakeHyMT.got_context = None
    fake = FakeHyMT()
    e.ctx.engine = lambda kind, name: fake if name == "hymt" else None
    assert e.translate(["Hola."], "es", ["en"], context=CTX) == {"en": "hymt:Hola."}
    assert FakeHyMT.got_context == CTX


def test_a_server_that_does_not_answer_is_not_offered():
    """Health: a refused connection marks the server down, so the stack's
    translator list moves on; any HTTP answer (even 501 to GET) counts as up."""
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead = sock.getsockname()[1]
    sock.close()                                   # nothing listens there now
    up = serve()
    ctx = Context(table={"ht": {"translator": ["llmmt", "madlad"], "llmmt": f"chat http://127.0.0.1:{dead}/v1 g4"},
                         "lo": {"translator": ["llmmt", "madlad"], "llmmt": f"milmmt http://127.0.0.1:{up}/v1 mi"}})
    ctx.engine = lambda kind, name: None
    e = llmmt.LlmMT(ctx)
    e.load()
    assert not e.supports_pair("en", "ht") and not e.supports_pair("ht", "en")
    assert e.supports_pair("en", "lo") and e.supports_pair("lo", "en")
    assert not e.supports_pair("en", "es")         # no server named for the pair
    os.environ["LLMMT_HEALTH"] = "0"               # checks off: every named server counts as up
    try:
        e2 = llmmt.LlmMT(ctx)
        e2.load()
        assert e2.supports_pair("en", "ht")
    finally:
        del os.environ["LLMMT_HEALTH"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
