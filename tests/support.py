"""What the tests share: the repository's paths, and the modules they load by
path. conftest.py puts this directory and server/ on sys.path before any test
module is imported, so a test file does

    import support
    srv = support.stack_server()          # server/server.py
    stt = support.omni_stt()              # services/omni-stt/server.py

Every module is loaded once per process and cached in sys.modules: all the
test files run in one pytest process, so a test that changes a module's state
(srv.pipeline.TTS_POOL, stt.vad_windows, ...) must put it back, with pytest's
`monkeypatch` fixture.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER = os.path.join(ROOT, "server")
OMNI_STT = os.path.join(ROOT, "services", "omni-stt")
EVAL_TOOLS = os.path.join(ROOT, "eval", "tools")


def on_path(*dirs):
    """Put these directories at the front of sys.path (once each)."""
    for d in reversed(dirs):
        if d not in sys.path:
            sys.path.insert(0, d)


def load(name, path):
    """The module at `path`, imported as `name` (once: later calls return it).
    For files that are not importable by their own name: server/server.py and
    services/omni-stt/server.py are both `server`, and eval/tools and
    services/omni-stt both have a dips.py."""
    mod = sys.modules.get(name)
    if mod is not None:
        if os.path.abspath(getattr(mod, "__file__", "") or "") != os.path.abspath(path):
            raise ImportError(f"{name} is already {mod!r}, not {path}")
        return mod
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def stack_server():
    """server/server.py, the stack's WebSocket server. Its parts (pipeline,
    rooms, connection, handlers) are ordinary imports from server/: patch
    state where it lives (srv.pipeline.TTS_POOL, srv.rooms.room_speak), not on
    the re-exports."""
    on_path(SERVER)
    return load("stack_server", os.path.join(SERVER, "server.py"))


def omni_stt():
    """services/omni-stt/server.py. Its own modules (partials, ctc_stream,
    voices, denoise, ht_numbers, omni_batch) are imported by their names, from
    services/omni-stt, as the service imports them."""
    on_path(OMNI_STT)
    return load("omni_stt_server", os.path.join(OMNI_STT, "server.py"))


def omni_stt_module(name):
    """A services/omni-stt module whose name is taken elsewhere (dips)."""
    return load(f"omni_stt_{name}", os.path.join(OMNI_STT, f"{name}.py"))


def eval_tool(name):
    """eval/tools/<name>.py, as eval_tool_<name> (eval/tools is not on sys.path:
    its dips.py would shadow omni-stt's)."""
    return load(f"eval_tool_{name}", os.path.join(EVAL_TOOLS, f"{name}.py"))


def write_temp(text, suffix=".toml"):
    """A temporary file holding `text`; its path."""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path
