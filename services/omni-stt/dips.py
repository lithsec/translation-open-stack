"""Energy dips: short drops well under the running level of the speech, and
which of them follow a word end closely enough to mark a sentence end.

    dips = find_dips(audio)                       # 16 kHz float samples
    ends = sentence_end_candidates(dips, word_ends_ms)

A dip is a run of 20 ms frames (FRAME_MS) whose level is at least depth_db
(12) under the running level, lasting min_ms (60) or more. The running level
is the RMS of the trailing level_ms (1500) of audio before the frame, in dB:
it follows the speaker's own loudness, so a quiet speaker's gaps count as
well as a loud one's, and a long silence stops counting as a dip once the
level has sunk to it. Each dip: start_ms, end_ms, depth_db (how far under
the level its quietest frame was).

sentence_end_candidates(dips, word_ends, lead_ms=-100, lag_ms=250) pairs
each word end (ms) with the first dip starting between lead_ms and lag_ms
after it: a word followed by a gap. The companion apps measured, on their own
test set with their recogniser's word timings, an AUC of 0.92 for telling
sentence ends from other word ends with this rule (a dip of 12 dB or more
starting within -100..+250 ms of the word end). That figure is their
measurement, from their implementation; it has not been reproduced here.

Omnilingual gives no word timings, so on this service the dips are a
secondary signal for where a forced cut should go, not a sentence detector:
pause_cut (server.py) chooses the longest run of low VAD probability in the
last few seconds; a dip could rank two runs of one length, or stand in when
the VAD finds no run (today the fallback is the quietest 20 ms, which lands
inside words). Neither is wired yet; see docs/dev/omni-stt-partials.md.
Only numpy; nothing here touches a model.
"""
from collections import namedtuple

import numpy as np

RATE = 16000
FRAME_MS = 20
LEVEL_MS = 1500
DEPTH_DB = 12.0
MIN_DIP_MS = 60
FLOOR = 1e-6          # -120 dB: digital silence has a level too

Dip = namedtuple("Dip", "start_ms end_ms depth_db")
Candidate = namedtuple("Candidate", "word_end_ms dip")


def frame_power(audio, rate=RATE, frame_ms=FRAME_MS):
    """Mean square per frame (the last partial frame dropped)."""
    x = np.asarray(audio, dtype=np.float64)
    n = max(1, int(rate * frame_ms / 1000))
    m = len(x) // n
    if m == 0:
        return np.zeros(0)
    return (x[:m * n].reshape(m, n) ** 2).mean(axis=1)


def running_level(power, frame_ms=FRAME_MS, level_ms=LEVEL_MS):
    """Per frame, the RMS level in dB of the level_ms before it (not
    including it; the first frame's is its own)."""
    m = len(power)
    if m == 0:
        return np.zeros(0)
    k = max(1, int(round(level_ms / frame_ms)))
    csum = np.concatenate([[0.0], np.cumsum(power)])
    idx = np.arange(m)
    lo = np.maximum(0, idx - k)
    count = idx - lo
    mean = np.where(count > 0, (csum[idx] - csum[lo]) / np.maximum(count, 1), power)
    return 20 * np.log10(np.sqrt(mean) + FLOOR)


def find_dips(audio, rate=RATE, depth_db=DEPTH_DB, min_ms=MIN_DIP_MS, frame_ms=FRAME_MS,
              level_ms=LEVEL_MS):
    """The dips in `audio` (16 kHz float samples), oldest first."""
    power = frame_power(audio, rate, frame_ms)
    if len(power) == 0:
        return []
    db = 20 * np.log10(np.sqrt(power) + FLOOR)
    level = running_level(power, frame_ms, level_ms)
    under = level - db
    low = under >= depth_db
    need = max(1, int(round(min_ms / frame_ms)))
    out = []
    i, m = 0, len(low)
    while i < m:
        if not low[i]:
            i += 1
            continue
        j = i
        while j < m and low[j]:
            j += 1
        if j - i >= need:
            out.append(Dip(i * frame_ms, j * frame_ms, float(under[i:j].max())))
        i = j
    return out


def sentence_end_candidates(dips, word_ends, lead_ms=-100, lag_ms=250):
    """For each word end (ms) followed by a dip starting within
    [word_end + lead_ms, word_end + lag_ms]: Candidate(word_end_ms, dip), the
    earliest such dip. Word ends with no dip there are left out."""
    out = []
    starts = [d.start_ms for d in dips]
    for t in word_ends:
        lo, hi = t + lead_ms, t + lag_ms
        for s, d in zip(starts, dips):
            if s > hi:
                break
            if s >= lo:
                out.append(Candidate(t, d))
                break
    return out


def dip_at(dips, t_ms, lead_ms=-100, lag_ms=250):
    """The first dip starting within [t_ms + lead_ms, t_ms + lag_ms], or None:
    for ranking one candidate cut point against another."""
    hits = sentence_end_candidates(dips, [t_ms], lead_ms, lag_ms)
    return hits[0].dip if hits else None
