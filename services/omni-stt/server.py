#!/usr/bin/env python3
"""Hosted speech to text: Meta Omnilingual ASR, with spoken-language ID among
the languages a room actually uses; and Haitian Creole voices (/speak). No translation.

    STT_TOKEN=... python3 services/omni-stt/server.py          # port $PORT, default 8080
    STT_OPEN=1    python3 services/omni-stt/server.py          # no token (a laptop test only)

Protocol:

    client connects  wss://host/listen?langs=ht,en[&rate=24000][&transcribe=ht|none]
                     Authorization: Bearer <token>, or (a browser, which cannot
                     set that header) the subprotocols "omni-stt" and
                     "bearer.<token>": Sec-WebSocket-Protocol: omni-stt, bearer.<token>
                     (the server answers "omni-stt"). ?token= still works but is
                     deprecated: URLs are logged (Cloud Run's request log too).
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
                     With STT_PARTIALS=1 (off by default; partials.py), while a piece is
                     still being spoken, about every STT_PARTIAL_MS of audio:
                     {"type":"partial","text":"...","lang":"ht","confidence":0.93,
                      "start_ms":1200,"end_ms":2700}   the whole current hypothesis
                     {"type":"stable","text":"...","delta":"...", ...same fields}
                                          the prefix two passes agreed on (never retracted)
                     With STT_CTC_STREAM=1 and ?stream=ctc[&lookahead=1|2] on a km or lo
                     connection (ctc_stream.py): the hello adds "stream": {...}, and
                     about every 500 ms of speech, connection-wide:
                     {"type":"partial","track":"ctc","text":<revisable tail>,"lang":"km",
                      "start_ms":...,"end_ms":...}
                     {"type":"committed","track":"ctc","text":<newly committed text>,
                      "lang":"km","start_ms":...,"end_ms":...,"end":false}   never revised

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
    GET /info        what this service offers, as JSON (service_info): the model
                     ("300m", "7b", "3b"), the languages /listen serves, and the
                     /speak voices; with the token (the Authorization header) also
                     the edition that token is served in and the voices it may use
    GET /mic         a microphone test page (mic.html): speak, see each transcript

Per utterance, the stack's own pipeline minus the translation (server/server.py):
Silero VAD ends a turn after ENDPOINT_MS of quiet (200 ms; a turn with less
than MIN_SPEECH_MS of speech waits longer; past CUT_EARLY_S a shorter pause
will do), with a forced cut by MAX_UTTERANCE_S (10 s) at the best pause of the
last CUT_WINDOW_S (3.5 s, at most a third of the cap; see pause_cut), the
rest kept for the next utterance; VoxLingua107 picks the
language, but only among ?langs (one language: no guess at all); Omnilingual
transcribes with that language's code. The recogniser is the stack's engine
(server/engines/omnilingual.py), the audio input its AudioIn (server/audio_in.py),
and the token check its stack_auth.py, so a fix there is a fix here.

?transcribe (default: every language in ?langs) names the languages whose
utterances are transcribed; the others get only their "language" message
(?transcribe=none: every utterance gets only that, language ID alone). A
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
counts as a "nonprofit" claim; a token without a claim is commercial in every
edition, so a non-profit-only server refuses it on /speak with 4403: speak_edition),
STT_VOICES (the voices loaded, default: every one EDITION allows), STT_MAX_SPEAKERS (open /speak
sockets, default 4), STT_SERVE ("listen,speak" by default; "speak" skips the
recogniser's models, for a laptop test of the voices), STT_TOKEN, STT_TOKEN_NONPROFIT,
STT_SIGNING_KEY (Credentials, below), STT_OPEN=1,
PORT, STT_DEVICE (default: cuda when torch sees one, else cpu), OMNI_CARD,
STT_MAX_CONNECTIONS, STT_MAX_PENDING, ENDPOINT_MS (default 200), MAX_UTTERANCE_S
(default 10.0), MIN_SPEECH_MS (default 1000), CUT_WINDOW_S (default 3.5), CUT_DIP_PROB
(0.5), CUT_DIP_MS (96), CUT_ENDPOINT_MS (200): where a forced cut lands, CUT_EARLY_S
(4.0): the progressive pause cut (Endpointing, below), STT_MODELS (the baked models).
STT_BATCH_MAX (default 8) and STT_BATCH_WAIT_MS (default 10): the GPU micro-batcher
(Batcher); STT_LID_BATCH=0 runs language ID one utterance at a time inside a batch;
STT_ALIGNED=0 decodes batches with the library's own batched call (omni_batch.py
says why the default is not that); STT_BATCH_GEN_RATIO tunes the length grouping
that path needs (pick_group).
STT_MAX_CHARS_PER_S (default 30) and STT_MAX_REPEATS (default 6): the repetition
guard (repetition_guard).
STT_CTC_STREAM=1 (default 0): load the streaming track's CTC card beside the
recogniser (ctc_stream.py; STT_CTC_CARD, default omniASR_CTC_3B; STT_CTC_LANGS,
default km,lo; STT_CTC_CHUNK_MS 500, STT_CTC_LEFT_MS 8000, STT_CTC_LOOKAHEAD_MS
2000: a connection's ?lookahead=1|2 overrides it; STT_CTC_QUIET_MS 2000: the pass
rhythm while the VAD hears nothing; STT_CTC_DITHER 1e-4; STT_CTC_BATCH_MAX 16).
STT_DENOISE=1 (default 0): a spectral noise reducer in front of the VAD, per
connection (denoise.py; STT_DENOISE_NR_DB, STT_DENOISE_TRACK_S,
STT_DENOISE_OVERSUB tune it). For a distant or noisy microphone; off by default
because it can cost a little on clean close-mic audio (README, Noisy input).

Credentials, any or all; each app gets its own, and with it its edition:

  STT_SIGNING_KEY      the stack's short-lived signed tokens (stack_auth.py), whose
                       "ed" claim names the edition: what a server can mint per
                       connection uses (Lithos Talk's Worker: "commercial"). Their
                       "aud": "omni-stt" (this service only; a stack refuses it)
                       or "stack" (what issuers mint today; still accepted).
  STT_TOKEN_NONPROFIT  a static token whose connections are served as non-profit:
                       for an app an operator configures by hand (Live Translation,
                       a non-profit's app, pastes it into its settings). Signed
                       tokens cannot stand in there: they live at most a day.
  STT_TOKEN            the original static token, no edition: commercial, so a
                       client that still sends it keeps working and never gains a
                       non-commercial voice (on a non-profit-only server, which has
                       no commercial voices to give, its /speak is refused, 4403;
                       its /listen is served as ever).

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
import partials  # noqa: E402  (beside this file, as omni_batch is)
import ctc_stream  # noqa: E402

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
    # Cape Verdean Creole (Kabuverdianu): in omnilingual-asr 0.1.0's lang_ids; not in VoxLingua107,
    # so it is served alone (?langs=kea), like Tagalog (eval/2026-10-language-short-check).
    "kea": "kea_Latn",
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
# second of everyone's captions. 200 ms of quiet ends a turn (a breath between
# clauses is enough), and a speaker who never pauses is cut by 10 s, at the best
# pause of the last few seconds (CUT_WINDOW_S, below).
# Measured on five minutes of continuous news speech
# (eval/2026-10-continuous-ht): a presenter takes 21 breaths a minute of
# 200 ms or more but only 6 of 500 ms, so with 700 ms / 15 s the cap did the
# cutting (12.7 s pieces, first audio at 19.5 s, each piece 18.2 s behind);
# 200 ms / 10 s / 1 s of minimum speech gave 3.8 s pieces, first audio at
# 8.4 s, 9.1 s behind. The trade-off: a short piece gives the translator less
# to work out a misheard name or phrase from (quality 2.52 -> 2.21 on a 0-3
# scale) unless it gets context, which the companion apps now send (the
# previous pieces and the last translation, as context only: 2.52-2.67).
ENDPOINT_MS = int(os.environ.get("ENDPOINT_MS", "200"))
MAX_UTTERANCE_S = float(os.environ.get("MAX_UTTERANCE_S", "10.0"))
# A turn with less speech than this is not ended by a short pause: VoxLingua107
# picks a language from the whole clip, and on a lone syllable ("wi", "OK") or
# a cough its choice is close to a coin toss -- and a wrong "language" message
# sends that utterance to the wrong recogniser in the client. So a short turn
# waits up to SHORT_TURN_ENDPOINT_MS (the old 700 ms) for more speech, which
# then joins it (the gap is a normal in-turn pause, not padding); a word that
# really stands alone still goes out, as late as it did before this change.
# Merging beats skipping the language ID: the client needs every utterance
# named to release what it holds, and beats a guess: one-word answers are
# where a room's languages are most alike. 1 s (was 400 ms) with the 200 ms
# endpoint: a 200 ms breath comes after a phrase as often as after a sentence,
# and a sub-second fragment is both a poor language ID clip and a poor piece
# to translate; on the news clip it took the pieces under 1.5 s from 9 to 3
# and the median from 3.3 s to 3.8 s. The 700 ms wait stays: a phrase under
# 1 s followed by a 200-700 ms breath joins the next one, and a word that
# really stands alone still goes out 700 ms after it ends, as before.
MIN_SPEECH_MS = int(os.environ.get("MIN_SPEECH_MS", "1000"))
SHORT_TURN_ENDPOINT_MS = 700
TRAILING_KEEP_MS = 250
# Where a forced cut lands. A speaker who never pauses for ENDPOINT_MS still
# breathes, or lets the VAD's speech probability sag between phrases, and that
# is where a cut belongs: at MAX_UTTERANCE_S the Segmenter looks back over the
# last CUT_WINDOW_S for runs of Silero's 32 ms windows under CUT_DIP_PROB that
# last CUT_DIP_MS or more, and cuts in the longest (then the lowest, then the
# latest), at its quietest 20 ms. Only when no such dip exists does it fall back
# to the old rule (the quietest 20 ms of the last 2 s: quietest_cut), which on
# unbroken speech is often inside a word: a 20 ms energy minimum is as likely a
# stop consonant's closure as a gap. The audio after the cut stays in the buffer
# and starts the next utterance: nothing lost, nothing sent twice.
# CUT_ENDPOINT_MS: inside that last window a shorter pause (this much quiet)
# ends the turn at once, instead of waiting for the cap to cut back to it.
# CUT_WINDOW_S=0 restores the old forced cut. (The window is at most a third
# of the cap: 3.33 s with the 10 s cap, so the near-cap rule runs from 6.67 s.)
CUT_WINDOW_S = float(os.environ.get("CUT_WINDOW_S", "3.5"))
CUT_DIP_PROB = float(os.environ.get("CUT_DIP_PROB", "0.5"))
CUT_DIP_MS = int(os.environ.get("CUT_DIP_MS", "96"))
CUT_ENDPOINT_MS = int(os.environ.get("CUT_ENDPOINT_MS", "200"))
# Progressive pause cut. A piece that has run past CUT_EARLY_S is already long
# enough to translate, so from there the quiet that ends it falls, in a
# straight line, from ENDPOINT_MS at CUT_EARLY_S to CUT_ENDPOINT_MS at the cap
# (Segmenter._need_ms): the longer a piece runs, the shorter the breath that
# ends it, and it usually ends at a breath of its own well before the cap
# instead of at the cap's look-back. The VAD runs in 96 ms blocks, so the
# line is really a few steps (with 700 ms -> 200 ms over 4 s -> 15 s: 672,
# 576, 480, 384, 288 ms, each about 2 s later). It matters only when
# ENDPOINT_MS is above CUT_ENDPOINT_MS (a 500 ms endpoint for a language whose
# recogniser wants longer pieces, say): with the 200 ms default the two are
# equal and nothing changes. 0 disables it, as does CUT_ENDPOINT_MS=0.
CUT_EARLY_S = float(os.environ.get("CUT_EARLY_S", "4.0"))
# Silero's probability falls a window or two after the speech stops: a dip's
# quiet starts up to this much before its first low window.
VAD_LAG_MS = 64
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
    """?transcribe=ht -> {"ht"}; absent or empty -> every language in langs;
    "none" -> no language: language ID only (a client that hands the speech to
    another recogniser once it hears the switch, e.g. Haitian Creole to Amazon
    Transcribe beside the 7B service)."""
    if not raw:
        return set(langs)
    if raw.strip().lower() == "none":
        return set()
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


# A signed token's "aud" accepted here: "omni-stt" (a token for this service
# only, which a stack refuses) and, for the tokens issuers mint today, "stack".
# Issuers (Lithos Talk's Worker, Live Translation) should switch to "omni-stt";
# "stack" stays accepted until they have.
AUDIENCES = ("omni-stt", "stack")

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


# A browser's WebSocket cannot send an Authorization header, so mic.html (and
# any browser client) offers two subprotocols instead: AUTH_PROTOCOL, which
# the server picks and echoes, and TOKEN_PROTOCOL_PREFIX + the token, which it
# reads and never echoes. Request headers stay out of Cloud Run's request
# log; a ?token= URL does not. (The stack's own clients use the header; its
# stack_auth.presented_token also still takes ?key= and a /<token>/ path from
# older clients, for the same reason this keeps ?token=.)
AUTH_PROTOCOL = "omni-stt"
TOKEN_PROTOCOL_PREFIX = "bearer."


def offered_protocols(headers):
    """The subprotocols a client offered (Sec-WebSocket-Protocol, every header line)."""
    if headers is None:
        return []
    get_all = getattr(headers, "get_all", None)
    lines = get_all("Sec-WebSocket-Protocol") if get_all else [headers.get("Sec-WebSocket-Protocol")]
    return [p.strip() for line in lines if line for p in line.split(",") if p.strip()]


def select_subprotocol(connection, subprotocols):
    """websockets' hook: AUTH_PROTOCOL when offered (a browser fails the
    handshake unless the server picks one of its subprotocols), else none."""
    return AUTH_PROTOCOL if AUTH_PROTOCOL in subprotocols else None


def presented_token_via(headers, query):
    """(the client's token, how it came: "header" | "protocol" | "query" | "none").
    The Authorization header, else the bearer.<token> subprotocol, else ?token=
    (deprecated: the URL is logged)."""
    auth = (headers.get("Authorization", "") if headers is not None else "") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip(), "header"
    for p in offered_protocols(headers):
        if p.startswith(TOKEN_PROTOCOL_PREFIX) and len(p) > len(TOKEN_PROTOCOL_PREFIX):
            return p[len(TOKEN_PROTOCOL_PREFIX):], "protocol"
    token = (query.get("token") or [""])[0]
    return token, ("query" if token else "none")


def presented_token(headers, query):
    """The client's token (presented_token_via, without the how)."""
    return presented_token_via(headers, query)[0]


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
                                          (env.get("STT_TOKEN") or "").strip(), audience=AUDIENCES)
    if sub is not None:
        return sub, claim
    nonprofit = (env.get("STT_TOKEN_NONPROFIT") or "").strip()
    if token and nonprofit and hmac.compare_digest(token.encode(), nonprofit.encode()):
        return NONPROFIT_SUBJECT, "nonprofit"
    return None, None


