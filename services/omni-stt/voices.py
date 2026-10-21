"""Haitian Creole voices for /speak: the stack's MMS-TTS and Coqui VITS engines
(server/engines/mms.py and coqui.py, with their fixes: to_pcm16's 24 kHz
resample and 3 ms edge ramps, peak_normalise's level, trim_silence's cut of
the dead air both voices pad (60 ms kept before the speech, 80 ms after),
MMS's empty-input guard), so a fix there is a fix here.

    mms    facebook/mms-tts-hat                             CC-BY-NC-4.0: non-commercial use only
    coqui  multilingual-tts/VITS-OpenBible-Haitian-Creole   CC-BY-SA-4.0: credit the OpenBible voice

The licences come from server/licences.py (SERVICE_VOICES), the stack's one
licence authority, and decide which voices an edition may use (permitted()):
EDITION=commercial never loads MMS, and on EDITION=both a commercial connection
is never offered it (server.py: service_editions, handle_speak).

Neither model is thread-safe, so each has its own lock (two requests on one
voice take turns; MMS and Coqui run side by side). Text goes through
ht_numbers.spell_numbers first (neither voice says digits) and is spoken a
sentence at a time, so the first sentence's audio goes out while the next is
being made.
"""
import re
import threading

from ht_numbers import spell_numbers

LANG = "ht"
VOICE_REPOS = {
    "mms": "facebook/mms-tts-hat",
    "coqui": "multilingual-tts/VITS-OpenBible-Haitian-Creole",
}
VOICES = tuple(VOICE_REPOS)

# A piece longer than this is cut at its commas, then between words: a long
# sentence would hold back its first audio for the whole of its synthesis.
MAX_PIECE_CHARS = 220
HARD_PIECE_CHARS = 320


def licence(name):
    """The voice's licences.Lic (unclear when licences.py does not list its repo)."""
    import licences
    return licences.service_voice_lookup(VOICE_REPOS[name])


def permitted(names, edition):
    """The voices of `names` that `edition` (nonprofit|commercial) may use, in
    order. There is no licence review here: an unclear voice is never commercial."""
    import licences
    return [n for n in names if licences.allowed(licence(n), edition)]


def describe(name):
    """'facebook/mms-tts-hat (⛔ CC-BY-NC-4.0)'"""
    import licences
    return f"{VOICE_REPOS[name]} ({licences.describe(licence(name))})"


def parse_voice(raw, default):
    """?voice= / "voice": -> "mms" | "coqui"; empty means the default. ValueError otherwise."""
    v = (raw or "").strip().lower() or default
    if v not in VOICES:
        raise ValueError(f"voice must be one of {', '.join(VOICES)}")
    return v


def _cut(piece, limit):
    """Words of `piece` packed into runs of at most `limit` characters."""
    out, cur = [], ""
    for w in piece.split():
        if cur and len(cur) + 1 + len(w) > limit:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        out.append(cur)
    return out


def pieces(text):
    """Text -> what is synthesised in one call each: sentences (the stack's
    voice_sentences rule: after . ! ? ; :), long ones cut at commas, then
    between words."""
    from engines.common import voice_sentences
    out = []
    for s in voice_sentences(text.strip()):
        if len(s) <= MAX_PIECE_CHARS:
            out.append(s)
            continue
        cur = ""
        for part in re.split(r"(?<=,)\s+", s):
            if cur and len(cur) + 1 + len(part) > MAX_PIECE_CHARS:
                out.append(cur)
                cur = part
            else:
                cur = f"{cur} {part}" if cur else part
        if cur:
            out.append(cur)
    final = []
    for p in out:
        final.extend(_cut(p, HARD_PIECE_CHARS) if len(p) > HARD_PIECE_CHARS else [p])
    return [p for p in final if p.strip()]


def prepare(text):
    """What the voices are given: numbers in words, split for synthesis."""
    return pieces(spell_numbers(text))


class Voices:
    """The loaded voices: name -> the stack's engine, each with its own lock."""

    def __init__(self, device, names=VOICES):
        from engines.base import Context
        from engines.coqui import Coqui
        from engines.mms import MMS
        classes = {"mms": MMS, "coqui": Coqui}
        self.engines = {}
        for name in names:
            lock = threading.Lock()
            ctx = Context(device=device,
                          tables={"MMS_VOICES": {LANG: VOICE_REPOS["mms"]},
                                  "COQUI_VOICES": {LANG: VOICE_REPOS["coqui"]}},
                          options={name: True}, voice_lock=lambda lang, lock=lock: lock)
            eng = classes[name](ctx)
            eng.load()
            if not eng.available:
                raise SystemExit(f"[stt] voice {name} failed to load; see above")
            # Both engines build their model on the first sentence; do it now,
            # before the port opens (and at image build, so the weights are cached).
            if not eng.synthesise("Bonjou.", LANG):
                raise SystemExit(f"[stt] voice {name} could not speak; see above")
            self.engines[name] = eng
            print(f"[stt] voice {name}: {describe(name)}", flush=True)

    @property
    def names(self):
        return list(self.engines)

    def synthesise(self, name, piece):
        """24 kHz mono PCM16 bytes for one piece, or None when the voice failed."""
        return self.engines[name].synthesise(piece, LANG)
