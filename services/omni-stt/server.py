#!/usr/bin/env python3
"""Hosted speech to text: Meta Omnilingual ASR, with spoken-language ID among
the languages a room actually uses; and Haitian Creole voices (/speak). No translation.

    STT_TOKEN=... python3 services/omni-stt/server.py          # port $PORT, default 8080
    STT_OPEN=1    python3 services/omni-stt/server.py          # no token (a laptop test only)

Protocol:

    client connects  wss://host/listen?langs=ht,en[&rate=24000][&transcribe=ht]
                     Authorization: Bearer <token>   (or ?token=, which proxies log)
                     token: STT_TOKEN, STT_TOKEN_NONPROFIT, or a token signed with
                     STT_SIGNING_KEY (Credentials, below)
    server sends     {"type":"hello","langs":["ht","en"],"rate":16000}
    client sends     binary 16 kHz mono PCM16 (24 kHz with ?rate=24000)
                     {"type":"flush"}  optional: end the current utterance now
    server sends     {"type":"language","lang":"ht","confidence":0.93,
                      "start_ms":1200,"end_ms":4810}   per utterance, as soon as it is identified
                     {"type":"inputTranscript","text":"...","lang":"ht",
                      "confidence":0.93,"start_ms":1200,"end_ms":4810}   then its words
                     {"type":"flushed"}   after a flush, once everything before it is sent
                     {"type":"error","detail":"..."}

    client connects  wss://host/speak[?voice=mms|coqui]   (same token)
    server sends     {"type":"hello","lang":"ht","voices":["mms","coqui"],"voice":"coqui","rate":24000,
                      "edition":"nonprofit"}   voices: those the connection's edition may use
    client sends     {"type":"speak","text":"...","voice":"mms","id":"7"}   voice, id optional
    server sends     per sentence: {"type":"sentence","id":"7","index":0,"bytes":96000}
                     then that sentence's audio as binary frames: 24 kHz mono PCM16
                     {"type":"done","id":"7","voice":"mms","sentences":2,
                      "audio_ms":4100,"first_audio_ms":180,"ms":420}   after the last
                     {"type":"error","id":"7","detail":"..."}   (a failed request; the socket stays open)
    Requests on one socket are spoken in order; a client may keep it open.
    Before the voices have loaded (they load beside the recogniser) the hello
    waits; if they failed to load the socket is closed with 4503. A token for an
    edition this server does not serve is closed with 4403 (as the stack does).

    GET /health      200 "ok" once the models are loaded (the port opens only then)
    GET /mic         a microphone test page (mic.html): speak, see each transcript

Per utterance, the stack's own pipeline minus the translation (server/server.py):
Silero VAD ends a turn after ENDPOINT_MS of quiet (300 ms; a turn with less
than MIN_SPEECH_MS of speech waits longer), with a forced cut by MAX_UTTERANCE_S
(6 s) at the quietest recent instant; VoxLingua107 picks the
language, but only among ?langs (one language: no guess at all); Omnilingual
transcribes with that language's code. The recogniser is the stack's engine
(server/engines/omnilingual.py), the audio input its AudioIn (server/audio_in.py),
and the token check its stack_auth.py, so a fix there is a fix here.

?transcribe (default: every language in ?langs) names the languages whose
utterances are transcribed; the others get only their "language" message. A
client that takes one language from here and the rest from another recogniser
(Live Translation's Haitian Creole exception beside Azure) learns within the
language ID's ~50 ms that an English utterance is not its business, and the GPU
never decodes it.

confidence is the language ID's share of the score among ?langs (0..1), 1.0 when
the room has one language. Omnilingual gives no confidence of its own.

start_ms/end_ms count from the first sample of this connection, at 16 kHz.

/speak (voices.py): Haitian Creole only, by the stack's MMS-TTS (facebook/mms-tts-hat,
CC-BY-NC-4.0: non-commercial use only) or Coqui VITS
(multilingual-tts/VITS-OpenBible-Haitian-Creole, CC-BY-SA-4.0) engines. Which a
connection may use is its edition's call (EDITION, below; server/licences.py). Numbers
are spelled out first (ht_numbers.py: neither voice says digits). A WebSocket, not
an HTTP POST: the websockets server here answers GET only, and a socket lets the
first sentence's audio go out while the rest is made. Text never goes in the URL
(URLs are logged).

Environment: HT_VOICE (mms|coqui, default coqui: the voice when a request names none),
EDITION (commercial, the default: Coqui only, MMS never loads; nonprofit: both
voices; both: each /speak connection in the edition its signed token's "ed" claim
names, commercial for a token without one, e.g. STT_TOKEN; STT_TOKEN_NONPROFIT
counts as a "nonprofit" claim),
STT_VOICES (the voices loaded, default: every one EDITION allows), STT_MAX_SPEAKERS (open /speak
sockets, default 4), STT_SERVE ("listen,speak" by default; "speak" skips the
recogniser's models, for a laptop test of the voices), STT_TOKEN, STT_TOKEN_NONPROFIT,
STT_SIGNING_KEY (Credentials, below), STT_OPEN=1,
PORT, STT_DEVICE (default: cuda when torch sees one, else cpu), OMNI_CARD,
STT_MAX_CONNECTIONS, STT_MAX_PENDING, ENDPOINT_MS (default 300), MAX_UTTERANCE_S
(default 6.0), MIN_SPEECH_MS (default 400), STT_MODELS (the baked models).
STT_BATCH_MAX (default 8) and STT_BATCH_WAIT_MS (default 10): the GPU micro-batcher
(Batcher); STT_LID_BATCH=0 runs language ID one utterance at a time inside a batch;
STT_ALIGNED=0 decodes batches with the library's own batched call (omni_batch.py
says why the default is not that); STT_BATCH_GEN_RATIO tunes the length grouping
that path needs (pick_group).
STT_MAX_CHARS_PER_S (default 30) and STT_MAX_REPEATS (default 6): the repetition
guard (repetition_guard).

Credentials, any or all; each app gets its own, and with it its edition:

  STT_SIGNING_KEY      the stack's short-lived signed tokens (stack_auth.py), whose
                       "ed" claim names the edition: what a server can mint per
                       connection uses (Lithos Talk's Worker: "commercial").
  STT_TOKEN_NONPROFIT  a static token whose connections are served as non-profit:
                       for an app an operator configures by hand (Live Translation,
                       a non-profit's app, pastes it into its settings). Signed
                       tokens cannot stand in there: they live at most a day.
  STT_TOKEN            the original static token, no edition: commercial (the
                       strictest served), so a client that still sends it keeps
                       working and never gains a non-commercial voice.

The two static tokens must differ (the server will not start otherwise).
"""
import asyncio
import collections
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
# The stack's modules: next to this file in the image (deploy.sh stages them),
# ../../server in a checkout.
for p in (HERE, os.path.join(HERE, "..", "..", "server")):
    if os.path.isdir(os.path.join(p, "engines")):
        sys.path.insert(0, os.path.abspath(p))
        break

VAD_RATE = 16000
RATES = (16000, 24000)
MAX_LANGS = 8

