"""VoxCPM2 (OpenBMB, Apache 2.0), through server/voxcpm_service.py: voxcpm =
true. The clearest Khmer and Lao tested (recognised at 8.5% / 10% character
error against MMS's 22.8% / 15%), and in EDITION=commercial the voice of ko tr
ru ar id sw vi as well.

The model runs in its own process and virtualenv (it pins library versions the
stack must not inherit); this engine is its HTTP client. The service clones a
fixed reference voice per language (voices/voxcpm/<lang>.wav), halves its
48 kHz output to 24 kHz with a stateful filter, and applies the streaming gain
and soft limiter: all of that lives in voxcpm_service.py.

Enabled with --voxcpm URL[,URL...]; which languages: `voxcpm = true`, or
--voxcpm-langs (VOXCPM_LANGS in run.sh), which wins. Streaming: each sentence's
audio is sent as it is generated, so Khmer starts ~0.1 s after its text
instead of 1.5 s.

Capacity. One service makes ONE voice at a time (its model lock; RTF ~0.28
on an A100, 0.46 on an RTX PRO 4500): a five-second sentence takes ~1.4 s of
GPU, so one GPU keeps two to three listeners in real time by taking their
sentences in turn. scripts/run.sh starts one service per GPU it may use
(stack_config.voxcpm_plan) and passes every URL. The queue is HERE, not in
the services:

  - an instance takes --voxcpm-max-inflight sentences at once
    (VOXCPM_MAX_INFLIGHT, default 1: what the service really runs at once).
    A higher cap only queues requests inside the service, where the balancer
    cannot see them, another GPU cannot take them, and a listener who left is
    still generated for;
  - each sentence goes to the healthy instance with the fewest sentences in
    flight (ties: the one that has served fewest);
  - when every healthy instance is full the sentence waits for the first slot
    that frees on ANY instance, up to VOXCPM_QUEUE_S (2 s) when another voice
    follows VoxCPM2 in its chain, up to VOXCPM_WAIT_S (15 s) when nothing does
    (Khmer, Lao, Tagalog in commercial). Past that it goes to fallback() (the
    rest of the chain; eSpeak NG at the end of every commercial chain), or is
    text only. 2 s is about one long sentence's generation: for a sentence
    in the middle of an utterance the wait is hidden behind the previous
    sentence still playing (audio is made ~3.5x faster than it plays); only
    the first sentence of an utterance is heard later. Every instance down:
    no wait;
  - the wait blocks the thread iterating the stream. server.send_speech gives
    each stream its own thread for that reason: waiting on the shared TTS
    pool starved the streams holding the slots (2026-09-30);
  - a connection error marks that instance down for VOXCPM_RETRY_S (15 s), then
    it is tried again; a sentence whose instance was unreachable, or answered
    503 busy (another client shares it), tries the next instance before
    falling back;
  - overflow is logged at most every 10 s, with a count, and a stats line (per
    instance: served, peak in flight, errors; overflow) at most once a minute
    while there is traffic.
"""
import json
import os
import threading
import time
from urllib.parse import urlparse

from engines import register
from engines.base import Voice, RATE
from engines.common import to_pcm16

DEFAULT_MAX_INFLIGHT = 1
OVERFLOW_LOG_S = 10.0
STATS_LOG_S = float(os.environ.get("VOXCPM_STATS_S", "60"))


# When this server started: VOXCPM_START_WAIT_S counts from here, as run.sh's
# wait used to count from launching the services.
START = time.time()


