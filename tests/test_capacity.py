#!/usr/bin/env python3
"""VoxCPM2 capacity: the instance plan (stack_config.voxcpm_plan), balancing
and overflow in engines/voxcpm.py against fake voxcpm_service.py instances
(small local HTTP servers, no model), server.send_speech's handling of a
stream (its own thread: waiting streams must not starve the TTS pool),
voxcpm_service.py itself with a stand-in model (busy -> 503, abandoned
requests skipped), and the eSpeak NG last-resort voice.

    python3 tests/test_capacity.py        (or python3 -m pytest tests/test_capacity.py)

The eSpeak NG test is skipped when `espeak-ng` is not installed
(apt-get install espeak-ng; brew install espeak-ng).
"""
import contextlib
import io
import json
import os
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

import stack_config as c  # noqa: E402
from engines.base import Context, AudioStream, RATE  # noqa: E402
from engines.espeak import ESpeak, ESPEAK_VOICES  # noqa: E402
from engines.manager import EngineSet  # noqa: E402
from engines.voxcpm import VoxCPM  # noqa: E402


# ---------------------------------------------------------------- fake services

class FakeService:
    """A voxcpm_service.py stand-in: /health, and /tts (whole or streamed) that
    waits on `gate` before answering, so a test can hold requests in flight.
    A stream is `chunks` chunks `delay` s apart; `status` and `rate` set the
    answer's status and X-Sample-Rate; `truncate` breaks the stream after its
    first chunk (the connection drops without the end marker)."""

    def __init__(self, chunks=1, delay=0.0, status=200, rate=str(RATE), truncate=False, port=0):
        self.gate = threading.Event()
        self.gate.set()
        self.served = []
        self.chunks, self.delay, self.status, self.rate, self.truncate = chunks, delay, status, rate, truncate
        svc = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                svc.gate.wait(10)
                svc.served.append(body["text"])
                pcm = b"\x01\x00" * 480
                if svc.status != 200:
                    self.send_response(svc.status)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("X-Sample-Rate", svc.rate)
                if body.get("stream"):
                    pcm = b"\x01\x00" * 2400
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    try:
                        for i in range(svc.chunks):
                            time.sleep(svc.delay)
                            self.wfile.write(b"%x\r\n%s\r\n" % (len(pcm), pcm))
                            self.wfile.flush()
                            if svc.truncate:
                                self.close_connection = True
                                return
                        self.wfile.write(b"0\r\n\r\n")
                    except OSError:
                        self.close_connection = True
                else:
                    self.send_header("Content-Length", str(len(pcm)))
                    self.end_headers()
                    self.wfile.write(pcm)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.httpd.daemon_threads = True
        self.httpd.handle_error = lambda *a: None       # a client that hung up (tested on purpose)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _dead_url():
    """A port nothing listens on."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make_vox(urls, cap=3, clock=None, queue_s=0.0):
    """queue_s: how long a sentence with a fallback waits for a slot (0 here: at once, so
    the cap tests are about the cap; test_fallback_language_waits_briefly covers the wait)."""
    ctx = Context(options={"voxcpm": ",".join(urls), "voxcpm_langs": ["ko", "ru"], "voxcpm_max_inflight": cap})
    v = VoxCPM(ctx, clock=clock or time.monotonic)
    v.queue_s = queue_s
    with contextlib.redirect_stdout(io.StringIO()):
        v.load()
    return v


def _server():
    """server.py as a module (as tests/test_streaming.py loads it)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("stack_server_cap", os.path.join(ROOT, "server", "server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _WS:
    """A listener's socket: counts what it is sent; `fail_after` sends, then raises."""

    def __init__(self, fail_after=None):
        self.n = 0
        self.sends = 0
        self.fail_after = fail_after

    async def send(self, b):
        if self.fail_after is not None and self.sends >= self.fail_after:
            raise ConnectionError("listener gone")
        self.sends += 1
        self.n += len(b)


def _settle(v, timeout=3.0):
    """Wait until nothing is in flight (a closed stream releases on its own thread)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if all(i["inflight"] == 0 for i in v.stats()["instances"]):
            return True
        time.sleep(0.02)
    return False


def _open_stream(v, text, fallback=lambda: b"FALLBACK"):
    """Start a stream (which reserves its slot) and return (generator, first chunk)."""
    g = v.stream(text, "ko", fallback)
    return g, next(g)


# ---------------------------------------------------------------- balancing

def test_last_voice_waits_for_a_slot():
    """A language with nothing after VoxCPM2 (km, lo, tl in commercial) waits for a slot;
    one with a fallback overflows at once."""
    a = FakeService()
    try:
        v = make_vox([a.url], cap=1)
        v.wait_s = 2.0
        v.ctx.voice_after = lambda lang, name: lang != "km"
        held = v.acquire("ko")
        assert held is not None
        with contextlib.redirect_stdout(io.StringIO()):
            assert v.acquire("ko") is None                      # has a fallback: overflow now
        got = {}
        t = threading.Thread(target=lambda: got.setdefault("inst", v.acquire("km")))
        t0 = time.monotonic()
        t.start()
        time.sleep(0.3)
        assert t.is_alive()                                     # waiting, not overflowed
        v.release(held)
        t.join(2)
        assert got["inst"] is not None and time.monotonic() - t0 < 1.5
        v.release(got["inst"])
        # Nothing frees up: it gives up after wait_s (then the sentence is text only).
        held = v.acquire("ko")
        v.wait_s = 0.4
        with contextlib.redirect_stdout(io.StringIO()):
            t0 = time.monotonic()
            assert v.acquire("km") is None
            assert 0.35 <= time.monotonic() - t0 < 1.5
        v.release(held)
    finally:
        a.close()


def test_least_loaded_balancing():
    a, b = FakeService(), FakeService()
    try:
        v = make_vox([a.url, b.url], cap=3)
        # Idle: sentences alternate (fewest in flight, then fewest served).
        with contextlib.redirect_stdout(io.StringIO()):
            for i in range(4):
                assert v.synthesise(f"s{i}", "ko") is not None
        assert len(a.served) == 2 and len(b.served) == 2
        # Held in flight: each new sentence goes to the instance with fewer.
        a.gate.clear()
        b.gate.clear()
        held = [v.acquire("ko") for _ in range(5)]
        assert [h.port for h in held].count(a.port) == 3 and [h.port for h in held].count(b.port) == 2
        v.release(held[0])                        # a: 2 in flight, b: 2
        nxt = v.acquire("ko")
        assert nxt.inflight == 3 and v.stats()["overflow"] == 0
        for h in held[1:] + [nxt]:
            v.release(h)
        assert all(i["inflight"] == 0 for i in v.stats()["instances"])
    finally:
        a.gate.set()
        b.gate.set()
        a.close()
        b.close()


def test_streams_are_balanced_while_they_play():
    """A stream holds its slot until it ends, so concurrent streams spread."""
    a, b = FakeService(), FakeService()
    try:
        v = make_vox([a.url, b.url], cap=3)
        with contextlib.redirect_stdout(io.StringIO()):
            gens = [_open_stream(v, f"s{i}") for i in range(4)]
        assert sorted(i["inflight"] for i in v.stats()["instances"]) == [2, 2]
        for g, first in gens:
            assert first != b"FALLBACK" and len(first) % 2 == 0
            g.close()                              # the listener hung up
        s = v.stats()
        assert [i["inflight"] for i in s["instances"]] == [0, 0]
        assert [i["errors"] for i in s["instances"]] == [0, 0]
    finally:
        a.close()
        b.close()


# ---------------------------------------------------------------- the cap

def test_cap_returns_none_and_calls_fallback():
    a = FakeService()
    try:
        v = make_vox([a.url], cap=2)
        a.gate.clear()
        held = [v.acquire("ko"), v.acquire("ko")]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            t = time.monotonic()
            assert v.synthesise("busy", "ko") is None                   # None: the next voice speaks
            calls = []
            chunks = list(v.stream("busy too", "ru", lambda: calls.append(1) or b"espeak"))
            assert time.monotonic() - t < 0.5                          # immediately, not queued
        assert chunks == [b"espeak"] and calls == [1]
        assert v.stats()["overflow"] == 2 and a.served == []
        # Logged once (rate-limited), with what went where.
        log = out.getvalue()
        assert log.count("VoxCPM2 busy") == 1 and "all 1 instance at 2 sentences" in log and "ko" in log
        for h in held:
            v.release(h)
        a.gate.set()
        with contextlib.redirect_stdout(io.StringIO()):
            assert v.synthesise("free again", "ko") is not None
    finally:
        a.gate.set()
        a.close()


def test_overflow_log_is_rate_limited():
    clock = Clock()
    v = make_vox([_dead_url()], cap=1, clock=clock)   # (load marks it down: every call overflows)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        for _ in range(50):
            assert v.acquire("ko") is None
        clock.t += 11
        assert v.acquire("ru") is None
    lines = [x for x in out.getvalue().splitlines() if "VoxCPM2 busy" in x]
    assert len(lines) == 2 and v.stats()["overflow"] == 51
    assert "50 sentences" in lines[1] or "ko×49" in lines[1], lines   # the count since the last line
    assert "down" in lines[0]


# ---------------------------------------------------------------- health

def test_unreachable_instance_is_skipped_then_retried():
    clock = Clock()
    a = FakeService()
    dead = _dead_url()
    try:
        v = make_vox([dead, a.url], cap=3, clock=clock)
        s = v.stats()["instances"]
        assert s[0]["down"] and not s[1]["down"]            # load()'s health check
        clock.t += 20                                       # its pause is over: tried again...
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            got = b"".join(v.stream("hello", "ko", lambda: b"FALLBACK"))
        assert got != b"FALLBACK" and a.served == ["hello"]   # ...fails, and the sentence moves on
        s = v.stats()["instances"]
        assert s[0]["down"] and s[0]["errors"] == 1 and s[1]["served"] == 1
        assert "unreachable" in out.getvalue()
        # While it is down, nothing is sent there (no error, no delay).
        with contextlib.redirect_stdout(io.StringIO()):
            assert v.synthesise("again", "ko") is not None
        assert v.stats()["instances"][0]["errors"] == 1
        # Every instance down: fallback, counted as overflow.
        a.close()
        with contextlib.redirect_stdout(io.StringIO()):
            assert b"".join(v.stream("x", "ko", lambda: b"FALLBACK")) == b"FALLBACK"
            assert b"".join(v.stream("y", "ko", lambda: b"FALLBACK")) == b"FALLBACK"
        assert all(i["down"] for i in v.stats()["instances"]) and v.stats()["overflow"] == 1
    finally:
        a.close()


def test_server_waits_for_a_service_that_starts_after_it():
    """run.sh starts the services and the server together; the server loads its own
    models, then waits for VoxCPM2 before warm-up and "ready" (wait_ready)."""
    import engines.voxcpm as vx
    url = _dead_url()
    v = make_vox([url])
    assert v.instances[0].down_until > 0            # not up yet at load()
    port = int(url.rsplit(":", 1)[1])
    late = []
    threading.Timer(1.5, lambda: late.append(FakeService(port=port))).start()
    t0 = time.time()
    with contextlib.redirect_stdout(io.StringIO()) as out:
        v.wait_ready()
    assert 1.0 < time.time() - t0 < 8, time.time() - t0
    assert v.instances[0].down_until == 0 and "1 of 1 instance up" in out.getvalue()
    late[0].close()
    assert vx.START <= time.time()


def test_server_gives_up_on_a_service_whose_process_has_gone():
    import engines.voxcpm as vx
    v = make_vox([_dead_url()])
    saved, vx.START = vx.START, time.time() - 120     # past the 60 s grace; no such process
    try:
        t0 = time.time()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            v.wait_ready()
    finally:
        vx.START = saved
    assert time.time() - t0 < 10 and v.instances[0].down_until > 0
    assert "process has exited" in out.getvalue() and "0 of 1 instance up" in out.getvalue()


def test_server_stops_waiting_at_the_deadline():
    import engines.voxcpm as vx
    v = make_vox(["http://192.0.2.1:8791"])            # remote (TEST-NET): never given up on by process
    os.environ["VOXCPM_START_WAIT_S"] = "0"
    try:
        t0 = time.time()
        with contextlib.redirect_stdout(io.StringIO()):
            v.wait_ready()
    finally:
        del os.environ["VOXCPM_START_WAIT_S"]
    assert time.time() - t0 < 2 and v.instances[0].down_until > 0
    assert vx.START > 0


def test_thread_safety_under_load():
    a, b = FakeService(), FakeService()
    try:
        v = make_vox([a.url, b.url], cap=2)
        results = []

        def one(i):
            got = b"".join(v.stream(f"s{i}", "ko", lambda: b"FB"))
            results.append(got == b"FB")

        with contextlib.redirect_stdout(io.StringIO()):
            ts = [threading.Thread(target=one, args=(i,)) for i in range(40)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        s = v.stats()
        assert len(results) == 40
        assert sum(i["served"] for i in s["instances"]) + s["overflow"] == 40
        assert results.count(True) == s["overflow"]
        assert all(i["inflight"] == 0 and i["peak"] <= 2 for i in s["instances"])
    finally:
        a.close()
        b.close()


def test_fallback_language_waits_briefly():
    """A language with a voice after VoxCPM2 waits up to queue_s for a slot (the queue
    is in the stack, not in the service), then overflows. Every instance down: no wait."""
    a = FakeService()
    try:
        v = make_vox([a.url], cap=1, queue_s=1.0)
        held = v.acquire("ko")
        got = {}
        t = threading.Thread(target=lambda: got.setdefault("inst", v.acquire("ko")))
        t0 = time.monotonic()
        t.start()
        time.sleep(0.2)
        assert t.is_alive()
        v.release(held)
        t.join(2)
        assert got["inst"] is not None and time.monotonic() - t0 < 0.8
        with contextlib.redirect_stdout(io.StringIO()):
            t0 = time.monotonic()
            assert v.acquire("ko") is None                      # nothing frees: overflow after queue_s
            assert 0.95 <= time.monotonic() - t0 < 1.6
            t0 = time.monotonic()
            assert v.acquire("ko", wait=False) is None          # synthesise(): never waits
            assert time.monotonic() - t0 < 0.1
        v.release(got["inst"])
    finally:
        a.close()
    v = make_vox([_dead_url()], cap=1, queue_s=5)               # (load marks it down)
    v.wait_s = 5
    v.ctx.voice_after = lambda lang, name: False
    with contextlib.redirect_stdout(io.StringIO()):
        t0 = time.monotonic()
        assert v.acquire("ko") is None and v.acquire("ru") is None
        assert time.monotonic() - t0 < 0.2                      # down, not busy: waiting can't help


def test_waiting_streams_do_not_starve_the_tts_pool():
    """Regression (2026-09-30 audit, scratchpad poc/starve.py): streams that wait for a
    VoxCPM2 slot must not take the shared TTS pool's workers. They did (send_speech ran
    next() in TTS_POOL): 1 instance, cap 3, 8 workers, 11 Khmer listeners -> the
    streams holding the slots could not advance, every waiter hit VOXCPM_WAIT_S, 5
    listeners got silence, and a Piper sentence for another language waited as long."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    srv = _server()
    a = FakeService(chunks=10, delay=0.05)                      # a 0.5 s sentence, 10 chunks
    pool = ThreadPoolExecutor(max_workers=8)                    # TTS_POOL's default
    saved = srv.TTS_POOL
    srv.TTS_POOL = pool
    try:
        v = make_vox([a.url], cap=3)
        v.wait_s = 4.0
        v.ctx.voice_after = lambda lang, name: False            # nothing after VoxCPM2: it waits

        async def listener():
            ws = _WS()
            t0 = time.monotonic()
            await srv.send_speech(ws, AudioStream(v.stream("sentence", "ko", lambda: None)))
            return time.monotonic() - t0, ws.n

        async def other_language():                             # Piper for Spanish, meanwhile
            await asyncio.sleep(0.3)
            t0 = time.monotonic()
            await asyncio.get_running_loop().run_in_executor(srv.TTS_POOL, time.sleep, 0.05)
            return time.monotonic() - t0

        async def main():
            return await asyncio.gather(other_language(), *[listener() for _ in range(11)])

        t0 = time.monotonic()
        with contextlib.redirect_stdout(io.StringIO()):
            other, *listeners = asyncio.run(main())
        wall = time.monotonic() - t0
        silent = sum(1 for _, n in listeners if n == 0)
        assert silent == 0, f"{silent} of 11 listeners got silence; {sorted(listeners)}"
        assert all(n == 10 * 4800 for _, n in listeners), listeners
        assert other < 0.5, f"another language's sentence waited {other:.1f}s for a TTS worker"
        assert wall < 3.5, wall                                 # 4 turns of 0.5 s, not VOXCPM_WAIT_S
        assert v.stats()["overflow"] == 0 and _settle(v)
    finally:
        srv.TTS_POOL = saved
        pool.shutdown(wait=False)
        a.close()


def test_stream_releases_its_slot_on_every_exit():
    """However a stream ends, its slot is released and its connection closed."""
    closed = []

    def tracked(v):
        real = v._open

        def _open(inst, text, lang):
            conn, r = real(inst, text, lang)
            orig = conn.close
            conn.close = lambda: (closed.append(1), orig())
            return conn, r
        v._open = _open
        return v

    def check(v, errors, conns):
        # A cancelled stream's own thread may still be taking its slot and closing its
        # connection when we get here (slow CI runners): give it a moment.
        end = time.monotonic() + 5
        while len(closed) < conns and time.monotonic() < end:
            time.sleep(0.02)
        assert _settle(v), v.stats()
        s = v.stats()["instances"]
        assert [i["errors"] for i in s] == errors, s
        assert len(closed) == conns, closed
        closed.clear()

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        # A bad X-Sample-Rate (used to raise outside the try: slot and connection leaked).
        for rate in ("abc", "", "48000"):
            a = FakeService(rate=rate)
            v = tracked(make_vox([a.url], cap=1))
            assert b"".join(v.stream("x", "ko", lambda: b"FB")) == b"FB"
            check(v, [1], 1)
            a.close()
        # HTTP 500: falls back. 503 busy (another client): not an error, the next instance.
        a, b = FakeService(status=500), FakeService(status=503)
        v = tracked(make_vox([a.url], cap=1))
        assert b"".join(v.stream("x", "ko", lambda: b"FB")) == b"FB"
        check(v, [1], 1)
        good = FakeService()
        v = tracked(make_vox([b.url, good.url], cap=1))
        v.instances[1].served = 1                                # so the busy one is tried first
        got = b"".join(v.stream("x", "ko", lambda: b"FB"))
        assert got != b"FB" and b.served == ["x"] and good.served == ["x"]
        check(v, [0, 0], 2)
        assert v.stats()["instances"][0]["served"] == 0 and v.stats()["instances"][1]["served"] == 2
        # Broken mid-sentence: what came is kept, the rest is not re-spoken.
        t = FakeService(chunks=3, truncate=True)
        v = tracked(make_vox([t.url], cap=1))
        got = b"".join(v.stream("x", "ko", lambda: b"FB"))
        assert got and b"FB" not in got
        check(v, [1], 1)
        # The listener hangs up mid-stream: close(), garbage collection.
        s = FakeService(chunks=5, delay=0.02)
        v = tracked(make_vox([s.url], cap=1))
        g = v.stream("x", "ko", lambda: b"FB")
        next(g)
        g.close()
        check(v, [0], 1)
        g = v.stream("x", "ko", lambda: b"FB")
        next(g)
        del g
        import gc
        gc.collect()
        check(v, [0], 1)
        # Through send_speech: the socket fails mid-stream; the sender is cancelled
        # while its stream waits for a slot.
        import asyncio
        srv = _server()
        asyncio.run(_send_then_fail(srv, v))
        check(v, [0], 1)
        held = v.acquire("ko")
        v.wait_s = 0.5
        v.ctx.voice_after = lambda lang, name: False

        async def cancelled():
            task = asyncio.ensure_future(srv.send_speech(_WS(), AudioStream(v.stream("x", "ko", lambda: None))))
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            v.release(held)                                      # the waiter gets the slot now...
        asyncio.run(cancelled())
        check(v, [0], 1)                                         # ...and gives it back
    for f in (a, b, good, t, s):
        f.close()


async def _send_then_fail(srv, v):
    try:
        await srv.send_speech(_WS(fail_after=1), AudioStream(v.stream("x", "ko", lambda: b"FB")))
        assert False, "send_speech should raise when the socket fails"
    except ConnectionError:
        pass


_FAKE_VOXCPM = """
import os, time
import numpy as np
LOG = os.environ["FAKE_VOXCPM_LOG"]
class _M:
    sample_rate = 48000
class VoxCPM:
    tts_model = _M()
    @classmethod
    def from_pretrained(cls, path, **kw):
        return cls()
    def generate(self, text, **kw):
        return np.zeros(4800, np.float32)
    def generate_streaming(self, text, **kw):
        for i in range(20):                      # 20 chunks, 0.1 s each: 2 s of GPU
            with open(LOG, "a") as f:
                f.write(f"{text} {i}\\n")
            time.sleep(0.1)
            yield np.full(4800, 0.1, np.float32)
"""


def test_service_answers_busy_and_skips_abandoned_requests():
    """voxcpm_service.py with a stand-in model: headers as soon as the model is free,
    503 (not a silent queue) when it stays busy, no GPU work for a client that has
    gone, and a listener hanging up stops the generation."""
    import socket
    import subprocess
    import tempfile
    import urllib.request
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "voxcpm.py"), "w") as f:
        f.write(_FAKE_VOXCPM)
    with open(os.path.join(tmp, "huggingface_hub.py"), "w") as f:
        f.write("def snapshot_download(repo, revision=None):\n    return repo\n")
    log = os.path.join(tmp, "gen.log")
    port = int(_dead_url().rsplit(":", 1)[1])
    env = dict(os.environ, PYTHONPATH=tmp, FAKE_VOXCPM_LOG=log, VOXCPM_REF_DIR=tmp)
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "server", "voxcpm_service.py"), "--port", str(port)],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise AssertionError(p.stdout.read1(4000) if p.poll() is not None else "service did not start")

        def generated(text):
            try:
                return sum(1 for x in open(log) if x.split()[0] == text)
            except FileNotFoundError:
                return 0

        def raw(text):
            c = socket.create_connection(("127.0.0.1", port))
            body = json.dumps({"text": text, "stream": True}).encode()
            c.sendall(b"POST /tts HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                      b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
            return c

        import http.client
        v = make_vox([url], cap=1)
        # A: generating for 2 s. Its headers come at once.
        t0 = t_a = time.monotonic()
        conn_a, r_a = v._open(v.instances[0], "aaa", "ko")
        assert r_a.status == 200 and r_a.getheader("X-Sample-Rate") == str(RATE)
        assert time.monotonic() - t0 < 0.5
        # B meanwhile: 503 after ~1 s (BUSY_WAIT_S), not a 30 s wait for headers.
        t0 = time.monotonic()
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("POST", "/tts", json.dumps({"text": "bbb", "stream": True}), {"Content-Type": "application/json"})
        r = c.getresponse()
        assert r.status == 503 and 0.8 < time.monotonic() - t0 < 1.8, (r.status, time.monotonic() - t0)
        r.read()
        c.close()
        # C asks while A has ~0.5 s left, and gives up at once: when A ends C gets the model,
        # sees its client gone, and closes without an answer and without any GPU work.
        time.sleep(max(0.0, t_a + 1.5 - time.monotonic()))
        cc = raw("ccc")
        cc.shutdown(socket.SHUT_WR)
        r_a.read()                                   # A to the end
        cc.settimeout(3)
        assert cc.recv(100) == b""                   # no 503: it waited, then found nobody
        cc.close()
        conn_a.close()
        time.sleep(1.2)
        assert generated("aaa") == 20 and generated("bbb") == 0 and generated("ccc") == 0, open(log).read()
        # D hangs up after its first chunk: the generation stops there, and the model is free.
        d = raw("ddd")
        d.recv(100)
        d.close()
        time.sleep(0.6)
        assert generated("ddd") < 10, generated("ddd")
        t0 = time.monotonic()
        conn_e, r_e = v._open(v.instances[0], "eee", "ko")
        assert r_e.status == 200 and time.monotonic() - t0 < 0.5
        conn_e.close()
    finally:
        p.kill()
        p.wait()
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- the instance plan

def test_instance_plan():
    two = [("0", 81920), ("1", 81920)]
    p = c.voxcpm_plan("commercial", two)
    assert p["instances"] == [("0", 8791), ("1", 8792)] and p["message"] == "VoxCPM2: 2 instances (GPU 0, GPU 1)"
    # Nonprofit keeps today's single instance unless asked.
    p = c.voxcpm_plan("nonprofit", two)
    assert p["instances"] == [("0", 8791)] and "overflow → fallback voices" in p["message"]
    assert c.voxcpm_plan("nonprofit", two, "auto")["instances"] == [("0", 8791), ("1", 8792)]
    p = c.voxcpm_plan("commercial", [("0", 46068)])
    assert p["instances"] == [("0", 8791)] and p["message"] == "VoxCPM2: 1 instance (one GPU); overflow → fallback voices"
    # A card too small for an instance is left out, and said so.
    p = c.voxcpm_plan("commercial", [("0", 81920), ("1", 8192), ("2", 24576)])
    assert p["instances"] == [("0", 8791), ("2", 8792)] and "GPU 1 not used" in p["notes"][0]
    # Capped; a number; more than there are GPUs; VOXCPM_GPUS; off.
    many = [(str(i), 49152) for i in range(8)]
    assert len(c.voxcpm_plan("commercial", many)["instances"]) == c.VOXCPM_MAX_INSTANCES
    assert len(c.voxcpm_plan("commercial", many, max_instances=6)["instances"]) == 6
    assert c.voxcpm_plan("commercial", two, "1")["instances"] == [("0", 8791)]
    p = c.voxcpm_plan("commercial", two, "3")
    assert len(p["instances"]) == 2 and "VOXCPM_INSTANCES=3" in p["notes"][0]
    assert c.voxcpm_plan("commercial", two, None, ["0", "1", "1"])["instances"] == [
        ("0", 8791), ("1", 8792), ("1", 8793)]
    assert c.voxcpm_plan("commercial", two, "2", ["1", "0", "1"])["instances"] == [("1", 8791), ("0", 8792)]
    assert c.voxcpm_plan("commercial", two, "0")["instances"] == []
    assert c.voxcpm_plan("commercial", [])["instances"] == [(None, 8791)]
    for bad in (("many", None), (None, ["7"])):
        try:
            c.voxcpm_plan("commercial", two, *bad)
            assert False, bad
        except ValueError:
            pass


def test_instance_plan_cli():
    import subprocess
    cfg = os.path.join(ROOT, "server", "stack_config.py")

    def run(env, *args):
        e = {k: v for k, v in os.environ.items() if not k.startswith("VOXCPM_")}
        e.update(env)
        return subprocess.run([sys.executable, cfg, "voxcpm-plan", *args], capture_output=True, text=True, env=e)

    out = run({"STACK_GPUS": "0:81920,1:46068"}, "--edition", "commercial")
    assert out.returncode == 0 and out.stdout == "0 8791\n1 8792\n", out
    assert "VoxCPM2: 2 instances (GPU 0, GPU 1)" in out.stderr
    out = run({"STACK_GPUS": "0:81920,1:46068", "EDITION": "nonprofit"})
    assert out.stdout == "0 8791\n"
    out = run({"STACK_GPUS": ""}, "--edition", "commercial")
    assert out.stdout == "- 8791\n" and "no GPU detected" in out.stderr
    assert run({"STACK_GPUS": "0:1", "VOXCPM_INSTANCES": "lots"}, "--edition", "commercial").returncode != 0


# ---------------------------------------------------------------- eSpeak NG and the chains

def test_espeak_output_format():
    if not shutil.which("espeak-ng"):
        print("skip test_espeak_output_format: espeak-ng not installed")
        return
    import numpy as np
    ctx = Context(langs=["fa", "ro", "ko", "km"], options={"espeak": True})
    e = ESpeak(ctx)
    with contextlib.redirect_stdout(io.StringIO()):
        e.load()
    assert e.available and e.langs == {"fa", "ro", "ko"}         # no Khmer voice
    assert e.supports("fa") and not e.supports("km")
    for lang, text in (("fa", "سلام، حال شما چطور است؟"), ("ro", "Bună ziua, ce mai faceți?"),
                       ("ko", "안녕하세요. 만나서 반갑습니다.")):
        pcm = e.synthesise(text, lang)
        assert isinstance(pcm, bytes) and len(pcm) % 2 == 0
        x = np.frombuffer(pcm, "<i2").astype("float32") / 32768
        assert 0.5 < len(x) / RATE < 10, len(x) / RATE              # 24 kHz mono: a plausible length
        assert 0.85 < np.abs(x).max() < 0.9                          # peak -1 dBFS, like the other voices
        assert abs(x[0]) < 0.01 and abs(x[-1]) < 0.01               # ramped ends: no click at the seams
    # Untrusted text never reaches a command line or markup.
    assert e.synthesise("-v en --stdout <speak>ok</speak>", "ro") is not None
    # `espeak = false` takes it out of a language.
    ctx = Context(langs=["ro"], table={"ro": {"espeak": False}}, options={"espeak": True})
    e = ESpeak(ctx)
    with contextlib.redirect_stdout(io.StringIO()):
        e.load()
    assert not e.supports("ro")


def test_espeak_languages():
    """What eSpeak NG covers of the 25 (checked with `espeak-ng --voices`)."""
    served = set(c.DEFAULTS)
    assert served - set(ESPEAK_VOICES) == {"km", "lo", "tl", "ja"}
    assert not any(v.startswith("mb") for v in ESPEAK_VOICES.values())     # never MBROLA


class _Pool:
    def submit(self, fn, *a):
        from concurrent.futures import Future
        f = Future()
        f.set_result(fn(*a))
        return f


def test_commercial_chains_overflow_to_espeak():
    """In EngineSet: VoxCPM2 full -> the sentence is spoken by eSpeak NG (ko);
    fa and ro speak eSpeak NG; km (no eSpeak voice) has nothing behind VoxCPM2."""
    a = FakeService()
    try:
        ctx = Context(models=c.MODEL_DEFAULTS, table=c.DEFAULTS, tables=c.tables(c.DEFAULTS),
                      langs=["ko", "fa", "ro", "km", "en"], srcs=["en"],
                      options=dict(voxcpm=a.url, voxcpm_max_inflight=1, espeak=True, edition="commercial"))
        with contextlib.redirect_stdout(io.StringIO()):
            es = EngineSet(ctx)
            es.load(["voxcpm", "espeak"])
        vox, esp = es.engines["voice"]["voxcpm"], es.engines["voice"]["espeak"]
        if not esp.available:          # no espeak-ng here: pretend, with a stand-in voice
            esp.available, esp.langs = True, {"ko", "fa", "ro", "en"}
            esp.synthesise = lambda text, lang: b"espeak:" + text.encode()
        for eng in es.engines["voice"].values():
            eng.available = True
        es._chains.clear()
        assert [e.name for e in es.chain("ko")] == ["voxcpm", "espeak"]
        assert [e.name for e in es.chain("fa")] == ["espeak"] and [e.name for e in es.chain("ro")] == ["espeak"]
        assert [e.name for e in es.chain("km")] == ["voxcpm"]
        assert es.chain("en")[-1].name == "espeak"
        # Free: VoxCPM2 speaks. Full: the same sentence goes to eSpeak NG after VOXCPM_QUEUE_S.
        vox.queue_s = 0.3
        (f,) = es.synthesise_futures("안녕하세요.", "ko", _Pool())
        s = f.result()
        assert isinstance(s, AudioStream)
        first = next(s.chunks)                       # holds VoxCPM2's one slot
        with contextlib.redirect_stdout(io.StringIO()):
            (g,) = es.synthesise_futures("반갑습니다.", "ko", _Pool())
            t0 = time.monotonic()
            out = b"".join(g.result().chunks)
        assert out and out != first and vox.stats()["overflow"] == 1
        assert 0.25 < time.monotonic() - t0 < 1.5
        s.chunks.close()
        assert vox.stats()["instances"][0]["inflight"] == 0
        # fa: eSpeak NG is the voice.
        (h,) = es.synthesise_futures("سلام.", "fa", _Pool())
        assert h.result()
    finally:
        a.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
