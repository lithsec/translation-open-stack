#!/usr/bin/env python3
"""services/omni-stt/deploy.sh without Google Cloud: DRY_RUN=1 prints the
gcloud/docker commands instead of running them, and stub gcloud/docker on PATH
fail the test if anything calls them anyway. Checks the private-registry guard
on fine-tuned builds, private.env (read, never run; the environment wins), and
that no private default is left in the committed script.

    python3 tests/test_omni_stt_deploy.py   (or python3 -m pytest tests/test_omni_stt_deploy.py)

Needs bash and git; nothing is built or pushed.
"""
import os
import re
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SVC = os.path.join(ROOT, "services", "omni-stt")
DEPLOY = os.path.join(SVC, "deploy.sh")
KEEP = ("HOME", "LANG", "LC_ALL", "TMPDIR")


def _run(cmd, env=None, private_env=""):
    """(exit code, stdout+stderr, whether a stub gcloud/docker was called)."""
    with tempfile.TemporaryDirectory() as tmp:
        stubs = os.path.join(tmp, "bin")
        os.mkdir(stubs)
        called = os.path.join(tmp, "called")
        for name in ("gcloud", "docker"):
            path = os.path.join(stubs, name)
            with open(path, "w") as f:
                f.write(f"#!/bin/sh\necho \"$0 $*\" >> '{called}'\nexit 99\n")
            os.chmod(path, 0o755)
        pe = os.path.join(tmp, "private.env")
        with open(pe, "w") as f:
            f.write(private_env)
        full = {k: os.environ[k] for k in KEEP if k in os.environ}
        full.update({"PATH": stubs + os.pathsep + "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                     "DRY_RUN": "1", "PRIVATE_ENV": pe, "PROJECT": "proj"})
        full.update(env or {})
        full = {k: v for k, v in full.items() if v is not None}
        p = subprocess.run(["bash", DEPLOY, cmd], env=full, capture_output=True, text=True, cwd=tmp, timeout=60)
        return p.returncode, p.stdout + p.stderr, os.path.exists(called)


FT = {"FT_CARD": "omniASR_LLM_300M_test", "FT_WEIGHTS": "gs://a-private-bucket/models/x", "BASE_TAG": "abc123"}


def test_build_ft_dry_run_to_artifact_registry():
    code, out, called = _run("build-ft", FT)
    assert code == 0, out
    assert "+ gcloud builds submit" in out and not called
    assert "us-east4-docker.pkg.dev/proj/omni-stt/omni-stt:abc123-omniASR_LLM_300M_test" in out


def test_build_ft_refuses_public_registries():
    for extra in ({"REPO": "ghcr.io/lithsec"}, {"REPO": "docker.io/lithsec"}, {"PROJECT": "ghcr.io"},
                  {"REPO_REGION": "ghcr.io/x"}, {"REPO": "a/b"}, {"TAG": "x y"}):
        code, out, called = _run("build-ft", {**FT, **extra})
        assert code == 3 and "refusing build-ft" in out and not called, (extra, code, out)
    code, out, _ = _run("build-voices", {"BASE_TAG": "abc", "REPO": "ghcr.io/lithsec"})
    assert code == 3 and "refusing build-voices" in out, out


def test_build_ft_needs_its_private_settings():
    for missing in ("FT_CARD", "FT_WEIGHTS", "BASE_TAG"):
        code, out, called = _run("build-ft", {**FT, missing: None})
        assert code != 0 and missing in out and not called, (missing, out)
    code, out, _ = _run("build-ft", {**FT, "FT_WEIGHTS": "https://example.com/weights"})
    assert code == 3 and "gs://" in out, out
    code, out, _ = _run("build-ft", {**FT, "FT_CARD": "card;rm -rf"})
    assert code == 3, out


def test_private_env_is_read_never_run_and_the_environment_wins():
    with tempfile.TemporaryDirectory() as tmp:
        marker = os.path.join(tmp, "ran")
        private = (f"# a comment\n\nFT_CARD=fromfile\nFT_WEIGHTS=\"gs://b/m\"\nBASE_TAG=$(touch {marker})\n"
                   f"touch {marker}\nnot a line\n")
        code, out, called = _run("build-ft", {"BASE_TAG": "base"}, private_env=private)
        assert code == 0, out
        assert ":base-fromfile" in out and not os.path.exists(marker) and not called, out
        code, out, _ = _run("build-ft", {"BASE_TAG": "base", "FT_CARD": "fromenv"}, private_env=private)
        assert code == 0 and ":base-fromenv" in out, out


def test_deploy_passes_the_edition():
    code, out, called = _run("deploy")
    assert code == 0 and not called, out
    assert "EDITION=commercial" in out, out
    code, out, _ = _run("deploy", {"EDITION": "both"})
    assert "EDITION=both" in out, out


def test_deploy_mounts_only_the_secrets_named():
    code, out, _ = _run("deploy")
    assert code == 0 and "--set-secrets STT_TOKEN=omni-stt-token:latest " in out, out
    assert "STT_SIGNING_KEY" not in out and "STT_TOKEN_NONPROFIT" not in out
    code, out, called = _run("deploy", {"SIGNING_SECRET": "omni-stt-signing-key", "NONPROFIT_SECRET": "omni-stt-token-nonprofit"})
    assert code == 0 and not called, out
    out = out.replace("\\,", ",")             # the dry run prints with printf %q
    assert ("--set-secrets STT_TOKEN=omni-stt-token:latest,STT_SIGNING_KEY=omni-stt-signing-key:latest,"
            "STT_TOKEN_NONPROFIT=omni-stt-token-nonprofit:latest ") in out, out
    # From private.env too (the environment still wins).
    code, out, _ = _run("deploy", private_env="NONPROFIT_SECRET=np-from-file\n")
    out = out.replace("\\,", ",")
    assert "STT_TOKEN_NONPROFIT=np-from-file:latest" in out, out
    # A name that is not a plain secret name, or the STT_TOKEN secret again, is refused.
    for extra in ({"SIGNING_SECRET": "a,STT_TOKEN=b"}, {"NONPROFIT_SECRET": "omni-stt-token"}):
        code, out, called = _run("deploy", extra)
        assert code == 3 and "refusing" in out and not called, (extra, out)


def test_3b_targets_dry_run():
    code, out, called = _run("3b-build", {"TAG": "abc"})
    assert code == 0 and not called, out
    assert "+ gcloud builds submit" in out
    assert "https://dl.fbaipublicfiles.com/mms/omniASR-CTC-3B.pt" in out
    assert '"-t", "us-east4-docker.pkg.dev/proj/omni-stt/omni-stt:abc-3b"' in out
    code, out, called = _run("3b-deploy", {"TAG": "abc", "SIGNING_SECRET": "omni-stt-signing-key"})
    assert code == 0 and not called, out
    out = out.replace("\\,", ",")
    assert "+ gcloud run deploy omni-stt-3b-stream " in out, out
    assert "--image us-east4-docker.pkg.dev/proj/omni-stt/omni-stt:abc-3b " in out
    assert "--min-instances 0 --max-instances 2 --concurrency 6 --timeout 3600 " in out
    assert "STT_CTC_STREAM=1,OMNI_CARD=omniASR_CTC_3B_bf16,STT_CTC_CARD=omniASR_CTC_3B_bf16,STT_MAX_CONNECTIONS=6," in out
    assert "--set-secrets STT_TOKEN=omni-stt-token:latest,STT_SIGNING_KEY=omni-stt-signing-key:latest " in out
    code, out, called = _run("3b-deploy", {"MAX_STREAMS_3B": "6,X=1"})
    assert code == 3 and not called, out


def _private_values():
    """The private values (card, bucket, project) in this checkout's own
    services/omni-stt/private.env, if any: never in a committed file."""
    path = os.path.join(SVC, "private.env")
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip().strip("\"'")
            # The private ones; a region or the repository name is public anyway.
            if k.strip() in ("FT_CARD", "FT_WEIGHTS", "PROJECT") and v:
                out.append(v)
    return out


def test_duo_build_dry_run():
    code, out, called = _run("duo-build", {"BASE_TAG": "abc123", "TAG": "def456"})
    assert code == 0, out
    assert "+ gcloud builds submit" in out and not called
    assert "BASE_IMAGE=us-east4-docker.pkg.dev/proj/omni-stt/omni-stt:abc123-7b" in out
    assert "us-east4-docker.pkg.dev/proj/omni-stt/omni-stt:def456-duo" in out
    assert "omniASR-CTC-3B.pt" in out and "Dockerfile.duo" in out
    code, out, _ = _run("duo-build", {"BASE_TAG": None})
    assert code != 0 and "BASE_TAG" in out


def test_no_private_default_is_committed():
    names = ("deploy.sh", "Dockerfile", "Dockerfile.ft", "Dockerfile.voices", "README.md", "private.env.example")
    texts = {n: open(os.path.join(SVC, n), encoding="utf-8").read() for n in names}
    deploy = texts["deploy.sh"]
    assert 'FT_CARD="${FT_CARD:-' not in deploy and 'FT_WEIGHTS="${FT_WEIGHTS:-' not in deploy
    assert not re.search(r"gs://[a-z0-9]", deploy), "deploy.sh names a bucket"
    for value in _private_values():
        for name, text in texts.items():
            assert value not in text, f"{name} names a private.env value"
    ignored = subprocess.run(["git", "-C", ROOT, "check-ignore", "-q", "services/omni-stt/private.env"])
    assert ignored.returncode == 0, "services/omni-stt/private.env must be git-ignored"


def test_7b_deploy_with_the_voices():
    # Default: /listen only, as before.
    code, out, called = _run("7b-deploy", {"TAG": "abc123"})
    assert code == 0 and not called, out
    d = next(l for l in out.splitlines() if "run deploy omni-stt-7b" in l).replace("\\,", ",")
    assert "STT_SERVE=listen," in d and "--concurrency 6" in d and "EDITION=" not in d, d
    # VOICES_7B=1: /speak too, its sockets counted in --concurrency.
    code, out, called = _run("7b-deploy", {"TAG": "abc123", "VOICES_7B": "1", "EDITION": "nonprofit"})
    assert code == 0 and not called, out
    d = next(l for l in out.splitlines() if "run deploy omni-stt-7b" in l).replace("\\,", ",")
    for want in ("STT_SERVE=listen+speak,", "EDITION=nonprofit", "HT_VOICE=coqui", "STT_MAX_SPEAKERS=4",
                 "--concurrency 10", "OMNI_CARD=omniASR_LLM_7B_bf16"):
        assert want in d, (want, d)
    code, out, _ = _run("7b-deploy", {"TAG": "abc123", "VOICES_7B": "yes"})
    assert code == 2 and "VOICES_7B" in out, out


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
