#!/usr/bin/env python3
"""Hosted speech to text: Meta Omnilingual ASR, with spoken-language ID among
the languages a room actually uses; and Haitian Creole voices (/speak). No translation.

    STT_TOKEN=... python3 services/omni-stt/server.py          # port $PORT, default 8080
    STT_OPEN=1    python3 services/omni-stt/server.py          # no token (a laptop test only)

Protocol:

    client connects  wss://host/listen?langs=ht,en[&rate=24000][&transcribe=ht]
                     Authorization: Bearer <STT_TOKEN>   (or ?token=, which proxies log)
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
    server sends     {"type":"hello","lang":"ht","voices":["mms","coqui"],"voice":"coqui","rate":24000}
    client sends     {"type":"speak","text":"...","voice":"mms","id":"7"}   voice, id optional
    server sends     per sentence: {"type":"sentence","id":"7","index":0,"bytes":96000}
                     then that sentence's audio as binary frames: 24 kHz mono PCM16
                     {"type":"done","id":"7","voice":"mms","sentences":2,
                      "audio_ms":4100,"first_audio_ms":180,"ms":420}   after the last
                     {"type":"error","id":"7","detail":"..."}   (a failed request; the socket stays open)
    Requests on one socket are spoken in order; a client may keep it open.
    Before the voices have loaded (they load beside the recogniser) the hello
    waits; if they failed to load the socket is closed with 4503.

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
CC-BY-NC-4.0: non-commercial use, which a non-profit service is) or Coqui
VITS (multilingual-tts/VITS-OpenBible-Haitian-Creole, CC-BY-SA-4.0) engines. Numbers
are spelled out first (ht_numbers.py: neither voice says digits). A WebSocket, not
an HTTP POST: the websockets server here answers GET only, and a socket lets the
first sentence's audio go out while the rest is made. Text never goes in the URL
(URLs are logged).

Environment: HT_VOICE (mms|coqui, default coqui: the voice when a request names none),
STT_VOICES (the voices loaded, default "mms,coqui"), STT_MAX_SPEAKERS (open /speak
sockets, default 4), STT_SERVE ("listen,speak" by default; "speak" skips the
recogniser's models, for a laptop test of the voices), STT_TOKEN (or STT_SIGNING_KEY, the stack's signed tokens), STT_OPEN=1,
PORT, STT_DEVICE (default: cuda when torch sees one, else cpu), OMNI_CARD,
STT_MAX_CONNECTIONS, STT_MAX_PENDING, ENDPOINT_MS (default 300), MAX_UTTERANCE_S
(default 6.0), MIN_SPEECH_MS (default 400), STT_MODELS (the baked models).
"""
import asyncio
import json
import os
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
    if env.get("STT_TOKEN") or env.get("STT_SIGNING_KEY"):
        return "token"
    return "open" if env.get("STT_OPEN") == "1" else None


def presented_token(headers, query):
    """The client's token: the Authorization header, else ?token=."""
    auth = (headers.get("Authorization", "") if headers is not None else "") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (query.get("token") or [""])[0]


def subject_for(headers, query, env=None):
    """Who this is ("open", "static" or a signed token's subject), or None to refuse."""
    import stack_auth
    env = os.environ if env is None else env
    mode = auth_mode(env)
    if mode == "open":
        return "open"
    if mode is None:
        return None
    return stack_auth.verify(presented_token(headers, query),
                             env.get("STT_SIGNING_KEY", "").strip(), env.get("STT_TOKEN", "").strip())


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


# ---------------------------------------------------------------- models

def models_dir():
    return os.environ.get("STT_MODELS", "/opt/models")


class Models:
    """One copy of each model, shared by every connection. Recognition and
    language ID run on one worker thread (MODEL_POOL): a single GPU gains
    nothing from two at once, and neither model is documented as thread-safe."""

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

    def transcribe(self, pcm16k, lang):
        return self.omni.transcribe(pcm16k, lang)


def served(env=None):
    """STT_SERVE -> {"listen", "speak"} (default both)."""
    env = os.environ if env is None else env
    want = {p.strip() for p in env.get("STT_SERVE", "listen,speak").split(",") if p.strip()}
    if not want or want - {"listen", "speak"}:
        raise SystemExit("[stt] STT_SERVE must name listen and/or speak")
    return want


def voice_list(env=None):
    """STT_VOICES -> the voices to load (default every one)."""
    from voices import VOICES
    env = os.environ if env is None else env
    names = [v.strip() for v in env.get("STT_VOICES", ",".join(VOICES)).split(",") if v.strip()]
    if not names or any(v not in VOICES for v in names):
        raise SystemExit(f"[stt] STT_VOICES must be among {','.join(VOICES)}")
    return names


