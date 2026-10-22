"""Lao and Khmer on Omnilingual's larger card, the repetition guard on the
stack's Omnilingual text, and per-language endpointing. No GPU, no models:
the pipelines are stand-ins.  python3 tests/test_omni_large.py"""
import importlib.util, os, pathlib, sys, tempfile

SERVER = pathlib.Path(__file__).resolve().parent.parent / "server"
sys.path.insert(0, str(SERVER))
import numpy as np  # noqa: E402
import stack_config as c  # noqa: E402
from engines.base import Context, VAD_RATE  # noqa: E402
from engines.omnilingual import Omnilingual  # noqa: E402

MODELS = {"omnilingual": {"card": "base-card"}, "omnilingual_large": {"card": "large-card"}}


class FakePipeline:
    """ASRInferencePipeline's transcribe(inputs, lang=[...], batch_size=n)."""
    def __init__(self, card, reply=None):
        self.card, self.calls, self.reply = card, [], reply

    def transcribe(self, inputs, lang, batch_size):
        assert len(inputs) == len(lang) == batch_size
        self.calls.append(list(lang))
        return [self.reply or f"{self.card}:{code}" for code in lang]


def engine(omni_large=True, fail_large=False, table=None, srcs=()):
    table = table if table is not None else c.load()[0]
    ctx = Context(models=MODELS, table=table, tables=c.tables(table), srcs=srcs,
                  options={"omni": True, "omni_large": omni_large})
    eng = Omnilingual(ctx)
    made = {}

    def pipeline(card):
        if fail_large and card == "large-card":
            raise RuntimeError("download failed")
        made[card] = FakePipeline(card)
        return made[card]
    eng._pipeline = pipeline
    eng.load()
    return eng, made


def second(n=1.0):
    return np.zeros(int(VAD_RATE * n), dtype=np.float32)


def test_shipped_config_puts_lao_and_khmer_on_the_large_card():
    table, _ = c.load()
    assert {l for l, e in table.items() if e.get("omni") == "large"} == {"lo", "km"}
    assert c.load_models()[0]["omnilingual_large"] == {"card": "omniASR_LLM_7B"}


def test_large_card_serves_its_languages_when_loaded():
    eng, made = engine()
    assert set(made) == {"base-card", "large-card"}
    assert eng.transcribe(second(), "lo") == "large-card:lao_Laoo"
    assert eng.transcribe(second(), "km") == "large-card:khm_Khmr"
    assert eng.transcribe(second(), "ht") == "base-card:hat_Latn"


def test_without_omni_large_every_language_stays_on_the_base_card():
    eng, made = engine(omni_large=False)
    assert set(made) == {"base-card"}
    assert eng.transcribe(second(), "lo") == "base-card:lao_Laoo"


def test_a_large_card_that_fails_to_load_falls_back_to_the_base():
    eng, made = engine(fail_large=True)
    assert eng.available and eng.large is None
    assert eng.transcribe(second(), "lo") == "base-card:lao_Laoo"


def test_no_large_language_no_large_card():
    table = {"ht": {"asr": "omni:hat_Latn"}}
    eng, made = engine(table=table)
    assert set(made) == {"base-card"}
    eng, made = engine(srcs=["en", "ht", "es"])      # Lao and Khmer not among the sources
    assert set(made) == {"base-card"}
    eng, made = engine(srcs=["en", "lo"])
    assert set(made) == {"base-card", "large-card"} and eng.large_langs == {"lo"}


def test_batch_splits_by_card_and_keeps_order():
    eng, made = engine()
    items = [(second(), "ht"), (second(), "lo"), (second(), "sw"), (second(), "km")]
    assert eng.transcribe_batch(items) == ["base-card:hat_Latn", "large-card:lao_Laoo",
                                           "base-card:swh_Latn", "large-card:khm_Khmr"]
    assert made["base-card"].calls == [["hat_Latn", "swh_Latn"]]
    assert made["large-card"].calls == [["lao_Laoo", "khm_Khmr"]]


def test_repetition_guard_on_the_stacks_omnilingual_text():
    eng, made = engine()
    loop = "ສະບາຍດີ " + "ກາ " * 60
    made["large-card"].reply = loop
    assert eng.transcribe(second(4), "lo") == "ສະບາຍດີ ກາ"                  # cut back to before the loop
    made["large-card"].reply = "ກາ" * 80
    assert eng.transcribe(second(0.6), "lo") == ""                           # nothing but the loop: dropped
    made["large-card"].reply = "ສະບາຍດີ ທຸກຄົນ"
    assert eng.transcribe_batch([(second(2), "lo")]) == ["ສະບາຍດີ ທຸກຄົນ"]  # speech untouched


def test_omni_key_values():
    assert Omnilingual.check_lang("lo", "large") is None
    assert Omnilingual.check_lang("lo", "base") is None
    assert "omni must be" in Omnilingual.check_lang("lo", "7b")


