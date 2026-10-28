"""Simultaneous mode's agree policy (server/agree.py, and room_flush in server/server.py): what is spoken from
successive translations of the turn so far, the pending cap, the end of the turn, and a room that mixes agree and
clause-rule listeners. Gemma is a stand-in; no GPU, no server.

    python3 tests/test_agree.py
"""
import asyncio
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

import agree  # noqa: E402


def scripted(*answers):
    """ask() that returns these translations in turn, and records the prompts."""
    it, seen = iter(answers), []

    def ask(prompt):
        seen.append(prompt)
        a = next(it)
        if isinstance(a, Exception):
            raise a
        return a
    ask.seen = seen
    return ask


def test_eligible_directions():
    assert agree.eligible("en", "es") and agree.eligible("en", "de") and agree.eligible("fr", "en")
    assert not agree.eligible("en", "ja")          # verb-final: whole clauses
    assert not agree.eligible("hi", "en")          # broke down into English (two prefixes agree on a guessed verb)
    assert not agree.eligible("es", "fr")          # neither side English


def test_speaks_only_what_two_translations_agree_on():
    ask = scripted("Hola a", "Hola a todos y", "Hola a todos y bienvenidos al", "unused")
    t = agree.AgreeTurn(ask, "English", "Spanish")
    assert t.step("Hello every".split()) == ""                 # nothing to agree with yet
    assert t.step("Hello everyone and".split()) == "Hola a"
    assert t.step("Hello everyone and".split()) == ""          # no new words: no call
    assert len(ask.seen) == 2
    assert t.step("Hello everyone and welcome to".split()) == "todos y"
    assert t.spoken == "Hola a todos y".split()


def test_a_rewritten_start_waits():
    ask = scripted("El perro", "El perro", "La perra corre", "La perra corre rápido")
    t = agree.AgreeTurn(ask, "English", "Spanish")
    t.step(["The"])
    assert t.step("The dog".split()) == "El perro"
    assert t.step("The dog runs".split()) == ""                 # contradicts what was spoken: never re-said
    assert t.step("The dog runs fast".split()) == ""
    assert t.spoken == ["El", "perro"]


def test_pending_cap_speaks_the_latest_translation():
    words = [f"w{i}" for i in range(agree.AGREE_MAX_PENDING + 2)]
    ask = scripted("a b", "c d", "x y z")
    t = agree.AgreeTurn(ask, "English", "Spanish")
    t.step(words[:1])
    t.step(words[:2])                                         # "a b" vs "c d": nothing agreed
    assert t.step(words) == "x y z"                           # over the cap: the latest translation, whole


def test_finish_completes_or_translates_whole():
    ask = scripted("Hola", "Hola a", '"todos."')
    t = agree.AgreeTurn(ask, "English", "Spanish")
    t.step(["Hello"]); t.step("Hello every".split())
    assert t.spoken == ["Hola"]
    assert t.finish("Hello everyone.", lambda s: "WHOLE") == "todos."   # quotes stripped
    assert 'Already spoken in Spanish for it: "Hola"' in ask.seen[-1]
    fresh = agree.AgreeTurn(scripted(), "English", "Spanish")
    assert fresh.finish("Hi.", lambda s: "Hola.") == "Hola."    # nothing spoken: the utterance translation


def test_a_failed_call_ends_agree_for_the_turn():
    ask = scripted(RuntimeError("down"))
    t = agree.AgreeTurn(ask, "English", "Spanish")
    assert t.step(["Hello"]) == "" and t.failed
    assert t.step("Hello there".split()) == ""                # no more calls this turn
    assert len(ask.seen) == 1
    assert t.finish("Hello there.", lambda s: "Hola.") == "Hola."


def test_call_cap():
    ask = scripted(*["Hola"] * 50)
    t = agree.AgreeTurn(ask, "English", "Spanish")
    for n in range(1, 30):
        t.step(["w"] * n)
    assert len(ask.seen) == agree.AGREE_MAX_CALLS


def test_context_head_goes_first():
    ask = scripted("Hola")
    agree.AgreeTurn(ask, "English", "Spanish", head="CONTEXT\n").step(["Hello"])
    assert ask.seen[0].startswith("CONTEXT\n") and "Prefix: Hello" in ask.seen[0]


# ------------------------------------------------------------------ the room

def load_server():
    spec = importlib.util.spec_from_file_location("stack_server", os.path.join(ROOT, "server", "server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakePipe:
    """es agrees (a scripted Gemma), ja keeps the clause rule (translate_batch tags the text)."""

    def __init__(self, gemma):
        self.gemma, self.batches = gemma, []

    def agree_turn(self, src, lang, context=None):
        return agree.AgreeTurn(self.gemma, "English", "Spanish") if lang == "es" else None

    def translate_batch(self, text, langs, src=None, context=None):
        self.batches.append((text, tuple(langs)))
        return [f"[{lg}] {text}" for lg in langs]


def test_room_mixes_agree_and_clause_members():
    srv = load_server()
    said = []

    async def fake_speak(pipe, room, lg, w, tr):
        said.append((lg, tr))
    srv.room_speak = fake_speak
    room = srv.Room()
    room.policy, room.turn_src = "agree", "en"
    room.members = {"ws-es": "es", "ws-ja": "ja", "ws-en": "en"}
    pipe = FakePipe(scripted("Hola a", "Hola a todos", "y bienvenidos."))

    async def turn():
        await srv.room_flush(pipe, room, "Hello every".split(), False)
        await srv.room_flush(pipe, room, "Hello everyone and".split(), False)
        await srv.room_flush(pipe, room, "Hello everyone and welcome.".split(), True)
    asyncio.run(turn())
    es = [tr for lg, tr in said if lg == "es"]
    ja = [tr for lg, tr in said if lg == "ja"]
    assert es == ["Hola a", "y bienvenidos."], es
    assert ja == ["[ja] Hello everyone and welcome."], ja        # the clause rule, alone
    assert all(lg != "en" for lg, _ in said)                      # the speaker's own language: the relay, not this
    assert all(langs == ("ja",) for _, langs in pipe.batches)


def test_policy_default_is_clause():
    srv = load_server()
    assert srv.Room().policy == "clause" and srv.STREAM_POLICY == "clause"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
