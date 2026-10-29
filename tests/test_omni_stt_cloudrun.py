#!/usr/bin/env python3
"""services/omni-stt/cloudrun/setup.sh and teardown.sh without Google Cloud: a
stub gcloud on PATH answers the read-only calls and records every other one.
With DRY_RUN=1 the scripts must call nothing that changes anything; without it,
the stub plays a project (and, when asked, a GPU quota refusal).

    python3 tests/test_omni_stt_cloudrun.py   (or python3 -m pytest tests/test_omni_stt_cloudrun.py)

Needs bash, git and openssl; nothing is built, deployed or deleted.
"""
import os
import re
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CR = os.path.join(ROOT, "services", "omni-stt", "cloudrun")
SETUP = os.path.join(CR, "setup.sh")
TEARDOWN = os.path.join(CR, "teardown.sh")
KEEP = ("HOME", "LANG", "LC_ALL", "TMPDIR")
DIGEST = "sha256:" + "ab" * 32
PINNED = "ghcr.io/lithsec/omni-stt@" + DIGEST

# Read-only calls answer from the environment the test sets; anything else is
# a change: recorded in $CALLS, then refused (DRY_RUN) or allowed.
STUB = r"""#!/bin/bash
args="$*"
case "$args" in
  "auth list"*) echo "someone@example.com"; exit 0 ;;
  "config get-value project"*) echo "proj-test"; exit 0 ;;
  "projects list"*) exit 0 ;;
  "projects describe"*) echo "proj-test"; exit 0 ;;
  "billing projects describe"*) echo "${STUB_BILLING:-True}"; exit 0 ;;
  "beta quotas info list"*) [ -n "${STUB_QUOTA_JSON:-}" ] || exit 1; echo "$STUB_QUOTA_JSON"; exit 0 ;;
  "iam service-accounts describe"*) [ -n "${STUB_SA_DISPLAY:-}" ] || exit 1; echo "$STUB_SA_DISPLAY"; exit 0 ;;
  "secrets describe"*) l="${STUB_SECRET_LABELS:-${STUB_LABELS:-}}"; [ -n "$l" ] || exit 1; echo "$l"; exit 0 ;;
  "artifacts repositories list"*) exit 0 ;;
  "artifacts repositories describe"*) [ -n "${STUB_LABELS:-}" ] || exit 1; echo "$STUB_LABELS"; exit 0 ;;
  "artifacts docker images describe"*) [ -n "${STUB_DIGEST:-}" ] || exit 1; echo "$STUB_DIGEST"; exit 0 ;;
  "run services describe"*"status.conditions"*) echo "${STUB_READY:-True}"; exit 0 ;;
  "run services describe"*)
    if [ -n "${STUB_LABELS:-}" ]; then echo "$STUB_LABELS"; exit 0; fi
    [ "${STUB_ALLOW:-0}" = 1 ] || exit 1; echo "https://omni-stt-xyz.a.run.app"; exit 0 ;;
esac
echo "$args" >> "$CALLS"
[ "${STUB_ALLOW:-0}" = 1 ] || exit 99
case "$args" in
  "run deploy"*) if [ -n "${STUB_DEPLOY_ERR:-}" ]; then echo "$STUB_DEPLOY_ERR" >&2; exit 1; fi ;;
  "builds submit"*) [ -z "${STUB_BUILT:-}" ] || : > "$STUB_BUILT" ;;
esac
cat > /dev/null
exit 0
"""


def _run(script, env=None, args=()):
    """(exit code, stdout+stderr, the changing gcloud calls made)."""
    with tempfile.TemporaryDirectory() as tmp:
        stubs = os.path.join(tmp, "bin")
        os.mkdir(stubs)
        calls = os.path.join(tmp, "calls")
        open(calls, "w").close()
        path = os.path.join(stubs, "gcloud")
        with open(path, "w") as f:
            f.write(STUB)
        os.chmod(path, 0o755)
        full = {k: os.environ[k] for k in KEEP if k in os.environ}
        full.update({"PATH": stubs + os.pathsep + "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                     "CALLS": calls, "DRY_RUN": "1", "ASSUME_YES": "1",
                     "PROJECT": "proj-test", "REGION": "us-east4", "WITH_7B": "no", "NONPROFIT": "no"})
        full.update(env or {})
        p = subprocess.run(["bash", script, *args], env=full, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120)
        with open(calls) as f:
            made = f.read().splitlines()
        return p.returncode, p.stdout + p.stderr, made