# ---------------------------------------------------------------- editions

# EDITION, as the stack's (server/stack_config.py): nonprofit, commercial, or
# both (each connection in the edition its token's "ed" claim names; none:
# commercial, speak_edition). It only decides the /speak
# voices: the recogniser, language ID and VAD are permissive in every edition.
# The default here is commercial, not the stack's nonprofit: a deployment that
# says nothing never loads a non-commercial voice (MMS).
EDITIONS = ("nonprofit", "commercial", "both")
DEFAULT_EDITION = "commercial"
CLOSE_EDITION = 4403        # the stack's code for a token of an edition not served here


def speak_edition(served, claim, open_server=False):
    """The edition a /speak connection is served in, or None to refuse it (4403).

    A token with an "ed" claim (a signed token's, or STT_TOKEN_NONPROFIT's
    "nonprofit"): stack_auth.connection_edition, as the stack. A token
    WITHOUT one (STT_TOKEN, a signed token whose issuer names none) is
    commercial: served as commercial wherever commercial is served, and
    refused on a non-profit-only server rather than given its non-commercial
    voices (the stack's rule, "the strictest edition served", would make it
    nonprofit there: right for a stack's own LAN token, not for a hosted
    service whose claim-less tokens are commercial apps'). An open server
    (STT_OPEN=1, a laptop test: no credential at all) keeps the stack's rule."""
    import stack_auth
    if claim is None and not open_server:
        return "commercial" if "commercial" in served else None
    return stack_auth.connection_edition(served, claim)


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