# Our two-letter codes -> Omnilingual's (ISO 639-3 + script). The stack's
# asr = "omni:<code>" languages (languages.toml) plus the ones the stack sends to
# Whisper, which Omnilingual also covers: a room is usually ht + en, and the
# English half has to come out of the same model. tests/test_omni_stt.py checks
# these against languages.toml. One deliberate difference: Persian is fas_Arab.
# languages.toml says pes_Arab, which is not in omnilingual-asr 0.1.0's
# supported_langs (fas_Arab is); the pipeline accepts it without complaint, so
# nothing says the language hint is being ignored.
OMNI_CODES = {
    "en": "eng_Latn", "es": "spa_Latn", "fr": "fra_Latn", "pt": "por_Latn", "it": "ita_Latn",
    "de": "deu_Latn", "ru": "rus_Cyrl", "uk": "ukr_Cyrl", "zh": "cmn_Hans", "ja": "jpn_Jpan",
    "ko": "kor_Hang", "vi": "vie_Latn", "ar": "arb_Arab", "fa": "fas_Arab", "id": "ind_Latn",
    "tr": "tur_Latn", "bn": "ben_Beng", "ur": "urd_Arab", "hi": "hin_Deva", "sw": "swh_Latn",
    "ro": "ron_Latn", "ht": "hat_Latn", "km": "khm_Khmr", "lo": "lao_Laoo", "tl": "tgl_Latn",
}

# Language ID: the stack's model, at the stack's pinned revision (languages.toml [models.lid]).
LID_REPO = "speechbrain/lang-id-voxlingua107-ecapa"
LID_REVISION = "0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9"
# Silero VAD, the stack's pin (languages.toml [models.vad]; v6.2.3).
VAD_REPO = "snakers4/silero-vad"
VAD_REF = "5cd7945676eb32225748052e2e6a0580e4686a08"

# Endpointing. Shorter than the stack's (server/server.py: 700 ms, 280 ms past
# 5 s, a forced cut at 9 s), because a client here waits on this service: Live
# Translation holds its other recogniser's sentences until the Haitian
# utterance beside them is named, so every second an utterance runs on is a
# second of everyone's captions. 300 ms of quiet ends a turn (a breath between
# clauses is enough), and a speaker who never pauses is cut by 6 s, at the
# quietest instant of the last 2 s.
ENDPOINT_MS = int(os.environ.get("ENDPOINT_MS", "300"))
MAX_UTTERANCE_S = float(os.environ.get("MAX_UTTERANCE_S", "6.0"))
# A turn with less speech than this is not ended by a short pause: VoxLingua107
# picks a language from the whole clip, and on a lone syllable ("wi", "OK") or
# a cough its choice is close to a coin toss -- and a wrong "language" message
# sends that utterance to the wrong recogniser in the client. So a short turn
# waits up to SHORT_TURN_ENDPOINT_MS (the old 700 ms) for more speech, which
# then joins it (the gap is a normal in-turn pause, not padding); a word that
# really stands alone still goes out, as late as it did before this change.
# Merging beats skipping the language ID: the client needs every utterance
# named to release what it holds, and beats a guess: one-word answers are
# where a room's languages are most alike.
MIN_SPEECH_MS = int(os.environ.get("MIN_SPEECH_MS", "400"))
SHORT_TURN_ENDPOINT_MS = 700
TRAILING_KEEP_MS = 250
# Utterances waiting for the model, per connection, before the oldest is
# dropped (and logged): a backlog only makes every caption later.
MAX_PENDING = int(os.environ.get("STT_MAX_PENDING", "3"))
MAX_FRAME_BYTES = 256 * 1024
# /speak: characters per request, and audio per binary frame (1 s at 24 kHz).
SPEAK_MAX_CHARS = 2000
SPEAK_FRAME_BYTES = 48000

CLOSE_BAD_REQUEST = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_BUSY = 4429
CLOSE_UNAVAILABLE = 4503
# How long a /speak connection waits for the voices to finish loading.
VOICES_WAIT_S = 120


class BadRequest(ValueError):
    pass


# ---------------------------------------------------------------- request

def parse_langs(raw, lid_codes=None):
    """?langs=ht,en -> ["ht", "en"], or BadRequest saying what is wrong.
    lid_codes: the languages the language ID knows (needed when there are two or more)."""
    langs = []
    for part in (raw or "").split(","):
        code = part.strip().lower()
        if code and code not in langs:
            langs.append(code)
    if not langs:
        raise BadRequest("langs is required, e.g. ?langs=ht,en")
    if len(langs) > MAX_LANGS:
        raise BadRequest(f"at most {MAX_LANGS} languages per connection")
    unknown = [c for c in langs if c not in OMNI_CODES]
    if unknown:
        raise BadRequest(f"not served: {','.join(c[:8] for c in unknown)} "
                         f"(served: {','.join(sorted(OMNI_CODES))})")
    if len(langs) > 1 and lid_codes is not None:
        blind = [c for c in langs if c not in lid_codes]
        if blind:
            raise BadRequest(f"language ID cannot recognise {','.join(blind)}; connect with that language alone")
    return langs


def parse_transcribe(raw, langs):
    """?transcribe=ht -> {"ht"}; absent or empty -> every language in langs."""
    if not raw:
        return set(langs)
    want = {c.strip().lower() for c in raw.split(",") if c.strip()}
    stray = sorted(want - set(langs))
    if stray:
        raise BadRequest(f"transcribe must be among langs; not in langs: {clean(','.join(stray), 80)}")
    return want


def parse_rate(raw):
    if not raw:
        return 16000
    try:
        rate = int(raw)
    except ValueError:
        rate = 0
    if rate not in RATES:
        raise BadRequest(f"rate must be one of {', '.join(map(str, RATES))}")
    return rate


# ---------------------------------------------------------------- auth

def auth_mode(env=None):
    """"token" | "open", or None when the server must not start: no credential
    and no explicit STT_OPEN=1. A public URL left open by a missing secret is
    a GPU anyone can run up a bill on, so open has to be asked for."""
    env = os.environ if env is None else env
    if any((env.get(k) or "").strip() for k in CREDENTIALS):
        return "token"
    return "open" if env.get("STT_OPEN") == "1" else None


# The credentials auth_mode looks for (Credentials, in the docstring at the top).
CREDENTIALS = ("STT_TOKEN", "STT_TOKEN_NONPROFIT", "STT_SIGNING_KEY")
NONPROFIT_SUBJECT = "static:nonprofit"


def check_credentials(env=None):
    """Stop at startup on credentials that would be ambiguous: one static token
    for both editions would serve whoever holds it in either."""
    env = os.environ if env is None else env
    plain = (env.get("STT_TOKEN") or "").strip()
    nonprofit = (env.get("STT_TOKEN_NONPROFIT") or "").strip()
    if plain and nonprofit and plain == nonprofit:
        raise SystemExit("[stt] STT_TOKEN and STT_TOKEN_NONPROFIT must differ")


def presented_token(headers, query):
    """The client's token: the Authorization header, else ?token=."""
    auth = (headers.get("Authorization", "") if headers is not None else "") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (query.get("token") or [""])[0]


def subject_for(headers, query, env=None):
    """Who this is ("open", "static" or a signed token's subject), or None to refuse."""
    return credentials_for(headers, query, env)[0]


def credentials_for(headers, query, env=None):
    """(subject or None to refuse, the token's edition claim or None). A signed
    token's claim is its "ed"; STT_TOKEN_NONPROFIT's is "nonprofit"; STT_TOKEN
    and an open server carry none (stack_auth.verify_claims)."""
    import hmac
    import stack_auth
    env = os.environ if env is None else env
    mode = auth_mode(env)
    if mode == "open":
        return "open", None
    if mode is None:
        return None, None
    token = presented_token(headers, query)
    sub, claim = stack_auth.verify_claims(token, (env.get("STT_SIGNING_KEY") or "").strip(),
                                          (env.get("STT_TOKEN") or "").strip())
    if sub is not None:
        return sub, claim
    nonprofit = (env.get("STT_TOKEN_NONPROFIT") or "").strip()
    if token and nonprofit and hmac.compare_digest(token.encode(), nonprofit.encode()):
        return NONPROFIT_SUBJECT, "nonprofit"
    return None, None


