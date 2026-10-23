"""server/engines/llmmt.py against a stand-in OpenAI-compatible server: which
pairs go to which server, the two prompt styles, and what a failure leaves for
MADLAD. Standard library only.

    python3 tests/test_llmmt.py
"""
import json
import os
import sys
import threading
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
        if "FAIL" in json.dumps(body):
            self.send_response(500)
            self.end_headers()
            return
        if self.path.endswith("/completions") and "prompt" in body:
            src = body["prompt"].split("\n")[1].split(": ", 1)[1]
            reply = {"choices": [{"text": f" <{src}>\nignored"}]}
        else:
            src = body["messages"][0]["content"].split("\n\n", 1)[1]
            reply = {"choices": [{"message": {"content": f"[{src}]"}}]}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_port


class FakeHyMT:
    available = True

    def supports_source(self, lang):
        return lang != "ht"

    def translate(self, sentences, src, targets, text=None):
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


def test_a_failed_sentence_leaves_the_target_to_madlad():
    e, _, _ = engine()
    assert e.translate(["fine", "FAIL"], "en", ["ht"]) == {}   # nothing half-translated


def test_a_bad_server_line_is_refused_by_the_config_check():
    assert llmmt.LlmMT.check_lang("ht", "chat not-a-url m")
    assert llmmt.LlmMT.check_lang("ht", "chat http://127.0.0.1:8101/v1 some/model") is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
