"""python3 tests/test_profiles.py  (needs Python 3.11+; no GPU, no torch)

Hardware profiles (profiles/*.toml, STACK_PROFILE) and [devices]: what they
change, in what order they win, and that every mistake in one is loud."""
import os, subprocess, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "server"))
import stack_config as c  # noqa: E402
from engines.base import Context, Engine  # noqa: E402
from engines.common import ct2_device, is_gpu  # noqa: E402

CFG = os.path.join(ROOT, "server", "stack_config.py")


def _write(text, suffix=".toml"):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


def _clean_env():
    for k in ("STACK_PROFILE", "STACK_DEVICES", "STACK_CONFIG", "MADLAD", "VOXCPM_GPUS"):
        os.environ.pop(k, None)


def test_every_shipped_profile_loads():
    _clean_env()
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


def test_no_profile_changes_nothing():
    _clean_env()
    assert c.load_profile() == {}
    assert c.load_devices() == {"default": "auto"}
    assert c.load(profile="cuda-48gb")[0] == c.load()[0]
    assert c.load_models(profile="cuda-48gb")[0] == c.load_models()[0]
    assert c.profile_env_lines() == []


def test_profile_env_yields_to_the_environment():
    _clean_env()
    assert c.profile_env_lines("cuda-32gb") == ["export MADLAD=3b"]
    os.environ["MADLAD"] = "7b"
    try:
        assert c.profile_env_lines("cuda-32gb") == []
    finally:
        del os.environ["MADLAD"]
    # Quoted for eval: a value can't break out of its assignment.
    p = _write('[env]\nX_Y = "a b; rm -rf /"\nFLAG = true\n')
    assert c.profile_env_lines(p) == ["export X_Y='a b; rm -rf /'", "export FLAG=1"]


def test_devices_order_file_then_profile_then_environment():
    _clean_env()
    cfg = _write('[devices]\ndefault = "cuda:0"\nwhisper = "cpu"\nkokoro = "cuda:0"\n')
    prof = _write('[devices]\nwhisper = "cuda:1"\n')
    os.environ["STACK_CONFIG"] = cfg
    try:
        assert c.load_devices() == {"default": "cuda:0", "whisper": "cpu", "kokoro": "cuda:0"}
        assert c.load_devices(profile=prof)["whisper"] == "cuda:1"
        os.environ["STACK_DEVICES"] = "whisper=mps, lid=cuda:1"
        d = c.load_devices(profile=prof)
        assert d["whisper"] == "mps" and d["lid"] == "cuda:1" and d["kokoro"] == "cuda:0"
        # [devices] is not a language
        assert "devices" not in c.load()[0]
    finally:
        _clean_env()


def test_profile_models_and_languages_win_over_the_file():
    _clean_env()
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


def test_bad_profiles_fail_loudly():
    _clean_env()
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
    os.environ["STACK_DEVICES"] = "whisper"
    try:
        c.load_devices()
        assert False
    except ValueError:
        pass
    finally:
        _clean_env()


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


def test_the_user_guide_example_profile_is_valid():
    """docs/user-guide.md "Create a profile" shows a complete profile; it must load."""
    import re
    guide = open(os.path.join(ROOT, "docs", "user-guide.md"), encoding="utf-8").read()
    sec = guide[guide.index("### Create a profile"):guide.index("### AMD and Mac")]
    blocks = [b for b in re.findall(r"```toml\n(.*?)```", sec, re.S) if "[devices]" in b]
    assert len(blocks) == 1, "expected one example profile in the section"
    p = _write("\n".join(line[3:] if line.startswith("   ") else line for line in blocks[0].splitlines()))
    _clean_env()
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