# ---------------------------------------------------------------- editions

# EDITION, as the stack's (server/stack_config.py): nonprofit, commercial, or
# both (each connection in the edition its token's "ed" claim names; none: the
# strictest served, stack_auth.connection_edition). It only decides the /speak
# voices: the recogniser, language ID and VAD are permissive in every edition.
# The default here is commercial, not the stack's nonprofit: a deployment that
# says nothing never loads a non-commercial voice (MMS).
EDITIONS = ("nonprofit", "commercial", "both")
DEFAULT_EDITION = "commercial"
CLOSE_EDITION = 4403        # the stack's code for a token of an edition not served here


def service_editions(env=None):
    """EDITION -> the editions served: ["commercial"], ["nonprofit"] or both."""
    env = os.environ if env is None else env
    ed = (env.get("EDITION") or DEFAULT_EDITION).strip().lower()
    if ed not in EDITIONS:
        raise SystemExit(f"[stt] EDITION must be nonprofit, commercial or both (got {clean(ed, 16)!r})")
    return ["nonprofit", "commercial"] if ed == "both" else [ed]


# ---------------------------------------------------------------- language ID

def constrained_choice(probs, keep):
    """The stack's constrained argmax (server.py Pipeline.identify_conf): the
    best of `keep` [(lang, label index)] in the classifier's output `probs`, and
    its share of their mass. Choosing among the room's own languages instead of
    all 107 stops a quiet voice being read as Hindi or Vietnamese."""
    import math
    scores = {code: float(probs[idx]) for code, idx in keep}
    # SpeechBrain hands back log-probabilities; normalising them as if they
    # were plain ones flattens every score to 1/N, so check which space it is.
    mx = max(scores.values())
    weights = {c: math.exp(v - mx) for c, v in scores.items()} if mx <= 0.0 else dict(scores)
    total = sum(weights.values()) or 1.0
    best = max(weights, key=weights.get)
    return best, weights[best] / total


def lid_label_index(lab2ind):
    """VoxLingua107's labels ("ht: Haitian" -> 37) -> {"ht": 37}."""
    out = {}
    for label, idx in lab2ind.items():
        code = str(label).split(":")[0].strip().lower()
        if code and code.isalpha():
            out.setdefault(code, idx)
    return out


# ---------------------------------------------------------------- endpointing

def quietest_cut(buf, window_s=2.0, frame_ms=20):
    """The stack's forced-cut point (server.py quietest_cut): the quietest
    20 ms in the last 2 s, never the live last 300 ms. Omnilingual has no word
    timings, so the stack cuts its languages here too rather than after a sentence."""
    import numpy as np
    frame = max(1, int(VAD_RATE * frame_ms / 1000))
    start = max(0, len(buf) - int(VAD_RATE * window_s))
    tail = buf[start:]
    n = len(tail) // frame
    keep = max(1, int(0.3 * 1000 / frame_ms))
    if n < 2 or n <= keep:
        return len(buf)
    energies = np.abs(tail[: n * frame].reshape(n, frame)).mean(axis=1)
    return start + int(np.argmin(energies[: n - keep])) * frame


