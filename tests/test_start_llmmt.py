"""scripts/start-llmmt.sh's choice of whether, and where, to start Gemma 4 (and MiLMMT-46, never in commercial)
beside the stack: its dry run against stand-in GPU sizes. No GPU, no vLLM.

    python -m pytest tests/test_start_llmmt.py
"""
import os
import subprocess

from support import ROOT


def plan(gpus, **env):
    e = {k: v for k, v in os.environ.items() if k not in ("LLMMT", "EDITION", "OMNI_LARGE", "STACK_PROFILE")}
    e.update(LLMMT_DRY_RUN="1", LLMMT_GPUS_GB=gpus, **env)
    return subprocess.run(["bash", os.path.join(ROOT, "scripts", "start-llmmt.sh")], env=e,
                          capture_output=True, text=True, check=True).stdout


def test_one_card_needs_room_beside_the_stack():
    assert "gemma on GPU 0 (96 GB, vLLM share 0.38)" in plan("96")
    assert "gemma on GPU 0 (80 GB" in plan("80")
    assert "no room" in plan("48")
    # nvidia-smi's 97887 MiB on a 96 GB card is 95 here: with the 7B (53 + 36 + 4 = 93) Gemma still fits, at
    # vLLM share 36 / 95 (the eval ran 0.41 there and peaked at 95.9 of 97.9 GB, eval/2026-11-commercial-edition).
    assert "gemma on GPU 0 (95 GB, vLLM share 0.38)" in plan("95", OMNI_LARGE="1")
    assert "gemma on GPU 0 (96 GB, vLLM share 0.38)" in plan("96", OMNI_LARGE="1")
    assert "gemma on GPU 0 (95 GB, vLLM share 0.38)" in plan("95", OMNI_LARGE="1", EDITION="commercial")
    assert "no room" in plan("80", OMNI_LARGE="1")       # the 7B's 20 GB leaves too little on 80 GB
    assert "no room" in plan("92", OMNI_LARGE="1")       # 53 + 36 + 4 = 93
    assert "gemma on GPU 0 (80 GB, vLLM share 0.45)" in plan("80")   # without the 7B: 33 + 36 + 4 <= 80
    assert "no room" in plan("")                          # no GPU seen


def test_several_cards_put_gemma_on_the_last():
    assert "gemma on GPU 1 (48 GB, vLLM share 0.85)" in plan("48 48")
    assert "no room" in plan("24 24")
    assert "no room" in plan("48 48", STACK_PROFILE="cuda-2gpu")   # recognition and voices are there
    assert "gemma on GPU 1 (80 GB, vLLM share 0.45)" in plan("80 80", STACK_PROFILE="cuda-2gpu")


def test_operator_choices():
    assert "off" in plan("96", LLMMT="0")
    assert "gemma milmmt on GPU 1 (48 GB, vLLM share 0.42)" in plan("48 48", LLMMT="gemma,milmmt")
    assert "gemma on GPU 0" in plan("48", LLMMT="gemma")      # forced: no room check


def test_commercial_starts_gemma_not_milmmt():
    """Gemma 4 is Apache-2.0; MiLMMT-46 (Gemma terms, restricted) stays out of commercial."""
    out = plan("96", EDITION="commercial")
    assert "gemma on GPU 0 (96 GB, vLLM share 0.38)" in out and "milmmt" not in out
    out = plan("48 48", EDITION="commercial", LLMMT="gemma,milmmt")
    assert "not starting milmmt (xiaomi-research/MiLMMT-46-12B-v0.1): EDITION=commercial leaves it out" in out
    assert "gemma on GPU 1 (48 GB, vLLM share 0.85)" in out     # one model: the single-model share
    out = plan("96", EDITION="commercial", LLMMT="milmmt")
    assert "not starting milmmt" in out and "nothing to start in commercial" in out and " on GPU " not in out
    assert "no room" in plan("48", EDITION="commercial")       # auto still checks the room

