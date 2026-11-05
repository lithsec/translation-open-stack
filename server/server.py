#!/usr/bin/env python3
"""
The open-weight speech translation stack, as one WebSocket server.

    python3 server/server.py --langs es,fr,pt --port 8790   (scripts/run.sh starts it; --help)

A client connects to ws://host:8790/translate?lang=<target>&src=<spoken language,
or auto>, sends 24 kHz mono PCM16 and gets back the transcript, the translation
text and 24 kHz PCM16 speech (docs/dev/protocol.md). Each utterance runs:

    Silero VAD -> VoxLingua107 language ID (?src=auto) -> recogniser -> translator -> voice

  recogniser  per spoken language in languages.toml (asr): faster-whisper, or
              Meta Omnilingual ASR for the languages Whisper serves badly
              (ht km lo sw hi fa bn ur ro).
  translator  per direction (translator, translator_to_en): llmmt first (Gemma 4,
              or for Lao MiLMMT then Gemma 4, on vLLM beside the stack) while a
              server answers, then Hy-MT2, with MADLAD-400 for the rest and as fallback.
  voice       Kokoro, VoxCPM2 (voxcpm_service.py, its own virtualenv), Piper,
              Meta MMS (--mms, CC-BY-NC) and eSpeak NG (--espeak) as the last resort.

The default is an utterance cascade: it translates once the VAD closes an
utterance, so first audio lands 1.5-3 s after the speaker pauses. Simultaneous
mode (?stream=1 when a room is opened; --streaming for connections outside a
room) re-transcribes the growing utterance, commits the words two passes agree
on (LocalAgreement) and translates and speaks them clause by clause.

?room=<id> joins a room: one speaker's audio, translated once per listener
language and fanned out. One recogniser and one translator serve every
connection, so the GPU bill does not grow with the number of languages.

The models are engines (server/engines/, one file each); languages.toml picks
them per language. Details: docs/dev/architecture.md; adding one:
docs/dev/adding-an-engine.md.
"""
import argparse, asyncio, copy, json, os, re, time  # noqa: F401 (json, re: as before, for readers of srv.)

import stack_config
# Re-exported, with everything below, for anything that reads server.py as a
# module (the tests load it by path and read srv.Room, srv.Pipeline, ...).
from engines.base import Context, AudioStream, RATE, VAD_RATE  # noqa: F401
from engines.manager import EngineSet  # noqa: F401
from engines.common import float_to_pcm16, hf_snapshot  # noqa: F401
# Re-exported for tests: tests/test_nonspeech.py reads these from server.py,
# tests/test_stack_config.py reads HYMT_NAMES.
from engines.common import (  # noqa: F401
    is_nonspeech, content_units, SHORT_NOISE_P, SHORT_NOISE_UNITS)
from engines.hymt import HYMT_NAMES  # noqa: F401
from translation_context import TranslationMemory  # noqa: F401

# The server, by part (docs/dev/architecture.md, module map):
#   pipeline.py    the shared models (Pipeline), the turn rules and tunables, forced cuts
#   connection.py  per-connection limits and close codes, clean(), the send helpers
#   rooms.py       Room, ROOMS, handle_room and the room_* coroutines
#   handlers.py    handle() (request parsing, the hello), solo and --streaming connections
# This file: the token and limits gate (guarded), warm-up, /health, flags, main().
import pipeline, rooms  # noqa: F401,E401  (srv.pipeline, srv.rooms: where main() and the tests set things)
from pipeline import (  # noqa: F401
    LANG_CONFIG, LANG_CONFIG_SRC, _T, MODELS, DEVICES, LICENCE_REVIEW,
    LONG_ENDPOINT_MS, endpointing, SHORT_TURN_HOLD_MS, min_speech_ms, short_turn,
    SENTENCE_CUT, PASSTHROUGH_MIN_CONF, PASSTHROUGH_MIN_S, STREAM_PASS_MS, STREAM_MAX_WORDS,
    STREAM_MIN_WORDS, STREAM_COMMA_WORDS, STREAM_POLICY, STREAM_TRIM, STREAM_TRIM_S,
    SWITCH_MIN_CONF, SWITCH_FREE_S, TRAILING_KEEP_MS,
    LANG_TO_MADLAD, KOKORO_VOICES, VOXCPM_LANGS, COQUI_VOICES, PIPER_VOICES, MMS_VOICES, MADLAD_ONLY,
    TTS_POOL, Pipeline, quietest_cut, common_prefix_words, forced_cut)
from connection import (  # noqa: F401
    MAX_FRAME_BYTES, AUDIO_MAX_SPEED, AUDIO_BURST_S, CLOSE_BAD_REQUEST, CLOSE_TOO_FAST, ROOM_ID_RE,
    MAX_CANDS, clean, AudioMeter, too_fast, Fanout, send_json, send_speech, speak_to)
