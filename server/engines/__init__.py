"""Speech recognisers, translators and voices, as plug-ins.

Every module in this directory whose name does not start with "_" is imported
once, in name order, and each class it decorates with @register becomes an
engine that languages.toml can name. Out-of-tree engines work the same way:
put the file in a directory and list that directory in STACK_ENGINES_PATH
(os.pathsep-separated, like PATH). Nothing else is scanned, and nothing is
registered implicitly.

    from engines import register
    from engines.base import Translator

    @register
    class Echo(Translator):
        name = "echo"
        ...

    [de]
    translator = "echo"

Interfaces: engines/base.py. How to write one: docs/dev/adding-an-engine.md.
"""
import importlib
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = ("recognizer", "translator", "voice")
# Modules here that are helpers, not engines.
_NOT_ENGINES = {"base", "common", "manager"}

# Per-language keys that are not engine names.
_RESERVED = {"asr", "translator", "voice", "models", "commercial", "licence_review"}

_registry = {k: {} for k in KINDS}
_origin = {}          # (kind, name) -> the file that registered it
_loaded = False


def register(cls):
    """Class decorator: make an engine available under cls.name."""
    kind, name = getattr(cls, "kind", None), getattr(cls, "name", None)
    if kind not in KINDS:
        raise TypeError(f"{cls.__name__}: subclass Recognizer, Translator or Voice (engines/base.py)")
    if not name or not isinstance(name, str) or not name.replace("_", "").isalnum() or name != name.lower():
        raise TypeError(f"{cls.__name__}: name must be lowercase letters, digits and _ (got {name!r})")
    if name in _RESERVED:
        raise TypeError(f"{cls.__name__}: {name!r} is a languages.toml key, not an engine name")
    # A per-language key is named after its engine, so one name is one engine
    # across all kinds (except that MADLAD's `madlad` key is the translator's).
    for other in KINDS:
        if other != kind and name in _registry[other]:
            raise ValueError(f"{name!r} is already a {other} ({_origin[(other, name)]}); pick another name")
    where = sys.modules.get(cls.__module__)
    where = getattr(where, "__file__", cls.__module__)
    if name in _registry[kind] and _registry[kind][name] is not cls:
        raise ValueError(f"two {kind}s named {name!r}: {_origin[(kind, name)]} and {where}")
    _registry[kind][name] = cls
    _origin[(kind, name)] = where
    return cls


def _import_file(path, modname):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        sys.modules.pop(modname, None)
        raise ImportError(f"engine file {path} failed to import: {type(e).__name__}: {e}") from e
    return mod


def extra_dirs():
    """The directories named by STACK_ENGINES_PATH."""
    return [d for d in os.environ.get("STACK_ENGINES_PATH", "").split(os.pathsep) if d.strip()]


def _is_engine_file(fn):
    """A module to import: *.py, not private (_x), not hidden, a valid name. Skips the
    ._x.py AppleDouble files a Mac's tar or Finder copy leaves beside every file,
    which crashed discovery ("No module named 'engines.'")."""
    stem = fn[:-3]
    return fn.endswith(".py") and not fn.startswith(("_", ".")) and stem.isidentifier()


def discover(force=False):
    """Import every engine module (built in, then STACK_ENGINES_PATH). Idempotent."""
    global _loaded
    if _loaded and not force:
        return
    _loaded = True
    for fn in sorted(os.listdir(HERE)):
        stem = fn[:-3]
        if _is_engine_file(fn) and stem not in _NOT_ENGINES:
            importlib.import_module(f"engines.{stem}")
    for d in extra_dirs():
        if not os.path.isdir(d):
            raise FileNotFoundError(f"STACK_ENGINES_PATH names {d}, which is not a directory")
        for fn in sorted(os.listdir(d)):
            if _is_engine_file(fn):
                _import_file(os.path.join(d, fn), f"stack_engine_ext_{fn[:-3]}")


def registry(kind=None):
    """{kind: {name: class}} or, with kind, {name: class}."""
    discover()
    return dict(_registry[kind]) if kind else {k: dict(v) for k, v in _registry.items()}


def get(kind, name):
    """The class registered as `name`, or a ValueError listing what exists."""
    reg = registry(kind)
    if name not in reg:
        raise ValueError(f"unknown {kind} {name!r} (registered: {', '.join(sorted(reg)) or 'none'})")
    return reg[name]


def origin(kind, name):
    """The file that registered an engine (for `stack_config.py engines`)."""
    registry(kind)
    return _origin.get((kind, name))