class Segmenter:
    """One stream's turn-taking: feed 16 kHz blocks with their speech
    probability, get back finished utterances as (samples, start_ms, end_ms).
    No model inside, so tests drive it directly."""

    def __init__(self, endpoint_ms=None, max_s=None, min_speech_ms=None,
                 short_endpoint_ms=SHORT_TURN_ENDPOINT_MS):
        import numpy as np
        self.np = np
        self.endpoint_ms = ENDPOINT_MS if endpoint_ms is None else endpoint_ms
        self.max_s = MAX_UTTERANCE_S if max_s is None else max_s
        self.min_speech_ms = MIN_SPEECH_MS if min_speech_ms is None else min_speech_ms
        self.short_endpoint_ms = max(self.endpoint_ms, short_endpoint_ms)
        self.buf = np.zeros(0, dtype=np.float32)
        self.buf_start = 0          # stream sample index of buf[0]
        self.total = 0              # samples seen on this stream
        self.quiet_ms = 0.0
        self.speech_ms = 0.0        # speech (VAD > 0.5) in the current turn
        self.speech_seen = False

    def _take(self, n):
        """The first n samples of the buffer as an utterance, with its times."""
        u = self.buf[:n]
        start_ms = int(self.buf_start * 1000 / VAD_RATE)
        end_ms = int((self.buf_start + n) * 1000 / VAD_RATE)
        self.buf = self.buf[n:]
        self.buf_start += n
        return u, start_ms, end_ms

    def feed(self, block, prob):
        np = self.np
        self.buf = np.concatenate([self.buf, block]) if len(self.buf) else np.asarray(block, dtype=np.float32)
        self.total += len(block)
        chunk_ms = len(block) / VAD_RATE * 1000
        if prob > 0.5:
            self.speech_seen = True
            self.quiet_ms = 0.0
            self.speech_ms += chunk_ms
        else:
            self.quiet_ms += chunk_ms
        if not self.speech_seen:
            # Idle: keep a half-second pre-roll so the first word keeps its onset.
            drop = max(0, len(self.buf) - VAD_RATE // 2)
            self.buf, self.buf_start = self.buf[drop:], self.buf_start + drop
            return []
        if len(self.buf) / VAD_RATE >= self.max_s:
            # Still talking: cut at the quietest instant and keep listening.
            out = [self._take(quietest_cut(self.buf))]
            self.quiet_ms = 0.0
            # The rest was all talk (no pause long enough to end a turn).
            self.speech_ms = len(self.buf) / VAD_RATE * 1000
            return out
        need_ms = self.endpoint_ms if self.speech_ms >= self.min_speech_ms else self.short_endpoint_ms
        if self.quiet_ms < need_ms:
            return []
        return [self._end_turn()]

    def _end_turn(self):
        # The speech, not the pause that ended it (a recogniser fills silence
        # with invented words), keeping a short tail so no word loses its release.
        trail = int(VAD_RATE * max(0.0, self.quiet_ms - TRAILING_KEEP_MS) / 1000)
        n = len(self.buf) - trail if 0 < trail < len(self.buf) else len(self.buf)
        out = self._take(n)
        # The trimmed silence is gone from the buffer too: the next turn starts after it.
        self.buf_start += len(self.buf)
        self.buf = self.np.zeros(0, dtype=self.np.float32)
        self.quiet_ms = 0.0
        self.speech_ms = 0.0
        self.speech_seen = False
        return out

    def flush(self):
        """End the turn now (the client's {"type":"flush"}, or end of stream)."""
        if not self.speech_seen or len(self.buf) < VAD_RATE // 4:
            self.buf_start += len(self.buf)
            self.buf = self.np.zeros(0, dtype=self.np.float32)
            self.speech_seen, self.quiet_ms, self.speech_ms = False, 0.0, 0.0
            return []
        return [self._end_turn()]


class PassThrough:
    """AudioIn's resampler for a client that already sends 16 kHz."""

    def process(self, x):
        import numpy as np
        return np.asarray(x, dtype=np.float32)


def audio_input(rate, label):
    """The stack's AudioIn (fixed 96 ms blocks whatever the message size, issue
    #13): 24 kHz resampled as the stack does, 16 kHz passed through."""
    from audio_in import AudioIn
    conn_in = AudioIn(label)
    if rate == VAD_RATE:
        conn_in.rs = PassThrough()
    return conn_in


# ---------------------------------------------------------------- repetition guard

# The fine-tuned 300M card (and the 7B) sometimes turn a fragment under a second
# into 150-200+ characters of one syllable over and over: the LLM decoder loops
# and the pipeline's own stop (a compression check every 250 steps) comes too
# late for a short clip. Speech runs at ~10-18 characters a second in every
# language served here; 30 a second, plus a little slack for a lone word on a
# very short clip, is past anything a person says.
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


def guard_log(action, before, after, audio_s):
    # Lengths only: the text is the speaker's, and is not logged.
    if action:
        print(f"[stt] repetition guard: {action} {before} -> {after} chars "
              f"({audio_s:.1f}s of audio)", flush=True)


# ---------------------------------------------------------------- models

def models_dir():
    return os.environ.get("STT_MODELS", "/opt/models")


class Models:
    """One copy of each model, shared by every connection. Recognition and
    language ID run on one worker thread (Batcher), several connections'
    utterances per call: neither model is documented as thread-safe, and one
    batched call keeps the GPU busier than the same utterances one by one."""

    def __init__(self, device=None, card=None, serve=None, voice_names=None):
        import copy
        import torch
        self.copy = copy
        self.device = device or os.environ.get("STT_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
        self.card = card or os.environ.get("OMNI_CARD", "omniASR_LLM_300M")
        self.serve = serve if serve is not None else served()
        print(f"[stt] device={self.device} torch={torch.__version__} serving {','.join(sorted(self.serve))}", flush=True)
        self.lid_index = {}
        self.omni = None
        # The voices load on a thread of their own, beside the recogniser: on a
        # cold Cloud Run instance Coqui's import alone took ~30 s (2026-10-19),
        # which /listen, the service's first job, should not wait for. /speak
        # waits for voices_ready instead.
        self.voices = None
        self.voices_error = None
        self.voices_ready = threading.Event()
        loader = None
        if "speak" in self.serve:
            names = voice_names if voice_names is not None else voice_list()
            loader = threading.Thread(target=self._load_voices, args=(names,), name="voices-load", daemon=True)
            loader.start()
        else:
            self.voices_ready.set()
        if "listen" in self.serve:
            self.vad = load_vad()
            self.lid, self.lid_index = load_lid(self.device)
            self.omni = load_omni(self.device, self.card)
        elif loader:
            loader.join()

    def _load_voices(self, names):
        try:
            from voices import Voices
            t0 = time.time()
            voices = Voices(self.device, names)
            # (Each voice already spoke once at load; this times a sentence warm.)
            for name in voices.names:
                t1 = time.time()
                voices.synthesise(name, "Bonjou tout moun, mèsi paske nou la jodi a.")
                print(f"[stt] voice {name}: a sentence in {time.time() - t1:.2f}s", flush=True)
            self.voices = voices
            print(f"[stt] voices ready in {time.time() - t0:.0f}s", flush=True)
        except BaseException as e:  # SystemExit from Voices included: /listen carries on without them
            self.voices_error = f"{type(e).__name__}: {clean(e, 200)}"
            print(f"[stt] voices failed to load: {self.voices_error}", flush=True)
        finally:
            self.voices_ready.set()

    def new_vad(self):
        """Silero keeps state between calls, so each stream gets its own copy
        (one shared detector mixed four callers' audio, 2026-09-29)."""
        vad = self.copy.deepcopy(self.vad)
        vad.reset_states()
        return vad

    def identify(self, pcm16k, langs):
        """(lang, confidence) among langs."""
        if len(langs) == 1:
            return langs[0], 1.0
        import torch
        with torch.inference_mode():
            pred = self.lid.classify_batch(torch.tensor(pcm16k).unsqueeze(0))
        probs = pred[0].squeeze()
        return constrained_choice(probs, [(c, self.lid_index[c]) for c in langs])

    def identify_batch(self, items):
        """[(pcm16k, langs), ...] -> [(lang, confidence), ...]: one classify_batch
        for every item that has a choice to make. SpeechBrain takes the true
        lengths (wav_lens, relative to the longest) and pools over them only.
        A lone item goes through identify() unchanged."""
        out = [None] * len(items)
        need = []
        for i, (pcm, langs) in enumerate(items):
            if len(langs) == 1:
                out[i] = (langs[0], 1.0)
            else:
                need.append(i)
        if len(need) == 1 or (need and not LID_BATCH):
            for i in need:
                out[i] = self.identify(*items[i])
            return out
        if need:
            import torch
            longest = max(len(items[i][0]) for i in need)
            wavs = torch.zeros(len(need), longest)
            for row, i in enumerate(need):
                pcm = items[i][0]
                wavs[row, :len(pcm)] = torch.as_tensor(pcm)
            lens = torch.tensor([len(items[i][0]) / longest for i in need])
            with torch.inference_mode():
                pred = self.lid.classify_batch(wavs, lens)
            probs = pred[0].reshape(len(need), -1)
            for row, i in enumerate(need):
                out[i] = constrained_choice(probs[row], [(c, self.lid_index[c]) for c in items[i][1]])
        return out

    def transcribe(self, pcm16k, lang):
        return self.transcribe_batch([(pcm16k, lang)])[0]

    @property
    def length_sensitive(self):
        """Whether a recognition batch pays for mixing lengths (the library's
        own batched decode), so the Batcher groups by length (pick_group)."""
        return not aligned_ok(self.omni)

    def transcribe_batch(self, items):
        """[(pcm16k, lang), ...] -> [text, ...]: one batched decode (omni_batch's
        aligned decode when the card allows it, else the library's), then the
        repetition guard on each text against its own audio length."""
        texts = decode_batch(self.omni, items)
        out = []
        for (pcm, _), text in zip(items, texts):
            audio_s = len(pcm) / VAD_RATE
            kept, action = repetition_guard(text, audio_s)
            guard_log(action, len(text), len(kept), audio_s)
            out.append(kept)
        return out


ALIGNED = os.environ.get("STT_ALIGNED", "1") != "0"


def aligned_ok(engine):
    """omni_batch's aligned decode for this engine's pipeline? (STT_ALIGNED=0: never.)"""
    pipeline = getattr(engine, "omni", None)
    if not ALIGNED or pipeline is None:
        return False
    try:
        import omni_batch
    except ImportError:
        return False
    return omni_batch.supported(pipeline)


def decode_batch(engine, items):
    """The stack engine's texts for [(pcm16k, lang), ...], in order."""
    if not items:
        return []
    if len(items) == 1 or not aligned_ok(engine):
        # One utterance: the library's own decode, exactly as before batching.
        return engine.transcribe_batch(items)
    import omni_batch
    from engines.common import on_device
    from engines.omnilingual import wav_bytes
    with on_device(engine.device):
        texts = omni_batch.transcribe(engine.omni, [wav_bytes(p) for p, _ in items],
                                      [engine.codes[lang] for _, lang in items])
    if len(texts) != len(items):
        raise RuntimeError(f"{len(texts)} texts for {len(items)} utterances")
    return [engine._filtered((t or "").strip()) for t in texts]


def served(env=None):
    """STT_SERVE -> {"listen", "speak"} (default both)."""
    env = os.environ if env is None else env
    want = {p.strip() for p in env.get("STT_SERVE", "listen,speak").split(",") if p.strip()}
    if not want or want - {"listen", "speak"}:
        raise SystemExit("[stt] STT_SERVE must name listen and/or speak")
    return want


def voice_list(env=None):
    """STT_VOICES -> the voices to load: by default every voice an edition
    served here may use (EDITION=commercial: never MMS). Naming a voice no
    served edition may use is an error, not a silent drop."""
    from voices import VOICES, permitted
    env = os.environ if env is None else env
    eds = service_editions(env)
    allowed = [v for v in VOICES if any(v in permitted([v], ed) for ed in eds)]
    raw = env.get("STT_VOICES")
    if raw is None:
        return allowed
    names = [v.strip() for v in raw.split(",") if v.strip()]
    if not names or any(v not in VOICES for v in names):
        raise SystemExit(f"[stt] STT_VOICES must be among {','.join(VOICES)}")
    barred = [v for v in names if v not in allowed]
    if barred:
        raise SystemExit(f"[stt] STT_VOICES: {','.join(barred)} may not load with EDITION="
                         f"{'both' if len(eds) > 1 else eds[0]} (server/licences.py)")
    return names


def default_voice(names, env=None, quiet=False):
    """HT_VOICE when among `names`, else coqui, else the first of them."""
    env = os.environ if env is None else env
    want = env.get("HT_VOICE", "").strip().lower() or "coqui"
    if want in names:
        return want
    if env.get("HT_VOICE") and not quiet:
        print(f"[stt] HT_VOICE={clean(want, 16)} is not loaded; using {names[0]}", flush=True)
    return "coqui" if "coqui" in names else names[0]


def load_vad():
    import torch
    local = os.path.join(models_dir(), "torch", "hub", f"{VAD_REPO.replace('/', '_')}_{VAD_REF}")
    if os.path.isdir(local):
        # Baked into the image: load from disk, no GitHub at cold start.
        vad, _ = torch.hub.load(local, "silero_vad", source="local", trust_repo=True)
    else:
        vad, _ = torch.hub.load(f"{VAD_REPO}:{VAD_REF}", "silero_vad", trust_repo=True)
    return vad


def load_lid(device):
    from huggingface_hub import snapshot_download
    from speechbrain.inference.classifiers import EncoderClassifier
    local = snapshot_download(LID_REPO, revision=LID_REVISION)
    # The model's hyperparams.yaml names the repo again for its checkpoints, so
    # point that at the snapshot too (as the stack does).
    lid = EncoderClassifier.from_hparams(
        source=local, savedir=os.path.join(models_dir(), "voxlingua-ecapa"),
        overrides={"pretrained_path": local}, run_opts={"device": device})
    return lid, lid_label_index(lid.hparams.label_encoder.lab2ind)


def load_omni(device, card):
    """The stack's Omnilingual engine, given just what it reads from a Context.
    The stack treats a failed load as "fall back to Whisper"; here there is
    nothing to fall back to, so it stops the server."""
    from engines.base import Context
    from engines.omnilingual import Omnilingual
    ctx = Context(device=device, models={"omnilingual": {"card": card}},
                  tables={"OMNI_LANGS": OMNI_CODES}, options={"omni": True})
    skip_identity_reorder()
    omni = Omnilingual(ctx)
    omni.load()
    if not omni.available:
        raise SystemExit(f"[stt] Omnilingual ({card}) failed to load; see above")
    return omni


def skip_identity_reorder():
    """Omnilingual's beam search (nbest 1 by default) reorders the decoder's KV
    cache after every step, by an order that with one hypothesis per utterance
    is always 0..B-1; fairseq2 copies the whole cache anyway (index_select per
    layer), a cost that grows with the batch and the utterance. Skipping a
    reorder that keeps every row in place changes nothing else."""
    import torch
    from fairseq2.nn import IncrementalStateBag
    if getattr(IncrementalStateBag.reorder, "_skips_identity", False):
        return
    original = IncrementalStateBag.reorder

    def reorder(self, new_order):
        if new_order.dim() == 1 and torch.equal(
                new_order, torch.arange(new_order.size(0), device=new_order.device, dtype=new_order.dtype)):
            return
        original(self, new_order)
    reorder._skips_identity = True
    IncrementalStateBag.reorder = reorder


# ---------------------------------------------------------------- connection

# The micro-batcher: utterances from every connection, decoded together.
BATCH_MAX = max(1, int(os.environ.get("STT_BATCH_MAX", "8")))
BATCH_WAIT_MS = max(0.0, float(os.environ.get("STT_BATCH_WAIT_MS", "10")))
LID_BATCH = os.environ.get("STT_LID_BATCH", "1") != "0"
BATCH_LOG_S = 60
# Which utterances may share a recognition batch. Omnilingual's LLM decoder
# prefills only the SHORTEST prompt in a batch; a longer item's remaining audio
# frames (50 a second) then go through the decoder one step at a time, as slow
# as generating a token each. So a 2 s and a 12 s utterance together cost ~500
# extra decoder steps, more than decoding the 2 s one alone (the first deploy
# batched by arrival order and was slower than no batching, 2026-10-20).
# pick_group() adds an utterance only when the steps it adds to the batch's loop
# are fewer than the ones it would cost alone: STT_BATCH_GEN_RATIO is the text
# tokens generated per audio frame (~15 characters a second / 50 frames), and
# BATCH_ALONE_STEPS a lone decode's fixed overhead (its prefill and setup) in steps.
FRAME_SAMPLES = 320                # 20 ms: one encoder frame, one decoder position
BATCH_GEN_RATIO = float(os.environ.get("STT_BATCH_GEN_RATIO", "0.3"))
BATCH_ALONE_STEPS = 10


def batch_loop_steps(frames_lo, frames_hi, gen=None):
    """The decoder steps one batch takes: from the end of its shortest prompt
    to the end of its longest prompt's text."""
    gen = BATCH_GEN_RATIO if gen is None else gen
    return (1 + gen) * frames_hi - frames_lo


def pick_group(lengths, max_batch, gen=None, alone=BATCH_ALONE_STEPS):
    """Indices into lengths (samples per waiting utterance, oldest first) of the
    ones to decode together. The oldest always goes (nothing waits forever);
    each later one joins when the steps it adds to the batch are no more than
    it would take on its own."""
    gen = BATCH_GEN_RATIO if gen is None else gen
    if not lengths:
        return []
    frames = [max(1, n // FRAME_SAMPLES) for n in lengths]
    chosen = [0]
    lo = hi = frames[0]
    for j in range(1, len(frames)):
        if len(chosen) >= max_batch:
            break
        f = frames[j]
        nlo, nhi = min(lo, f), max(hi, f)
        added = batch_loop_steps(nlo, nhi, gen) - batch_loop_steps(lo, hi, gen)
        if added <= gen * f + alone:
            chosen.append(j)
            lo, hi = nlo, nhi
    return chosen


class Batcher:
    """One GPU worker thread for every connection's language ID ("lid") and
    recognition ("asr"). A connection submits one utterance and awaits its
    future; the worker takes up to max_batch waiting items of a kind and runs
    them in ONE model call (Models.identify_batch / transcribe_batch, or the
    one-at-a-time identify / transcribe when a model has no batch method),
    then hands each result to the future it came with, on that future's loop.
    With omni_batch's aligned decode (the default for the LLM cards) any
    lengths batch well and the oldest max_batch go together. Otherwise
    (models.length_sensitive) a recognition batch holds utterances of similar
    length (pick_group: the oldest waiting one, and those that make the batch
    cheaper than going alone); the rest wait for the next batch, oldest first.

    Waiting: after the first item the worker waits up to wait_ms for more, but
    only while fewer items wait than there are open streams (each connection
    has at most one utterance in flight, so with one stream there is nothing
    to wait for). Under load the next batch fills while the GPU runs this one.

    Order: language ID first (it is fast, and its message releases the
    client's other captions), then recognition. A failed batch is retried item
    by item, so one bad utterance fails alone. /speak never comes here: it has
    its own threads (VOICE_POOL)."""

    KINDS = ("lid", "asr")

    def __init__(self, models, max_batch=None, wait_ms=None, group_by_length=True):
        self.models = models
        self.group_by_length = group_by_length
        self.max_batch = BATCH_MAX if max_batch is None else max(1, int(max_batch))
        self.wait_s = (BATCH_WAIT_MS if wait_ms is None else max(0.0, float(wait_ms))) / 1000
        self.cond = threading.Condition()
        self.queues = {k: collections.deque() for k in self.KINDS}
        self.streams = 0
        self.stats = {k: {"batches": 0, "items": 0, "max": 0, "busy_s": 0.0, "audio_s": 0.0} for k in self.KINDS}
        self.logged = time.monotonic()
        self.thread = threading.Thread(target=self._run, name="model-batcher", daemon=True)
        self.thread.start()

    # -- the event loop's side

    def opened(self):
        with self.cond:
            self.streams += 1

    def closed(self):
        with self.cond:
            self.streams = max(0, self.streams - 1)
            self.cond.notify()

    def submit(self, kind, pcm, arg):
        """An awaitable for one utterance: (lang, confidence) for "lid" (arg:
        the langs), the text for "asr" (arg: the lang)."""
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        with self.cond:
            self.queues[kind].append((pcm, arg, loop, fut))
            self.cond.notify()
        return fut

    # -- the worker's side

    def _waiting(self):
        return sum(len(q) for q in self.queues.values())

    def _take(self):
        with self.cond:
            while not self._waiting():
                self.cond.wait()
            if self.wait_s > 0:
                deadline = time.monotonic() + self.wait_s
                while True:
                    want = min(self.max_batch, max(1, self.streams))
                    if self._waiting() < want:
                        left = deadline - time.monotonic()
                        if left > 0:
                            self.cond.wait(left)
                            continue
                    break
            out = {"lid": [self.queues["lid"].popleft() for _ in range(min(self.max_batch, len(self.queues["lid"])))]}
            q = self.queues["asr"]
            if self.group_by_length and getattr(self.models, "length_sensitive", True):
                keep = set(pick_group([len(job[0]) for job in q], self.max_batch))
            else:
                keep = set(range(min(self.max_batch, len(q))))
            jobs = list(q)
            q.clear()
            q.extend(job for i, job in enumerate(jobs) if i not in keep)
            out["asr"] = [job for i, job in enumerate(jobs) if i in keep]
            return out

    def _run(self):
        while True:
            taken = self._take()
            for kind in self.KINDS:
                if taken[kind]:
                    self._do(kind, taken[kind])
            self._maybe_log()

    def _call(self, kind, items):
        m = self.models
        if kind == "lid":
            if hasattr(m, "identify_batch"):
                return m.identify_batch(items)
            return [m.identify(p, a) for p, a in items]
        if hasattr(m, "transcribe_batch"):
            return m.transcribe_batch(items)
        return [m.transcribe(p, a) for p, a in items]

    def _do(self, kind, jobs):
        items = [(pcm, arg) for pcm, arg, _, _ in jobs]
        t0 = time.monotonic()
        try:
            results = self._call(kind, items)
            if len(results) != len(jobs):
                raise RuntimeError(f"{len(results)} results for {len(jobs)} items")
            outcomes = [(r, None) for r in results]
        except Exception as e:
            if len(jobs) == 1:
                outcomes = [(None, e)]
            else:
                print(f"[stt] a batch of {len(jobs)} ({kind}) failed ({type(e).__name__}: {clean(e, 120)}); "
                      f"retrying one by one", flush=True)
                outcomes = []
                for item in items:
                    try:
                        outcomes.append((self._call(kind, [item])[0], None))
                    except Exception as e1:
                        outcomes.append((None, e1))
        st = self.stats[kind]
        st["batches"] += 1
        st["items"] += len(jobs)
        st["max"] = max(st["max"], len(jobs))
        st["busy_s"] += time.monotonic() - t0
        st["audio_s"] += sum(len(p) for p, _ in items) / VAD_RATE
        for (_, _, loop, fut), (result, err) in zip(jobs, outcomes):
            try:
                loop.call_soon_threadsafe(_resolve, fut, result, err)
            except RuntimeError:
                pass  # that connection's loop is gone: nobody to tell

    def _maybe_log(self):
        now = time.monotonic()
        if now - self.logged < BATCH_LOG_S:
            return
        self.logged = now
        parts = []
        for kind, st in self.stats.items():
            if st["batches"]:
                parts.append(f"{kind} {st['items']} in {st['batches']} batches "
                             f"(mean {st['items'] / st['batches']:.2f}, max {st['max']}, busy {st['busy_s']:.1f}s "
                             f"for {st['audio_s']:.0f}s of audio)")
                self.stats[kind] = {"batches": 0, "items": 0, "max": 0, "busy_s": 0.0, "audio_s": 0.0}
        if parts:
            print(f"[stt] batcher, last {BATCH_LOG_S}s: {'; '.join(parts)}; streams {self.streams}", flush=True)


def _resolve(fut, result, err):
    if fut.done():  # the connection gave up on it (closed)
        return
    if err is not None:
        fut.set_exception(err)
    else:
        fut.set_result(result)


_BATCHERS = {}
_BATCHERS_LOCK = threading.Lock()


def batcher_for(models):
    """The one Batcher per Models (one GPU worker for the whole server)."""
    with _BATCHERS_LOCK:
        b = _BATCHERS.get(id(models))
        if b is None or b.models is not models:
            b = _BATCHERS[id(models)] = Batcher(models)
        return b


def clean(value, n=64):
    return "".join(ch if ch.isprintable() else "?" for ch in str(value))[:n]


async def recognise(models, utt, langs, transcribe, send, batcher=None):
    """One utterance: send its language, then (when wanted) its words.
    Returns whether a transcript was sent."""
    batcher = batcher or batcher_for(models)
    pcm, start_ms, end_ms = utt
    if len(langs) == 1:
        lang, conf = langs[0], 1.0
    else:
        lang, conf = await batcher.submit("lid", pcm, langs)
    span = {"lang": lang, "confidence": round(conf, 3), "start_ms": start_ms, "end_ms": end_ms}
    await send({"type": "language", **span})
    if lang not in transcribe:
        return False
    text = await batcher.submit("asr", pcm, lang)
    if not text:
        return False
    await send({"type": "inputTranscript", "text": text, **span})
    return True


async def handle(ws, models, sub="open"):
    """One /listen connection, after auth and admission."""
    from urllib.parse import urlparse, parse_qs
    from audio_in import vad_block
    q = parse_qs(urlparse(ws.request.path).query)
    try:
        langs = parse_langs((q.get("langs") or [""])[0], set(models.lid_index))
        rate = parse_rate((q.get("rate") or [""])[0])
        transcribe = parse_transcribe((q.get("transcribe") or [""])[0], langs)
    except BadRequest as e:
        print(f"[stt] {clean(sub, 24)}: refused: {clean(e, 200)}", flush=True)
        await ws.send(json.dumps({"type": "error", "detail": str(e)}))
        await ws.close(code=CLOSE_BAD_REQUEST, reason="bad request")
        return
    await ws.send(json.dumps({"type": "hello", "langs": langs, "rate": rate}))
    who = clean(sub, 24)
    print(f"[stt] {who}: listening, langs={','.join(langs)} rate={rate} "
          f"transcribe={','.join(c for c in langs if c in transcribe)}", flush=True)

    conn_in = audio_input(rate, who)
    seg = Segmenter()
    vad = models.new_vad()
    # The model works through a queue on its own task, so this loop keeps
    # reading the socket (and the VAD keeps time) while an utterance is decoded.
    queue = asyncio.Queue()
    heard = {"n": 0, "audio_s": 0.0, "busy_s": 0.0}
    batcher = batcher_for(models)

    async def worker():
        while True:
            item = await queue.get()
            if item == "flush":
                await ws.send(json.dumps({"type": "flushed"}))
                continue
            t0 = time.monotonic()
            try:
                said = await recognise(models, item, langs, transcribe,
                                       lambda m: ws.send(json.dumps(m, ensure_ascii=False)), batcher)
            except Exception as e:  # one bad utterance must not end the session
                print(f"[stt] {who}: recognition failed: {type(e).__name__}: {clean(e, 200)}", flush=True)
                await ws.send(json.dumps({"type": "error", "detail": "recognition failed for one utterance"}))
                continue
            heard["busy_s"] += time.monotonic() - t0
            heard["audio_s"] += len(item[0]) / VAD_RATE
            if said:
                heard["n"] += 1

    def enqueue(utts):
        for utt in utts:
            if queue.qsize() >= MAX_PENDING:
                dropped = queue.get_nowait()
                if dropped == "flush":
                    queue.put_nowait(dropped)
                else:
                    print(f"[stt] {who}: behind, dropped a {len(dropped[0]) / VAD_RATE:.1f}s utterance", flush=True)
            queue.put_nowait(utt)

    task = asyncio.create_task(worker())
    batcher.opened()
    try:
        async for msg in ws:
            if isinstance(msg, str):
                try:
                    kind = json.loads(msg).get("type")
                except Exception:
                    kind = None
                if kind == "flush":
                    enqueue(seg.flush())
                    queue.put_nowait("flush")
                else:
                    await ws.send(json.dumps({"type": "error", "detail": "text messages: only {\"type\":\"flush\"}"}))
                continue
            for block in conn_in.feed(msg):
                enqueue(seg.feed(block, vad_block(vad, block)))
        # Disconnected: nothing more can be sent, so the unfinished turn is dropped.
    finally:
        batcher.closed()
        task.cancel()
        if heard["audio_s"]:
            print(f"[stt] {who}: closed; {heard['n']} transcripts, {heard['audio_s']:.0f}s of speech, "
                  f"real-time factor {heard['busy_s'] / heard['audio_s']:.2f}", flush=True)


# ---------------------------------------------------------------- /speak

# Synthesis runs here, not on the Batcher's thread: a sentence being voiced never waits
# behind an utterance being transcribed. Two threads, one per voice; each
# voice's own lock makes two requests on the same voice take turns.
VOICE_POOL = ThreadPoolExecutor(2, thread_name_prefix="voice")


async def speak_one(voices, voice, text, req_id, send):
    """One request: each sentence's audio as soon as it is made, then "done".
    Returns (sentences spoken, audio ms)."""
    from voices import prepare
    loop = asyncio.get_running_loop()
    t0 = time.monotonic()
    first_ms = None
    spoken, nbytes, failed = 0, 0, 0
    tag = {"id": req_id} if req_id is not None else {}
    for piece in prepare(text):
        pcm = await loop.run_in_executor(VOICE_POOL, voices.synthesise, voice, piece)
        if not pcm:
            failed += 1
            continue
        if first_ms is None:
            first_ms = int((time.monotonic() - t0) * 1000)
        await send({"type": "sentence", **tag, "index": spoken, "bytes": len(pcm)})
        for off in range(0, len(pcm), SPEAK_FRAME_BYTES):
            await send(pcm[off:off + SPEAK_FRAME_BYTES])
        spoken += 1
        nbytes += len(pcm)
    audio_ms = nbytes * 1000 // 48000
    if failed and not spoken:
        await send({"type": "error", **tag, "detail": "the voice could not say that"})
    await send({"type": "done", **tag, "voice": voice, "sentences": spoken, "audio_ms": audio_ms,
                "first_audio_ms": first_ms, "ms": int((time.monotonic() - t0) * 1000)})
    return spoken, audio_ms


def unavailable(voice, edition=None):
    """Why a voice cannot be used: not licensed for the connection's edition, else not loaded."""
    from voices import permitted
    if edition and not permitted([voice], edition):
        return f"voice {voice} is not available in the {edition} edition"
    return f"voice {voice} is not loaded here"


def parse_speak(msg, default_voice, names, edition=None):
    """A client text message -> (text, voice, id), or BadRequest. `names`: the
    voices this connection may use (loaded, and permitted in its edition)."""
    from voices import parse_voice
    try:
        m = json.loads(msg)
    except Exception:
        raise BadRequest('send {"type":"speak","text":"..."}')
    if not isinstance(m, dict) or m.get("type") != "speak":
        raise BadRequest('send {"type":"speak","text":"..."}')
    text = m.get("text")
    if not isinstance(text, str) or not text.strip():
        raise BadRequest("text is required")
    if len(text) > SPEAK_MAX_CHARS:
        raise BadRequest(f"text is at most {SPEAK_MAX_CHARS} characters")
    try:
        voice = parse_voice(m.get("voice") if isinstance(m.get("voice"), str) else "", default_voice)
    except ValueError as e:
        raise BadRequest(str(e))
    if voice not in names:
        raise BadRequest(unavailable(voice, edition))
    req_id = m.get("id")
    req_id = clean(req_id, 64) if isinstance(req_id, (str, int)) and not isinstance(req_id, bool) else None
    return text, voice, req_id


async def handle_speak(ws, voices, sub="open", env=None, edition=None):
    """One /speak connection, after auth and admission, in `edition` (guarded:
    stack_auth.connection_edition; None: as a token without a claim would be).

    Only the voices that edition may use are offered (hello) or spoken. A voice
    it may not use is refused like one that is not loaded, never swapped for
    another: the client asked for that voice and can fall back itself (Talk to
    Gemini; Live Translation to captions). With no voice named, the default
    (HT_VOICE) is used when permitted, else the first permitted voice, as the
    stack's voice chain skips a voice the edition may not use."""
    from urllib.parse import urlparse, parse_qs
    from voices import parse_voice, permitted, LANG
    import stack_auth
    if edition is None:
        edition = stack_auth.connection_edition(service_editions(env), None)
    q = parse_qs(urlparse(ws.request.path).query)
    names = permitted(voices.names, edition)
    if not names:
        await ws.send(json.dumps({"type": "error", "detail": f"no voice here is available in the {edition} edition"}))
        await ws.close(code=CLOSE_EDITION, reason=f"no voice for the {edition} edition")
        return
    try:
        voice = parse_voice((q.get("voice") or [""])[0], default_voice(names, env, quiet=True))
        if voice not in names:
            raise ValueError(unavailable(voice, edition))
    except ValueError as e:
        await ws.send(json.dumps({"type": "error", "detail": str(e)}))
        await ws.close(code=CLOSE_BAD_REQUEST, reason="bad request")
        return
    await ws.send(json.dumps({"type": "hello", "lang": LANG, "voices": names, "voice": voice, "rate": 24000,
                              "edition": edition}))
    who = clean(sub, 24)

    async def send(m):
        await ws.send(m if isinstance(m, bytes) else json.dumps(m, ensure_ascii=False))

    n, audio_ms = 0, 0
    async for msg in ws:
        if isinstance(msg, bytes):
            await send({"type": "error", "detail": "send text messages: {\"type\":\"speak\",\"text\":\"...\"}"})
            continue
        try:
            text, v, req_id = parse_speak(msg, voice, names, edition)
        except BadRequest as e:
            await send({"type": "error", "detail": str(e)})
            continue
        try:
            said, ms = await speak_one(voices, v, text, req_id, send)
        except Exception as e:  # one bad request must not end the socket
            if type(e).__name__.startswith("Connection"):
                raise
            print(f"[stt] {who}: speech failed: {type(e).__name__}: {clean(e, 200)}", flush=True)
            await send({"type": "error", **({"id": req_id} if req_id is not None else {}),
                        "detail": "speech failed"})
            continue
        n += 1
        audio_ms += ms
        # Lengths and timings only: the text is the client's, and is not logged.
        print(f"[stt] {who}: spoke {len(text)} chars, {said} sentences, {ms} ms of audio ({v})", flush=True)
    if n:
        print(f"[stt] {who}: speak closed; {n} requests, {audio_ms / 1000:.0f}s of audio", flush=True)


# ---------------------------------------------------------------- serving

LIMITS = None
SPEAK_LIMITS = None
ENDPOINTS = ("/listen", "/speak")


async def guarded(ws, models):
    """Auth, admission and a fence: one client's failure never reaches the serve loop."""
    from urllib.parse import urlparse, parse_qs
    url = urlparse(ws.request.path)
    path = url.path.rstrip("/")
    open_paths = [p for p in ENDPOINTS if p.lstrip("/") in models.serve]
    if path not in open_paths:
        await ws.close(code=CLOSE_BAD_REQUEST, reason=f"the endpoints are {' and '.join(open_paths)}")
        return
    sub, claim = credentials_for(ws.request.headers, parse_qs(url.query))
    if sub is None:
        print("[stt] refused: bad or missing token", flush=True)
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="unauthorized")
        return
    edition = None
    if path == "/speak":
        # The edition only matters for the voices; /listen is the same in all.
        import stack_auth
        served_eds = service_editions()
        edition = stack_auth.connection_edition(served_eds, claim)
        if edition is None:
            print(f"[stt] refused {clean(sub, 24)}: its token is for the {claim} edition; this server "
                  f"serves {'/'.join(served_eds)}", flush=True)
            await ws.close(code=CLOSE_EDITION, reason=f"this server does not serve the {claim} edition")
            return
    limits = SPEAK_LIMITS if path == "/speak" else LIMITS
    why = limits.admit(sub)
    if why:
        await ws.close(code=CLOSE_BUSY, reason=why)
        return
    try:
        if path == "/speak":
            ready = getattr(models, "voices_ready", None)
            if ready is not None and not ready.is_set():
                # Still loading (a cold start): wait rather than refuse.
                await asyncio.get_running_loop().run_in_executor(None, ready.wait, VOICES_WAIT_S)
            if models.voices is None:
                await ws.send(json.dumps({"type": "error", "detail": "the voices are not available on this server"}))
                await ws.close(code=CLOSE_UNAVAILABLE, reason="voices unavailable")
                return
            await handle_speak(ws, models.voices, sub, edition=edition)
        else:
            await handle(ws, models, sub)
    except Exception as e:
        print(f"[stt] client ended: {type(e).__name__}: {clean(e, 200)}", flush=True)
    finally:
        limits.release(sub)


def warmup(models):
    """The first decode builds kernels and caches; pay it before the port opens."""
    import numpy as np
    t0 = time.time()
    if models.omni is not None:
        rng = np.random.default_rng(0)
        noise = (rng.standard_normal(VAD_RATE * 2) * 0.01).astype(np.float32)
        models.transcribe(noise, "en")
        if len(models.lid_index) > 1:
            models.identify(noise, ["en", "ht"])
    # (The voices warm themselves on their loading thread: Models._load_voices.)
    print(f"[stt] warm in {time.time() - t0:.1f}s", flush=True)


async def main():
    mode = auth_mode()
    if mode is None:
        raise SystemExit("[stt] set STT_TOKEN, STT_TOKEN_NONPROFIT or STT_SIGNING_KEY, or STT_OPEN=1 for an open test server")
    check_credentials()
    eds = service_editions()          # a bad EDITION stops here, before any model loads
    print(f"[stt] edition: {'both' if len(eds) > 1 else eds[0]}", flush=True)
    t0 = time.time()
    models = Models()
    warmup(models)
    global LIMITS, SPEAK_LIMITS
    import stack_auth
    n = int(os.environ.get("STT_MAX_CONNECTIONS", "8"))
    LIMITS = stack_auth.Limits(per_client=n, total=n)
    k = int(os.environ.get("STT_MAX_SPEAKERS", "4"))
    SPEAK_LIMITS = stack_auth.Limits(per_client=k, total=k)

    import websockets
    from http import HTTPStatus

    with open(os.path.join(HERE, "mic.html"), encoding="utf-8") as fh:
        mic_page = fh.read()

    def http(connection, request):
        # 200 once the models are loaded: the port only opens after that.
        path = request.path.split("?")[0]
        if path == "/health":
            return connection.respond(HTTPStatus.OK, "ok\n")
        if path == "/mic":
            # The page holds no secret: the token is typed into it.
            resp = connection.respond(HTTPStatus.OK, mic_page)
            resp.headers["Content-Type"] = "text/html; charset=utf-8"
            resp.headers["Cache-Control"] = "no-store"
            return resp
        return None

    port = int(os.environ.get("PORT", "8080"))
    # Cloud Run's front end closes idle connections, and keepalive pings from a
    # busy event loop have killed sessions in the stack: the client pings, or
    # audio flows, so the server sends none.
    async with websockets.serve(lambda ws: guarded(ws, models), "0.0.0.0", port,
                                max_size=MAX_FRAME_BYTES, ping_interval=None, process_request=http):
        voices = "; voices loading" if "speak" in models.serve and not models.voices_ready.is_set() else (
            f"; voices {','.join(models.voices.names)}, default {default_voice(models.voices.names)}" if models.voices else "")
        print(f"[stt] ready on :{port} ({mode}; card {models.card}{voices}; loaded in {time.time() - t0:.0f}s)",
              flush=True)
        await asyncio.Future()


def fetch():
    """Image build: load every model once, by the same code the server runs, so
    each lands in the cache the server will look in (deploy.sh, Dockerfile).
    The voices of EDITION, which defaults to both here (the Dockerfile's ARG):
    the image holds the weights; the running service's EDITION decides what
    loads. Build with EDITION=commercial for an image without MMS's weights."""
    env = dict(os.environ)
    env.setdefault("EDITION", "both")
    models = Models(device="cpu", serve={"listen", "speak"}, voice_names=voice_list(env))
    models.voices_ready.wait()
    if models.voices is None:
        raise SystemExit(f"[stt] voices: {models.voices_error}")
    print("[stt] models fetched", flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--fetch"]:
        fetch()
    else:
        asyncio.run(main())