def _bad(text):
    fd, path = tempfile.mkstemp(suffix=".toml")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    try:
        c.load(path)
    except ValueError as e:
        return str(e)
    finally:
        os.unlink(path)
    return None


def test_endpointing_keys_are_checked():
    assert _bad('[lo]\nasr = "omni:lao_Laoo"\nendpoint_ms = 700\nmax_utterance_s = 15\n') is None
    assert "outside" in _bad('[lo]\nendpoint_ms = 7\n')
    assert "outside" in _bad('[lo]\nmax_utterance_s = 120\n')
    assert "must be a int" in _bad('[lo]\nmax_utterance_s = 15.5\n')
    assert "must be a int" in _bad('[lo]\nendpoint_ms = true\n')
    assert "omni must be" in _bad('[lo]\nasr = "omni:lao_Laoo"\nomni = "huge"\n')


def _server():
    spec = importlib.util.spec_from_file_location("stack_server_omni_large", SERVER / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_endpointing_per_spoken_language():
    s = _server()
    flags = (s.ENDPOINT_MS, s.LONG_UTTERANCE_S, s.LONG_ENDPOINT_MS, s.MAX_UTTERANCE_S)
    assert s.endpointing("es") == flags
    # English: the shorter gap from 8 s at 400 ms, cut at 15 s (eval/2026-10-english-80).
    assert s.endpointing("en") == (900, 8, 400, 15)
    assert s.endpointing("auto") == flags
    # 900 ms, 500 ms past 8 s, forced cut at 15 s; at least 2.5 s of speech (eval/2026-10-pauses).
    for lang in ("ja", "ht", "km", "lo"):
        assert s.endpointing(lang) == (900, 8, 500, 15)
        assert s.min_speech_ms(lang) == 2500
    assert s.min_speech_ms("en") == 0
    s.ENDPOINT_MS, s.MAX_UTTERANCE_S = 600, 12     # an operator's flags: these languages keep their own
    assert s.endpointing("lo") == (900, 8, 500, 15)
    assert s.endpointing("es")[0] == 600 and s.endpointing("es")[3] == 12


def test_endpointing_one_key_keeps_the_flag_for_the_other():
    s = _server()
    s._T = dict(s._T, ENDPOINTING={"xx": {"max_utterance_s": 20}})
    assert s.endpointing("xx") == (s.ENDPOINT_MS, 20, s.ENDPOINT_MS, 20)



def test_turn_keys_are_checked():
    ok = '[ht]\nasr = "omni:hat_Latn"\nlong_utterance_s = 8\nlong_endpoint_ms = 400\nmin_speech_ms = 2000\n'
    assert _bad(ok) is None
    assert "outside" in _bad('[ht]\nlong_endpoint_ms = 50\n')
    assert "outside" in _bad('[ht]\nlong_utterance_s = 1\n')
    assert "outside" in _bad('[ht]\nmin_speech_ms = 9000\n')
    assert "must be a int" in _bad('[ht]\nmin_speech_ms = 1.5\n')


def test_clause_gap_per_language():
    s = _server()
    # Both long keys: the clause gap at the language's own length and pause.
    s._T = dict(s._T, ENDPOINTING={"xx": {"long_utterance_s": 8, "long_endpoint_ms": 400, "max_utterance_s": 15}})
    assert s.endpointing("xx") == (s.ENDPOINT_MS, 8, 400, 15)
    # One of them: the flag for the other.
    s._T = dict(s._T, ENDPOINTING={"xx": {"long_utterance_s": 8}})
    assert s.endpointing("xx") == (s.ENDPOINT_MS, 8, s.LONG_ENDPOINT_MS, s.MAX_UTTERANCE_S)
    # Only min_speech_ms: the flags for the rest.
    s._T = dict(s._T, ENDPOINTING={"xx": {"min_speech_ms": 2000}})
    assert s.endpointing("xx") == (s.ENDPOINT_MS, s.LONG_UTTERANCE_S, s.LONG_ENDPOINT_MS, s.MAX_UTTERANCE_S)
    assert s.min_speech_ms("xx") == 2000 and s.min_speech_ms("en") == 0


def test_short_turn_waits_for_the_rest_of_its_sentence():
    s = _server()
    # 1.2 s of speech then 0.9 s quiet: under 2 s of speech, quiet under the 1.5 s hold -> wait.
    assert s.short_turn(2.1, 900, 900, 2000)
    # The quiet reaches the hold: a speaker who stopped is answered.
    assert not s.short_turn(2.7, 1500, 900, 2000)
    # Enough speech: the pause ends the turn as before.
    assert not s.short_turn(3.4, 900, 900, 2000)
    # min 0 (every language that doesn't set it): never waits.
    assert not s.short_turn(1.2, 900, 900, 0)
    # A pause longer than the hold (Lao's 700 ms is not) still has to reach the endpoint.
    assert s.short_turn(2.5, 1600, 2000, 2000)

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