from rooms import (  # noqa: F401
    Room, ROOMS, MAX_PENDING_UTTERANCES, room_heartbeat, room_worker, room_utterance, trim_point,
    resume_point, room_speak, room_flush, room_agree_flush, room_clause_flush, room_pass, handle_room)
from handlers import handle_streaming, BadRequest, _code, parse_request, handle  # noqa: F401

# Set by main() from its flags, on pipeline (where endpointing() reads them),
# so they are read from there, live, rather than copied here.
_PIPELINE_FLAGS = ("ENDPOINT_MS", "LONG_UTTERANCE_S", "MAX_UTTERANCE_S")


def __getattr__(name):
    if name in _PIPELINE_FLAGS:
        return getattr(pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


LIMITS = None  # stack_auth.Limits, made in main()


# A token for an edition this stack doesn't serve (a commercial client on a
# non-profit-only stack): refused rather than served with voices it may not use.
CLOSE_EDITION = 4403


def connection_edition(served, claim):
    """The edition a connection is served in, or None to refuse it
    (stack_auth.connection_edition, which services/omni-stt shares)."""
    import stack_auth
    return stack_auth.connection_edition(served, claim)


async def guarded(ws, pipe):
    """One client's failure must never reach the serve loop.

    Found the hard way on a metered GPU: a bench client cancelling its receive
    task produced a keepalive-ping timeout that propagated out of the handler
    and killed the whole server — it had logged "ready", then refused every
    later connection with ECONNREFUSED, which reads exactly like a port
    problem and is not one.
    """
    from urllib.parse import urlparse, parse_qs
    import stack_auth
    url = urlparse(ws.request.path)
    sub, via, claim = stack_auth.credentials_for(ws.request.headers, url.path, parse_qs(url.query))
    if sub is None:
        print(f"[stack] refused: bad or missing token (via {clean(via, 12)})", flush=True)
        await ws.close(code=4401, reason="unauthorized")
        return
    who = clean(sub, 24)    # the subject comes from the token: printable, bounded
    edition = connection_edition(pipe.editions, claim)
    if edition is None:
        print(f"[stack] refused {who}: its token is for the {claim} edition; this stack serves "
              f"{'/'.join(pipe.editions)}", flush=True)
        await ws.close(code=CLOSE_EDITION, reason=f"this stack does not serve the {claim} edition")
        return
    why = LIMITS.admit(sub)
    if why:
        print(f"[stack] refused {who}: {why}", flush=True)
        await ws.close(code=4429, reason=why)
        return
    if via in ("path", "query"):
        print(f"[stack] {who} sent its token in the URL — clients should use the Authorization header", flush=True)
    try:
        await asyncio.wait_for(handle(ws, pipe, sub, edition), LIMITS.session_s)
    except asyncio.TimeoutError:
        print(f"[stack] {who}: session time limit reached", flush=True)
        await ws.close(code=4408, reason="session time limit")
    except Exception as e:
        print(f"[stack] client ended: {type(e).__name__}: {clean(e, 200)}")
    finally:
        LIMITS.release(sub)


def warmup(pipe, langs):
    """First calls compile CUDA kernels and build caches — measured as
    seconds of the FIRST utterance's latency (Spanish paid ~3s of it in the
    first bench). Pay it at boot instead, before "ready" is printed, so no
    listener ever does.

    The voices warm in parallel, one thread per voice ENGINE (the first in each
    language's chain), each going through its own languages in turn: every
    language is still warmed, but no engine is ever called by two warm-up
    threads at once (VoxCPM2 takes one sentence at a time, and a second would
    overflow to eSpeak). Sequentially this took ~34 s on a GPU with 25 languages.
    STACK_WARM_LANGS=en,es limits it to those languages (the rest then pay their
    first-call cost, a few seconds, on their first sentence)."""
    import numpy as np
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.time()
    only = [l.strip() for l in os.environ.get("STACK_WARM_LANGS", "").split(",") if l.strip()]
    langs = [l for l in langs if l in only] if only else list(langs)
    silence = np.zeros(VAD_RATE, dtype=np.float32)
    pipe.transcribe(silence, "en")
    if pipe.asr_multi is not None:
        pipe.transcribe(silence, "es")
    texts = pipe.translate_batch("Hello, welcome to the service.", langs) if langs else []
    # Grouped by the engine object, so a voice shared by both editions' sets
    # (EDITION=both) is one group, and each of its languages is warmed once.
    by_engine, seen = {}, set()
    for ed, vs in pipe.voice_sets.items():
        for lg, tr in zip(langs, texts):
            chain = vs.chain(lg)
            key = id(chain[0]) if chain else None
            if (key, lg) not in seen:
                seen.add((key, lg))
                by_engine.setdefault(key, []).append((lg, tr, ed))

    def warm(items):
        for lg, tr, ed in items:
            pipe.synthesise(tr, lg, ed)

    with ThreadPoolExecutor(max(1, len(by_engine)), thread_name_prefix="warm") as pool:
        for f in [pool.submit(warm, pairs) for pairs in by_engine.values()]:
            f.result()
    print(f"[stack] warm in {time.time() - t0:.1f}s ({len(langs)} languages, "
          f"{len(by_engine)} voice engines in parallel) — first utterance pays nothing")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", default="es,fr,pt")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--xeng", action="store_true",
                    help="also load multilingual whisper so ?src=<lang> works (X -> English)")
    ap.add_argument("--clone", metavar="REF_WAV", default=None,
                    help="CosyVoice2 zero-shot: en/es/fr/pt spoken in this reference voice")
    ap.add_argument("--srcs", default="en,ru,es",
                    help="with --xeng: source languages to expect / auto-route among")
    ap.add_argument("--asr-model", default="distil-large-v3",
                    help="faster-whisper model id; 'tiny' for a CPU plumbing smoke")
    ap.add_argument("--asr-revision", default="",
                    help="pin --asr-model to this revision of its repo (scripts/run.sh passes "
                         "languages.toml [models.whisper] revision); shared with --asr-multi-model "
                         "when both name the same model")
    ap.add_argument("--asr-multi-revision", default="",
                    help="pin --asr-multi-model to this revision when it differs from --asr-model "
                         "(languages.toml [models.whisper] multi_revision)")
    ap.add_argument("--asr-multi-model", default="large-v3",
                    help="multilingual whisper for --xeng; 'tiny' (which IS multilingual, "
                         "unlike distil) for a CPU plumbing smoke")
    ap.add_argument("--mt-model", default="google/madlad400-3b-mt",
                    help="T5-family MT model. Anything but MADLAD is a PLUMBING smoke: "
                         "other T5s ignore the <2xx> language tags and emit junk on purpose")
    ap.add_argument("--voices-dir", default=None, help="Piper voices dir (default: <script>/voices)")
    ap.add_argument("--serial-tts", action="store_true",
                    help="run GPU voices one at a time. Costs ~0.06s to the last "
                         "of five languages; use on a card that cannot hold "
                         "several voices' activations at once")
    ap.add_argument("--coqui", action="store_true",
                    help="use Coqui VITS checkpoints where mapped (Haitian Creole); "
                         "CC-BY-SA, and the way off MMS for that language")
    ap.add_argument("--kokoro", action="store_true",
                    help="use Kokoro (GPU, 24kHz native) for en/es/fr/it/pt; "
                         "Piper still serves everything else")
    ap.add_argument("--mt-ct2", default=None,
                    help="directory of a CTranslate2-converted MT model; replaces "
                         "the HF decode path (see README for the convert command)")
    ap.add_argument("--voxcpm", default=None,
                    help="URL(s) of voxcpm_service.py, comma-separated (e.g. http://127.0.0.1:8791,"
                         "http://127.0.0.1:8792; scripts/run.sh starts one per GPU it may use): VoxCPM2 voices "
                         "for --voxcpm-langs, each sentence to the least-loaded instance; when all are busy or "
                         "down, the next voice in the chain speaks it")
    ap.add_argument("--voxcpm-max-inflight", type=int,
                    default=int(os.environ["VOXCPM_MAX_INFLIGHT"]) if os.environ.get("VOXCPM_MAX_INFLIGHT") else None,
                    help="sentences one VoxCPM2 instance takes at once before overflow goes to the next voice "
                         "(default: $VOXCPM_MAX_INFLIGHT, else what each instance's /health says: its batch)")
    ap.add_argument("--espeak", action="store_true",
                    help="eSpeak NG (the espeak-ng program, GPL-3.0, run as a separate process) as the last "
                         "voice of every language it speaks: VoxCPM2's overflow, and fa/ro in commercial")
    ap.add_argument("--voxcpm-langs", default="",
                    help="languages VoxCPM2 speaks (it sustains ~2 real-time voices per GPU); default: the "
                         "`voxcpm = true` languages of the edition (languages.toml)")
    ap.add_argument("--edition", default=os.environ.get("EDITION") or "nonprofit",
                    choices=stack_config.EDITIONS,
                    help="nonprofit: every configured voice; commercial: only voices and models licensed for "
                         "commercial use (server/licences.py, docs/licences.md); both: each connection in the "
                         "edition its token names (claim \"ed\"), commercial when it names none. "
                         "Default: $EDITION or nonprofit")
    ap.add_argument("--hymt", default=None,
                    help="directory of the 4-bit Hy-MT2 7B built by prepare-mt.sh; translates into "
                         "the 36 languages it supports, MADLAD the rest")
    ap.add_argument("--long-utterance-s", type=float, default=5.0,
                    help="past this much buffered speech, accept a clause-length "
                         "gap as an endpoint instead of a full pause")
    ap.add_argument("--max-utterance-s", type=float, default=9.0,
                    help="cut an utterance here even if the speaker never pauses")
    ap.add_argument("--endpoint-ms", type=int, default=700,
                    help="silence that ends an utterance (lower = faster, riskier mid-sentence)")
    ap.add_argument("--streaming", action="store_true",
                    help="LocalAgreement streaming: translate while they talk, clause by clause")
    ap.add_argument("--mms", action="store_true",
                    help="synthesise ht/km/lo with MMS-TTS (CC-BY-NC, downloaded by YOU, not shipped)")
    ap.add_argument("--omni", action="store_true",
                    help="with --xeng: Omnilingual ASR for ht/km/lo/sw sources (pip install omnilingual-asr)")
    ap.add_argument("--omni-large", action="store_true", default=os.environ.get("OMNI_LARGE") == "1",
                    help="with --omni: also load [models.omnilingual_large] (the 7B, ~20 GB) for the languages "
                         "with omni = \"large\" (Lao, Khmer). Default: $OMNI_LARGE=1")
    args = ap.parse_args()
    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    # X->eng needs an English voice on the way out.
    if args.xeng and "en" not in langs:
        langs.append("en")

    srcs = [l.strip() for l in args.srcs.split(",") if l.strip()]
    print(f"[stack] language config: {LANG_CONFIG_SRC}")
    print(f"[stack] edition: {args.edition}", flush=True)
    if args.edition in ("commercial", "both"):
        # The shared models (and the Whisper flags, which can differ from
        # [models.whisper]) must be commercially licensed, or nothing starts.
        models = copy.deepcopy(MODELS)
        models["whisper"]["model"] = args.asr_model
        if args.xeng and args.asr_multi_model != args.asr_model:
            models["whisper_multi"] = {"model": args.asr_multi_model, "revision": args.asr_multi_revision}
        if not args.hymt:
            models.pop("hymt", None)
        bad = stack_config.commercial_problems(models, LICENCE_REVIEW)
        if bad:
            raise SystemExit("[licence] EDITION=commercial refuses to start:\n  " + "\n  ".join(bad))
    pipe = Pipeline(langs, xeng=args.xeng, clone_ref=args.clone, srcs=srcs, omni=args.omni, mms=args.mms,
                    asr_model=args.asr_model, mt_model=args.mt_model,
                    mt_ct2=args.mt_ct2, kokoro=args.kokoro, coqui=args.coqui, serial_tts=args.serial_tts,
                    asr_multi_model=args.asr_multi_model, asr_multi_revision=args.asr_multi_revision or None,
                    voices_dir=args.voices_dir, hymt=args.hymt,
                    voxcpm=args.voxcpm, voxcpm_langs=[l for l in args.voxcpm_langs.split(",") if l],
                    asr_revision=args.asr_revision, edition=args.edition,
                    voxcpm_max_inflight=args.voxcpm_max_inflight, espeak=args.espeak,
                    omni_large=args.omni_large)
    pipe.streaming = args.streaming
    # On pipeline, where endpointing() reads them (not module globals here).
    pipeline.ENDPOINT_MS = args.endpoint_ms
    pipeline.LONG_UTTERANCE_S = args.long_utterance_s
    pipeline.MAX_UTTERANCE_S = args.max_utterance_s

    warmup(pipe, langs)
    global LIMITS
    import stack_auth
    LIMITS = stack_auth.Limits()
    print(f"[stack] access: {'signed tokens' if os.environ.get('STACK_SIGNING_KEY') else ''}"
          f"{' + ' if os.environ.get('STACK_SIGNING_KEY') and os.environ.get('STACK_TOKEN') else ''}"
          f"{'static token' if os.environ.get('STACK_TOKEN') else ''}{'OPEN (LAN only)' if not stack_auth.auth_required() else ''}"
          f"; limits {LIMITS.per_client}/client, {LIMITS.total} total, {LIMITS.session_s // 60} min/session", flush=True)

    import websockets
    from http import HTTPStatus

    def health(connection, request):
        # Plain GET /health answers 200 once models are loaded (the port only
        # opens after warm-up), so a launcher can tell "pod up" from "ready"
        # without a token or a WebSocket. It reveals nothing else.
        if request.path == "/health":
            return connection.respond(HTTPStatus.OK, "ok\n")
        return None

    async with websockets.serve(lambda ws: guarded(ws, pipe), "0.0.0.0", args.port,
                                max_size=MAX_FRAME_BYTES, ping_interval=None, process_request=health):
        print(f"[stack] ready on :{args.port} for {langs}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
