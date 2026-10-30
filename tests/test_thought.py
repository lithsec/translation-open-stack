"""Simultaneous mode's thought policy (server/thought.py, and room_flush in server/server.py): a thought commits when
two decisions in a row end at the same word, the long-tail fallback, the end of the turn, a failed decision, and a
room where thought, agree and the clause rule each serve their own listeners. Gemma is a stand-in; no GPU, no
server.

    python3 tests/test_thought.py
"""
import asyncio
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

import agree  # noqa: E402
import thought  # noqa: E402


def load_server():
    spec = importlib.util.spec_from_file_location("stack_server", os.path.join(ROOT, "server", "server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SRV = load_server()


def scripted(*answers):
    it, seen = iter(answers), []

    def ask(prompt):
        seen.append(prompt)
        a = next(it)
        if isinstance(a, Exception):
            raise a
        return a
    ask.seen = seen
    return ask


def turn(ask, context=()):
    return thought.ThoughtTurn(ask, SRV.resume_point, "English", ["German"], context)


def test_directions_and_parse():
    assert thought.eligible("en", "de") and thought.eligible("de", "en") and not thought.eligible("en", "es")
    assert thought.parse("COMPLETE 4", 6) == 4 and thought.parse("complete: 2", 3) == 2
    assert thought.parse("WAIT", 5) is None and thought.parse("COMPLETE 9", 5) is None


def test_two_decisions_on_the_same_end_word_commit():
    ask = scripted("COMPLETE 3", "COMPLETE 3", "WAIT", "WAIT")
    t = turn(ask)
    assert t.step("The museum opened".split()) == ""              # first "complete": wait for a second look
    assert t.step("The museum opened in".split()) == "The museum opened"
    assert t.step("The museum opened in".split()) == ""           # the tail "in" is new: one decision, WAIT
    assert t.step("The museum opened in".split()) == ""           # the same tail again: no call
    assert t.step("The museum opened in 1990".split()) == ""      # "in 1990" WAIT
    assert len(ask.seen) == 4
    assert "1:in 2:1990" in ask.seen[-1]                           # the tail only, numbered from 1


def test_a_moved_end_does_not_commit():
    ask = scripted("COMPLETE 2", "COMPLETE 4", "COMPLETE 4")
    t = turn(ask)
    t.step("It is still".split())
    assert t.step("It is still standing".split()) == ""
    assert t.step("It is still standing today".split()) == "It is still standing"


def test_long_tail_and_end_of_turn():
    words = [f"w{i}" for i in range(thought.THOUGHT_MAX_TAIL + 1)]
    t = turn(scripted())
    assert t.step(words) == " ".join(words)                         # over the cap: no decision, all of it
    t = turn(scripted("WAIT"))
    t.step("Hello there my".split())
    assert t.finish("Hello there my friend.".split()) == "Hello there my friend."


def test_end_of_turn_after_a_respelt_start():
    t = turn(scripted("COMPLETE 2", "COMPLETE 2"))
    t.step("Good morning everyone".split())
    assert t.step("Good morning everyone we".split()) == "Good morning"
    # the final pass respells a word already committed: only what follows is left
    assert t.finish("Good morning, everyone, we begin.".split()) == "everyone, we begin."


def test_failed_decision_waits_for_the_end():
    ask = scripted(RuntimeError("down"))
    t = turn(ask)
    assert t.step("Hello there".split()) == "" and t.failed
    assert t.step("Hello there friend".split()) == "" and len(ask.seen) == 1
    assert t.finish("Hello there friend.".split()) == "Hello there friend."


def test_context_is_the_last_thoughts():
    ask = scripted("COMPLETE 1", "COMPLETE 1", "WAIT")
    t = turn(ask, context=["Earlier one."])
    t.step(["Yes", "and"]); t.step(["Yes", "and", "then"])
    t.step(["Yes", "and", "then", "we"])
    assert "- Earlier one.\n- Yes" in ask.seen[-1]


class FakePipe:
    """de: thought (a scripted decider), es: agree (a scripted Gemma), ja: the clause rule."""

    def __init__(self, decider, gemma):
        self.decider, self.gemma, self.batches = decider, gemma, []

    def thought_turn(self, src, langs, context=()):
        assert langs == ["de"]
        return thought.ThoughtTurn(self.decider, SRV.resume_point, "English", ["German"], context)

    def agree_turn(self, src, lang, context=None):
        return agree.AgreeTurn(self.gemma, "English", "Spanish") if lang == "es" else None

    def translate_batch(self, text, langs, src=None, context=None):
        self.batches.append((text, tuple(langs)))
        return [f"[{lg}] {text}" for lg in langs]


def test_room_serves_each_listener_by_its_policy():
    said = []

    async def fake_speak(pipe, room, lg, w, tr):
        said.append((lg, tr))
    SRV.room_speak = fake_speak
    room = SRV.Room()
    room.policy, room.turn_src = "thought", "en"
    room.members = {"ws-de": "de", "ws-es": "es", "ws-ja": "ja"}
    pipe = FakePipe(scripted("COMPLETE 2", "COMPLETE 2"), scripted("Hola a", "Hola a todos", "y bienvenidos."))

    async def run():
        await SRV.room_flush(pipe, room, "Hello everyone".split(), False)
        await SRV.room_flush(pipe, room, "Hello everyone and".split(), False)
        await SRV.room_flush(pipe, room, "Hello everyone and welcome.".split(), True)
    asyncio.run(run())
    by = lambda lg: [tr for l, tr in said if l == lg]  # noqa: E731
    assert by("de") == ["[de] Hello everyone", "[de] and welcome."], by("de")
    assert by("es") == ["Hola a", "y bienvenidos."], by("es")
    assert by("ja") == ["[ja] Hello everyone and welcome."], by("ja")


def test_policy_query_takes_thought():
    class P:
        srcs, lid, langs = [], None, ["en", "de"]
    try:
        SRV.parse_request({"lang": ["de"], "policy": ["sometimes"]}, P())
        assert False, "an unknown policy must be refused"
    except SRV.BadRequest as e:
        assert "thought" in str(e)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
