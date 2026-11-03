"""pytest setup for tests/: the import paths, the shared fixtures, and a guard
that puts back what a test changed in the process.

    pip install pytest numpy scipy websockets
    python -m pytest                 (from the repository root; pytest.ini)

All the test files run in one process, so the modules they import (server/'s,
services/omni-stt's) are shared between them. support.py loads the ones that
need loading by path.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402

# The stack's modules by name (stack_config, engines, audio_in, ...), as
# server.py imports them from beside itself; omni-stt's (partials, voices,
# denoise, ...), as its server.py imports them. Neither directory's server.py
# is imported by name: support.stack_server() and support.omni_stt().
support.on_path(support.SERVER, support.OMNI_STT)


@pytest.fixture(autouse=True)
def _restore_process_state():
    """Each test starts with the environment, sys.path and working directory
    the one before it started with. Tests set these with `monkeypatch`; this
    is the net under the ones that set them through the code under test (a
    module that edits sys.path when first imported, say)."""
    env, path, cwd = _env(), list(sys.path), os.getcwd()
    yield
    now = _env()
    for k in now.keys() - env.keys():
        del os.environ[k]
    for k, v in env.items():
        if now.get(k) != v:
            os.environ[k] = v
    if sys.path != path:
        sys.path[:] = path
    if os.getcwd() != cwd:
        os.chdir(cwd)


def _env():
    """os.environ without pytest's own PYTEST_CURRENT_TEST (which changes by phase)."""
    return {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}


@pytest.fixture
def engine_registry(monkeypatch):
    """engines' registry, put back after the test: for a test that registers an
    engine (the registry is process-wide, and test_licences checks that every
    registered engine has a licence)."""
    import engines
    engines.registry()             # the built-ins first: their modules import (and register) only once
    monkeypatch.setattr(engines, "_registry", {k: dict(v) for k, v in engines._registry.items()})
    monkeypatch.setattr(engines, "_origin", dict(engines._origin))
    return engines


@pytest.fixture(scope="session")
def srv():
    """server/server.py as a module."""
    return support.stack_server()


@pytest.fixture
def fake_vad(monkeypatch):
    """omni-stt's per-window speech probabilities (vad_windows) from the level
    alone: three 32 ms windows a block, speech above 0.05."""
    import numpy as np
    stt = support.omni_stt()
    monkeypatch.setattr(stt, "vad_windows", lambda vad, block: [1.0 if np.abs(block).max() > 0.05 else 0.0] * 3)