def test_prebuilt_image_goes_through_a_ghcr_remote_repository():
    code, out, made = _run(SETUP, {"OMNI_STT_IMAGE": PINNED})
    assert code == 0, out
    assert made == [], made                   # a dry run changes nothing
    assert re.search(r"artifacts repositories create ghcr .*--mode remote-repository --remote-docker-repo https://ghcr\.io", out), out
    assert "run deploy omni-stt --image us-east4-docker.pkg.dev/proj-test/ghcr/lithsec/omni-stt@" + DIGEST in out, out
    deploy = next(line for line in out.splitlines() if "run deploy omni-stt " in line)
    for flag in ("--gpu 1", "--gpu-type nvidia-l4", "--no-gpu-zonal-redundancy", "--cpu 4", "--memory 16Gi",
                 "--no-cpu-throttling", "--min-instances 0", "--max-instances 1", "--timeout 3600",
                 "--concurrency 4", "STT_TOKEN_NONPROFIT=omni-stt-app-token:latest", "EDITION=commercial",
                 "--no-invoker-iam-check", "--service-account omni-stt-run@proj-test.iam.gserviceaccount.com"):
        assert flag in deploy, (flag, deploy)
    assert "builds submit" not in out and "cloudbuild.googleapis.com" not in out
    assert "omni-stt-7b" not in out.split("== 7/7")[1].split("Done.")[0]
    assert "Omnilingual 7B URL" not in out
    assert not re.search(r"\b[0-9a-f]{64}\b", out.replace(DIGEST, "")), "a token was printed in a dry run"


def test_images_env_pins_a_published_digest():
    # The checked-in images.env is what a real run pulls: a ghcr digest, no tag.
    with open(os.path.join(os.path.dirname(SETUP), "images.env")) as f:
        pins = [l.strip() for l in f if l.startswith("OMNI_STT_IMAGE=")]
    assert len(pins) == 1, pins
    assert re.fullmatch(r"OMNI_STT_IMAGE=ghcr\.io/lithsec/omni-stt@sha256:[0-9a-f]{64}", pins[0]), pins
    code, out, made = _run(SETUP)                 # no override: images.env decides
    assert code == 0, out
    assert "run deploy omni-stt --image us-east4-docker.pkg.dev/proj-test/ghcr/lithsec/omni-stt@sha256:" in out, out
    assert "builds submit" not in out


def test_build_path_and_the_7b_service():
    code, out, made = _run(SETUP, {"WITH_7B": "yes", "NONPROFIT": "yes", "OMNI_STT_IMAGE": "build"})
    assert code == 0, out
    assert made == [], made
    assert "cloudbuild.googleapis.com" in out
    assert out.count("builds submit") == 2, out      # omni-stt, then the 7B
    assert "artifacts repositories create omni-stt" in out
    d7 = next(line for line in out.splitlines() if "run deploy omni-stt-7b " in line)
    for flag in ("--concurrency 6", "--gpu-type nvidia-l4", "--max-instances 1", "--timeout 3600",
                 "--startup-probe", "STT_SERVE=listen", "OMNI_CARD=omniASR_LLM_7B_bf16",
                 "STT_TOKEN_NONPROFIT=omni-stt-app-token:latest"):
        assert flag in d7, (flag, d7)
    assert "EDITION=nonprofit" in next(line for line in out.splitlines() if "run deploy omni-stt " in line)
    assert "Omnilingual 7B URL for Lao and Khmer:" in out
    assert "gcloud storage cp" not in out           # 7b-build without MODEL_BUCKET: no bucket copy
    # Cloud Build's service account gets its role (a new project gives it none),
    # before the first build.
    grant = out.index("--role roles/cloudbuild.builds.builder")
    assert "compute@developer.gserviceaccount.com" in out[out.rindex("\n", 0, grant):grant], out
    assert grant < out.index("builds submit")
    # omni-stt is deployed before the hour-long 7B build starts.
    lines = out.splitlines()
    first_deploy = next(i for i, l in enumerate(lines) if "run deploy omni-stt " in l)
    builds = [i for i, l in enumerate(lines) if "builds submit" in l]
    assert builds[0] < first_deploy < builds[1], (builds, first_deploy)


