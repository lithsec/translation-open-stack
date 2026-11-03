"""python -m pytest tests/test_profiles.py  (needs Python 3.11+; no GPU, no torch)

Hardware profiles (profiles/*.toml, STACK_PROFILE) and [devices]: what they
change, in what order they win, and that every mistake in one is loud."""
import os
import subprocess
import sys

import stack_config as c
from engines.base import Context, Engine
from engines.common import ct2_device, is_gpu
from support import ROOT, write_temp as _write

CFG = os.path.join(ROOT, "server", "stack_config.py")


def _clean_env(monkeypatch):
    """None of the settings a profile yields to (monkeypatch puts them back)."""
    for k in ("STACK_PROFILE", "STACK_DEVICES", "STACK_CONFIG", "MADLAD", "VOXCPM_GPUS"):
        monkeypatch.delenv(k, raising=False)


def test_every_shipped_profile_loads(monkeypatch):
    _clean_env(monkeypatch)
    names = [n for n, _ in c.list_profiles()]
    assert {"cuda-48gb", "cuda-32gb", "cuda-2gpu", "radeon-32+16"} <= set(names), names
    for name, desc in c.list_profiles():
        assert desc, f"{name}: no description"
        prof = c.load_profile(name)
        c.load(profile=name)
        c.load_models(profile=name)
        c.load_devices(profile=name)
        assert c.profile_lines(name)[0].startswith(f"profile {name}:")
        assert prof["name"] == name


def test_no_profile_changes_nothing(monkeypatch):
    _clean_env(monkeypatch)
    assert c.load_profile() == {}
    assert c.load_devices() == {"default": "auto"}
    assert c.load(profile="cuda-48gb")[0] == c.load()[0]
    assert c.load_models(profile="cuda-48gb")[0] == c.load_models()[0]
    assert c.profile_env_lines() == []


def test_profile_env_yields_to_the_environment(monkeypatch):
    _clean_env(monkeypatch)
    assert c.profile_env_lines("cuda-32gb") == ["export MADLAD=3b"]
    with monkeypatch.context() as m:
        m.setenv("MADLAD", "7b")
        assert c.profile_env_lines("cuda-32gb") == []
    # Quoted for eval: a value can't break out of its assignment.
    p = _write('[env]\nX_Y = "a b; rm -rf /"\nFLAG = true\n')
    assert c.profile_env_lines(p) == ["export X_Y='a b; rm -rf /'", "export FLAG=1"]


def test_devices_order_file_then_profile_then_environment(monkeypatch):
    _clean_env(monkeypatch)
    cfg = _write('[devices]\ndefault = "cuda:0"\nwhisper = "cpu"\nkokoro = "cuda:0"\n')
    prof = _write('[devices]\nwhisper = "cuda:1"\n')
    monkeypatch.setenv("STACK_CONFIG", cfg)
    assert c.load_devices() == {"default": "cuda:0", "whisper": "cpu", "kokoro": "cuda:0"}
    assert c.load_devices(profile=prof)["whisper"] == "cuda:1"
    monkeypatch.setenv("STACK_DEVICES", "whisper=mps, lid=cuda:1")
    d = c.load_devices(profile=prof)
    assert d["whisper"] == "mps" and d["lid"] == "cuda:1" and d["kokoro"] == "cuda:0"
    # [devices] is not a language
    assert "devices" not in c.load()[0]


def test_profile_models_and_languages_win_over_the_file(monkeypatch):
    _clean_env(monkeypatch)
    prof = _write('[models.whisper]\nmodel = "large-v3-turbo"\nrevision = ""\n'
                  '[languages.km]\nasr = "whisper"\n')
    models, src = c.load_models(profile=prof)
    assert models["whisper"]["model"] == "large-v3-turbo" and "profile" in src
    assert models["hymt"] == c.MODEL_DEFAULTS["hymt"]
    table, src = c.load(profile=prof)
    base, _ = c.load()
    # Merged key by key: Khmer keeps its voices and translator, only asr changes.
    assert table["km"] == {**base["km"], "asr": "whisper"} and "profile" in src
    assert c.tables(table)["OMNI_LANGS"].get("km") is None