def _local_service_alive(inst):
    """False only when a service on this machine has no process left (pgrep, as
    run.sh's check). A remote one, or no pgrep, counts as alive: wait it out.
    The first 60 s always count as alive: a just-forked process can miss pgrep."""
    if inst.host not in ("127.0.0.1", "localhost") or time.time() - START < 60:
        return True
    import shutil, subprocess
    if not shutil.which("pgrep"):
        return True
    r = subprocess.run(["pgrep", "-f", f"voxcpm_service[.]py --port {inst.port}( |$)"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


class Instance:
    """One voxcpm_service.py: its URL and what this server has in flight there."""

    def __init__(self, url):
        self.url = url.rstrip("/")
        u = urlparse(self.url)
        self.host, self.port = u.hostname, u.port or 80
        self.name = f"{self.host}:{self.port}"
        self.inflight = 0
        self.peak = 0
        self.served = 0
        self.errors = 0
        self.down_until = 0.0      # monotonic time; 0 = up


@register
class VoxCPM(Voice):
    name = "voxcpm"
    title = "VoxCPM2"
    lang_key = bool
    priority = 20
    streaming = True
    # The services make one voice at a time; there is no model in this process.
    lock_policy = "none"
    licence = "Apache-2.0"

    @classmethod
    def enabled(cls, ctx):
        return bool(ctx.options.get("voxcpm"))

    def __init__(self, ctx, clock=time.monotonic):
        super().__init__(ctx)
        urls = [u.strip() for u in str(ctx.options.get("voxcpm") or "").split(",") if u.strip()]
        # EDITION=both builds one VoxCPM2 engine per edition (they speak different
        # languages) over the SAME services: ctx.options["voxcpm_shared"], one dict
        # for both, makes them share the instances and the slot accounting, so the
        # two can never put more on a service than its cap between them.
        shared = ctx.options.get("voxcpm_shared")
        if shared is not None and "instances" in shared:
            self.instances, self._guard, self._freed = shared["instances"], shared["guard"], shared["freed"]
        else:
            self.instances = [Instance(u) for u in urls]
            self._guard = threading.Lock()
            self._freed = threading.Condition(self._guard)
            if shared is not None:
                shared.update(instances=self.instances, guard=self._guard, freed=self._freed)
        self.url = self.instances[0].url if self.instances else None
        langs = ctx.options.get("voxcpm_langs")
        self.langs = set(langs) if langs else set(ctx.tables.get("VOXCPM_LANGS", set()))
        self.cap = int(ctx.options.get("voxcpm_max_inflight") or os.environ.get("VOXCPM_MAX_INFLIGHT")
                       or DEFAULT_MAX_INFLIGHT)
        if self.cap < 1:
            raise ValueError(f"VOXCPM_MAX_INFLIGHT must be at least 1 (got {self.cap})")
        self.retry_s = float(os.environ.get("VOXCPM_RETRY_S", "15"))
        self.timeout = float(os.environ.get("VOXCPM_TIMEOUT_S", "30"))
        self._clock = clock
        # How long a sentence waits for a slot when every healthy instance is full: a language with
        # no voice after VoxCPM2 (Khmer, Lao, Tagalog in commercial) waits up to wait_s instead of
        # going text only (2026-09-30: Khmer went silent under an 8-language room load); one with a
        # fallback up to queue_s, about one long sentence's generation, before a plainer voice.
        self.wait_s = float(os.environ.get("VOXCPM_WAIT_S", "15"))
        self.queue_s = float(os.environ.get("VOXCPM_QUEUE_S", "2"))
        self.overflows = 0
        self._overflow_pending = {}          # lang -> count since the last overflow line
        self._overflow_logged = None
        self._stats_logged = clock()
        self._stats_dirty = False

    def supports(self, lang):
        return bool(self.instances) and lang in self.langs

    def load(self):
        if not self.instances:
            return
        import urllib.request
        for inst in self.instances:
            try:
                urllib.request.urlopen(f"{inst.url}/health", timeout=5).read()
            except Exception as e:
                print(f"[stack] VoxCPM2 instance {inst.name} not up yet — waited for after the other models",
                      flush=True)
                inst.down_until = self._clock() + self.retry_s
        n = len(self.instances)
        print(f"[stack] VoxCPM2 voices for {sorted(self.langs)} via {n} instance{'s' * (n > 1)} "
              f"({', '.join(i.name for i in self.instances)}), {self.cap} sentence{'s' * (self.cap > 1)} each at once; "
              f"when all are busy a sentence waits up to {self.queue_s:g}s for a slot ({self.wait_s:g}s with no "
              "voice after VoxCPM2), then goes to the next voice in its chain", flush=True)
        self.available = True

    def wait_ready(self):
        """Wait for instances that weren't up at load(). scripts/run.sh starts the
        services and the server together (VoxCPM2 takes ~2.5 min to load, about as
        long as everything else), so this runs after every other model is loaded
        and before warm-up and "ready": the start overlaps both instead of adding
        them up (2026-10-01; run.sh used to wait for VoxCPM2 before starting the
        server). Gives up on an instance at VOXCPM_START_WAIT_S (600) from the
        server's start, or as soon as a local one's process has gone; one that
        never came up stays retried every VOXCPM_RETRY_S, as before."""
        down = [i for i in self.instances if i.down_until > 0]
        if not down:
            return
        import urllib.request
        deadline = START + float(os.environ.get("VOXCPM_START_WAIT_S", "600"))
        print(f"[stack] waiting for VoxCPM2 ({', '.join(i.name for i in down)})…", flush=True)
        t0 = self._clock()
        while down and time.time() < deadline:
            for inst in list(down):
                try:
                    urllib.request.urlopen(f"{inst.url}/health", timeout=5).read()
                    inst.down_until = 0.0
                    down.remove(inst)
                except Exception:
                    if not _local_service_alive(inst):
                        print(f"[stack] VoxCPM2 {inst.name}: its process has exited (see its log)", flush=True)
                        down.remove(inst)
            if down:
                time.sleep(2)
        up = len(self.instances) - sum(1 for i in self.instances if i.down_until > 0)
        print(f"[stack] VoxCPM2: {up} of {len(self.instances)} instance{'s' * (len(self.instances) > 1)} up "
              f"({self._clock() - t0:.0f}s waited)" + ("" if up else
              " — its languages use the next voice in their chain, or text"), flush=True)

    # ------------------------------------------------------------ balancing

    def _ready(self, tried, now):
        return [i for i in self.instances if i not in tried and i.down_until <= now and i.inflight < self.cap]

    def acquire(self, lang="", tried=(), wait=True):
        """Reserve a slot on the least-loaded healthy instance (not in `tried`)
        and return it; None when every instance is full or down. When they are
        full (not down) and `wait`, first wait for a slot: up to queue_s, or
        wait_s for a language with no voice after VoxCPM2. None is an overflow,
        counted and logged, unless this sentence already tried an instance
        (then it is an error, logged by the caller).

        The wait blocks the calling thread: never call it with wait=True from
        a shared worker pool (server.send_speech runs each stream on its own
        thread)."""
        with self._guard:
            now = self._clock()
            ready = self._ready(tried, now)
            if not ready and not tried and lang and wait and any(i.down_until <= now for i in self.instances):
                budget = self.wait_s if not self.ctx.voice_after(lang, self.name) else self.queue_s
                end = time.monotonic() + budget
                while not ready:
                    left = end - time.monotonic()
                    if left <= 0:
                        break
                    self._freed.wait(timeout=left)
                    now = self._clock()
                    ready = self._ready(tried, now)
            if not ready:
                if not tried:
                    self._overflow(lang, now)
                return None
            inst = min(ready, key=lambda i: (i.inflight, i.served, self.instances.index(i)))
            inst.inflight += 1
            inst.peak = max(inst.peak, inst.inflight)
            inst.down_until = 0.0     # (a retry after its pause)
            return inst

    def release(self, inst, ok=True, unreachable=False):
        """Give back a slot from acquire(). ok: True served, False an error,
        None neither (the service said busy)."""
        with self._guard:
            inst.inflight -= 1
            self._freed.notify_all()
            if ok:
                inst.served += 1
            elif ok is not None:
                inst.errors += 1
            if unreachable:
                inst.down_until = self._clock() + self.retry_s
            self._stats_dirty = True
            self._maybe_log_stats()
        if unreachable:
            print(f"[stack] VoxCPM2 instance {inst.name} unreachable — skipped for {self.retry_s:.0f}s", flush=True)

    def _overflow(self, lang, now):
        """Every instance full or down (called under the guard). Logged at most
        every OVERFLOW_LOG_S, with the count and languages since the last line."""
        self.overflows += 1
        self._stats_dirty = True
        self._overflow_pending[lang] = self._overflow_pending.get(lang, 0) + 1
        if self._overflow_logged is None or now - self._overflow_logged >= OVERFLOW_LOG_S:
            n = sum(self._overflow_pending.values())
            down = sum(1 for i in self.instances if i.down_until > now)
            k = len(self.instances)
            what = f"all {k} instance{'s' * (k > 1)} at {self.cap} sentences" + (f" or down ({down})" if down else "")
            langs = ",".join(f"{g}×{v}" if v > 1 else g for g, v in sorted(self._overflow_pending.items()))
            print(f"[stack] VoxCPM2 busy: {what} — {n} sentence{'s' * (n > 1)} to the next voice ({langs}); "
                  f"{self.overflows} in total", flush=True)
            self._overflow_pending = {}
            self._overflow_logged = now

    def _maybe_log_stats(self):
        now = self._clock()
        if self._stats_dirty and now - self._stats_logged >= STATS_LOG_S:
            print(f"[stack] {self._stats_line()}", flush=True)
            self._stats_logged = now
            self._stats_dirty = False

    def stats(self):
        """Counters since start, per instance and overall."""
        with self._guard:
            return self._stats()

    def _stats(self):
        now = self._clock()
        return {"instances": [{"url": i.url, "inflight": i.inflight, "peak": i.peak, "served": i.served,
                               "errors": i.errors, "down": i.down_until > now} for i in self.instances],
                "overflow": self.overflows, "max_inflight": self.cap}

    def _stats_line(self):
        s = self._stats()
        per = "; ".join(f":{urlparse(i['url']).port} served {i['served']} peak {i['peak']} errors {i['errors']}"
                        + (" DOWN" if i["down"] else "") for i in s["instances"])
        return f"VoxCPM2 stats: {per}; overflow {s['overflow']}"

    # ------------------------------------------------------------ synthesis

    def synthesise(self, text, lang):
        """VoxCPM2 via the least-loaded service; None when all are busy or
        unreachable, or the service fails the sentence (the next voice speaks)."""
        import urllib.error
        import urllib.request
        import numpy as np
        tried = []
        while True:
            # No waiting: this may run on a shared worker pool (see acquire()).
            inst = self.acquire(lang, tried, wait=False)
            if inst is None:
                return None
            tried.append(inst)
            ok = unreachable = False
            try:
                req = urllib.request.Request(f"{inst.url}/tts", data=json.dumps({"text": text, "lang": lang}).encode(),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    native = int(r.headers.get("X-Sample-Rate", "48000"))
                    pcm = np.frombuffer(r.read(), "<i2").astype("float32") / 32768
                ok = True
                return to_pcm16(pcm, native) if len(pcm) else None
            except urllib.error.HTTPError as e:
                if e.code == 503:    # busy with another client's sentence: the next instance
                    ok = None
                    continue
                print(f"[stack] VoxCPM2 {lang} failed on {inst.name} ({e}) — falling back", flush=True)
                return None
            except OSError as e:     # refused, reset, timed out: the instance, not the sentence
                unreachable = True
                print(f"[stack] VoxCPM2 {lang} failed on {inst.name} ({e})", flush=True)
            except Exception as e:
                print(f"[stack] VoxCPM2 {lang} failed on {inst.name} ({e}) — falling back", flush=True)
                return None
            finally:
                self.release(inst, ok=ok, unreachable=unreachable)

    def _open(self, inst, text, lang):
        """(connection, response) for a streaming request, or raise."""
        import http.client
        conn = http.client.HTTPConnection(inst.host, inst.port, timeout=self.timeout)
        try:
            conn.request("POST", "/tts", json.dumps({"text": text, "lang": lang, "stream": True}),
                         {"Content-Type": "application/json"})
            return conn, conn.getresponse()
        except BaseException:
            conn.close()
            raise

    def stream(self, text, lang, fallback):
        """VoxCPM2 audio for one sentence as 24 kHz PCM16 chunks, as it is made.
        Nothing is reserved until the stream is first read (the streams of an
        utterance open lazily, in order). When every instance is full past the
        wait (acquire()) or unreachable, or the service refuses the sentence,
        it goes to fallback() (the rest of the chain) in one piece.

        next() blocks: waiting for a slot, for the service's headers, for each
        chunk. Iterate it on a thread of its own (server.send_speech).

        Every exit releases the slot and closes the connection: the finally
        below covers an exception anywhere after acquire() (a bad header
        included), a broken stream, and close() or garbage collection while
        suspended at a yield (GeneratorExit: the listener went away; closing
        the connection makes the service's next write fail, which stops the
        generation)."""
        tried = []
        while True:
            inst = self.acquire(lang, tried)
            if inst is None:
                break
            tried.append(inst)
            conn = None
            ok = unreachable = started = False
            try:
                conn, r = self._open(inst, text, lang)
                if r.status == 503:
                    ok = None     # busy with another client's sentence: not an error; the next instance
                    continue
                rate = r.getheader("X-Sample-Rate")
                if r.status != 200 or rate != str(RATE):
                    print(f"[stack] VoxCPM2 {lang} stream failed on {inst.name} (HTTP {r.status}, rate "
                          f"{rate}) — falling back", flush=True)
                    break
                started = True
                carry = b""
                while True:
                    b = r.read1(16384)
                    if not b:
                        break
                    b = carry + b
                    cut = len(b) - len(b) % 2  # whole samples only
                    carry = b[cut:]
                    if cut:
                        yield b[:cut]
                ok = True
                return
            except GeneratorExit:
                ok = True           # the listener went away: not the instance's fault
                raise
            except OSError as e:
                # Refused, reset, timed out: the service died or hung. Before any audio the
                # sentence can still go to the next instance; mid-sentence it ends here.
                unreachable = True
                print(f"[stack] VoxCPM2 {lang} stream {'broke' if started else 'failed'} on {inst.name} ({e})",
                      flush=True)
                if started:
                    return
            except Exception as e:
                print(f"[stack] VoxCPM2 {lang} stream {'broke' if started else 'failed'} on {inst.name} ({e})"
                      + ("" if started else " — falling back"), flush=True)
                if started:
                    return
                break
            finally:
                if conn is not None:
                    conn.close()
                self.release(inst, ok=ok, unreachable=unreachable)
        out = fallback()
        if out:
            yield out