def pause_cut(buf, buf_start, probs, window_s, dip_prob=0.5, dip_ms=96, frame_ms=20):
    """Where to force-cut buf (an index into it), or None when the last
    window_s holds no pause. probs: (stream start sample, end sample, speech
    probability) per VAD window, oldest first; buf_start: the stream sample of
    buf[0]. A pause is a run of windows under dip_prob lasting dip_ms or more,
    after the buffer's first speech (never the quiet it starts with: that
    would send a sliver of pre-roll as an utterance); the longest wins (then the lowest mean probability, then the latest), and
    the cut goes at its quietest frame_ms (ties: the one nearest the middle),
    searched from VAD_LAG_MS before the run (the probability lags the audio)
    to its end."""
    import numpy as np
    end = buf_start + len(buf)
    lo = max(buf_start, end - int(VAD_RATE * window_s))
    need = int(round(VAD_RATE * dip_ms / 1000))
    runs, cur, talked = [], None, False
    for s, e, p in probs:
        if e <= buf_start or s >= end:
            continue
        if not talked:
            talked = p >= dip_prob
            continue
        if e <= lo:
            continue
        s = max(s, lo)
        if p < dip_prob:
            if cur and s <= cur[1]:
                cur[1], cur[2], cur[3] = e, cur[2] + p, cur[3] + 1
            else:
                if cur:
                    runs.append(cur)
                cur = [s, e, p, 1]
        elif cur:
            runs.append(cur)
            cur = None
    if cur:
        runs.append(cur)
    runs = [r for r in runs if r[1] - r[0] >= need]
    if not runs:
        return None
    a, b, _, _ = max(runs, key=lambda r: (r[1] - r[0], -r[2] / r[3], r[1]))
    a = max(buf_start, a - int(VAD_RATE * VAD_LAG_MS / 1000)) - buf_start
    b = min(end, b) - buf_start
    frame = max(1, int(VAD_RATE * frame_ms / 1000))
    n = (b - a) // frame
    if n < 1:
        return (a + b) // 2
    energies = np.abs(buf[a:a + n * frame].reshape(n, frame)).mean(axis=1)
    # Nearly as quiet nearer the middle wins: clear of the last word's release
    # and the next one's onset (and the middle, in digital silence).
    dist = np.abs(np.arange(n) - (n - 1) / 2) / n
    return a + int(np.argmin(energies * (1 + dist) + 1e-6 * dist)) * frame + frame // 2


