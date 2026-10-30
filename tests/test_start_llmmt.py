"""scripts/start-llmmt.sh's choice of whether, and where, to start Gemma 4 beside the stack: its dry run against
stand-in GPU sizes. No GPU, no vLLM.

    python3 tests/test_start_llmmt.py
"""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plan(gpus, **env):
    e = {k: v for k, v in os.environ.items() if k not in ("LLMMT", "EDITION", "OMNI_LARGE", "STACK_PROFILE")}
    e.update(LLMMT_DRY_RUN="1", LLMMT_GPUS_GB=gpus, **env)
    return subprocess.run(["bash", os.path.join(ROOT, "scripts", "start-llmmt.sh")], env=e,
                          capture_output=True, text=True, check=True).stdout


def test_one_card_needs_room_beside_the_stack():
    assert "gemma on GPU 0 (96 GB, vLLM share 0.38)" in plan("96")
    assert "gemma on GPU 0 (80 GB" in plan("80")
    assert "no room" in plan("48")
    assert "no room" in plan("96", OMNI_LARGE="1")       # the 7B's 20 GB leaves too little
    assert "no room" in plan("")                          # no GPU seen


def test_several_cards_put_gemma_on_the_last():
    assert "gemma on GPU 1 (48 GB, vLLM share 0.85)" in plan("48 48")
    assert "no room" in plan("24 24")
    assert "no room" in plan("48 48", STACK_PROFILE="cuda-2gpu")   # recognition and voices are there
    assert "gemma on GPU 1 (80 GB, vLLM share 0.45)" in plan("80 80", STACK_PROFILE="cuda-2gpu")


def test_operator_choices():
    assert "off" in plan("96", LLMMT="0")
    assert "not started" in plan("96", EDITION="commercial")
    assert "gemma milmmt on GPU 1 (48 GB, vLLM share 0.42)" in plan("48 48", LLMMT="gemma,milmmt")
    assert "gemma on GPU 0" in plan("48", LLMMT="gemma")      # forced: no room check


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
