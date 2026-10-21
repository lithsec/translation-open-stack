#!/usr/bin/env python3
"""Per-hour cost of each live translation route, from list prices.

    python3 eval/tools/cost.py                  # every route's per-hour estimate, formula and assumptions
    python3 eval/tools/cost.py --json           # the same as JSON
    python3 eval/tools/cost.py --prices PATH    # another price file (default site/data/list-prices.json)
    python3 eval/tools/cost.py --foundry PATH   # another measured translation step
                                                # (default eval/2026-10-translation-cost/results.json)

Every figure is a list-price estimate (pay as you go, US regions), with its
formula and the assumptions behind it; nothing here is read from a bill. The
prices and assumptions come from site/data/list-prices.json; the translation
step (cost per listener-language hour of the LLM translator) is measured, in
eval/2026-10-translation-cost/results.json, and read from there.

The research site's Cost page (site/build.py, build_cost) imports this module
and calls estimate() for its numbers, so the page and this script cannot
drift: change a price in list-prices.json and both move. estimate() takes the
two JSON documents and returns one dictionary (building blocks, routes, the
two worked examples), which --json prints as is.

Standard library only.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PRICES = "site/data/list-prices.json"
FOUNDRY = "eval/2026-10-translation-cost/results.json"

# The services a route names. site/build.py passes its own (anonymised in an
# anonymised build); the command line uses these.
NAMES = {
    "az": "Azure",
    "azs": "Azure Speech",
    "fdy": "GPT-5.6-sol on Azure AI Foundry",
    "gem": "Gemini",
    "glt": "Gemini Live Translate",
}

# Which measured Foundry direction and reasoning setting prices the translation
# step for each listener language (the news set, long spoken sentences).
FOUNDRY_CHOICE = {"fr": ("en-fr", "none"), "pt": ("en-pt", "none"), "es": ("en-es", "none"), "ht": ("en-ht", "low")}
LANG = {"fr": "French", "pt": "Portuguese", "es": "Spanish", "ht": "Haitian Creole"}


def money(v, d=2):
    return f"${v:,.{d}f}"


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_prices(path=None):
    return load_json(path or os.path.join(ROOT, PRICES))


def load_foundry(path=None):
    return load_json(path or os.path.join(ROOT, FOUNDRY))


def estimate(prices, foundry, names=None):
    """Every number of the cost page, from the two JSON documents.

    prices: site/data/list-prices.json as loaded; foundry: the measured
    translation step (eval/2026-10-translation-cost/results.json); names:
    service names to print (NAMES, or site/build.py's)."""
    n = dict(NAMES, **(names or {}))
    p = {k: v["value"] for k, v in prices["prices"].items()}
    a = {k: v.get("value") for k, v in prices["assumptions"].items()}
    news = foundry["results"]["news"]
    per_hour_key = "usd_per_hour"

    # Building blocks: per hour of continuous speech.
    voice_h = a["voice_chars_per_hour"] * p["azure_tts_per_million_chars"] / 1e6
    omni_h = p["cloud_run_l4_gpu_per_hour"] + p["cloud_run_4vcpu_per_hour"] + p["cloud_run_16gib_per_hour"]
    tail = a["omni_stt_idle_tail_h"] * omni_h
    lt_h = p["gemini_lt_per_minute"] * 60
    stt_lid = p["azure_stt_per_hour"] + p["azure_language_id_per_hour"]
    fh = {l: news[pp][eff][per_hour_key] for l, (pp, eff) in FOUNDRY_CHOICE.items()}
    back_h = news["ht-en"]["low"][per_hour_key]
    req_cost_back = news["ht-en"]["low"]["usd_per_request"]
    blocks = {
        "voice_h": {"what": f"{n['az']} neural voice, per language-hour",
                    "formula": f'{a["voice_chars_per_hour"]:,} chars × {money(p["azure_tts_per_million_chars"])} ÷ 1,000,000', "value": voice_h},
        "omni_h": {"what": "omni-stt, one L4 instance, per running hour",
                   "formula": f'{money(p["cloud_run_l4_gpu_per_hour"])} + {money(p["cloud_run_4vcpu_per_hour"])} + {money(p["cloud_run_16gib_per_hour"])}', "value": omni_h},
        "omni_tail": {"what": "omni-stt idle tail after the last stream, per session",
                      "formula": f'{a["omni_stt_idle_tail_h"]:g} h × {money(omni_h)}', "value": tail},
        "lt_h": {"what": f"{n['glt']}, per target language-hour",
                 "formula": f'{money(p["gemini_lt_per_minute"], 3)} × 60', "value": lt_h},
        "stt_lid": {"what": f"{n['az']} speech to text with language detection, per audio hour",
                    "formula": f'{money(p["azure_stt_per_hour"])} + {money(p["azure_language_id_per_hour"])}', "value": stt_lid},
    }
    for l, (pp, eff) in FOUNDRY_CHOICE.items():
        blocks[f"foundry_{l}"] = {"what": f"{n['fdy']} translation step, English into {LANG[l]}, reasoning {eff} (measured)",
                                  "formula": f"{pp} at reasoning {eff}, {foundry['sentences_per_listener_language_hour']} sentences an hour", "value": fh[l]}
    blocks["foundry_ht_en"] = {"what": f"{n['fdy']} translation step, Haitian Creole into English, reasoning low (measured)",
                               "formula": f"ht-en at reasoning low, {foundry['sentences_per_listener_language_hour']} sentences an hour", "value": back_h}
    blocks["foundry_ht_en_request"] = {"what": f"{n['fdy']} one request, Haitian Creole into English, reasoning low (measured)",
                                       "formula": "ht-en at reasoning low, per request", "value": req_cost_back}

    # Routes: one speaker, one listener language, one hour of continuous speech.
    routes = [
        {"route": f"{n['azs']} translation → {n['az']} voice",
         "formula": f'{money(p["azure_speech_translation_per_hour"])} + {money(voice_h)}',
         "per_hour": p["azure_speech_translation_per_hour"] + voice_h,
         "note": "one target language; Haitian Creole has no voice on this route"},
        {"route": f"{n['az']} STT → {n['fdy']} → {n['az']} voice, into Spanish",
         "formula": f'{money(p["azure_stt_per_hour"])} + {money(fh["es"])} + {money(voice_h)}',
         "per_hour": p["azure_stt_per_hour"] + fh["es"] + voice_h,
         "note": "French and Portuguese within a few cents"},
        {"route": f"{n['az']} STT → {n['fdy']} → {n['gem']} voice, into Haitian Creole",
         "formula": f'{money(p["azure_stt_per_hour"])} + {money(fh["ht"])} + {money(a["gemini_voice_per_hour"])}',
         "per_hour": p["azure_stt_per_hour"] + fh["ht"] + a["gemini_voice_per_hour"],
         "note": "the voice price is an estimate"},
        {"route": f"omni-stt → {n['fdy']} → {n['az']} voice, Haitian Creole into English, alone on its instance",
         "formula": f'{money(omni_h)} × (1 + {a["omni_stt_idle_tail_h"]:g}) + {money(back_h)} + {money(voice_h)}',
         "per_hour": omni_h * (1 + a["omni_stt_idle_tail_h"]) + back_h + voice_h,
         "note": "one session, including the idle tail"},
        {"route": "the same, sharing a full instance",
         "formula": f'{money(omni_h)} ÷ {a["omni_stt_streams_300m"]} + {money(back_h)} + {money(voice_h)}',
         "per_hour": omni_h / a["omni_stt_streams_300m"] + back_h + voice_h,
         "note": f'{a["omni_stt_streams_300m"]} streams per instance (about {a["omni_stt_streams_7b"]} with the 7B model)'},
        {"route": n["glt"],
         "formula": f'{money(p["gemini_lt_per_minute"], 3)} × 60',
         "per_hour": lt_h,
         "note": "per target language; speech to speech in one step"},
    ]

    # Worked example 1: one room, one hour, English into French, Portuguese, Spanish and Haitian Creole.
    ex1 = [
        {"part": "Recognise the English speaker, language detection on",
         "formula": f'{money(p["azure_stt_per_hour"])} + {money(p["azure_language_id_per_hour"])}', "per_hour": stt_lid},
        {"part": "Translate into French, Portuguese, Spanish (reasoning none)",
         "formula": " + ".join(money(fh[l]) for l in ("fr", "pt", "es")), "per_hour": fh["fr"] + fh["pt"] + fh["es"]},
        {"part": "Translate into Haitian Creole (reasoning low)", "formula": money(fh["ht"]), "per_hour": fh["ht"]},
        {"part": f"{n['az']} voices for French, Portuguese, Spanish",
         "formula": f'3 × {a["voice_chars_per_hour"]:,} chars × {money(p["azure_tts_per_million_chars"])}/M', "per_hour": 3 * voice_h},
        {"part": f"{n['gem']} voice for Haitian Creole (estimate)", "formula": money(a["gemini_voice_per_hour"]), "per_hour": a["gemini_voice_per_hour"]},
    ]
    t1 = sum(r["per_hour"] for r in ex1)
    example1 = {"title": "One room, one hour: English into French, Portuguese, Spanish and Haitian Creole",
                "rows": ex1, "total": t1,
                "live_translate_4": 4 * lt_h, "live_translate_5": 5 * lt_h,
                "live_translate_note": f"{n['glt']}: 4 languages × {money(lt_h)}; 5 sessions if listeners are translated back into English all hour"}

    # Worked example 2: two rooms, short comments back into English, per room-hour on top of example 1.
    cm = a["comment_minutes_per_room_hour"]
    ex2 = [
        {"part": "Recognise the comments, language detection on",
         "formula": f'{cm} min × ({money(p["azure_stt_per_hour"])} + {money(p["azure_language_id_per_hour"])})/60', "per_hour": cm * stt_lid / 60},
        {"part": "Translate the comments into English",
         "formula": f'{cm} min × {a["foundry_comment_requests_per_minute"]:g} requests/min × {money(req_cost_back, 4)}',
         "per_hour": cm * a["foundry_comment_requests_per_minute"] * req_cost_back},
        {"part": "English voice for the comments", "formula": f'{cm}/60 × {money(voice_h)}', "per_hour": cm / 60 * voice_h},
        {"part": "omni-stt for Haitian Creole comments, one instance shared by the two rooms",
         "formula": f'({money(omni_h)} × (1 + {a["omni_stt_idle_tail_h"]:g} h idle tail)) ÷ 2',
         "per_hour": omni_h * (1 + a["omni_stt_idle_tail_h"]) / 2},
    ]
    t2 = t1 + sum(r["per_hour"] for r in ex2)
    example2 = {"title": f"Two rooms, with {cm} minutes of short comments an hour back into English: per room-hour, on top of example 1",
                "rows": ex2, "total": t2,
                "live_translate_open": 5 * lt_h, "live_translate_ptt": 4 * lt_h + cm * p["gemini_lt_per_minute"],
                "live_translate_note": f"{n['glt']}: an English session open all hour in each room, or a return session only while someone speaks"}

    return {
        "as_of": prices.get("as_of"),
        "currency": prices.get("currency", "USD"),
        "note": "List-price estimates for one hour of continuous speech; nothing here is read from a bill.",
        "prices": {k: dict(v) for k, v in prices["prices"].items()},
        "assumptions": {k: dict(v) for k, v in prices["assumptions"].items()},
        "blocks": blocks,
        "routes": routes,
        "example1": example1,
        "example2": example2,
    }


def _tbl(headers, rows, numeric=()):
    """A plain-text table: columns two spaces apart, the `numeric` columns right-aligned."""
    rows = [[str(c) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    def line(r):
        cells = [c.rjust(w) if i in numeric else c.ljust(w) for i, (c, w) in enumerate(zip(r, widths))]
        return "  ".join(cells).rstrip()

    return "\n".join([line(headers), "  ".join("-" * w for w in widths)] + [line(r) for r in rows])


def format_table(est):
    """The estimate as plain text."""
    out = [f"Cost per hour of live translation, list prices as of {est['as_of']} ({est['currency']}).", est["note"], ""]
    out += ["List prices", _tbl(["Price", "Value", "What"],
                                 [[k, money(v["value"], 3) if v["value"] < 0.1 else money(v["value"]), v["what"]] for k, v in est["prices"].items()], numeric={1}), ""]
    out += ["Assumptions", _tbl(["Assumption", "Value", "What"],
                                 [[k, v["value"], v["what"]] for k, v in est["assumptions"].items()], numeric={1}), ""]
    out += ["Building blocks (per hour unless stated)", _tbl(["Block", "Formula", "Value", "What"],
                                                              [[k, b["formula"], money(b["value"], 4 if b["value"] < 0.1 else 2), b["what"]] for k, b in est["blocks"].items()], numeric={2}), ""]
    out += ["Per hour, by route: one speaker, one listener language, one hour of continuous speech",
            _tbl(["Route", "Formula", "Per hour", "Note"], [[r["route"], r["formula"], money(r["per_hour"]), r["note"]] for r in est["routes"]], numeric={2}), ""]
    for key in ("example1", "example2"):
        ex = est[key]
        rows = [[r["part"], r["formula"], money(r["per_hour"])] for r in ex["rows"]] + [["Total", "", money(ex["total"])]]
        out += [f"Worked example: {ex['title']}", _tbl(["Part", "Formula", "Per room-hour"], rows, numeric={2})]
        if key == "example1":
            out += [f"  {ex['live_translate_note']}: {money(ex['live_translate_4'])} / {money(ex['live_translate_5'])}", ""]
        else:
            out += [f"  {ex['live_translate_note']}: {money(ex['live_translate_open'])} / {money(ex['live_translate_ptt'])}", ""]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print the estimate as JSON")
    ap.add_argument("--prices", default=None, help=f"price file (default {PRICES})")
    ap.add_argument("--foundry", default=None, help=f"measured translation step (default {FOUNDRY})")
    a = ap.parse_args(argv)
    est = estimate(load_prices(a.prices), load_foundry(a.foundry))
    if a.json:
        json.dump(est, sys.stdout, indent=1, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print(format_table(est))
    return 0


if __name__ == "__main__":
    sys.exit(main())
