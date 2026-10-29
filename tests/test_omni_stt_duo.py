#!/usr/bin/env python3
"""services/omni-stt/duo/router.py with two stand-in services: which one a
connection reaches, that the token and subprotocols reach it unchanged, that
its close codes come back, /health only while both are up, and the idle stop.

    python3 tests/test_omni_stt_duo.py   (or python3 -m pytest tests/test_omni_stt_duo.py)

Needs websockets; no models, no GPU.
"""
import asyncio
import json
import os
import sys
import urllib.request
from http import HTTPStatus

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "omni-stt", "duo"))
import router  # noqa: E402


def test_backend_for():
    assert router.backend_for("/listen?langs=km&stream=ctc&lookahead=2") == "stream"
    assert router.backend_for("/listen?langs=km&stream=") == "stream"       # a bad value: the service refuses it
    assert router.backend_for("/listen?langs=km&transcribe=km") == "listen"
    assert router.backend_for("/listen") == "listen"
    assert router.backend_for("/speak?voice=coqui") == "listen"
    assert router.backend_for("/listen?langs=km&upstream=x") == "listen"


def test_forward_headers_carry_only_the_token():
    from websockets.datastructures import Headers
    h = Headers([("Authorization", "Bearer abc"), ("Host", "x"), ("Sec-WebSocket-Key", "k"), ("Cookie", "c")])
    assert router.forward_headers(h) == {"Authorization": "Bearer abc"}
    assert router.forward_headers(Headers([("Host", "x")])) == {}
    h = Headers([("Sec-WebSocket-Protocol", "omni-stt, bearer.tok")])
    assert router.offered_protocols(h) == ["omni-stt", "bearer.tok"]


async def _service(name, seen, close_with=None):
    """A stand-in omni-stt: says hello with its name and what it was given, echoes frames."""
    import websockets

    async def handle(ws):
        seen.append({"name": name, "path": ws.request.path, "auth": ws.request.headers.get("Authorization"),
                     "proto": ws.subprotocol})
        if close_with:
            await ws.close(code=close_with[0], reason=close_with[1])
            return
        await ws.send(json.dumps({"type": "hello", "service": name}))
        async for m in ws:
            await ws.send(m)

    def http(connection, request):
        if request.path == "/health":
            return connection.respond(HTTPStatus.OK, "ok\n")
        return None

    return await websockets.serve(handle, "127.0.0.1", 0, process_request=http,
                                  select_subprotocol=router.select_subprotocol)


def _port(server):
    return server.sockets[0].getsockname()[1]


async def _with_router(fn, close_listen=None):
    import websockets
    seen = []
    a = await _service("listen", seen, close_listen)
    b = await _service("stream", seen)
    r = router.Router(f"127.0.0.1:{_port(a)}", f"127.0.0.1:{_port(b)}")
    front = await websockets.serve(r.handle, "127.0.0.1", 0, process_request=r.http,
                                   select_subprotocol=router.select_subprotocol)
    try:
        await fn(f"127.0.0.1:{_port(front)}", seen, r, a, b)
    finally:
        front.close()
        a.close()
        b.close()


def test_routes_by_stream_and_passes_everything_through():
    import websockets

    async def go(addr, seen, r, a, b):
        async with websockets.connect(f"ws://{addr}/listen?langs=km&stream=ctc&lookahead=2",
                                      additional_headers={"Authorization": "Bearer t1"}) as ws:
            assert json.loads(await ws.recv())["service"] == "stream"
            await ws.send(b"\x01\x02" * 800)
            assert await ws.recv() == b"\x01\x02" * 800
            assert r.counts == {"listen": 0, "stream": 1}
        async with websockets.connect(f"ws://{addr}/listen?langs=km&transcribe=km",
                                      subprotocols=["omni-stt", "bearer.t2"]) as ws:
            assert json.loads(await ws.recv())["service"] == "listen"
            assert ws.subprotocol == "omni-stt"
            await ws.send(json.dumps({"type": "flush"}))
            assert json.loads(await ws.recv()) == {"type": "flush"}
        assert seen[0] == {"name": "stream", "path": "/listen?langs=km&stream=ctc&lookahead=2", "auth": "Bearer t1",
                           "proto": None}
        assert seen[1] == {"name": "listen", "path": "/listen?langs=km&transcribe=km", "auth": None, "proto": "omni-stt"}
        await asyncio.sleep(0.05)
        assert r.open == 0

    asyncio.run(_with_router(go))


def test_close_codes_come_back():
    import websockets

    async def go(addr, seen, r, a, b):
        async with websockets.connect(f"ws://{addr}/listen?langs=km") as ws:
            try:
                await ws.recv()
            except websockets.exceptions.ConnectionClosed:
                pass
            assert (ws.close_code, ws.close_reason) == (4401, "unauthorized")

    asyncio.run(_with_router(go, close_listen=(4401, "unauthorized")))


def test_health_needs_both_services():
    async def go(addr, seen, r, a, b):
        loop = asyncio.get_running_loop()

        def get():
            try:
                with urllib.request.urlopen(f"http://{addr}/health", timeout=5) as resp:
                    return resp.status
            except urllib.error.HTTPError as e:
                return e.code
        assert await loop.run_in_executor(None, get) == 200
        b.close()
        await b.wait_closed()
        assert await loop.run_in_executor(None, get) == 503

    asyncio.run(_with_router(go))


def test_a_service_that_is_gone_is_a_1011():
    import websockets

    async def go(addr, seen, r, a, b):
        b.close()
        await b.wait_closed()
        async with websockets.connect(f"ws://{addr}/listen?langs=lo&stream=ctc") as ws:
            try:
                await ws.recv()
            except websockets.exceptions.ConnectionClosed:
                pass
            assert ws.close_code == 1011

    asyncio.run(_with_router(go))


def test_idle_stop():
    stops = []
    r = router.Router("a", "b", idle_min=1, stop=lambda: stops.append(1))

    async def go():
        real = asyncio.sleep
        calls = {"n": 0}

        async def fast(s):
            calls["n"] += 1
            if calls["n"] > 4:
                raise asyncio.CancelledError
            await real(0)
        router.asyncio.sleep = fast
        try:
            r.idle_since -= 61
            await r.idle_watch()
        except asyncio.CancelledError:
            pass
        finally:
            router.asyncio.sleep = real
    asyncio.run(go())
    assert stops            # asked (and asked again 5 minutes on, if the pod is somehow still up)
    # With a connection open nothing stops, however long.
    stops.clear()
    r2 = router.Router("a", "b", idle_min=1, stop=lambda: stops.append(1))
    r2.open = 1
    r2.idle_since -= 3600
    asyncio.run(_one_watch(r2))
    assert stops == []


async def _one_watch(r):
    real = asyncio.sleep
    n = {"k": 0}

    async def fast(s):
        n["k"] += 1
        if n["k"] > 2:
            raise asyncio.CancelledError
        await real(0)
    router.asyncio.sleep = fast
    try:
        await r.idle_watch()
    except asyncio.CancelledError:
        pass
    finally:
        router.asyncio.sleep = real


def test_no_runpod_env_no_stop_call():
    for k in ("RUNPOD_POD_ID", "RUNPOD_API_KEY"):
        os.environ.pop(k, None)
    router.runpod_stop()          # says it cannot, and makes no request


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
