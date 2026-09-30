"""eSpeak NG (the system `espeak-ng` program): the LAST voice of every language
it speaks, in both editions. Robotic, but always there and nearly free (a CPU
process per sentence, ~50x real time), so a sentence that would otherwise be
silent is spoken:

  - when VoxCPM2 is at capacity (every instance at its limit) or down: the
    overflow sentence goes down the chain, and eSpeak is at its end;
  - for fa and ro in EDITION=commercial, which have no other commercially
    licensed voice (they were text only);
  - when every other voice of a language fails.

An implicit last resort: the manager appends it to every chain it supports
(after an explicit `voice = [...]` list too), so languages.toml needs no entry.
`espeak = false` in a language's table takes it out of that language's chain.
Enabled with --espeak (scripts/run.sh passes it when `espeak-ng` is installed;
ESPEAK=0 turns it off).

Licence: eSpeak NG, program and voice data, is GPL-3.0-or-later. It runs as a
separate process (never linked into the server); running it as a service, and
the audio it produces, carry no GPL duty. Distributing the image or a volume
does (docs/licences.md §8), the same as piper-tts. MBROLA voices (`mb-*`), which
have their own, mostly non-commercial licences, are never used.
"""
import os
import shutil
import subprocess

from engines import register
from engines.base import Voice
from engines.common import to_pcm16, peak_normalise

# Our language -> eSpeak NG voice (`espeak-ng --voices=<lang>`; eSpeak's own
# voices only, never MBROLA `mb-*`). Checked against espeak-ng 1.51 (Ubuntu
# 24.04) and 1.52. Not here, and why:
#   km lo tl   eSpeak NG has no Khmer, Lao or Tagalog voice
#   ja         it reads only kana: every kanji is spoken as "Chinese letter"
ESPEAK_VOICES = {
    "en": "en-us", "es": "es", "fr": "fr-fr", "pt": "pt-br", "it": "it", "de": "de", "ru": "ru", "uk": "uk",
    "zh": "cmn", "ko": "ko", "vi": "vi", "ar": "ar", "fa": "fa", "id": "id", "tr": "tr", "bn": "bn",
    "ur": "ur", "hi": "hi", "sw": "sw", "ro": "ro", "ht": "ht",
}

# Words per minute: a little under eSpeak's 175, which is hard to follow in a
# language you are only just hearing.
SPEED = int(os.environ.get("ESPEAK_SPEED", "160"))
# A test sentence per language, spoken at load: a missing dictionary (a distro
# that splits them out) must drop the language loudly, not at the first overflow.
_PROBE = "1 2 3"


def _wav_pcm(data):
    """The PCM16 samples of `espeak-ng --stdout` (a WAV whose sizes are unset,
    because it is written as a stream) and its rate."""
    import numpy as np
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("espeak-ng did not write a WAV")
    rate = int.from_bytes(data[24:28], "little")
    i = data.find(b"data", 12)
    if i < 0:
        raise ValueError("no data chunk")
    pcm = data[i + 8:]
    pcm = pcm[:len(pcm) - len(pcm) % 2]
    return np.frombuffer(pcm, "<i2").astype("float32") / 32768, rate


@register
class ESpeak(Voice):
    name = "espeak"
    title = "eSpeak NG"
    # `espeak = false`: not in this language's chain. (`true` is the default.)
    lang_key = bool
    priority = 90
    # Appended to every chain it supports, even an explicit `voice = [...]`.
    last_resort = True
    # A fresh process per sentence: nothing shared.
    lock_policy = "none"
    licence = "GPL-3.0-or-later (a separate process)"

    @classmethod
    def enabled(cls, ctx):
        return bool(ctx.options.get("espeak"))

    @classmethod
    def covers(cls, lang):
        """Does eSpeak NG speak this language at all (stack_config's chains)?"""
        return lang in ESPEAK_VOICES

    def __init__(self, ctx):
        super().__init__(ctx)
        self.binary = ctx.options.get("espeak_binary") or shutil.which("espeak-ng")
        self.langs = set()

    def supports(self, lang):
        return self.available and lang in self.langs and self.setting(lang) is not False

    def load(self):
        if not self.binary:
            print("[stack] eSpeak NG not installed (apt-get install espeak-ng) — no last-resort voice", flush=True)
            return
        bad = []
        for lang in self.ctx.langs:
            if lang not in ESPEAK_VOICES or self.setting(lang) is False:
                continue
            try:
                pcm, _ = _wav_pcm(self._run(_PROBE, lang))
                if len(pcm) < 1000:
                    raise ValueError("no audio")
                self.langs.add(lang)
            except Exception as e:
                bad.append(f"{lang} ({e})")
        self.available = bool(self.langs)
        print(f"[stack] eSpeak NG last-resort voice for {','.join(sorted(self.langs)) or 'nothing'}"
              + (f"; unavailable: {', '.join(bad)}" if bad else ""), flush=True)

    def _run(self, text, lang):
        # Text on stdin, never on the command line (it is untrusted: a
        # translation of what someone said). No -m: markup is read as text.
        r = subprocess.run([self.binary, "-v", ESPEAK_VOICES[lang], "-s", str(SPEED), "-b", "1", "--stdout"],
                           input=text.encode("utf-8"), capture_output=True, timeout=15)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode(errors="replace").strip()[:200] or f"exit {r.returncode}")
        return r.stdout

    def synthesise(self, text, lang):
        """24 kHz PCM16 at the other voices' level (peak -1 dBFS), or None."""
        try:
            pcm, rate = _wav_pcm(self._run(text, lang))
        except Exception as e:
            print(f"[stack] eSpeak NG {lang} failed ({e})", flush=True)
            return None
        if not len(pcm):
            return None
        return to_pcm16(peak_normalise(pcm), rate)
