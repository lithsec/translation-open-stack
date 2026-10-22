"""Helpers the engines share: audio conversion, level, text splitting and the
non-speech filter. Moved here unchanged from server.py (2026-09-29), so every
engine gets the same seams, the same levels and the same filtering. The
Omnilingual repetition guard joined them from services/omni-stt (2026-10-22)."""
import os
import re

from engines.base import RATE, VAD_RATE  # noqa: F401  (re-exported for engines)


def hf_snapshot(repo, revision, **kw):
    """A pinned Hugging Face snapshot's local path (from the cache when it is there)."""
    from huggingface_hub import snapshot_download
    return snapshot_download(repo, revision=revision, **kw)


# ---------------------------------------------------------------- devices

def resolve_device(spec):
    """A [devices] value -> the device to load on: "auto" is the first GPU when
    torch sees one, else the CPU. AMD GPUs under ROCm are "cuda" too (PyTorch's
    HIP build keeps the name), so "cuda:1" is the second card on either vendor."""
    spec = (spec or "auto").strip()
    if spec != "auto":
        return spec
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def ct2_device(device):
    """"cuda:1" -> ("cuda", 1) for CTranslate2 (faster-whisper, MADLAD), which
    takes the kind and the index separately. Anything but cuda -> ("cpu", 0):
    CTranslate2 has no Apple GPU backend."""
    kind, _, index = device.partition(":")
    if kind != "cuda":
        return "cpu", 0
    return "cuda", int(index or 0)


def is_gpu(device):
    return device.startswith("cuda")


def on_device(device):
    """Make `device` the current GPU for this thread, for libraries that only
    ever say "cuda" (Coqui, Omnilingual): inside it, "cuda" means that card.
    A no-op for the CPU and for plain "cuda"."""
    import contextlib
    kind, _, index = device.partition(":")
    if kind != "cuda" or not index:
        return contextlib.nullcontext()
    import torch
    return torch.cuda.device(int(index))


def gpu_used_mb(device):
    """Memory in use on a CUDA/ROCm device, in MB, by every process and library
    (CTranslate2's allocations included); None for the CPU."""
    if not is_gpu(device):
        return None
    import torch
    if not torch.cuda.is_available():
        return None
    free, total = torch.cuda.mem_get_info(torch.device(device))
    return (total - free) // (1024 * 1024)


# ---------------------------------------------------------------- audio

