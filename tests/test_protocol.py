#!/usr/bin/env python3
"""Protocol tests against the REAL server.py, on CPU, with the stand-in models
tools/dev-cpu.sh uses (whisper tiny, t5-small for MT, Piper voices, the real
VoxLingua107 language ID and Silero VAD). They prove the wire protocol and the
plumbing, not translation quality: t5-small emits junk translations by design.

    pip install -r requirements-test.txt     # see the file for CPU torch
    python3 -m pytest tests/test_protocol.py -v
    python3 tests/test_protocol.py           # the same

The first run downloads ~0.6 GB (whisper tiny, t5-small, VoxLingua107, Silero,
two Piper voices) into the usual Hugging Face / torch caches and
$LITHOS_TEST_CACHE (default ~/.cache/lithos-stack-test); later runs take about
two minutes. The whole module SKIPS when the packages are missing, or when the
models can't be fetched (offline). LITHOS_PROTOCOL_PYTHON picks another
interpreter for the server (default: this one).

Covered: /health; auth (none, bad, static, signed, expired, header, ?key=,
path, audience); the per-client limit (4429); the hello message; a short final
frame (< 512 samples); binary frames <= 64 KB; route=to skipping its own
language; cands narrowing detection; four concurrent connections each hearing
the whole utterance; parameter validation (4400); rooms (one per token subject,
several listeners per language, a listener leaving); the frame size limit
(1009), the audio rate limit (4413) and the forced cut of a solo utterance.

Not covered here: the shared-VAD regression (one Silero state for every
connection) did NOT reproduce on CPU when the fix was reverted, so its guard is
tools/smoke.py's concurrency case on a GPU stack.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

PY = os.environ.get("LITHOS_PROTOCOL_PYTHON", sys.executable)
CACHE = os.path.expanduser(os.environ.get("LITHOS_TEST_CACHE", "~/.cache/lithos-stack-test"))
TOKEN = "protocol-test-static-token"
SIGNING_KEY = "protocol-test-signing-key"
RATE = 24000
FRAME = RATE // 10 * 2
EN_TEXT = "Could you tell me where the train station is?"

if PY == sys.executable:
    missing = []
    for mod in ("torch", "faster_whisper", "transformers", "sentencepiece", "speechbrain", "piper",
                "websockets", "scipy", "numpy", "onnxruntime"):
        try:
            __import__(mod)
        except Exception:  # noqa: BLE001
            missing.append(mod)
    if missing:
        pytest.skip(f"SKIP protocol tests: missing {', '.join(missing)} (pip install -r requirements-test.txt)",
                    allow_module_level=True)

import stack_auth  # noqa: E402
import websockets  # noqa: E402
from smoke import heard_ok  # noqa: E402


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _espeak_dir():
    """macOS only: the piper wheel's espeak-ng looks for its data at a path baked
    in at build time and aborts the process (docs/dev/lessons-learned.md). Point
    ESPEAK_DATA_PATH at a directory shaped for both of its probes."""
    if sys.platform != "darwin" or os.environ.get("ESPEAK_DATA_PATH"):
        return os.environ.get("ESPEAK_DATA_PATH")
    out = subprocess.run([PY, "-c", "import piper, os; print(os.path.dirname(piper.__file__))"],
                         capture_output=True, text=True)
    data = os.path.join(out.stdout.strip(), "espeak-ng-data")
    if not os.path.isdir(data):
        return None
    d = os.path.join(CACHE, "espeak")
    os.makedirs(d, exist_ok=True)
    for name in os.listdir(data):
        link = os.path.join(d, name)
        if not os.path.lexists(link):
            os.symlink(os.path.join(data, name), link)
    link = os.path.join(d, "espeak-ng-data")
    if not os.path.lexists(link):
        os.symlink(data, link)
    return d


@pytest.fixture(scope="module")
def stack():
    voices = os.path.join(CACHE, "voices")
    fetched = subprocess.run(["bash", os.path.join(ROOT, "scripts", "fetch-voices.sh"), "en,es"],
                             env={**os.environ, "VOICES_DIR": voices}, capture_output=True, text=True)
    if not all(os.path.getsize(os.path.join(voices, f)) > 0 if os.path.exists(os.path.join(voices, f)) else False
               for f in ("en_US-lessac-medium.onnx", "es_ES-davefx-medium.onnx")):
        pytest.skip(f"SKIP protocol tests: could not fetch Piper voices ({fetched.stdout[-200:]})")
    port = _free_port()
    env = {**os.environ, "STACK_TOKEN": TOKEN, "STACK_SIGNING_KEY": SIGNING_KEY,
           "STACK_MAX_PER_CLIENT": "2", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "PYTHONUNBUFFERED": "1"}
    env.pop("STACK_OPEN", None)
    esp = _espeak_dir()
    if esp:
        env["ESPEAK_DATA_PATH"] = esp
    log = tempfile.NamedTemporaryFile("w+", suffix=".log", prefix="lithos-protocol-", delete=False)
    proc = subprocess.Popen(
        [PY, "-u", os.path.join(ROOT, "server", "server.py"),
         "--langs", "es", "--srcs", "en,es,fr", "--xeng",
         "--asr-model", "tiny", "--asr-multi-model", "tiny", "--mt-model", "t5-small",
         "--voices-dir", voices, "--port", str(port)],
        stdout=log, stderr=subprocess.STDOUT, env=env, cwd=ROOT)
    deadline = time.time() + float(os.environ.get("LITHOS_PROTOCOL_START_S", "900"))
    try:
        while True:
            if proc.poll() is not None:
                log.seek(0)
                tail = log.read()[-3000:]
                if "Connection" in tail or "resolve" in tail or "offline" in tail.lower():
                    pytest.skip(f"SKIP protocol tests: models unavailable (offline?)\n{tail[-600:]}")
                pytest.fail(f"server exited with {proc.returncode}:\n{tail}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                    if r.status == 200:
                        break
            except OSError:
                pass
            if time.time() > deadline:
                log.seek(0)
                pytest.fail(f"server not ready in time:\n{log.read()[-3000:]}")
            time.sleep(1)
        yield {"port": port, "base": f"ws://127.0.0.1:{port}", "log": log.name, "proc": proc}
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if proc.returncode not in (0, -15, None) or os.environ.get("LITHOS_PROTOCOL_LOG"):
            log.seek(0)
            print(log.read()[-4000:])
        log.close()


# ---------------------------------------------------------------- helpers

def signed(sub, ttl=600):
    return stack_auth.sign(SIGNING_KEY, sub, ttl)


def clip():
    with wave.open(os.path.join(ROOT, "tests", "audio", "en.wav")) as w:
        return w.readframes(w.getnframes())


def _connect(url, token=None, header=True):
    headers = {"Authorization": f"Bearer {token}"} if token and header else {}
    try:
        return websockets.connect(url, additional_headers=headers, max_size=2 ** 24, open_timeout=20)
    except TypeError:  # websockets < 14
        return websockets.connect(url, extra_headers=headers, max_size=2 ** 24, open_timeout=20)


async def first_message(url, token=None, header=True):
    """('hello', dict) or ('closed', code)."""
    try:
        async with _connect(url, token, header) as ws:
            m = await asyncio.wait_for(ws.recv(), 20)
            return "hello", json.loads(m)
    except websockets.ConnectionClosed as e:
        return "closed", (e.rcvd.code if e.rcvd else None)


async def converse(base, query, token, frames=None, expect_output=True, timeout=60, lead_s=0.5):
    """Stream the English clip (or the given frames) at real-time pace, then
    silence; collect everything that comes back."""
    frames = frames if frames is not None else [clip()[i:i + FRAME] for i in range(0, len(clip()), FRAME)]
    r = {"hello": None, "route": [], "heard": "", "said": "", "frames": [], "errors": [], "closed": None}
    async with _connect(f"{base}/translate?{query}", token) as ws:
        r["hello"] = json.loads(await asyncio.wait_for(ws.recv(), 20))
        state = {"end": None, "last": None}

        async def send():
            for _ in range(round(lead_s * 10)):  # room tone before the speech
                await ws.send(b"\x00" * FRAME)
                await asyncio.sleep(0.1)
            for f in frames:
                await ws.send(f)
                await asyncio.sleep(0.1 * len(f) / FRAME)
            state["end"] = time.monotonic()
            while True:
                await ws.send(b"\x00" * FRAME)
                await asyncio.sleep(0.1)

        async def receive():
            async for m in ws:
                if isinstance(m, bytes):
                    r["frames"].append(len(m))
                    state["last"] = time.monotonic()
                    continue
                d = json.loads(m)
                if d["type"] == "route":
                    r["route"].append(d["src"])
                elif d["type"] == "inputTranscript":
                    r["heard"] += d["text"]
                elif d["type"] == "transcript":
                    r["said"] += d["delta"]
                    state["last"] = state["last"] or time.monotonic()
                elif d["type"] == "error":
                    r["errors"].append(d["detail"])

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            await asyncio.sleep(0.2)
            now = time.monotonic()
            if any(t.done() for t in tasks):
                break
            if state["end"] is None:
                continue
            if expect_output and r["said"] and state["last"] and now - state["last"] > 2.5:
                break
            if not expect_output and now - state["end"] > 6:
                break
        for t in tasks:
            if t.done() and not t.cancelled() and t.exception() is not None:
                r["closed"] = repr(t.exception())
            elif t.done() and t is tasks[1]:
                r["closed"] = f"server closed ({ws.close_code})"
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return r


def run(coro):
    return asyncio.run(coro)


async def refusal(url, token):
    """(first message as a dict or None, close code) for a connection the server should refuse."""
    first = None
    try:
        async with _connect(url, token) as ws:
            first = json.loads(await asyncio.wait_for(ws.recv(), 20))
            await asyncio.wait_for(ws.recv(), 20)
    except websockets.ConnectionClosed as e:
        return first, (e.rcvd.code if e.rcvd else None)
    return first, None


async def listen(base, query, token, secs):
    """Join, send nothing, and collect what arrives for `secs` seconds."""
    got = {"hello": None, "text": [], "bytes": 0}
    async with _connect(f"{base}/translate?{query}", token) as ws:
        got["hello"] = json.loads(await asyncio.wait_for(ws.recv(), 20))
        t0 = time.monotonic()
        try:
            while (left := secs - (time.monotonic() - t0)) > 0:
                m = await asyncio.wait_for(ws.recv(), left)
                if isinstance(m, bytes):
                    got["bytes"] += len(m)
                else:
                    got["text"].append(json.loads(m))
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            pass
    return got


def speech_only():
    """The clip without its leading and trailing quiet, so repeats of it never pause."""
    import numpy as np
    pcm = np.frombuffer(clip(), "<i2")
    loud = np.nonzero(np.abs(pcm) > 600)[0]
    return pcm[loud[0]:loud[-1] + 1].tobytes()


# ---------------------------------------------------------------- tests

def test_health(stack):
    with urllib.request.urlopen(f"http://127.0.0.1:{stack['port']}/health", timeout=5) as r:
        assert r.status == 200
        assert r.read().decode().strip() == "ok"


def test_auth(stack):
    u = f"{stack['base']}/translate?lang=es"
    assert run(first_message(u)) == ("closed", 4401), "no token"
    assert run(first_message(u, "wrong-token")) == ("closed", 4401), "bad token"
    assert run(first_message(u, signed("expired", ttl=-10)))[0:2] == ("closed", 4401), "expired signed token"
    assert run(first_message(u, stack_auth.sign("another-key", "x", 600))) == ("closed", 4401), "foreign key"
    assert run(first_message(u, TOKEN))[0] == "hello", "static token in the header"
    assert run(first_message(u, signed("auth-test")))[0] == "hello", "signed token in the header"
    # The legacy URL forms, still accepted for old clients.
    assert run(first_message(f"{u}&key={TOKEN}", header=False))[0] == "hello", "?key="
    assert run(first_message(f"{stack['base']}/{TOKEN}/translate?lang=es", header=False))[0] == "hello", "path"
    assert run(first_message(f"{u}&key=wrong", header=False)) == ("closed", 4401), "bad ?key="
    # Audience: the pod's ready report is signed with the same key but opens nothing,
    # and a token without an audience is refused (STACK_ACCEPT_LEGACY_TOKENS is off).
    report = stack_auth.sign(SIGNING_KEY, "pod:x", 300, aud=stack_auth.AUD_REPORT)
    assert run(first_message(u, report)) == ("closed", 4401), "report token"
    assert run(first_message(u, stack_auth.sign(SIGNING_KEY, "legacy", 300, aud=None))) == ("closed", 4401), "no aud"


def test_per_client_limit(stack):
    """STACK_MAX_PER_CLIENT=2 for this server: a third connection is refused."""
    async def go():
        tok = signed("limit-test")
        u = f"{stack['base']}/translate?lang=es"
        async with _connect(u, tok) as a, _connect(u, tok) as b:
            assert json.loads(await a.recv())["type"] == "hello"
            assert json.loads(await b.recv())["type"] == "hello"
            kind, val = await first_message(u, tok)
            assert (kind, val) == ("closed", 4429)
            # Another subject is not affected.
            assert (await first_message(u, signed("limit-other")))[0] == "hello"
        # Released on close: the subject may connect again.
        for _ in range(20):
            if (await first_message(u, tok))[0] == "hello":
                return
            await asyncio.sleep(0.25)
        raise AssertionError("slots were not released")
    run(go())


def test_hello_shape(stack):
    kind, hello = run(first_message(f"{stack['base']}/translate?lang=es&src=auto", signed("hello")))
    assert kind == "hello"
    assert hello == {"type": "hello", "lang": "es", "src": "auto", "rate": 24000, "mode": "utterance"}
    kind, hello = run(first_message(f"{stack['base']}/translate?lang=es", signed("hello")))
    assert hello["src"] == "en"


def test_utterance_short_frames_and_frame_size(stack):
    """A final frame under 512 samples (Silero v5's frame) must not kill the
    connection, and every binary frame is at most 64 KB."""
    pcm = clip()
    frames, i, sizes = [b"\x00\x00"], 0, (FRAME, 998, FRAME, 202, FRAME * 2)  # one sample first
    while i < len(pcm):  # odd sizes, several under 512 samples (at 16 kHz, after resampling)
        n = sizes[len(frames) % len(sizes)]
        frames.append(pcm[i:i + n])
        i += n
    frames.append(b"\x00" * 600)  # 300 samples of silence: a short FINAL frame
    r = run(converse(stack["base"], "lang=es&src=en", signed("frames"), frames))
    assert not r["errors"] and r["closed"] is None, r
    assert heard_ok(r["heard"], EN_TEXT), r["heard"]
    assert r["said"].strip(), "no translation"
    assert r["frames"], "no audio came back"
    assert max(r["frames"]) <= 65536, max(r["frames"])
    assert sum(r["frames"]) / 2 / RATE > 0.5


def test_route_to_skips_its_own_language(stack):
    r = run(converse(stack["base"], "lang=en&src=auto&route=to&cands=en,es", signed("route-en"),
                     expect_output=False))
    assert r["route"][:1] == ["en"], r
    assert not r["heard"] and not r["said"] and not r["frames"], r


def test_route_to_translates_the_other_direction(stack):
    r = run(converse(stack["base"], "lang=es&src=auto&route=to&cands=en,es", signed("route-es")))
    assert r["route"][:1] == ["en"], r
    assert heard_ok(r["heard"], EN_TEXT), r["heard"]
    assert r["said"].strip() and r["frames"], r


def test_cands_narrows_detection(stack):
    """English speech, but the conversation is Spanish/French: detection must
    choose between those two (without cands it would say English)."""
    r = run(converse(stack["base"], "lang=en&src=auto&route=to&cands=es,fr", signed("cands"),
                     expect_output=False))
    assert r["route"] and r["route"][0] in ("es", "fr"), r


def test_concurrent_connections_hear_everything(stack):
    """Four callers at once, staggered, each must hear the whole sentence from
    its first words. (The shared-VAD regression that lost those words on a GPU
    does not reproduce on CPU; tools/smoke.py guards it there.)"""
    async def go():
        return await asyncio.gather(*[converse(stack["base"], "lang=es&src=auto", signed(f"conc-{n}"),
                                               lead_s=0.5 + 0.3 * n)
                                      for n in range(4)])
    for r in run(go()):
        assert not r["errors"] and r["closed"] is None, r
        assert heard_ok(r["heard"], EN_TEXT), r["heard"]
        assert r["heard"].strip().lower().startswith("could you"), r["heard"]
        assert r["said"].strip() and r["frames"], r


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------- hardening

def test_bad_parameters_refused(stack):
    """Unknown languages, routes, candidates and room ids: an error naming the
    problem, then close 4400. Nothing reaches the pipeline (or the log raw)."""
    base = f"{stack['base']}/translate"
    tok = signed("params")
    for query, word in [("lang=xx", "lang"), ("lang=es&src=zz", "src"), ("lang=es&route=from", "route"),
                        ("lang=es&src=auto&cands=en,qq", "cands"), ("lang=es&cands=" + ",".join(["en"] * 9), "cands"),
                        ("lang=es&room=a%20b", "room"), ("lang=es&room=" + "r" * 65, "room"),
                        ("lang=es&room=..%2Fx", "room"), ("lang=es&room=a%0Ab", "room"),
                        ("lang=es%0A%5Bstack%5D%20forged", "lang")]:
        first, code = run(refusal(f"{base}?{query}", tok))
        assert code == 4400, (query, first, code)
        assert first and first["type"] == "error" and word in first["detail"], (query, first)
    with open(stack["log"]) as f:
        assert "\n[stack] forged" not in f.read()
    # A region subtag is fine: served as the language.
    kind, hello = run(first_message(f"{base}?lang=es-ES&src=auto&cands=en-US,es", tok))
    assert kind == "hello" and hello["lang"] == "es", hello
    kind, hello = run(first_message(f"{base}?lang=es&room=Main_room-2", tok))
    assert kind == "hello", hello


def test_rooms_are_per_subject(stack):
    """Two tokens that both say ?room=main are in two rooms. The one who got
    there first is not the other's primary (it used to be: the second
    speaker's audio was discarded), and hears nothing of the other's speech
    (it used to get the transcript and, as a same-language listener, the raw
    microphone)."""
    async def go():
        spy = asyncio.create_task(listen(stack["base"], "lang=en&src=en&room=main", signed("room:mallory"), 25))
        await asyncio.sleep(1.0)
        victim = await converse(stack["base"], "lang=es&src=en&room=main", signed("room:alice"), timeout=40)
        return victim, await spy
    victim, spy = run(go())
    assert heard_ok(victim["heard"], EN_TEXT) and victim["said"].strip() and victim["frames"], victim
    assert spy["hello"]["type"] == "hello"
    assert spy["bytes"] == 0 and not spy["text"], spy


def test_two_listeners_of_one_language(stack):
    """Same subject, same room, same language: both receive the translation and
    its audio (the second used to replace the first)."""
    async def go():
        tok = signed("room:pair")
        main = asyncio.create_task(converse(stack["base"], "lang=es&src=en&room=pair", tok, timeout=40))
        await asyncio.sleep(0.3)      # main joins first: it is the primary, whose audio is used
        other = await listen(stack["base"], "lang=es&src=en&room=pair", tok, 25)
        return await main, other
    main, other = run(go())
    assert heard_ok(main["heard"], EN_TEXT) and main["said"].strip() and main["frames"], main
    types = [m["type"] for m in other["text"]]
    assert "inputTranscript" in types and "transcript" in types and other["bytes"] > 0, other


def test_a_listener_leaving_keeps_the_other(stack):
    """A second listener of the same language joins and leaves: the first keeps
    getting its language (leaving used to remove the language, so the first
    went deaf)."""
    async def go():
        tok = signed("room:leave")
        async def blip():
            await asyncio.sleep(0.3)
            await listen(stack["base"], "lang=es&src=en&room=leave", tok, 1.0)
        b = asyncio.create_task(blip())
        r = await converse(stack["base"], "lang=es&src=en&room=leave", tok, timeout=40, lead_s=2.5)
        await b
        return r
    r = run(go())
    assert heard_ok(r["heard"], EN_TEXT) and r["said"].strip() and r["frames"], r


def test_oversized_frame_refused(stack):
    """A WebSocket message over 256 KB closes the connection (1009)."""
    async def go():
        async with _connect(f"{stack['base']}/translate?lang=es&src=en", signed("big")) as ws:
            await ws.recv()
            await ws.send(b"\x00" * (300 * 1024))
            try:
                await asyncio.wait_for(ws.recv(), 20)
            except websockets.ConnectionClosed as e:
                return e.rcvd.code if e.rcvd else None
    assert run(go()) == 1009


def test_audio_faster_than_real_time_refused(stack):
    """The audit's DoS: megabytes of audio as fast as the socket takes them.
    Past the burst allowance the server closes with 4413."""
    async def go():
        async with _connect(f"{stack['base']}/translate?lang=es&src=en", signed("fast")) as ws:
            await ws.recv()
            frame = b"\x00" * (200 * 1024)          # 4.3 s of audio per message
            try:
                for _ in range(100):                  # 7 minutes of audio, sent at once
                    await ws.send(frame)
                await asyncio.wait_for(ws.recv(), 20)
            except websockets.ConnectionClosed as e:
                return e.rcvd.code if e.rcvd else None
    assert run(go()) == 4413


def test_solo_utterance_is_cut_at_the_maximum(stack):
    """Speech that never pauses is cut at MAX_UTTERANCE_S on a solo connection
    too (it used to grow one buffer for as long as the client kept talking)."""
    speech = speech_only() * 4                        # ~12 s without a pause
    frames = [speech[i:i + FRAME] for i in range(0, len(speech), FRAME)]
    with open(stack["log"]) as f:
        before = f.read().count("solo: forced cut")
    r = run(converse(stack["base"], "lang=es&src=en", signed("long"), frames, timeout=90))
    assert not r["errors"] and r["closed"] is None, r
    with open(stack["log"]) as f:
        assert f.read().count("solo: forced cut") > before
    assert r["said"].strip(), r
