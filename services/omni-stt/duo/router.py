"""One entry for two omni-stt processes on one GPU (../README.md, "One GPU for both"):

    :8080  this router
    :8081  the finals service    (OMNI_CARD=omniASR_LLM_7B_bf16: the text of record)
    :8082  the streaming service (OMNI_CARD=omniASR_CTC_3B_bf16, STT_CTC_STREAM=1)

A WebSocket whose query names stream= goes to the streaming service; every
other one to the finals service. Path, query, the Authorization header and the
offered subprotocols are passed through unchanged, so each service checks the
token itself, and its close code (4400, 4401, 4429, ...) and reason come back
to the client as sent. Frames are relayed both ways as they arrive.

    GET /health   200 "ok" only while both services answer their own /health
    GET /mic      the finals service's test page

The port opens only once both services are up (as server.py's does once its
models are warm). Only the websockets package is needed.

Optional idle stop, for a pod nobody may remember to stop: with DUO_IDLE_MIN
(minutes without a connection, counted from ready) or DUO_MAX_UPTIME_H set,
and RUNPOD_POD_ID and RUNPOD_API_KEY in the environment (RunPod sets both in
every pod), the router asks RunPod's API to stop its own pod. Exiting the
container is not a stop: RunPod restarts it and keeps billing.

Environment: PORT (8080), DUO_LISTEN (127.0.0.1:8081), DUO_STREAM
(127.0.0.1:8082), DUO_WAIT_S (900: how long to wait for both services before
giving up), DUO_IDLE_MIN, DUO_MAX_UPTIME_H.
"""
import asyncio
import json
import os
import sys
import time
import urllib.request
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

AUTH_PROTOCOL = "omni-stt"          # server.py's: picked when a browser offers it
CLOSE_UPSTREAM = 1011               # the chosen service refused the handshake or is gone
MAX_FRAME_BYTES = 1 << 20           # server.py's own limit is lower; it enforces its own


def backend_for(path):
    """A request path (with its query) -> "stream" or "listen"."""
    q = parse_qs(urlparse(path).query, keep_blank_values=True)
    return "stream" if "stream" in q else "listen"


def forward_headers(headers):
    """The handshake headers a service needs: the token, and nothing else
    (Host, Sec-WebSocket-* and the rest belong to this hop)."""
    auth = headers.get("Authorization") if headers is not None else None
    return {"Authorization": auth} if auth else {}


def offered_protocols(headers):
    if headers is None:
        return []
    out = []
    for v in headers.get_all("Sec-WebSocket-Protocol"):
        out += [p.strip() for p in v.split(",") if p.strip()]
    return out


def select_subprotocol(connection, subprotocols):
    return AUTH_PROTOCOL if AUTH_PROTOCOL in subprotocols else None


