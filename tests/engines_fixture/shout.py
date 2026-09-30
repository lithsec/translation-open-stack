"""Out-of-tree engines for tests/test_engines.py, loaded through
STACK_ENGINES_PATH: a translator that upper-cases, and a voice that beeps."""
from engines import register
from engines.base import Translator, Voice, RATE
from engines.common import to_pcm16


@register
class Shout(Translator):
    name = "shout"
    title = "shout (test)"
    languages = frozenset({"de", "fr"})
    models = {"repo": "example/shout", "revision": ""}

    def translate(self, sentences, src, targets, text=None):
        return {lg: " ".join(s.upper() for s in sentences) for lg in targets}


@register
class Beep(Voice):
    name = "beep"
    title = "beep (test)"
    lang_key = str            # beep = "<pitch in Hz>"

    @classmethod
    def check_lang(cls, lang, value):
        return None if value.isdigit() else "beep must be a pitch in Hz, e.g. \"440\""

    def synthesise(self, text, lang):
        import numpy as np
        hz = int(self.setting(lang, "440"))
        t = np.arange(int(RATE * 0.2)) / RATE
        return to_pcm16((0.5 * np.sin(2 * np.pi * hz * t)).astype("float32"), RATE)