def to_pcm16(pcm, native):
    """One synthesised segment -> 24kHz PCM16, joinable without a click.

    Simultaneous mode speaks a CLAUSE at a time, so a turn is many short
    segments butt-joined instead of one long one, and every seam shows two
    artifacts. A segment that ends on a non-zero sample followed by one
    that starts non-zero is a step discontinuity — heard as a tick. And
    resampling each short segment independently rings at its edges, since
    the polyphase filter has no signal to work with past the ends.

    Padding before the resample gives the filter that signal, and a 3ms
    ramp at each end guarantees the joins meet at zero. Both are inaudible
    on their own; together they are the difference between clean speech
    and the static reported in simultaneous mode.
    """
    import numpy as np
    from scipy.signal import resample_poly
    from math import gcd
    if native != RATE:
        g = gcd(RATE, native)
        pad = int(native * 0.01)
        pcm = np.pad(pcm, (pad, pad))
        pcm = resample_poly(pcm, RATE // g, native // g)
        cut = int(RATE * 0.01)
        if len(pcm) > 2 * cut:
            pcm = pcm[cut:len(pcm) - cut]
    n = min(int(RATE * 0.003), len(pcm) // 2)
    if n > 0:
        pcm = pcm.copy()
        pcm[:n] *= np.linspace(0.0, 1.0, n, dtype=pcm.dtype)
        pcm[-n:] *= np.linspace(1.0, 0.0, n, dtype=pcm.dtype)
    return (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()


def peak_normalise(pcm):
    """Bring the peak to -1 dBFS (0.891), gain capped at 4x so a near-silent
    segment is not amplified into noise.

    Piper masters to 1.0; Kokoro peaks around 0.4-0.7 and MMS renders ~11 dB
    below Piper (Haitian RMS -25.5 dBFS against -14 to -15, measured end to end
    over WebRTC). Left alone, a room switching languages hears the level jump,
    and a listener on a quiet voice loses it in the room."""
    import numpy as np
    peak = float(np.abs(pcm).max()) if len(pcm) else 0.0
    if peak > 1e-4:
        pcm = pcm * min(0.891 / peak, 4.0)
    return pcm


# Leading and trailing silence a voice model pads onto a sentence is pure
# listener lag: the first sound arrives late, and the next sentence waits for
# the dead air to play out. What the trim keeps around the speech: 60 ms
# before the first voiced frame (a soft onset below the threshold is inside
# it) and 80 ms after the last (a release or a final fricative tails off, and
# the gap to the next sentence is still a natural one). Measured on the stored
# Haitian Creole samples (eval/2026-10-ht-voices/silence.py): MMS pads 10-300 ms
# in front and 50-380 ms behind, 7% of its output (2-17% per sentence); Coqui
# about a second at each end before its first trim.
TRIM_LEAD_MS = 60
TRIM_TAIL_MS = 80
# A 10 ms frame is voiced when its RMS is within 40 dB of the clip's peak
# (the voices are peak-normalised to -1 dBFS first, so that is -41 dBFS) and
# above -45 dBFS. Both open voices' dead air sits 65-80 dB below the peak, and
# their speech edges are sharp: thresholds from 35 to 50 dB below the peak
# moved the edges by 30 ms at most, so 40 dB is nowhere near the speech. The
# absolute floor keeps a quiet hiss, or a clip that is nothing but hiss, from
# counting as speech.
TRIM_FRAME_MS = 10
TRIM_BELOW_PEAK_DB = 40.0
TRIM_FLOOR_DBFS = -45.0


def voiced_span(pcm, rate, frame_ms=TRIM_FRAME_MS, below_peak_db=TRIM_BELOW_PEAK_DB,
                floor_dbfs=TRIM_FLOOR_DBFS):
    """(start, end) in samples of the voiced part of `pcm` (float32, any rate):
    the first and the last frame whose RMS clears the threshold, frames
    inclusive; None when no frame does (silence, or a hiss under the floor)."""
    import numpy as np
    n = max(1, int(rate * frame_ms / 1000))
    if len(pcm) == 0:
        return None
    pcm = np.asarray(pcm, dtype="float32")
    peak = float(np.abs(pcm).max())
    if peak <= 0.0:
        return None
    frames = len(pcm) // n
    if frames == 0:
        rms = np.sqrt(float((pcm ** 2).mean()))
        rms_db = np.array([20 * np.log10(max(rms, 1e-9))])
        n, frames = len(pcm), 1
    else:
        tail = pcm[frames * n:]
        rms = np.sqrt((pcm[:frames * n].reshape(frames, n) ** 2).mean(axis=1))
        rms_db = 20 * np.log10(np.maximum(rms, 1e-9))
        if len(tail):                   # a last, short frame counts too
            t = np.sqrt(float((tail ** 2).mean()))
            rms_db = np.append(rms_db, 20 * np.log10(max(t, 1e-9)))
    threshold = max(20 * np.log10(peak) - below_peak_db, floor_dbfs)
    voiced = np.flatnonzero(rms_db > threshold)
    if not len(voiced):
        return None
    start = int(voiced[0]) * n
    end = min(len(pcm), (int(voiced[-1]) + 1) * n)
    return start, end


def trim_silence(pcm, rate, lead_ms=TRIM_LEAD_MS, tail_ms=TRIM_TAIL_MS):
    """`pcm` (float32 at `rate`) with its leading and trailing silence cut to
    at most `lead_ms` before and `tail_ms` after the speech. A clip with no
    voiced frame comes back as it is; one whose silence is already shorter is
    not padded. Call it before to_pcm16, whose 3 ms edge ramps then sit on the
    new ends, so the trim adds no click."""
    span = voiced_span(pcm, rate)
    if span is None:
        return pcm
    start, end = span
    a = max(0, start - int(rate * lead_ms / 1000))
    b = min(len(pcm), end + int(rate * tail_ms / 1000))
    if a == 0 and b == len(pcm):
        return pcm
    return pcm[a:b]


# The streaming soft limiter and fixed gain for VoxCPM2 live in
# server/voxcpm_service.py: that service runs in its own virtualenv and
# process, so it cannot import this module.


# ---------------------------------------------------------------- text

# Scripts written without spaces between sentences.
NO_SPACE_JOIN = {"zh", "ja"}
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")


def split_sentences(text):
    """Sentences of one utterance, for per-sentence translation. A fragment under
    three words joins the next sentence ("Dr." + "Smith is here.", "Yes." + ...),
    or the previous one when it comes last."""
    parts = [p.strip() for p in _SENTENCE_END.split(text.strip()) if p.strip()]
    out, carry = [], ""
    for p in parts:
        p = f"{carry} {p}".strip() if carry else p
        if len(p.split()) < 3:
            carry = p
        else:
            out.append(p)
            carry = ""
    if carry:
        if out:
            out[-1] = f"{out[-1]} {carry}"
        else:
            out.append(carry)
    return out or [text]


def join_sentences(parts, lang):
    """Per-sentence translations back into one text: a space between them,
    nothing for the scripts that do not space sentences (zh, ja)."""
    return (" " if lang not in NO_SPACE_JOIN else "").join(parts)


def voice_sentences(text):
    """An utterance split for synthesis, one piece per pool task."""
    sentences = [t.strip() for t in re.split(r"(?<=[.!?;:])\s+", text) if t.strip()]
    return sentences or [text]


# ---------------------------------------------------------------- non-speech

# What whisper says when it hears a cough.
#
# Measured, not guessed: eight recorded coughs through this pipeline produced
# "Cough, cough, cough.", "ぷっぷっ", and "ご視聴ありがとうございました"
# ("thank you for watching") -- at no_speech_prob 0.50-0.66, which is the same
# range as quiet real speech, so no confidence threshold separates them. The
# CONTENT is the signal: whisper learned these from captioned video, where
# non-speech is annotated rather than transcribed.
NONSPEECH_ANNOTATION = re.compile(
    r"^[\s\-–—.,!?:;'\"()\[\]{}*♪♫~]*$|"        # punctuation or music glyphs alone
    r"^\s*[\[(*].{0,40}[\])*]\s*$"                # [music], (coughing), *cough*
)
# Whole-segment text that is an annotation or a caption sign-off, never speech
# from a pulpit. Normalised: lowercased, punctuation and spaces removed.
NONSPEECH_PHRASES = {
    # annotations of the sound itself
    "cough", "coughs", "coughing", "coughcoughcough", "coughcough",
    "sneeze", "sneezes", "sneezing", "throatclearing", "clearsthroat",
    "laughs", "laughter", "laughing", "ha", "haha", "hahaha", "hehe", "hmm",
    "tos", "uh", "ah", "eh", "um", "hm",
    "applause", "music", "silence", "noise", "static", "breathing",
    "ぷっ", "ぷっぷっ", "うっ", "ああ", "はは", "ははは",
    "هاها", "ها", "هه",
    # caption sign-offs whisper appends to audio it cannot parse
    "ごしちょうありがとうございました", "ご視聴ありがとうございました",
    "ご視聴ありがとうございます", "チャンネル登録お願いします",
    "thanksforwatching", "thankyouforwatching", "pleasesubscribe",
    "graciasporsucomentario", "graciasporverelvideo",
    "subtitulosrealizadosporlacomunidaddeamaraorg",
    "字幕由amaraorg社群提供", "字幕志愿者",
    "mercidavoirregarde", "abonnezvous",
}


def _nonspeech_key(text):
    """Lowercase, strip everything that is not a letter or digit."""
    return re.sub(r"[^\w]", "", text.lower(), flags=re.UNICODE)


def is_nonspeech(text):
    """True when a segment is whisper annotating a noise, not transcribing speech."""
    t = text.strip()
    if not t or NONSPEECH_ANNOTATION.match(t):
        return True
    key = _nonspeech_key(t)
    if not key:
        return True
    if key in NONSPEECH_PHRASES:
        return True
    # A single NON-LEXICAL token repeated and nothing else -- "Cough, cough,
    # cough.", "Ha, ha, ha." The repetition alone is not enough to judge on:
    # "Holy, holy, holy." and "Amen, amen, amen." are liturgy, and an earlier
    # version of this rule dropped them. The repeated token has to be a noise
    # word in its own right.
    words = [w for w in re.split(r"[\s,.!?;:-]+", t.lower()) if w]
    if len(words) >= 2 and len(set(words)) == 1 and words[0] in NONSPEECH_PHRASES:
        return True
    return False


# REMOVED 2026-08-29, live: a duration+word-count guard cannot tell a cough
# from "Great." or "Thank you." Measured in a real session, it ate both -- a
# congregation says short things and means them. What actually caught the
# coughs that night was is_nonspeech() reading the CONTENT ("Cough, cough,
# cough.") and SHORT_NOISE_P reading whisper's own no_speech_prob (0.82-0.92
# on invented "Peace." / "Thank you.", against <=0.223 for real short
# speech). Brevity alone is not evidence. Do not reintroduce this.
#
# no_speech_prob as a SECONDARY signal, on segments that are already only a
# token or two. Measured over one run: every short genuine utterance came in
# at p<=0.223 ("Yas." 0.223, "Hallelujah!" 0.084, "Amen." 0.048) and every
# cough at p>=0.501 ("Oh" 0.650, "Coo-coo." 0.555, "Cough cough" 0.707).
# It is NOT safe as a global gate -- real scripture reading through a room mic
# measured 0.53-0.65, inside the cough band, and a p>0.5 gate ate it once
# already. Capping it at two tokens is what makes it safe: it cannot swallow a
# sentence, only a fragment that was already suspicious.
SHORT_NOISE_P = 0.45
SHORT_NOISE_UNITS = 2

# Khmer, Lao, Thai, Chinese and Japanese are written without spaces between
# words, so text.split() returns 1 for a whole sentence. Counting "words" that
# way let a 6-character cough artefact pass a 3-word test that a real Khmer
# sentence would also have failed.
_SPACELESS = re.compile(r"[ក-៿຀-໿฀-๿"
                        r"一-鿿぀-ヿ]")


def content_units(text):
    """Roughly how many words this is, in a script-aware way."""
    t = text.strip()
    if not t:
        return 0
    dense = _SPACELESS.findall(t)
    if len(dense) >= max(1, len(t) // 2):        # predominantly a spaceless script
        return max(1, len(dense) // 3)
    return len(t.split())


# ---------------------------------------------------------------- repetition guard

# Omnilingual's LLM decoder (the fine-tuned 300M cards and the 7B) sometimes
# turns a fragment under a second into 150-200+ characters of one syllable over
# and over, and the pipeline's own stop (a compression check every 250 steps)
# comes too late for a short clip. Speech runs at ~10-18 characters a second in
# every language served here; 30 a second, plus a little slack for a lone word
# on a very short clip, is past anything a person says. Used by services/omni-stt
# (every utterance) and the stack's Omnilingual engine; STT_MAX_CHARS_PER_S and
# STT_MAX_REPEATS tune both.
MAX_CHARS_PER_S = float(os.environ.get("STT_MAX_CHARS_PER_S", "30"))
# A unit (two characters up to a few words) said this many times in a row is
# the decoder looping, not a speaker: "alelouya" sung four times survives, a
# syllable sixty times does not. (Two characters at least, so "1000000" or a
# held "mmmmm" is not a loop; "aaaaaaaaaaaa" still is, as "aa" six times.)
MAX_REPEATS = int(os.environ.get("STT_MAX_REPEATS", "6"))
GUARD_SLACK_CHARS = 10
REPEAT_UNIT_MAX_CHARS = 40
_LOOPS = {}


def _loop_re(n):
    if n not in _LOOPS:
        # The shortest unit (2..40 characters, non-greedy) followed by n-1 more
        # copies of itself, anywhere in the text (re.search: the leftmost loop).
        _LOOPS[n] = re.compile(r"(.{2,%d}?)\1{%d,}" % (REPEAT_UNIT_MAX_CHARS, max(1, n - 1)), re.S)
    return _LOOPS[n]


def repetition_guard(text, audio_s, max_cps=None, max_repeats=None):
    """(text to send, what the guard did: None | "truncated" | "dropped").

    1. A loop (a unit repeated max_repeats times or more in a row) is cut back to
       the text before it plus one copy of the unit. Truncate, not drop: when
       the decoder loops after real words, the words before the loop are the
       good part of the utterance (and one copy of the unit may be what was
       said). Matched on the text with a trailing space, so the last word of a
       loop that ends the text counts as a copy.
    2. Then the rate: more than max_cps characters per audio second (+ slack)
       is dropped whole. Without a loop to cut at there is no telling which
       part is real, and an invented sentence on a cough is worse than none.
       A loop that WAS the whole over-long text (nothing before it) is dropped
       too, rather than sent as a lone syllable."""
    if not text:
        return text, None
    max_cps = MAX_CHARS_PER_S if max_cps is None else max_cps
    max_repeats = MAX_REPEATS if max_repeats is None else max_repeats
    limit = max_cps * max(0.0, audio_s) + GUARD_SLACK_CHARS
    action = None
    out = text
    if max_repeats > 1:
        m = _loop_re(max_repeats).search(text + " ")
        if m:
            prefix = text[:m.start()]
            out = (prefix + m.group(1)).strip()
            action = "truncated"
            if not prefix.strip() and len(text) > limit:
                return "", "dropped"
    if max_cps > 0 and len(out) > limit:
        return "", "dropped"
    return out, action
