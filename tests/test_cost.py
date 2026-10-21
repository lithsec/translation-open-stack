#!/usr/bin/env python3
"""eval/tools/cost.py, the cost page's formulas as a script: the worked
example matches the values in site/data/list-prices.json and the measured
translation step, a price change propagates (in the module and through
--prices), --json round-trips, and site/build.py uses the same functions.
Standard library only; no site build.

    python3 tests/test_cost.py        (or python3 -m pytest tests/test_cost.py)
"""
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
COST_PY = os.path.join(ROOT, "eval", "tools", "cost.py")
BUILD_PY = os.path.join(ROOT, "site", "build.py")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cost = _load(COST_PY, "cost_tool_under_test")


def _close(x, y):
    assert abs(x - y) < 1e-9, (x, y)


def test_worked_example_matches_prices():
    """Every building block, route and worked-example line is the stated
    formula applied to list-prices.json and the measured translation step."""
    prices, foundry = cost.load_prices(), cost.load_foundry()
    est = cost.estimate(prices, foundry)
    p = {k: v["value"] for k, v in prices["prices"].items()}
    a = {k: v["value"] for k, v in prices["assumptions"].items()}
    news = foundry["results"]["news"]
    voice = a["voice_chars_per_hour"] * p["azure_tts_per_million_chars"] / 1e6
    omni = p["cloud_run_l4_gpu_per_hour"] + p["cloud_run_4vcpu_per_hour"] + p["cloud_run_16gib_per_hour"]
    lt = p["gemini_lt_per_minute"] * 60
    B = est["blocks"]
    _close(B["voice_h"]["value"], voice)
    _close(B["omni_h"]["value"], omni)
    _close(B["omni_tail"]["value"], a["omni_stt_idle_tail_h"] * omni)
    _close(B["lt_h"]["value"], lt)
    _close(B["stt_lid"]["value"], p["azure_stt_per_hour"] + p["azure_language_id_per_hour"])
    for l, (pp, eff) in cost.FOUNDRY_CHOICE.items():
        _close(B[f"foundry_{l}"]["value"], news[pp][eff]["usd_per_hour"])
    _close(B["foundry_ht_en"]["value"], news["ht-en"]["low"]["usd_per_hour"])
    # routes, in the page's order
    r = est["routes"]
    assert len(r) == 6
    _close(r[0]["per_hour"], p["azure_speech_translation_per_hour"] + voice)
    _close(r[1]["per_hour"], p["azure_stt_per_hour"] + news["en-es"]["none"]["usd_per_hour"] + voice)
    _close(r[2]["per_hour"], p["azure_stt_per_hour"] + news["en-ht"]["low"]["usd_per_hour"] + a["gemini_voice_per_hour"])
    _close(r[3]["per_hour"], omni * (1 + a["omni_stt_idle_tail_h"]) + news["ht-en"]["low"]["usd_per_hour"] + voice)
    _close(r[4]["per_hour"], omni / a["omni_stt_streams_300m"] + news["ht-en"]["low"]["usd_per_hour"] + voice)
    _close(r[5]["per_hour"], lt)
    for row in r:
        assert row["route"] and row["formula"] and row["note"], row
        assert cost.money(row["per_hour"]).startswith("$")
    # worked example 1: one room, one hour, English into fr, pt, es, ht
    fh = {l: news[pp][eff]["usd_per_hour"] for l, (pp, eff) in cost.FOUNDRY_CHOICE.items()}
    t1 = (p["azure_stt_per_hour"] + p["azure_language_id_per_hour"]) + sum(fh.values()) + 3 * voice + a["gemini_voice_per_hour"]
    _close(est["example1"]["total"], t1)
    _close(sum(x["per_hour"] for x in est["example1"]["rows"]), t1)
    _close(est["example1"]["live_translate_4"], 4 * lt)
    _close(est["example1"]["live_translate_5"], 5 * lt)
    # worked example 2: comments back into English, per room-hour, on top of example 1
    cm = a["comment_minutes_per_room_hour"]
    req = news["ht-en"]["low"]["usd_per_request"]
    t2 = t1 + cm * (p["azure_stt_per_hour"] + p["azure_language_id_per_hour"]) / 60 \
        + cm * a["foundry_comment_requests_per_minute"] * req + cm / 60 * voice + omni * (1 + a["omni_stt_idle_tail_h"]) / 2
    _close(est["example2"]["total"], t2)
    _close(est["example2"]["live_translate_open"], 5 * lt)
    _close(est["example2"]["live_translate_ptt"], 4 * lt + cm * p["gemini_lt_per_minute"])
    # the formulas print the prices they use
    assert cost.money(p["azure_tts_per_million_chars"]) in B["voice_h"]["formula"]
    assert cost.money(voice) in r[0]["formula"]
    assert est["as_of"] == prices["as_of"]