def test_bad_profiles_fail_loudly(monkeypatch):
    _clean_env(monkeypatch)
    bad = ['[devicez]\nwhisper = "cpu"\n',                 # unknown table
           '[devices]\nwhisperr = "cpu"\n',                # unknown engine
           '[devices]\nwhisper = "gpu1"\n',                # bad device
           '[devices]\nwhisper = "cuda:one"\n',
           '[env]\nlower = "x"\n',                         # not UPPER_CASE
           '[env]\nX = ["a"]\n',                           # not a scalar
           '[languages]\nkm = "whisper"\n',                # not a table
           '[languages.km]\nasr = "nope"\n',               # unknown recogniser
           '[models.whisperr]\nmodel = "x"\n']             # unknown model
    for text in bad:
        p = _write(text)
        try:
            c.load(profile=p)
            c.load_models(profile=p)
            assert False, text
        except ValueError:
            pass
    for name in ("nope", "../etc/passwd", "a b"):
        try:
            c.load_profile(name)
            assert False, name
        except (ValueError, FileNotFoundError):
            pass
    monkeypatch.setenv("STACK_DEVICES", "whisper")
    try:
        c.load_devices()
        assert False
    except ValueError:
        pass


def test_cli():
    env = {k: v for k, v in os.environ.items() if k not in ("STACK_PROFILE", "MADLAD")}
    run = lambda *a, **kw: subprocess.run([sys.executable, CFG, *a], capture_output=True, text=True,
                                          env={**env, **kw})
    r = run("profiles")
    assert r.returncode == 0 and "radeon-32+16" in r.stdout
    r = run("profile-env", STACK_PROFILE="cuda-32gb")
    assert r.returncode == 0 and r.stdout.strip() == "export MADLAD=3b"
    r = run("check", STACK_PROFILE="cuda-2gpu")
    assert r.returncode == 0 and "profile: cuda-2gpu" in r.stdout and "whisper=cuda:1" in r.stdout
    r = run("check", STACK_PROFILE="nope")
    assert r.returncode != 0 and "Traceback" not in r.stderr and "cuda-32gb" in r.stderr
    # The shell side: a bad profile stops the start; a good one sets its defaults.
    sh = os.path.join(ROOT, "scripts", "profile-env.sh")
    r = subprocess.run(["bash", "-c", f'. "{sh}"; echo "MADLAD=$MADLAD"'], capture_output=True, text=True,
                       env={**env, "STACK_PROFILE": "cuda-32gb"})
    assert r.returncode == 0 and "MADLAD=3b" in r.stdout
    r = subprocess.run(["bash", "-c", f'. "{sh}"; echo reached'], capture_output=True, text=True,
                       env={**env, "STACK_PROFILE": "nope"})
    assert r.returncode != 0 and "reached" not in r.stdout


def test_the_user_guide_example_profile_is_valid(monkeypatch):
    """docs/user-guide.md "Create a profile" shows a complete profile; it must load."""
    import re
    guide = open(os.path.join(ROOT, "docs", "user-guide.md"), encoding="utf-8").read()
    sec = guide[guide.index("### Create a profile"):guide.index("### AMD and Mac")]
    blocks = [b for b in re.findall(r"```toml\n(.*?)```", sec, re.S) if "[devices]" in b]
    assert len(blocks) == 1, "expected one example profile in the section"
    p = _write("\n".join(line[3:] if line.startswith("   ") else line for line in blocks[0].splitlines()))
    _clean_env(monkeypatch)
    prof = c.load_profile(p)
    assert prof["devices"]["whisper"] == "cuda:1" and prof["env"]["MADLAD"] == "3b"
    assert c.load(profile=p)[0]["km"]["asr"] == "whisper"
    assert c.load_models(profile=p)[0]["whisper"]["model"] == "large-v3-turbo"


def test_engines_load_on_their_device():
    ctx = Context(device="cuda:0", devices={"whisper": "cuda:1", "lid": "cpu"})

    class W(Engine):
        name = "whisper"

    class K(Engine):
        name = "kokoro"

    assert W(ctx).device == "cuda:1" and K(ctx).device == "cuda:0"
    assert ctx.device_for("lid") == "cpu" and ctx.device_for("hymt") == "cuda:0"
    assert Context().device_for("whisper") == "cpu"


def test_ct2_device():
    assert ct2_device("cuda") == ("cuda", 0)
    assert ct2_device("cuda:1") == ("cuda", 1)
    assert ct2_device("cpu") == ("cpu", 0)
    assert ct2_device("mps") == ("cpu", 0)   # CTranslate2 has no Apple GPU backend
    assert is_gpu("cuda:1") and not is_gpu("mps") and not is_gpu("cpu")

