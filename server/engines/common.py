"""Helpers the engines share: audio conversion, level, text splitting and the
non-speech filter. Moved here unchanged from server.py (2026-09-29), so every
engine gets the same seams, the same levels and the same filtering."""
import re
import threading

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


_MLX = []
_MLX_GUARD = threading.Lock()


def mlx_run(fn, *args, **kw):
    """Run fn on THE MLX thread and return its result. MLX keeps its GPU stream
    per thread: a model loaded on one thread and called from the server's worker
    threads fails ("There is no Stream(gpu, 0) in current thread"; every Hy-MT2
    translation fell back to MADLAD on the first Mac run, 2026-09-30). One
    thread loads and runs every MLX model (Whisper and Hy-MT2), which also
    serialises them on the one GPU."""
    from concurrent.futures import ThreadPoolExecutor
    with _MLX_GUARD:
        if not _MLX:
            _MLX.append(ThreadPoolExecutor(1, thread_name_prefix="mlx"))
    return _MLX[0].submit(fn, *args, **kw).result()


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