def test_7b_only_layout_deploys_one_service_with_the_voices():
    code, out, made = _run(SETUP, {"WITH_7B": "", "LAYOUT": "7b-only", "NONPROFIT": "yes"})
    assert code == 0, out
    assert made == [], made
    lines = out.splitlines()
    assert not any("run deploy omni-stt " in l for l in lines), out      # no omni-stt service
    assert "remote-repository" not in out                               # nor its ghcr proxy
    assert "artifacts repositories create omni-stt" in out
    assert out.count("builds submit") == 1, out                          # the 7B only
    d7 = next(l for l in lines if "run deploy omni-stt-7b " in l).replace("\\,", ",")
    for flag in ("--concurrency 10", "STT_SERVE=listen+speak,", "STT_MAX_CONNECTIONS=6", "STT_MAX_SPEAKERS=4",
                 "EDITION=nonprofit", "HT_VOICE=coqui", "OMNI_CARD=omniASR_LLM_7B_bf16", "--gpu-type nvidia-l4",
                 "--max-instances 1", "STT_TOKEN_NONPROFIT=omni-stt-app-token:latest"):
        assert flag in d7, (flag, d7)
    # One address for Live Translation's one Omnilingual service field: the 7B's
    # (an older Live Translation, with two fields, is told to put it in both).
    svc = next(l for l in lines if l.strip().startswith("Omnilingual service:"))
    assert "omni-stt-7b" in svc, svc
    assert "Omnilingual 7B URL for Lao and Khmer:" not in out
    assert "the same address in both" in out
    assert "Amazon Transcribe" in out
    assert "One instance of the 7B takes about 6 rooms" in out
    # Commercial: the 7B never offers MMS.
    code, out, made = _run(SETUP, {"WITH_7B": "", "LAYOUT": "7b-only", "NONPROFIT": "no"})
    assert code == 0 and "EDITION=commercial" in out.replace("\\,", ","), out


def test_layout_is_asked_and_7b_only_is_the_default():
    code, out, made = _run(SETUP, {"WITH_7B": "", "LAYOUT": ""})
    assert code == 0, out
    assert "7B only (recommended)" in out and "Layout (1, 2 or 3) [1]: 1" in out, out
    assert not any("run deploy omni-stt " in l for l in out.splitlines())
    assert any("run deploy omni-stt-7b " in l for l in out.splitlines())
    code, out, made = _run(SETUP, {"WITH_7B": "", "LAYOUT": "7b"})
    assert code == 2 and "LAYOUT must be" in out, out
    # The older WITH_7B still means what it did.
    code, out, made = _run(SETUP, {"WITH_7B": "yes", "LAYOUT": "", "OMNI_STT_IMAGE": PINNED})
    assert code == 0 and any("run deploy omni-stt " in l for l in out.splitlines()), out
    assert any("run deploy omni-stt-7b " in l for l in out.splitlines())


def test_pulled_image_needs_no_cloud_build_role():
    code, out, made = _run(SETUP, {"OMNI_STT_IMAGE": PINNED})
    assert code == 0, out
    assert "cloudbuild.builds.builder" not in out


def test_refusals_say_why():
    code, out, made = _run(SETUP, {"STUB_BILLING": "False"})
    assert code == 4 and "billing is not enabled" in out and "billing/linkedaccount" in out, out
    code, out, made = _run(SETUP, {"REGION": "us-west2"})
    assert code == 2 and "no Cloud Run L4 GPUs" in out, out
    code, out, made = _run(SETUP, {"OMNI_STT_IMAGE": "ghcr.io/lithsec/omni-stt:latest"})
    assert code == 3 and "pinned digest" in out, out
    code, out, made = _run(SETUP, {"PROJECT": "Not A Project"})
    assert code == 2, out
    for _ in (1,):
        assert made == []


def test_zero_quota_warns_before_anything_is_built():
    q = '[{"metric": "run.googleapis.com/nvidia_l4_gpu_allocation_no_zonal_redundancy",' \
        ' "dimensionsInfos": [{"dimensions": {"region": "us-east4"}, "details": {"value": "0"}}]}]'
    code, out, made = _run(SETUP, {"STUB_QUOTA_JSON": q})
    assert code == 0 and "reads 0" in out and "iam-admin/quotas" in out, out


def test_quota_refusal_at_deploy_is_explained_and_no_token_leaks():
    err = "ERROR: (gcloud.run.deploy) Quota exceeded for total allowable count of GPUs per project per region."
    code, out, made = _run(SETUP, {"DRY_RUN": "0", "STUB_ALLOW": "1", "OMNI_STT_IMAGE": PINNED,
                                   "STUB_DEPLOY_ERR": err})
    assert code == 1, out
    assert "no Cloud Run L4 GPU quota left in us-east4" in out and "Edit quota" in out, out
    assert any(c.startswith("secrets create omni-stt-app-token") for c in made), made
    assert not re.search(r"\b[0-9a-f]{64}\b", out.replace(DIGEST, "")), "the token was printed before the end"