class Segmenter:
    """One stream's turn-taking: feed 16 kHz blocks with their speech
    probability (one number, or one per VAD window of the block: vad_windows),
    get back finished utterances as (samples, start_ms, end_ms).
    No model inside, so tests drive it directly."""

    def __init__(self, endpoint_ms=None, max_s=None, min_speech_ms=None,
                 short_endpoint_ms=SHORT_TURN_ENDPOINT_MS, cut_window_s=None,
                 cut_dip_prob=None, cut_dip_ms=None, cut_endpoint_ms=None, cut_early_s=None):
        import numpy as np
        self.np = np
        self.endpoint_ms = ENDPOINT_MS if endpoint_ms is None else endpoint_ms
        self.max_s = MAX_UTTERANCE_S if max_s is None else max_s
        self.min_speech_ms = MIN_SPEECH_MS if min_speech_ms is None else min_speech_ms
        self.short_endpoint_ms = max(self.endpoint_ms, short_endpoint_ms)
        # (At most a third of the cap: 3.33 s with the default 10 s; with a
        # 6 s cap, the old rule's 2 s.)
        self.cut_window_s = min(CUT_WINDOW_S if cut_window_s is None else cut_window_s, self.max_s / 3)
        self.cut_dip_prob = CUT_DIP_PROB if cut_dip_prob is None else cut_dip_prob
        self.cut_dip_ms = CUT_DIP_MS if cut_dip_ms is None else cut_dip_ms
        self.cut_endpoint_ms = CUT_ENDPOINT_MS if cut_endpoint_ms is None else cut_endpoint_ms
        self.cut_early_s = CUT_EARLY_S if cut_early_s is None else cut_early_s
        self.probs = []             # (stream start, end sample, probability) per VAD window in buf
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
        self._drop_probs()
        return u, start_ms, end_ms

    def _drop_probs(self):
        """Forget the probabilities of audio no longer in the buffer."""
        i = 0
        while i < len(self.probs) and self.probs[i][1] <= self.buf_start:
            i += 1
        if i:
            del self.probs[:i]

    def _restate(self):
        """After a forced cut: the speech and the trailing quiet of what is
        left, from its VAD windows (a rest that is all quiet is idle again)."""
        speech, quiet = 0, 0
        for s, e, p in self.probs:
            n = e - max(s, self.buf_start)
            if p > 0.5:
                speech, quiet = speech + n, 0
            else:
                quiet += n
        self.speech_ms = speech * 1000 / VAD_RATE
        self.quiet_ms = quiet * 1000 / VAD_RATE
        if not speech:
            self.speech_seen = False

    def _cut(self, window_s=None):
        """The forced cut's index into the buffer (pause_cut over the last
        window_s, default cut_window_s; else quietest_cut)."""
        cut = None
        if self.cut_window_s > 0:
            cut = pause_cut(self.buf, self.buf_start, self.probs, window_s or self.cut_window_s,
                            self.cut_dip_prob, self.cut_dip_ms)
        if cut is None or not 0 < cut <= len(self.buf):
            cut = quietest_cut(self.buf)
        return cut

    def feed(self, block, prob):
        np = self.np
        if np.ndim(prob) == 0:
            windows = [float(prob)]
        else:
            windows = [float(p) for p in prob] or [0.0]
        prob = max(windows)
        step = len(block) / len(windows)
        self.probs.extend((self.total + int(i * step), self.total + int((i + 1) * step), p)
                          for i, p in enumerate(windows))
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
            self._drop_probs()
            return []
        near_cap = (self.cut_window_s > 0 and self.cut_endpoint_ms > 0
                    and len(self.buf) / VAD_RATE >= self.max_s - self.cut_window_s
                    and self.speech_ms >= self.min_speech_ms and self.quiet_ms >= self.cut_endpoint_ms)
        over = len(self.buf) / VAD_RATE >= self.max_s
        if over or near_cap:
            # Still talking: cut at the best pause of the last few seconds
            # (pause_cut) and keep listening; the rest starts the next
            # utterance. Near the cap a short pause cuts at once (near_cap),
            # rather than the cap cutting back to it a few seconds later: in
            # that pause (the window: just it), not at its end, where the VAD
            # can still be under 0.5 on the first 30 ms of the next word.
            window_s = (self.quiet_ms + VAD_LAG_MS) / 1000 if near_cap and not over else None
            out = [self._take(self._cut(window_s))]
            self._restate()
            return out
        if self.quiet_ms < self._need_ms():
            return []
        return [self._end_turn()]

    def _need_ms(self):
        """The quiet that ends the turn now: SHORT_TURN_ENDPOINT_MS while the
        turn holds less than MIN_SPEECH_MS of speech, else ENDPOINT_MS, falling
        in a straight line to CUT_ENDPOINT_MS as the buffer grows from
        CUT_EARLY_S to the cap (the progressive pause cut; off when either
        is 0, or when ENDPOINT_MS is not above CUT_ENDPOINT_MS)."""
        if self.speech_ms < self.min_speech_ms:
            return self.short_endpoint_ms
        if (self.cut_early_s <= 0 or self.cut_endpoint_ms <= 0
                or self.cut_endpoint_ms >= self.endpoint_ms or self.max_s <= self.cut_early_s):
            return self.endpoint_ms
        run = (len(self.buf) / VAD_RATE - self.cut_early_s) / (self.max_s - self.cut_early_s)
        run = min(1.0, max(0.0, run))
        return self.endpoint_ms - run * (self.endpoint_ms - self.cut_endpoint_ms)

    def _end_turn(self):
        # The speech, not the pause that ended it (a recogniser fills silence
        # with invented words), keeping a short tail so no word loses its release.
        trail = int(VAD_RATE * max(0.0, self.quiet_ms - TRAILING_KEEP_MS) / 1000)
        n = len(self.buf) - trail if 0 < trail < len(self.buf) else len(self.buf)
        out = self._take(n)
        # The trimmed silence is gone from the buffer too: the next turn starts after it.
        self.buf_start += len(self.buf)
        self.buf = self.np.zeros(0, dtype=self.np.float32)
        self.probs.clear()
        self.quiet_ms = 0.0
        self.speech_ms = 0.0
        self.speech_seen = False
        return out

    def flush(self):
        """End the turn now (the client's {"type":"flush"}, or end of stream)."""
        if not self.speech_seen or len(self.buf) < VAD_RATE // 4:
            self.buf_start += len(self.buf)
            self.buf = self.np.zeros(0, dtype=self.np.float32)
            self.probs.clear()
            self.speech_seen, self.quiet_ms, self.speech_ms = False, 0.0, 0.0
            return []
        return [self._end_turn()]