def default_voice(names, env=None):
    """HT_VOICE when loaded, else coqui, else the first voice loaded."""
    env = os.environ if env is None else env
    want = env.get("HT_VOICE", "").strip().lower() or "coqui"
    if want in names:
        return want
    if env.get("HT_VOICE"):
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
    omni = Omnilingual(ctx)
    omni.load()
    if not omni.available:
        raise SystemExit(f"[stt] Omnilingual ({card}) failed to load; see above")
    return omni


# ---------------------------------------------------------------- connection

MODEL_POOL = ThreadPoolExecutor(1, thread_name_prefix="model")


def clean(value, n=64):
    return "".join(ch if ch.isprintable() else "?" for ch in str(value))[:n]


async def recognise(models, utt, langs, transcribe, send):
    """One utterance: send its language, then (when wanted) its words.
    Returns whether a transcript was sent."""
    loop = asyncio.get_running_loop()
    pcm, start_ms, end_ms = utt
    lang, conf = await loop.run_in_executor(MODEL_POOL, models.identify, pcm, langs)
    span = {"lang": lang, "confidence": round(conf, 3), "start_ms": start_ms, "end_ms": end_ms}
    await send({"type": "language", **span})
    if lang not in transcribe:
        return False
    text = await loop.run_in_executor(MODEL_POOL, models.transcribe, pcm, lang)
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

    async def worker():
        while True:
            item = await queue.get()
            if item == "flush":
                await ws.send(json.dumps({"type": "flushed"}))
                continue
            t0 = time.monotonic()
            try:
                said = await recognise(models, item, langs, transcribe,
                                       lambda m: ws.send(json.dumps(m, ensure_ascii=False)))
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
        task.cancel()
        if heard["audio_s"]:
            print(f"[stt] {who}: closed; {heard['n']} transcripts, {heard['audio_s']:.0f}s of speech, "
                  f"real-time factor {heard['busy_s'] / heard['audio_s']:.2f}", flush=True)


# ---------------------------------------------------------------- /speak

# Synthesis runs here, not on MODEL_POOL: a sentence being voiced never waits
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


def parse_speak(msg, default_voice, names):
    """A client text message -> (text, voice, id), or BadRequest."""
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
        raise BadRequest(f"voice {voice} is not loaded here")
    req_id = m.get("id")
    req_id = clean(req_id, 64) if isinstance(req_id, (str, int)) and not isinstance(req_id, bool) else None
    return text, voice, req_id


async def handle_speak(ws, voices, sub="open", env=None):
    """One /speak connection, after auth and admission."""
    from urllib.parse import urlparse, parse_qs
    from voices import parse_voice, LANG
    q = parse_qs(urlparse(ws.request.path).query)
    names = voices.names
    try:
        voice = parse_voice((q.get("voice") or [""])[0], default_voice(names, env))
        if voice not in names:
            raise ValueError(f"voice {voice} is not loaded here")
    except ValueError as e:
        await ws.send(json.dumps({"type": "error", "detail": str(e)}))
        await ws.close(code=CLOSE_BAD_REQUEST, reason="bad request")
        return
    await ws.send(json.dumps({"type": "hello", "lang": LANG, "voices": names, "voice": voice, "rate": 24000}))
    who = clean(sub, 24)

    async def send(m):
        await ws.send(m if isinstance(m, bytes) else json.dumps(m, ensure_ascii=False))

    n, audio_ms = 0, 0
    async for msg in ws:
        if isinstance(msg, bytes):
            await send({"type": "error", "detail": "send text messages: {\"type\":\"speak\",\"text\":\"...\"}"})
            continue
        try:
            text, v, req_id = parse_speak(msg, voice, names)
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
    sub = subject_for(ws.request.headers, parse_qs(url.query))
    if sub is None:
        print("[stt] refused: bad or missing token", flush=True)
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="unauthorized")
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
            await handle_speak(ws, models.voices, sub)
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
        raise SystemExit("[stt] set STT_TOKEN (or STT_SIGNING_KEY), or STT_OPEN=1 for an open test server")
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
    each lands in the cache the server will look in (deploy.sh, Dockerfile)."""
    models = Models(device="cpu", serve={"listen", "speak"})
    models.voices_ready.wait()
    if models.voices is None:
        raise SystemExit(f"[stt] voices: {models.voices_error}")
    print("[stt] models fetched", flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--fetch"]:
        fetch()
    else:
        asyncio.run(main())