def test_a_real_run_prints_the_token_once():
    code, out, made = _run(SETUP, {"DRY_RUN": "0", "STUB_ALLOW": "1", "OMNI_STT_IMAGE": PINNED})
    assert code == 0, out
    tokens = re.findall(r"\b[0-9a-f]{64}\b", out.replace(DIGEST, ""))
    assert len(tokens) == 1, tokens
    assert "COPY THE TOKEN NOW" in out and "Omnilingual service:" in out
    assert any(c.startswith("run deploy omni-stt ") for c in made), made


def test_with_the_7b_the_token_is_shown_before_its_build():
    with tempfile.TemporaryDirectory() as tmp:
        built = os.path.join(tmp, "built")
        code, out, made = _run(SETUP, {"DRY_RUN": "0", "STUB_ALLOW": "1", "OMNI_STT_IMAGE": PINNED,
                                       "WITH_7B": "yes", "STUB_DIGEST": "sha256:" + "cd" * 32,
                                       "STUB_BUILT": built})
    assert code == 0, out
    tokens = re.findall(r"\b[0-9a-f]{64}\b", out.replace(DIGEST, "").replace("cd" * 32, ""))
    assert len(tokens) == 1, tokens
    assert out.index(tokens[0]) < out.index("Now the 7B image"), out
    assert "(shown above, when omni-stt came up)" in out
    assert "Omnilingual 7B URL for Lao and Khmer:" in out
    assert any(c.startswith("secrets update omni-stt-app-token --update-labels token-shown=yes") for c in made), made


def test_a_token_never_shown_is_replaced():
    code, out, made = _run(SETUP, {"DRY_RUN": "0", "STUB_ALLOW": "1", "OMNI_STT_IMAGE": PINNED,
                                   "STUB_SECRET_LABELS": "managed-by=omni-stt-setup;token-shown=no"})
    assert code == 0, out
    assert "stopped before showing its token" in out
    assert any(c.startswith("secrets versions add omni-stt-app-token") for c in made), made
    assert len(re.findall(r"\b[0-9a-f]{64}\b", out.replace(DIGEST, ""))) == 1
    # A token that was shown is kept.
    code, out, made = _run(SETUP, {"DRY_RUN": "0", "STUB_ALLOW": "1", "OMNI_STT_IMAGE": PINNED,
                                   "STUB_SECRET_LABELS": "managed-by=omni-stt-setup;token-shown=yes"})
    assert code == 0, out
    assert not any(c.startswith("secrets versions add") for c in made), made
    assert "unchanged: the one you pasted before" in out


def test_a_slow_first_deploy_is_waited_out():
    err = "ERROR: (gcloud.run.deploy) Provisioning revision instances to receive traffic. Resource readiness deadline exceeded."
    code, out, made = _run(SETUP, {"DRY_RUN": "0", "STUB_ALLOW": "1", "OMNI_STT_IMAGE": PINNED,
                                   "STUB_DEPLOY_ERR": err})
    assert code == 0, out
    assert "omni-stt is ready." in out and "COPY THE TOKEN NOW" in out


def test_teardown_deletes_only_what_setup_made():
    code, out, made = _run(TEARDOWN)
    assert code == 0 and "Nothing made by setup.sh" in out, out
    assert made == []
    code, out, made = _run(TEARDOWN, {"STUB_LABELS": "managed-by=omni-stt-setup;cloud.googleapis.com/location=us-east4",
                                      "STUB_SA_DISPLAY": "omni-stt on Cloud Run (setup.sh)"})
    assert code == 0, out
    assert made == [], made
    for want in ("run services delete omni-stt ", "run services delete omni-stt-7b ", "secrets delete omni-stt-app-token",
                 "iam service-accounts delete omni-stt-run@", "artifacts repositories delete ghcr ",
                 "artifacts repositories delete omni-stt "):
        assert want in out, (want, out)
    code, out, made = _run(TEARDOWN, {"STUB_LABELS": "owner=someone-else"})
    assert "Leaving alone" in out and "delete" not in out.replace("to delete", ""), out


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)} passed")
