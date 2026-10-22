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
    assert s.endpointing("en") == flags
    assert s.endpointing("ht") == flags
    assert s.endpointing("auto") == flags
    # 700 ms at any length (no shorter clause gap), forced cut at 15 s.
    assert s.endpointing("lo") == (700, 15, 700, 15)
    assert s.endpointing("km") == (700, 15, 700, 15)
    s.ENDPOINT_MS, s.MAX_UTTERANCE_S = 900, 12     # what run.sh passes: Lao keeps its own
    assert s.endpointing("lo") == (700, 15, 700, 15)
    assert s.endpointing("es")[0] == 900 and s.endpointing("es")[3] == 12


def test_endpointing_one_key_keeps_the_flag_for_the_other():
    s = _server()
    s._T = dict(s._T, ENDPOINTING={"xx": (None, 20)})
    assert s.endpointing("xx") == (s.ENDPOINT_MS, 20, s.ENDPOINT_MS, 20)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