def http_ok(addr, path="/health", timeout=2.0):
    try:
        with urllib.request.urlopen(f"http://{addr}{path}", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def http_get(addr, path, timeout=5.0):
    with urllib.request.urlopen(f"http://{addr}{path}", timeout=timeout) as r:
        return r.read().decode("utf-8")


class Router:
    def __init__(self, listen, stream, idle_min=None, max_uptime_h=None, stop=None):
        self.backends = {"listen": listen, "stream": stream}
        self.open = 0
        self.counts = {"listen": 0, "stream": 0}
        self.idle_since = time.monotonic()
        self.started = time.monotonic()
        self.idle_min = idle_min
        self.max_uptime_h = max_uptime_h
        self.stop = stop
        self.mic = None

    async def healthy(self):
        loop = asyncio.get_running_loop()
        oks = await asyncio.gather(*(loop.run_in_executor(None, http_ok, a) for a in self.backends.values()))
        return all(oks)

    async def http(self, connection, request):
        path = request.path.split("?")[0]
        if path == "/health":
            if await self.healthy():
                return connection.respond(HTTPStatus.OK, "ok\n")
            return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, "a service is down\n")
        if path == "/mic":
            if self.mic is None:
                try:
                    self.mic = await asyncio.get_running_loop().run_in_executor(
                        None, http_get, self.backends["listen"], "/mic")
                except Exception:
                    return connection.respond(HTTPStatus.BAD_GATEWAY, "no test page\n")
            resp = connection.respond(HTTPStatus.OK, self.mic)
            resp.headers["Content-Type"] = "text/html; charset=utf-8"
            resp.headers["Cache-Control"] = "no-store"
            return resp
        return None

    async def handle(self, ws):
        import websockets
        which = backend_for(ws.request.path)
        url = f"ws://{self.backends[which]}{ws.request.path}"
        protos = offered_protocols(ws.request.headers)
        self.open += 1
        self.counts[which] += 1
        try:
            try:
                up = await websockets.connect(url, additional_headers=forward_headers(ws.request.headers),
                                              subprotocols=protos or None, max_size=None,
                                              ping_interval=None, open_timeout=10, compression=None)
            except Exception as e:
                print(f"[router] {which} refused the connection: {type(e).__name__}", flush=True)
                await ws.close(code=CLOSE_UPSTREAM, reason=f"the {which} service is unavailable")
                return
            async with up:
                await self._pipe(ws, up)
        finally:
            self.open -= 1
            self.counts[which] -= 1
            if self.open == 0:
                self.idle_since = time.monotonic()

    @staticmethod
    async def _pipe(client, up):
        """Relay both ways until either side closes; pass the service's close
        code and reason to the client, and the client's to the service."""
        from websockets.exceptions import ConnectionClosed

        async def copy(src, dst):
            try:
                async for m in src:
                    await dst.send(m)
            except ConnectionClosed:
                pass

        a = asyncio.create_task(copy(client, up))
        b = asyncio.create_task(copy(up, client))
        done, pending = await asyncio.wait({a, b}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if b in done:
            # The service closed (or went away): its code reaches the client.
            code = up.close_code or CLOSE_UPSTREAM
            if code == 1005 or code == 1006:
                code = 1000 if code == 1005 else CLOSE_UPSTREAM
            await client.close(code=code, reason=up.close_reason or "")
        else:
            code = client.close_code
            await up.close(code=code if code and code not in (1005, 1006) else 1000)

    async def idle_watch(self):
        """Stop the pod after DUO_IDLE_MIN without a connection, or after
        DUO_MAX_UPTIME_H in any case."""
        while True:
            await asyncio.sleep(30)
            now = time.monotonic()
            why = None
            if self.max_uptime_h and now - self.started > self.max_uptime_h * 3600:
                why = f"up {self.max_uptime_h} h"
            elif self.idle_min and self.open == 0 and now - self.idle_since > self.idle_min * 60:
                why = f"idle {self.idle_min} min"
            if why and self.stop:
                print(f"[router] {why}: stopping the pod", flush=True)
                await asyncio.get_running_loop().run_in_executor(None, self.stop)
                await asyncio.sleep(300)


def runpod_stop():
    """RunPod's v2 API, with the pod's own key: stop this pod."""
    pod, key = os.environ.get("RUNPOD_POD_ID", ""), os.environ.get("RUNPOD_API_KEY", "")
    if not (pod and key):
        print("[router] no RUNPOD_POD_ID/RUNPOD_API_KEY: cannot stop the pod", flush=True)
        return
    req = urllib.request.Request(f"https://api.runpod.io/v2/pods/{pod}/action",
                                 data=json.dumps({"action": "stop"}).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"[router] stop requested ({r.status})", flush=True)
    except Exception as e:
        print(f"[router] stop failed: {type(e).__name__} {getattr(e, 'code', '')}", flush=True)


def _num(name):
    v = os.environ.get(name, "").strip()
    return float(v) if v else None


async def main():
    import websockets
    listen = os.environ.get("DUO_LISTEN", "127.0.0.1:8081")
    stream = os.environ.get("DUO_STREAM", "127.0.0.1:8082")
    wait_s = float(os.environ.get("DUO_WAIT_S", "900"))
    t0 = time.time()
    router = Router(listen, stream, idle_min=_num("DUO_IDLE_MIN"), max_uptime_h=_num("DUO_MAX_UPTIME_H"),
                    stop=runpod_stop)
    while not await router.healthy():
        if time.time() - t0 > wait_s:
            raise SystemExit(f"[router] the services were not up after {wait_s:.0f} s")
        await asyncio.sleep(0.5)
    port = int(os.environ.get("PORT", "8080"))
    async with websockets.serve(router.handle, "0.0.0.0", port, max_size=MAX_FRAME_BYTES, ping_interval=None,
                                process_request=router.http, select_subprotocol=select_subprotocol,
                                compression=None):
        print(f"[router] ready on :{port} (finals {listen}, streaming {stream}; "
              f"both up {time.time() - t0:.0f} s after the router started)", flush=True)
        if router.idle_min or router.max_uptime_h:
            await router.idle_watch()
        else:
            await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