def vad_windows(vad, block):
    """audio_in.vad_block's probabilities, one per 512-sample window instead
    of only the highest: the Segmenter ends turns on the highest (as the stack
    does) and looks for a forced cut's pause in the windows."""
    import torch
    from audio_in import VAD_WINDOW
    out = []
    with torch.inference_mode():
        for i in range(0, len(block) - VAD_WINDOW + 1, VAD_WINDOW):
            w = torch.tensor(block[i:i + VAD_WINDOW], dtype=torch.float32)
            out.append(vad(w, VAD_RATE).item())
    return out


class PassThrough:
    """AudioIn's resampler for a client that already sends 16 kHz."""

    def process(self, x):
        import numpy as np
        return np.asarray(x, dtype=np.float32)


def audio_input(rate, label):
    """The stack's AudioIn (fixed 96 ms blocks whatever the message size, issue
    #13): 24 kHz resampled as the stack does, 16 kHz passed through. With
    STT_DENOISE=1 the blocks pass through a spectral noise reducer with this
    connection's own state (denoise.py) before the VAD hears them."""
    from audio_in import AudioIn
    import denoise
    conn_in = AudioIn(label)
    if rate == VAD_RATE:
        conn_in.rs = PassThrough()
    return denoise.wrap(conn_in, os.environ)


# ---------------------------------------------------------------- repetition guard

