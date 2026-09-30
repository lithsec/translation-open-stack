"""echo: a translator that hands the source text back unchanged.

For tests and plumbing only, and the smallest complete engine: nothing to
download, nothing to load. The unit tests route a language through it
(tests/test_engines.py), and a GPU run can prove a config change reached the
pipeline by setting one language's `translator = "echo"` and seeing its
captions come back in the speaker's own words.

    [ro]
    piper = "ro_RO-mihai-medium"
    translator = "echo"

Not a real translation: never deploy a language on it.
"""
from engines import register
from engines.base import Translator


@register
class Echo(Translator):
    name = "echo"
    title = "echo (test)"
    licence = "none (no model)"

    def translate(self, sentences, src, targets, text=None):
        said = text if text is not None else " ".join(sentences)
        return {lang: said for lang in targets}