def test_price_change_propagates():
    """Doubling the voice price doubles the voice block and moves every line
    that contains a voice, by exactly that much, and nothing else."""
    prices, foundry = cost.load_prices(), cost.load_foundry()
    before = cost.estimate(prices, foundry)
    changed = copy.deepcopy(prices)
    changed["prices"]["azure_tts_per_million_chars"]["value"] *= 2
    after = cost.estimate(changed, foundry)
    voice = before["blocks"]["voice_h"]["value"]
    assert voice > 0
    _close(after["blocks"]["voice_h"]["value"], 2 * voice)
    _close(after["blocks"]["omni_h"]["value"], before["blocks"]["omni_h"]["value"])
    deltas = [a["per_hour"] - b["per_hour"] for a, b in zip(after["routes"], before["routes"])]
    assert [round(d, 9) for d in deltas] == [round(x, 9) for x in (voice, voice, 0, voice, voice, 0)], deltas
    _close(after["example1"]["total"] - before["example1"]["total"], 3 * voice)
    assert after["routes"][0]["formula"] != before["routes"][0]["formula"]
    # and through --prices on the command line
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(changed, f)
        out = subprocess.run([sys.executable, COST_PY, "--json", "--prices", path], capture_output=True, text=True, check=True, cwd=ROOT)
        cli = json.loads(out.stdout)
        _close(cli["blocks"]["voice_h"]["value"], 2 * voice)
        _close(cli["example1"]["total"], after["example1"]["total"])
    finally:
        os.unlink(path)


def test_json_round_trips():
    """`cost.py --json` is estimate() as JSON, and the table names every route."""
    est = cost.estimate(cost.load_prices(), cost.load_foundry())
    out = subprocess.run([sys.executable, COST_PY, "--json"], capture_output=True, text=True, check=True, cwd=ROOT)
    assert json.loads(out.stdout) == json.loads(json.dumps(est))
    assert json.loads(json.dumps(est)) == est  # floats survive the trip
    table = subprocess.run([sys.executable, COST_PY], capture_output=True, text=True, check=True, cwd=ROOT).stdout
    for r in est["routes"]:
        assert r["route"] in table, r["route"]
        assert cost.money(r["per_hour"]) in table
    assert cost.money(est["example1"]["total"]) in table
    assert "not" in est["note"] and "bill" in est["note"]


def test_build_uses_the_same_functions():
    """site/build.py loads eval/tools/cost.py and takes its numbers from
    estimate(), so the page and the script cannot drift; the script is one of
    the build's inputs, so site/check_private.sh scans it."""
    build = _load(BUILD_PY, "site_build_under_test")
    assert os.path.samefile(build.COST.__file__, COST_PY)
    assert build.money is build.COST.money
    assert build.INPUTS["cost_tool"] == os.path.relpath(COST_PY, ROOT)
    listed = subprocess.run([sys.executable, BUILD_PY, "--list-inputs"], capture_output=True, text=True, check=True, cwd=ROOT).stdout.split()
    assert "eval/tools/cost.py" in listed and "site/data/list-prices.json" in listed
    src = open(BUILD_PY, encoding="utf-8").read()
    assert "COST.estimate(" in src
    assert 'src_link(INPUTS["cost_tool"])' in src


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