# The guard itself lives in server/engines/common.py, shared with the stack
# (which runs it on the Omnilingual 7B's Lao and Khmer). Re-exported here: the
# batcher below and the tests call it as this module's.
from engines.common import (MAX_CHARS_PER_S, MAX_REPEATS, repetition_guard,  # noqa: E402,F401
                            _loop_re)


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

    def __init__(self, device=None, card=None, serve=None, voice_names=None, defer_voices=False):
        import copy
        import torch
        self.copy = copy
        self.device = device or os.environ.get("STT_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
        self.card = card or os.environ.get("OMNI_CARD", "omniASR_LLM_300M")
        self.serve = serve if serve is not None else served()
        print(f"[stt] device={self.device} torch={torch.__version__} serving {','.join(sorted(self.serve))}", flush=True)
        self.lid_index = {}
        self.omni = None
        self.ctc = None
        # The voices load on a thread of their own: on a cold Cloud Run
        # instance Coqui's import alone took ~30 s (2026-10-19), which /listen,
        # the service's first job, should not wait for. /speak waits for
        # voices_ready instead. But that thread starts only once the
        # recogniser is BUILT (and, from main, warm): never beside it.
        # transformers' from_pretrained (MMS's VITS, Coqui's XTTS parts) builds
        # its model under accelerate-style init_empty_weights, which swaps
        # torch.nn.Module.register_parameter process-wide for the duration, not
        # per thread; a module the omni-load thread created meanwhile got its
        # parameters on the meta device, loading the checkpoint left them
        # there, and the warm-up decode died with "Tensor on device meta is not
        # on the expected device cuda:0" (most cold starts of the voices image,
        # 2026-10-21). Built one after the other, /listen still comes first.
        self.voices = None
        self.voices_error = None
        self.voices_ready = threading.Event()
        if "listen" in self.serve:
            # VAD first, before any loader thread starts: torch.hub.load(source=
            # "local") puts its directory on sys.path and takes it off again
            # (torch/hub.py, _add_to_sys_path), and an import on another thread
            # walking sys.path meanwhile can miss site-packages (the 7B
            # omni-load thread died with ModuleNotFoundError: fairseq2).
            # Silero's load is short; nothing else here touches sys.path.
            self.vad = load_vad()
        self._voice_names = voice_names
        self._voices_started = False
        if "speak" not in self.serve:
            self.voices_ready.set()
        if "listen" in self.serve:
            # The recogniser loads on its own thread while language ID loads
            # here: on a cold 7B instance VAD and language ID took 10-15 s,
            # which then no longer add to the checkpoint's read
            # (STT_PARALLEL_LOAD=0: one after the other, as before).
            if os.environ.get("STT_PARALLEL_LOAD", "1") != "0":
                box = {}

                def omni_load():
                    try:
                        box["omni"] = load_omni(self.device, self.card)
                    except BaseException as e:  # SystemExit included: re-raised below
                        box["error"] = e
                t = threading.Thread(target=omni_load, name="omni-load", daemon=True)
                t.start()
                self.lid, self.lid_index = load_lid(self.device)
                t.join()
                if "error" in box:
                    raise box["error"]
                self.omni = box["omni"]
            else:
                self.lid, self.lid_index = load_lid(self.device)
                self.omni = load_omni(self.device, self.card)
            self.ctc = None
            if ctc_stream.ENABLED:
                # The streaming track's card (ctc_stream.py), after the
                # recogniser: one fairseq2 load at a time. When the recogniser
                # is that card (the separate streaming service: the 7B and the
                # 3B do not fit one L4 together), its pipeline is shared.
                same = self.card == ctc_stream.CARD
                self.ctc = ctc_stream.CTCModel(self.device, pipeline=self.omni.omni if same else None)
            print(f"[stt] models loaded", flush=True)
            if not defer_voices:
                self.start_voices()
        elif "speak" in self.serve:
            self.start_voices().join()

    def start_voices(self):
        """Start loading the voices (once; after the recogniser: __init__ says
        why). Returns the loading thread, or None."""
        if "speak" not in self.serve or self._voices_started:
            return None
        self._voices_started = True
        names = self._voice_names if self._voice_names is not None else voice_list()
        loader = threading.Thread(target=self._load_voices, args=(names,), name="voices-load", daemon=True)
        loader.start()
        return loader

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
        ctc = getattr(self, "ctc", None)
        if ctc is not None and ctc.pipe is getattr(self.omni, "omni", None):
            # The recogniser is the streaming track's CTC card: its own
            # languages get the masked decode (CTCModel.transcribe_batch).
            mine = [i for i, (_, lang) in enumerate(items) if lang in ctc.langs]
            rest = [i for i in range(len(items)) if i not in set(mine)]
            texts = [None] * len(items)
            if mine:
                for i, t in zip(mine, ctc.transcribe_batch([items[i] for i in mine])):
                    texts[i] = self.omni._filtered(t)
            if rest:
                for i, t in zip(rest, decode_batch(self.omni, [items[i] for i in rest])):
                    texts[i] = t
        else:
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
    """STT_SERVE -> {"listen", "speak"} (default both). Comma- or plus-separated:
    "listen+speak" survives gcloud's comma-separated --set-env-vars."""
    env = os.environ if env is None else env
    want = {p.strip() for p in re.split(r"[,+]", env.get("STT_SERVE", "listen,speak")) if p.strip()}
    if not want or want - {"listen", "speak"}:
        raise SystemExit("[stt] STT_SERVE must name listen and/or speak")
    return want


def model_size(card):
    """An Omnilingual card name -> its size as a client names it ("300m", "7b",
    "3b"), or None. Only the size: a card's full name can be a private one
    (a fine-tuned card), and /info is answered without a token."""
    m = re.search(r"(\d+)([MB])(?![A-Za-z])", card or "")
    return f"{m.group(1)}{m.group(2).lower()}" if m else None


def service_info(models, headers=None, query=None, env=None):
    """GET /info: what this service offers, so a client (Live Translation's
    Omnilingual service setting) can show only what is there.

        {"type": "info", "service": "omni-stt", "models": ["7b"],
         "serve": ["listen", "speak"], "langs": [...], "editions": ["nonprofit"],
         "voices_state": "ready", "voices_by_edition": {"nonprofit": ["mms", "coqui"]},
         "edition": "nonprofit", "voices": ["mms", "coqui"]}

    models: the recogniser's size ([] when /listen is not served). langs: what
    /listen takes (OMNI_CODES). voices_state: "ready", "loading" (a cold start:
    the voices load after the recogniser; the names are then the ones that will
    load), "failed" or "none" (no /speak). voices_by_edition: per edition served,
    the voices it may use (voices.permitted). With a token this service takes
    (credentials_for), "edition" and "voices": that token's /speak edition
    (speak_edition; null: refused there, 4403) and its voices. Without one, or
    with a bad one, those two are absent: nothing here is secret, and nothing
    about a token is said without it. Never the card's name (model_size)."""
    env = os.environ if env is None else env
    serve = set(getattr(models, "serve", ()) or ())
    eds = service_editions(env)
    size = model_size(getattr(models, "card", "")) if "listen" in serve else None
    out = {"type": "info", "service": "omni-stt", "models": [size] if size else [],
           "serve": sorted(serve), "langs": sorted(OMNI_CODES) if "listen" in serve else [],
           "editions": eds}
    loaded = getattr(models, "voices", None)
    ready = getattr(models, "voices_ready", None)
    if "speak" not in serve:
        state, names = "none", []
    elif loaded is not None:
        state, names = "ready", list(loaded.names)
    elif ready is not None and not ready.is_set():
        state = "loading"
        try:
            names = list(getattr(models, "_voice_names", None) or voice_list(env))
        except SystemExit:
            names = []
    else:
        state, names = "failed", []
    out["voices_state"] = state
    try:
        from voices import permitted
    except Exception:  # noqa: BLE001 (a recogniser-only image without the voices' code)
        permitted = None
    by = {ed: (permitted(names, ed) if permitted else []) for ed in eds}
    out["voices_by_edition"] = by
    sub, claim = credentials_for(headers or {}, query or {}, env)
    if sub is not None:
        ed = speak_edition(eds, claim, open_server=(sub == "open"))
        out["edition"] = ed
        out["voices"] = by.get(ed, []) if ed else []
    return out


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
        # skip_validation: torch.hub's not-a-fork check asks api.github.com
        # without a token, and shared CI runners hit its rate limit (403). The
        # ref is a full commit SHA pinned above, so the check adds nothing.
        vad, _ = torch.hub.load(f"{VAD_REPO}:{VAD_REF}", "silero_vad", trust_repo=True,
                                skip_validation=True)
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
    fetch_checkpoint()
    if os.environ.get("OMNI_MMAP", "0") == "1":
        mmap_checkpoints()
    t0 = time.time()
    omni = Omnilingual(ctx)
    omni.load()
    if not omni.available:
        raise SystemExit(f"[stt] Omnilingual ({card}) failed to load; see above")
    print(f"[stt] {card} loaded in {time.time() - t0:.1f}s", flush=True)
    return omni


def mmap_checkpoints():
    """OMNI_MMAP=1: fairseq2 maps the checkpoint file instead of reading it whole
    into memory first (torch.load(mmap=True)); each tensor is read as it is
    copied to the GPU. For the 7B card (a 16 GB bf16 file) the whole file then
    never sits in the process's memory at once."""
    import functools
    from omnilingual_asr.models.inference import pipeline
    if not getattr(pipeline.load_model, "_mmap", False):
        patched = functools.partial(pipeline.load_model, mmap=True)
        patched._mmap = True
        pipeline.load_model = patched


def fetch_checkpoint():
    """OMNI_FETCH=gs://bucket/path/file.pt with OMNI_FETCH_TO=/tmp/models/file.pt:
    copy the checkpoint from Cloud Storage at start, in parallel ranged reads
    (google-cloud-storage's transfer manager), before the card naming
    OMNI_FETCH_TO loads. Cloud Run's /tmp is memory: size the instance for it."""
    src = os.environ.get("OMNI_FETCH", "")
    dst = os.environ.get("OMNI_FETCH_TO", "")
    if not src:
        return
    if not (src.startswith("gs://") and dst):
        raise SystemExit("[stt] OMNI_FETCH must be gs://bucket/object, with OMNI_FETCH_TO set")
    from google.cloud import storage
    from google.cloud.storage import transfer_manager
    t0 = time.time()
    bucket, _, name = src[len("gs://"):].partition("/")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    blob = storage.Client().bucket(bucket).blob(name)
    transfer_manager.download_chunks_concurrently(
        blob, dst, chunk_size=int(os.environ.get("OMNI_FETCH_CHUNK_MB", "64")) * 1024 * 1024,
        max_workers=int(os.environ.get("OMNI_FETCH_WORKERS", "16")))
    size = os.path.getsize(dst)
    dt = time.time() - t0
    print(f"[stt] fetched {size / 1e9:.1f} GB from Cloud Storage in {dt:.1f}s "
          f"({size / 1e6 / max(dt, 1e-3):.0f} MB/s)", flush=True)


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
    by item, so one bad utterance fails alone. A job whose future is already
    done (its client left and the awaiting task was cancelled) is dropped
    unrun, in a batch and in that retry. /speak never comes here: it has
    its own threads (voice_pool)."""

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
        self.inflight = {k: [] for k in self.KINDS}     # the batch being run (_crashed fails it)
        self.crashes = collections.deque()
        self.exit = os._exit                           # tests replace it
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
            # A job whose future is already done was given up on (its client
            # left, so the awaiting task was cancelled): no GPU time for it.
            for q in self.queues.values():
                live = [job for job in q if not job[3].done()]
                if len(live) != len(q):
                    q.clear()
                    q.extend(live)
            out = self.inflight = {k: [] for k in self.KINDS}
            out["lid"] = [self.queues["lid"].popleft() for _ in range(min(self.max_batch, len(self.queues["lid"])))]
            q = self.queues["asr"]
            if self.group_by_length and getattr(self.models, "length_sensitive", True):
                keep = set(pick_group([len(job[0]) for job in q], self.max_batch))
            else:
                keep = set(range(min(self.max_batch, len(q))))
            jobs = list(q)
            out["asr"] = [job for i, job in enumerate(jobs) if i in keep]
            q.clear()
            q.extend(job for i, job in enumerate(jobs) if i not in keep)
            return out

    def _run(self):
        while True:
            try:
                taken = self._take()
                for kind in self.KINDS:
                    if taken[kind]:
                        self._do(kind, taken[kind])
                self._maybe_log()
            except Exception as e:  # noqa: BLE001  the last resort: see _crashed
                self._crashed(e)

    # A model error fails its batch in _do; anything else that escapes the
    # loop (a bug here, a broken model attribute) lands in _crashed. Without
    # it the thread died silently and every later utterance waited forever on
    # a future nobody would resolve, while /health still said ok.
    CRASH_LIMIT = 3          # crashes within CRASH_WINDOW_S before the process exits
    CRASH_WINDOW_S = 60

    def _crashed(self, e):
        """Fail every job taken or waiting (their connections get an error and
        carry on), then run the loop again; on the CRASH_LIMIT-th crash within
        CRASH_WINDOW_S exit the process, so Cloud Run starts a fresh instance
        instead of serving from a worker that keeps failing."""
        err = RuntimeError(f"the model worker failed: {type(e).__name__}")
        with self.cond:
            jobs = [job for kind in self.KINDS for job in self.inflight.get(kind, [])]
            for q in self.queues.values():
                jobs.extend(q)
                q.clear()
            self.inflight = {k: [] for k in self.KINDS}
        for _, _, loop, fut in jobs:
            try:
                loop.call_soon_threadsafe(_resolve, fut, None, err)
            except RuntimeError:
                pass
        now = time.monotonic()
        self.crashes.append(now)
        while self.crashes and now - self.crashes[0] > self.CRASH_WINDOW_S:
            self.crashes.popleft()
        print(f"[stt] model worker failed ({type(e).__name__}: {clean(e, 120)}); failed {len(jobs)} "
              f"waiting utterances; {len(self.crashes)} in {self.CRASH_WINDOW_S}s", flush=True)
        if len(self.crashes) >= self.CRASH_LIMIT:
            print("[stt] model worker keeps failing: exiting for a fresh instance", flush=True)
            self.exit(70)

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
                for item, (_, _, _, fut) in zip(items, jobs):
                    if fut.done():          # given up on while the batch ran
                        outcomes.append((None, None))
                        continue
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


def push_bounded(queue, utt, limit):
    """Put utt on a connection's asyncio.Queue; when `limit` or more are
    already waiting, first take out the OLDEST utterance (returned, for the
    log; None when nothing was dropped). A "flush" marker is never dropped
    and keeps its place: re-queueing it behind newer utterances (as this once
    did) both let the queue outgrow the limit and sent "flushed" late."""
    if queue.qsize() >= limit:
        items = [queue.get_nowait() for _ in range(queue.qsize())]
        at = next((i for i, item in enumerate(items) if not (isinstance(item, str) and item == "flush")), None)
        dropped = items.pop(at) if at is not None else None
        for item in items:
            queue.put_nowait(item)
    else:
        dropped = None
    queue.put_nowait(utt)
    return dropped


async def handle(ws, models, sub="open"):
    """One /listen connection, after auth and admission."""
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(ws.request.path).query)
    try:
        langs = parse_langs((q.get("langs") or [""])[0], set(models.lid_index))
        rate = parse_rate((q.get("rate") or [""])[0])
        transcribe = parse_transcribe((q.get("transcribe") or [""])[0], langs)
        try:
            stream_cfg = ctc_stream.parse_stream(q, langs, getattr(models, "ctc", None) is not None)
        except ctc_stream.BadParam as e:
            raise BadRequest(str(e))
    except BadRequest as e:
        print(f"[stt] {clean(sub, 24)}: refused: {clean(e, 200)}", flush=True)
        await ws.send(json.dumps({"type": "error", "detail": str(e)}))
        await ws.close(code=CLOSE_BAD_REQUEST, reason="bad request")
        return
    hello = {"type": "hello", "langs": langs, "rate": rate}
    if stream_cfg is not None:
        hello["stream"] = ctc_stream.hello_field(stream_cfg)
    await ws.send(json.dumps(hello))
    who = clean(sub, 24)
    print(f"[stt] {who}: listening, langs={','.join(langs)} rate={rate} "
          f"transcribe={','.join(c for c in langs if c in transcribe) or 'none'}", flush=True)

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
                if track:
                    await track.drain()     # the streaming track's last commit goes first
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
            dropped = push_bounded(queue, utt, MAX_PENDING)
            if dropped is not None:
                print(f"[stt] {who}: behind, dropped a {len(dropped[0]) / VAD_RATE:.1f}s utterance", flush=True)

    # Partial text while a piece is still being spoken (STT_PARTIALS=1 only;
    # partials.py): extra passes over a copy of the Segmenter's buffer, through
    # the same Batcher; the final goes out by the path above, unchanged.
    # The streaming track (STT_CTC_STREAM=1 and ?stream=ctc; ctc_stream.py):
    # the CTC card's chunked passes over the same blocks, on its own worker.
    # It replaces the LLM partial passes on its connections.
    track = None
    if stream_cfg is not None and stream_cfg["track"] == "ctc":
        track = ctc_stream.CTCStream(stream_cfg["lang"], stream_cfg["lookahead_ms"], models.ctc.submit,
                                     lambda m: ws.send(json.dumps(m, ensure_ascii=False)), models.ctc.detok,
                                     who=who, joins=getattr(models.ctc, "joins", None))
    partial = None
    if partials.ENABLED and track is None:
        partial = partials.PartialStream(langs, transcribe, batcher.submit,
                                         lambda m: ws.send(json.dumps(m, ensure_ascii=False)),
                                         busy=lambda: partials.queue_busy(batcher), who=who)

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
                    if partial:
                        partial.piece_ended()
                    if track:
                        track.turn_ended()
                    enqueue(seg.flush())
                    queue.put_nowait("flush")
                else:
                    await ws.send(json.dumps({"type": "error", "detail": "text messages: only {\"type\":\"flush\"}"}))
                continue
            for block in conn_in.feed(msg):
                windows = vad_windows(vad, block)
                utts = seg.feed(block, windows)
                enqueue(utts)
                if partial:
                    partial.after_feed(seg, utts)
                if track:
                    track.feed(block, max(windows, default=0.0) if isinstance(windows, (list, tuple)) else float(windows))
                    if utts and not seg.speech_seen:
                        track.turn_ended()       # a pause ended the turn (not a cut mid-speech)
        # Disconnected: nothing more can be sent, so the unfinished turn is dropped.
    finally:
        batcher.closed()
        if partial:
            partial.close()
        if track:
            track.close()
        task.cancel()
        if heard["audio_s"]:
            print(f"[stt] {who}: closed; {heard['n']} transcripts, {heard['audio_s']:.0f}s of speech, "
                  f"real-time factor {heard['busy_s'] / heard['audio_s']:.2f}", flush=True)


# ---------------------------------------------------------------- /speak

# Synthesis runs here, not on the Batcher's thread: a sentence being voiced never waits
# behind an utterance being transcribed. One thread per voice (its own
# single-thread executor): requests on one voice take turns, as its lock
# would make them anyway, and never hold a thread another voice needs. (One
# shared pool of two let two Coqui requests take both threads, one of them
# just waiting on Coqui's lock, while an MMS request queued behind them.)
_VOICE_POOLS = {}
_VOICE_POOLS_LOCK = threading.Lock()


def voice_pool(voice):
    """The single-thread executor that voices `voice`."""
    with _VOICE_POOLS_LOCK:
        pool = _VOICE_POOLS.get(voice)
        if pool is None:
            pool = _VOICE_POOLS[voice] = ThreadPoolExecutor(1, thread_name_prefix=f"voice-{clean(voice, 16)}")
        return pool


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
        pcm = await loop.run_in_executor(voice_pool(voice), voices.synthesise, voice, piece)
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
    speak_edition; None: as on an open server, the strictest edition served).

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
        edition = stack_auth.connection_edition(service_editions(env), None)   # = speak_edition(..., open_server=True)
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
    query = parse_qs(url.query)
    sub, claim = credentials_for(ws.request.headers, query)
    if sub is None:
        print("[stt] refused: bad or missing token", flush=True)
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="unauthorized")
        return
    if sub != "open" and presented_token_via(ws.request.headers, query)[1] == "query":
        print(f"[stt] {clean(sub, 24)} sent its token in the URL (?token=, deprecated: URLs are logged); "
              f"use the Authorization header or the bearer.<token> subprotocol", flush=True)
    edition = None
    if path == "/speak":
        # The edition only matters for the voices; /listen is the same in all.
        served_eds = service_editions()
        edition = speak_edition(served_eds, claim, open_server=(sub == "open"))
        if edition is None:
            # A token without a claim counts as commercial (speak_edition).
            ed = claim or "commercial"
            print(f"[stt] refused {clean(sub, 24)}: its token is for the {ed} edition"
                  f"{'' if claim else ' (it names none)'}; this server serves {'/'.join(served_eds)}", flush=True)
            await ws.close(code=CLOSE_EDITION, reason=f"this server does not serve the {ed} edition")
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
    if getattr(models, "ctc", None) is not None:
        models.ctc.warm()
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
    print("[stt] starting", flush=True)
    models = Models(defer_voices=True)
    warmup(models)
    models.start_voices()           # only now: nothing else is building a model (Models.__init__)
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
        if path == "/info":
            # The token only from the header: a query token would be logged (the URL).
            info = service_info(models, request.headers, {})
            resp = connection.respond(HTTPStatus.OK, json.dumps(info) + "\n")
            resp.headers["Content-Type"] = "application/json"
            resp.headers["Cache-Control"] = "no-store"
            return resp
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
                                max_size=MAX_FRAME_BYTES, ping_interval=None, process_request=http,
                                select_subprotocol=select_subprotocol):
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
