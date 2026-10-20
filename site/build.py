#!/usr/bin/env python3
"""Build the research site from the eval results in this repository.

    python3 site/build.py                      # -> site/_site/
    python3 site/build.py --anonymise-vendors  # cloud services become "Vendor A", "Vendor B", ...
    python3 site/build.py --list-inputs        # the repository files the build reads

Standard library only (Python 3.11+). Every number on the site is read from
the eval/ files listed by --list-inputs or computed from them here; the prose
around the charts restates those numbers, not new ones. Charts are inline SVG
with a data table under each.
"""
import argparse
import html
import json
import os
import re
import shutil
import statistics as st
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "_site")
REPO_URL = "https://github.com/lithsec/translation-open-stack"
BLOB = REPO_URL + "/blob/main/"
TREE = REPO_URL + "/tree/main/"

INPUTS = {
    "bakeoff": "eval/2026-10-real-voices/out/stt-bakeoff/summary.json",
    "live": "eval/2026-10-real-voices/stt_transcribe_live.json",
    "degrade": "eval/2026-10-real-voices/out/stt-degrade/summary.json",
    "htmt": "eval/2026-10-real-voices/text-mt/run12.log",
    "shoot1": "eval/2026-10-translator-shootout/results.json",
    "shoot2": "eval/2026-10-translator-shootout/results-round2.json",
    "sizes": "eval/2026-10-omni-sizes/results.json",
    "voices": "eval/2026-10-ht-voices/scores.json",
    "judge": "eval/2026-10-ht-voices/judge.json",
    "mp3": "eval/2026-10-ht-voices/mp3",
    "langs": "languages.toml",
    # September 2026 model evaluation (Languages page)
    "sept_doc": "docs/dev/model-evaluation.md",
    "derived": "site/data/derived.json",  # scores copied by site/extract_derived.py
    "r6lao": "eval/2026-09-model-eval/results/round6_lao.json",
    "asr300": "eval/2026-09-model-eval/results/asr/omniASR_LLM_300M.json",
    "nat": "eval/2026-09-model-eval/results/voice_naturalness.json",
    "voxspeed": "eval/2026-09-model-eval/results/voxcpm_speed.json",
    "r8asr": "eval/2026-09-model-eval/results/round8_new_languages/new_asr.json",
    "r8mt": "eval/2026-09-model-eval/results/round8_new_languages/new_mt_judged.json",
    "r8nat": "eval/2026-09-model-eval/results/round8_new_languages/new_voice_naturalness.json",
    "stack_config": "server/stack_config.py",
    "licences": "server/licences.py",
    # Latency page
    "oct_doc": "docs/dev/route-findings-2026-10.md",
    "htv_readme": "eval/2026-10-ht-voices/README.md",
    "azg_readme": "eval/2026-10-azure-stt-gemini/README.md",
    "omni_readme": "services/omni-stt/README.md",
    "latency": "eval/2026-10-latency/results.json",  # optional: rendered when present
}
OPTIONAL_INPUTS = {"latency"}

# ---------------------------------------------------------------- names
# Every system that appears on a chart. vendor = the company whose cloud
# service it is (None for open weights). With --anonymise-vendors, a cloud
# system's label becomes "Vendor <letter> <what>"; open-weight models keep
# their names (their licences, not service terms, govern them).
VENDOR_ORDER = ["microsoft", "google", "openai", "elevenlabs", "assemblyai", "gladia"]
VENDOR_NAME = {"microsoft": "Microsoft Azure", "google": "Google", "openai": "OpenAI",
               "elevenlabs": "ElevenLabs", "assemblyai": "AssemblyAI", "gladia": "Gladia"}

SYSTEMS = {
    # recognisers
    "azure-speech": ("Azure Speech, real time", "microsoft", "live recogniser"),
    "gemini-3.5-transcribe-live": ("Google gemini-3.5-transcribe-live", "google", "live recogniser"),
    "omni": ("Omnilingual ASR 300M (open stack, live)", None, ""),
    "aai-batch": ("AssemblyAI batch (Universal-3.5 Pro / Universal-2), whole clip", "assemblyai", "batch recogniser"),
    "aai-stream": ("AssemblyAI Universal-3.6 Pro Streaming", "assemblyai", "live recogniser"),
    "el-realtime": ("ElevenLabs Scribe v2 Realtime, VAD 1.5 s (default)", "elevenlabs", "live recogniser, default"),
    "el-realtime-vad05": ("ElevenLabs Scribe v2 Realtime, VAD 0.5 s", "elevenlabs", "live recogniser, short pause"),
    "el-scribe-v2": ("ElevenLabs Scribe v2, batch, whole clip", "elevenlabs", "batch recogniser"),
    "gem__gemini-3.1-pro-preview": ("Gemini 3.1 Pro preview, per sentence", "google", "large LLM, per sentence"),
    "gem__gemini-3.8-flash": ("Gemini 3.8 Flash, per sentence", "google", "fast LLM, per sentence"),
    "oai-live": ("OpenAI gpt-live-transcribe (Realtime)", "openai", "live recogniser"),
    "oai__gpt-4o-mini-transcribe": ("OpenAI gpt-4o-mini-transcribe, per sentence", "openai", "batch recogniser 1"),
    "oai__gpt-4o-transcribe": ("OpenAI gpt-4o-transcribe, per sentence", "openai", "batch recogniser 2"),
    "oai__gpt-transcribe": ("OpenAI gpt-transcribe, per sentence", "openai", "batch recogniser 3"),
    "ht:gemini-2.5-pro": ("Gemini 2.5 Pro, batch per sentence", "google", "large LLM, older, per sentence"),
    "ht:gemini-2.5-flash": ("Gemini 2.5 Flash, batch per sentence", "google", "fast LLM, older, per sentence"),
    "ht:chirp3": ("Google Chirp 3, auto language, batch", "google", "batch recogniser"),
    "ht:gladia": ("Gladia Solaria-1, live", "gladia", "live recogniser"),
    "ht:gemini-live": ("Gemini Live, its input transcript", "google", "speech-to-speech model, its transcript"),
    # translators
    "hymt2-7b-nf4": ("Hy-MT2 7B, 4-bit (open stack)", None, ""),
    "madlad-7b-int8": ("MADLAD-400 7B, int8 (open stack fallback)", None, ""),
    "translategemma-12b": ("TranslateGemma 12B", None, ""),
    "azure-translator": ("Azure Translator", "microsoft", "translation service"),
    "gemini-3.5-flash@medium": ("Gemini 3.5 Flash, thinking medium", "google", "fast LLM, thinking medium"),
    "gemini-3.5-flash": ("Gemini 3.5 Flash, default thinking", "google", "fast LLM, default thinking"),
    "foundry-gpt-5.6-sol@low": ("GPT-5.6-sol, reasoning low (on Azure AI Foundry)", "openai", "LLM, reasoning low"),
    "stack-route": ("Open stack route: Hy-MT2, else MADLAD", None, ""),
    "gpt-oss-120b@low": ("gpt-oss-120b, reasoning low", None, ""),
    "gpt-oss-120b@medium": ("gpt-oss-120b, reasoning medium", None, ""),
    "gpt-oss-20b@low": ("gpt-oss-20b, reasoning low", None, ""),
    "qwen3.8-27b-fp8@low": ("Qwen3.8-27B FP8, thinking low", None, ""),
    "mt:foundry-gpt-5.6-sol@low": ("GPT-5.6-sol, reasoning low", "openai", "LLM, reasoning low"),
    "mt:gemini-3.5-flash@medium": ("Gemini 3.5 Flash, thinking medium", "google", "fast LLM, thinking medium"),
    "mt:gemini-3.5-flash": ("Gemini 3.5 Flash, default thinking", "google", "fast LLM, default thinking"),
    "mt:gpt-5.5@low": ("GPT-5.5, reasoning low", "openai", "LLM 2, reasoning low"),
    "mt:gemini-3.5-flash@low": ("Gemini 3.5 Flash, thinking low", "google", "fast LLM, thinking low"),
    "mt:foundry-gpt-5.6-luna@low": ("GPT-5.6-luna, reasoning low", "openai", "small LLM, reasoning low"),
    "mt:gpt-5.4-mini@low": ("GPT-5.4-mini, reasoning low", "openai", "small LLM 2, reasoning low"),
    "mt:gemma-4-31b": ("Gemma 4 31B", None, ""),
    "mt:gpt-4.1": ("GPT-4.1", "openai", "older LLM"),
    "mt:google-translate": ("Google Translate", "google", "translation service"),
    "mt:foundry-deepseek-v4.1-flash": ("DeepSeek-V4.1-Flash (hosted)", None, ""),
    "mt:nllb-200-3.3b": ("NLLB-200 3.3B", None, ""),
    "mt:translategemma-27b": ("TranslateGemma 27B", None, ""),
    "mt:azure-translator": ("Azure Translator", "microsoft", "translation service"),
    "mt:foundry-mistral-large-3": ("Mistral-Large-3 (hosted)", None, ""),
    "mt:kreyol-mt": ("Kreyòl-MT", None, ""),
    # voices
    "v:gemini-flash": ("Gemini 3.8 Flash TTS", "google", "voice, full model"),
    "v:gemini-lite": ("Gemini 3.8 Flash Lite TTS", "google", "voice, lite model"),
    "v:oai-coral": ("gpt-4o-mini-tts, coral", "openai", "voice 1"),
    "v:oai-coral-instr": ("gpt-4o-mini-tts, coral + accent instruction", "openai", "voice 1 + accent instruction"),
    "v:oai-sage-instr": ("gpt-4o-mini-tts, sage + accent instruction", "openai", "voice 2 + accent instruction"),
    "v:coqui": ("Coqui VITS OpenBible Haitian Creole", None, ""),
    "v:mms": ("Meta MMS-TTS (mms-tts-hat)", None, ""),
    # September end to end, October cloud pipelines
    "sept:stack": ("Open stack, recommended setup", None, ""),
    "sept:gemini-live": ("Gemini Live (Vertex AI)", "google", "speech-to-speech model"),
    "azg:azure_only": ("Azure speech translation + Azure voice", "microsoft", "speech translation + voice"),
    # grader
    "grader": ("Gemini 3.1 Pro (preview)", "google", "large LLM"),
    "grader-old": ("Gemini 2.5 Pro", "google", "large LLM, older"),
}

ANON = False


def vendor(v):
    """A vendor's name, or its letter when anonymised."""
    if not ANON:
        return VENDOR_NAME[v]
    return "Vendor " + "ABCDEFGH"[VENDOR_ORDER.index(v)]


def L(key):
    label, v, what = SYSTEMS[key]
    if ANON and v:
        return f"{vendor(v)} {what}".strip()
    return label


def VN(v, real, what):
    """A cloud product named in prose: its real name, or "Vendor X <what>" when anonymised."""
    return f"{vendor(v)} {what}".strip() if ANON else real


# Free text from an optional result file (eval/2026-10-latency) may name
# vendors and their products; anonymised builds replace them.
_ANON_PATTERNS = [
    ("microsoft", r"Microsoft(?: Azure)?|Azure(?: AI)?(?: Foundry| Speech| Translator| OpenAI)?|Foundry"),
    ("google", r"Google(?: Cloud)?|Vertex(?: AI)?|gemini-[\w.\-@]+|Gemini(?: [\d.]+)?(?: (?:Pro|Flash|Lite|Live|TTS))*|Chirp ?\d*"),
    ("openai", r"OpenAI|gpt-(?!oss)[\w.\-@]+|GPT-(?!oss)[\w.\-@]+"),
    ("elevenlabs", r"ElevenLabs|Scribe(?: v2)?(?: Realtime)?"),
    ("assemblyai", r"AssemblyAI|Universal-[\w.\-]+"),
    ("gladia", r"Gladia|Solaria-?\d*"),
]


def anon_text(s):
    s = str(s)
    if not ANON:
        return s
    for v, pat in _ANON_PATTERNS:
        s = re.sub(pat, vendor(v), s, flags=re.IGNORECASE)
    return s


def is_cloud(key):
    return SYSTEMS[key][1] is not None


def esc(s):
    return html.escape(str(s), quote=True)


def J(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


# ---------------------------------------------------------------- charts

_chart_n = [0]
SERIES = ["c1", "c2", "c3", "c4"]


def _cid(prefix):
    _chart_n[0] += 1
    return f"{prefix}-{_chart_n[0]}"


def _table(headers, rows, numeric_from=1):
    h = "".join(f'<th scope="col"{" class=num" if i >= numeric_from else ""}>{esc(x)}</th>' for i, x in enumerate(headers))
    body = ""
    for r in rows:
        cells = ""
        for i, x in enumerate(r):
            if i == 0:
                cells += f'<th scope="row">{esc(x)}</th>'
            else:
                cells += f'<td{" class=num" if i >= numeric_from else ""}>{esc(x)}</td>'
        body += f"<tr>{cells}</tr>"
    return f'<div class="table-wrap"><table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table></div>'


def _bar_svg(frac, cls, capped=False, title=""):
    w = max(0.0, min(1.0, frac)) * 100
    t = f"<title>{esc(title)}</title>" if title else ""
    fill = f'<rect x="0" y="1" width="{w:.2f}%" height="10" rx="2" class="{cls}"/>' if w > 0 else ""
    if capped:
        fill += f'<rect x="{max(0, w - 6):.2f}%" y="1" width="6%" height="10" class="capped"/>'
    return (f'<svg role="img" aria-hidden="true" focusable="false">{t}'
            f'<rect x="0" y="5.5" width="100%" height="1" class="base"/>{fill}</svg>')


def chart_frame(cid, title, sub, body, table_html, vendor_named, legend=None, note=None):
    flag = '<span class="vendor-flag" title="Names cloud vendors; anonymised by --anonymise-vendors">vendors named</span>' \
        if vendor_named and not ANON else ""
    leg = ""
    if legend:
        leg = '<ul class="legend">' + "".join(
            f'<li><span class="sw {c}"></span>{esc(n)}</li>' for n, c in legend) + "</ul>"
    nt = f'<p class="axis-note">{note}</p>' if note else ""
    return (f'<figure class="chart" id="{cid}" data-vendor-named="{str(bool(vendor_named)).lower()}" aria-labelledby="{cid}-t">'
            f'<figcaption><p class="chart-title" id="{cid}-t">{esc(title)}{flag}</p>'
            f'<p class="chart-sub">{sub}</p></figcaption>{leg}{body}{nt}'
            f'<details class="data"><summary>Data table</summary>{table_html}</details></figure>')


def hbar(title, sub, rows, *, fmt=lambda v: pct(v), maxv=None, cap=None, legend=None,
         vendor_named=False, table_headers=None, table_rows=None, note=None):
    """rows: dicts with label, value (None = not available), cls, hl, extra, nav (text if value None)."""
    cid = _cid("chart")
    vals = [r["value"] for r in rows if r["value"] is not None]
    top = maxv if maxv is not None else (max(vals) if vals else 1)
    if cap is not None:
        top = min(top, cap)
    out = '<div class="bars">'
    for r in rows:
        v = r["value"]
        lab = esc(r["label"]) + (f' <small>{esc(r["extra"])}</small>' if r.get("extra") else "")
        if v is None:
            line = f'<div class="bar-line">{_bar_svg(0, "c1")}<span class="v">{esc(r.get("nav", "n/a"))}</span></div>'
        else:
            capped = cap is not None and v > cap
            line = (f'<div class="bar-line">{_bar_svg(v / top if top else 0, r.get("cls", "c1"), capped, r["label"] + ": " + fmt(v))}'
                    f'<span class="v">{esc(fmt(v))}</span></div>')
        out += f'<div class="bar-row{" hl" if r.get("hl") else ""}"><div class="lab">{lab}</div><div class="bar-track">{line}</div></div>'
    out += "</div>"
    if table_rows is None:
        table_headers = ["System", "Value"]
        table_rows = [[r["label"] + (f' ({r["extra"]})' if r.get("extra") else ""),
                       fmt(r["value"]) if r["value"] is not None else r.get("nav", "n/a")] for r in rows]
    if cap is not None and any(v > cap for v in vals):
        note = (note + " " if note else "") + f"Bars beyond {fmt(cap)} are cut short (hatched end); the value is printed."
    return chart_frame(cid, title, sub, out, _table(table_headers, table_rows), vendor_named, legend, note)


def grouped(title, sub, groups, series, *, fmt=lambda v: pct(v), maxv=None, vendor_named=False, note=None, clamp_zero=True):
    """groups: [(label, [value per series or None], hl)]; series: [(name, cls)]."""
    cid = _cid("chart")
    vals = [v for _, vs, _ in groups for v in vs if v is not None]
    top = maxv if maxv is not None else max(vals)
    out = '<div class="bars grouped">'
    for label, vs, hl in groups:
        lines = ""
        for (sname, cls), v in zip(series, vs):
            if v is None:
                lines += f'<div class="bar-line">{_bar_svg(0, cls)}<span class="v">n/a</span></div>'
            else:
                lines += (f'<div class="bar-line">{_bar_svg((max(v, 0) if clamp_zero else v) / top, cls, False, f"{label}, {sname}: {fmt(v)}")}'
                          f'<span class="v">{esc(fmt(v))}</span></div>')
        out += f'<div class="bar-row{" hl" if hl else ""}"><div class="lab">{esc(label)}</div><div class="bar-track">{lines}</div></div>'
    out += "</div>"
    trows = [[label] + [fmt(v) if v is not None else "n/a" for v in vs] for label, vs, _ in groups]
    return chart_frame(cid, title, sub, out, _table([""] + [s for s, _ in series], trows), vendor_named,
                       legend=series, note=note)


def scatter(title, sub, points, *, xlabel, ylabel, xlog=True, xticks=(), yticks=(), xfmt=str, yfmt=str,
            vendor_named=False, legend=None, table_headers=None, table_rows=None, note=None):
    """points: dicts x, y, label, cls, anchor ('start'|'end'), dy."""
    import math
    cid = _cid("chart")
    W, H, ml, mr, mt, mb = 560, 340, 52, 16, 14, 46
    xs = [p["x"] for p in points]
    x0, x1 = (min(xticks), max(xticks)) if xticks else (min(xs), max(xs))
    y0, y1 = min(yticks), max(yticks)
    tx = (lambda v: math.log10(v)) if xlog else (lambda v: v)

    def X(v):
        return ml + (tx(v) - tx(x0)) / (tx(x1) - tx(x0)) * (W - ml - mr)

    def Y(v):
        return mt + (1 - (v - y0) / (y1 - y0)) * (H - mt - mb)
    s = f'<svg class="plot" viewBox="0 0 {W} {H}" role="img" aria-labelledby="{cid}-t">'
    for t in yticks:
        s += f'<line class="gridline" x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>'
        s += f'<text x="{ml - 6}" y="{Y(t) + 4:.1f}" font-size="12" text-anchor="end">{esc(yfmt(t))}</text>'
    for t in xticks:
        s += f'<line class="gridline" y1="{mt}" y2="{H - mb}" x1="{X(t):.1f}" x2="{X(t):.1f}"/>'
        s += f'<text x="{X(t):.1f}" y="{H - mb + 16}" font-size="12" text-anchor="middle">{esc(xfmt(t))}</text>'
    s += f'<text x="{(ml + W - mr) / 2}" y="{H - 8}" font-size="12" text-anchor="middle">{esc(xlabel)}</text>'
    s += f'<text x="14" y="{(mt + H - mb) / 2}" font-size="12" text-anchor="middle" transform="rotate(-90 14 {(mt + H - mb) / 2})">{esc(ylabel)}</text>'
    for p in points:
        cx, cy = X(p["x"]), Y(p["y"])
        s += (f'<g><title>{esc(p["label"])}: {esc(xfmt(p["x"]))}, {esc(yfmt(p["y"]))}</title>'
              f'<circle class="pt {p.get("cls", "c1")}" cx="{cx:.1f}" cy="{cy:.1f}" r="6"/></g>')
        anchor = p.get("anchor", "start")
        dx = 10 if anchor == "start" else -10
        s += f'<text class="lbl" x="{cx + dx:.1f}" y="{cy + 4 + p.get("dy", 0):.1f}" text-anchor="{anchor}">{esc(p.get("short", p["label"]))}</text>'
    s += "</svg>"
    if table_rows is None:
        table_headers = ["System", xlabel, ylabel]
        table_rows = [[p["label"], xfmt(p["x"]), yfmt(p["y"])] for p in points]
    return chart_frame(cid, title, sub, s, _table(table_headers, table_rows), vendor_named, legend, note)


def lines(title, sub, xcats, series, *, ylabel, yticks, yfmt, vendor_named=False, note=None, table_headers=None, table_rows=None):
    """series: [(name, cls, [y per xcat])]. Categorical x."""
    cid = _cid("chart")
    W, H, ml, mr, mt, mb = 560, 320, 48, 110, 14, 52
    y0, y1 = min(yticks), max(yticks)

    def X(i):
        return ml + i / (len(xcats) - 1) * (W - ml - mr)

    def Y(v):
        return mt + (1 - (v - y0) / (y1 - y0)) * (H - mt - mb)
    s = f'<svg class="plot" viewBox="0 0 {W} {H}" role="img" aria-labelledby="{cid}-t">'
    for t in yticks:
        s += f'<line class="gridline" x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>'
        s += f'<text x="{ml - 6}" y="{Y(t) + 4:.1f}" font-size="12" text-anchor="end">{esc(yfmt(t))}</text>'
    for i, c in enumerate(xcats):
        parts = c.split("\n")
        for k, part in enumerate(parts):
            s += f'<text x="{X(i):.1f}" y="{H - mb + 16 + 14 * k}" font-size="12" text-anchor="middle">{esc(part)}</text>'
    s += f'<text x="14" y="{(mt + H - mb) / 2}" font-size="12" text-anchor="middle" transform="rotate(-90 14 {(mt + H - mb) / 2})">{esc(ylabel)}</text>'
    ends = []
    for name, cls, ys in series:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
        s += f'<polyline class="ln {cls}" points="{pts}" style="fill:none"/>'
        for i, v in enumerate(ys):
            s += f'<g><title>{esc(name)}, {esc(xcats[i].replace(chr(10), " "))}: {esc(yfmt(v))}</title><circle class="pt {cls}" cx="{X(i):.1f}" cy="{Y(v):.1f}" r="5"/></g>'
        ends.append([Y(ys[-1]), name])
    ends.sort()
    for k in range(1, len(ends)):  # keep end labels apart
        if ends[k][0] - ends[k - 1][0] < 14:
            ends[k][0] = ends[k - 1][0] + 14
    for y, name in ends:
        s += f'<text class="lbl" x="{X(len(xcats) - 1) + 10:.1f}" y="{y + 4:.1f}">{esc(name)}</text>'
    s += "</svg>"
    if table_rows is None:
        table_headers = [""] + [c.replace("\n", " ") for c in xcats]
        table_rows = [[name] + [yfmt(v) for v in ys] for name, _, ys in series]
    return chart_frame(cid, title, sub, s, _table(table_headers, table_rows), vendor_named,
                       legend=[(n, c) for n, c, _ in series], note=note)


# ---------------------------------------------------------------- page shell

PAGES = [("index.html", "Home"), ("findings.html", "Findings"), ("languages.html", "Languages"),
         ("latency.html", "Latency"), ("voices.html", "Voices"),
         ("methodology.html", "Methodology"), ("models.html", "Models & licences")]


def page(fname, title, body, description, extra_head="", scripts=""):
    nav = "".join(f'<a href="{f}"{" aria-current=page" if f == fname else ""}>{esc(n)}</a>' for f, n in PAGES)
    anon = ('<span>Cloud vendor names are anonymised in this build.</span>' if ANON else "")
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="stylesheet" href="style.css">
{extra_head}</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><pattern id="hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2" height="4" fill="var(--fg-2)"/></pattern></defs></svg>
<header class="site"><div class="in"><a class="brand" href="index.html">Translation Open Stack · Research</a><nav aria-label="Pages">{nav}</nav></div></header>
<main id="main">
{body}
</main>
<footer class="site"><div class="in"><span>Results measured September–October 2026. Code: <a href="{REPO_URL}">lithsec/translation-open-stack</a> (Apache 2.0). {anon}</span><span>by <a href="https://vortas.io">Vortas</a></span></div></footer>
{scripts}</body>
</html>
"""
    with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f:
        f.write(doc)


def src_link(rel, text=None):
    url = (TREE if not os.path.splitext(rel)[1] else BLOB) + rel
    return f'<a href="{esc(url)}"><code>{esc(text or rel)}</code></a>'


# ---------------------------------------------------------------- data

def load():
    D = {}
    D["bakeoff"] = J(INPUTS["bakeoff"])
    D["live"] = J(INPUTS["live"])
    D["degrade"] = J(INPUTS["degrade"])
    D["shoot1"] = J(INPUTS["shoot1"])
    D["shoot2"] = J(INPUTS["shoot2"])
    D["sizes"] = J(INPUTS["sizes"])
    D["voices"] = J(INPUTS["voices"])
    D["judge"] = J(INPUTS["judge"])
    with open(os.path.join(ROOT, INPUTS["langs"]), "rb") as f:
        D["langs"] = tomllib.load(f)
    rows = {}
    with open(os.path.join(ROOT, INPUTS["htmt"]), encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^(gold|omnilingual)__(\S+)\s+fully correct (\d+)%\s+mean (\d+)%\s+critical (\d+)", line)
            if m:
                rows.setdefault(m.group(2), {})[m.group(1)] = {
                    "full": int(m.group(3)) / 100, "mean": int(m.group(4)) / 100, "critical": int(m.group(5))}
    D["htmt"] = rows
    return D


GROUPS1 = {
    "Into English (6 directions)": ["syn:ja-en", "syn:zh-en", "syn:km-en", "real:ja-en", "real:km-en", "real:fr-en"],
    "Out of English (11)": [f"syn:en-{t}" for t in ["ja", "zh", "km", "es", "fr", "ru", "de", "uk"]]
    + ["real:en-ja", "real:en-km", "real:en-fr"],
    "Lao, both ways (4)": ["syn:en-lo", "syn:lo-en", "real:en-lo", "real:lo-en"],
    "Haitian Creole, both ways (4)": ["syn:en-ht", "syn:ht-en", "real:en-ht", "real:ht-en"],
}
SYS1 = ["hymt2-7b-nf4", "madlad-7b-int8", "translategemma-12b", "azure-translator",
        "gemini-3.5-flash@medium", "gemini-3.5-flash", "foundry-gpt-5.6-sol@low"]


def shootout1(D):
    """Round 1 group means as shootout.py computes them (mean of direction scores,
    total critical), plus the open stack's route (Hy-MT2 where it runs, else MADLAD)."""
    dirs = D["shoot1"]["directions"]
    res = {}
    for s in SYS1 + ["stack-route"]:
        res[s] = {}
        for g, ds in list(GROUPS1.items()) + [("All 25 directions", list(dirs))]:
            xs = []
            for d in ds:
                sy = dirs[d]["systems"]
                if s == "stack-route":
                    xs.append(sy.get("hymt2-7b-nf4") or sy["madlad-7b-int8"])
                elif s in sy:
                    xs.append(sy[s])
                else:
                    xs = None
                    break
            if xs:
                res[s][g] = {"score": st.mean(x["score"] for x in xs), "critical": sum(x["critical"] for x in xs)}
        meds = []
        for d in dirs.values():
            x = d["systems"].get("hymt2-7b-nf4") or d["systems"]["madlad-7b-int8"] if s == "stack-route" else d["systems"].get(s)
            if x:
                meds.append(x["median_gpu_s"] if x.get("median_gpu_s") is not None else x["median_s"])
        res[s]["latency"] = st.median(meds)
    return res


def kind_cls(key):
    return "c1" if is_cloud(key) else "c3"


KIND_LEGEND = [("Cloud service", "c1"), ("Open weights", "c3")]


# ---------------------------------------------------------------- pages

def build_home(D, S1):
    E = sept_e2e_summary(D)
    all25 = "All 25 directions"
    rows = []
    for s in SYS1[1:] + ["stack-route"]:
        g = S1[s].get(all25)
        rows.append({"label": L(s), "value": g["score"], "cls": kind_cls(s), "hl": s == "stack-route",
                     "extra": f'{g["critical"]} critical errors', "s": s})
    rows.sort(key=lambda r: -r["value"])
    chart = hbar("Translation quality over 25 language directions",
                 f"Share of grading points (0–3 per sentence), same transcripts for every translator. "
                 f"Blind, side by side, one grading round by {L('grader')}. Higher is better.",
                 rows, maxv=1, legend=KIND_LEGEND, vendor_named=True,
                 table_headers=["Translator", "Score", "Critical errors", "Median s / sentence"],
                 table_rows=[[r["label"], pct(r["value"], 0), S1[r["s"]][all25]["critical"], f'{S1[r["s"]]["latency"]:.2f}'] for r in rows],
                 note="Open stack route = Hy-MT2 where it has the language, MADLAD for Lao and Haitian Creole.")
    live = {(r["system"], r["lang"], r["mode"]): r for r in D["live"]["runs"]}
    hcer = D["live"]["haitian_reference_cer"]["Meta Omnilingual ASR (open stack, live)"]
    sol = S1["foundry-gpt-5.6-sol@low"][all25]["score"]
    route = S1["stack-route"][all25]["score"]
    dg = degrade_means(D)[0]
    sw = D["sizes"]["endpointing_sweep"]["runs"][1]["rows"]
    lo_old = next(r for r in sw if r["lang"] == "lo" and r["endpoint_ms"] == 300 and r["max_s"] == 6.0)["cer"]
    lo_new = next(r for r in sw if r["lang"] == "lo" and r["endpoint_ms"] == 700 and r["max_s"] == 15.0)["cer"]
    body = f"""
<div class="prose">
<h1>Live speech translation on hardware you control</h1>
<p class="lede">Translation Open Stack is an open-source server: a client streams microphone audio in and gets back captions and spoken translation for every language its listeners need, in 25 languages, from open-weight models on one GPU. This site publishes what we measured in September and October 2026 while choosing how to hear, translate and voice live speech — including where the open models fall short.</p>
</div>
<section class="stats" aria-label="Headline numbers">
<div class="stat"><div class="n">{pct(hcer)}</div><div class="t">characters wrong: Omnilingual ASR hearing real Haitian Creole speakers, live</div></div>
<div class="stat"><div class="n">{pct(route, 0)}</div><div class="t">translation score for the open stack's own translators over 25 directions ({pct(sol, 0)} for the best cloud LLM)</div></div>
<div class="stat"><div class="n">+{dg['revnoise10'][0]:.0f} to +{dg['revnoise10'][1]:.0f}</div><div class="t">points of character error added by a room microphone — the biggest single factor</div></div>
<div class="stat"><div class="n">{pct(lo_old, 0)} → {pct(lo_new, 0)}</div><div class="t">Lao character error when live sentence cutting waits 0.7 s instead of 0.3 s</div></div>
</section>
{chart}
<div class="prose">
<h2>What we found</h2>
<ul>
<li><strong>Hearing decides most of it.</strong> A translator can only be as good as the transcript it gets. Lao and Khmer are the weak spots for every live recogniser we tried. <a href="findings.html#hearing">Speech recognition by language</a></li>
<li><strong>The open translator (Hy-MT2) beats a commercial translation API into English, but trails the cloud LLMs by about 15 points.</strong> LLMs repair recognition errors from context; dedicated translators translate them literally. <a href="findings.html#translation">Translation</a></li>
<li><strong>Open reasoning LLMs did not close the gap</strong> on one GPU. <a href="findings.html#open-llms">Round 2</a></li>
<li><strong>A bigger Omnilingual model is not better for Haitian Creole</strong>; the 7B card helps Lao. <a href="findings.html#sizes">Model sizes</a></li>
<li><strong>When to cut a sentence matters more than the model</strong> for live recognition. <a href="findings.html#endpointing">Endpointing</a></li>
<li><strong>Feed recognition from a sound board or a close mic.</strong> Compression barely matters; distance and noise do. <a href="findings.html#audio">Audio quality</a></li>
<li><strong>Per language (September):</strong> the open stack beat {L('sept:gemini-live')} end to end in {E['wins']} of {E['n']} directions ({pct(E['stack'], 0)} against {pct(E['gl'], 0)}, mean over all {E['n']}); every language's recognition, translation and voice scores, and which ones the commercial edition can still voice. <a href="languages.html">Languages</a></li>
<li><strong>Latency, labelled:</strong> the open stack's first translated audio about 0.8 s after the speaker stops; a cloud recogniser feeding a cloud voice about 1.3 s after each sentence ends; and what each other delay measures. <a href="latency.html">Latency</a></li>
<li><strong>Haitian Creole voices:</strong> hear the seven voices we compared. <a href="voices.html">Voices</a></li>
</ul>

<h2>Run it</h2>
<p>Three ways, same code and protocol: your own 48 GB NVIDIA GPU with Docker; your own Linux machine without Docker (NVIDIA or AMD); or a rented RunPod GPU from the published template. Quick start with Docker:</p>
<pre><code>git clone {REPO_URL}.git
cd translation-open-stack
cp .env.example .env            # set STACK_TOKEN (openssl rand -hex 32)
docker compose up -d --build    # first start downloads and builds the models
curl http://localhost:8790/health</code></pre>
<p>Then point a client at <code>ws://&lt;host&gt;:8790</code> with the token as its key. Full steps: the <a href="{BLOB}docs/user-guide.md">user guide</a>; the wire format: <a href="{BLOB}docs/dev/protocol.md">protocol</a>. The code is Apache 2.0; the models keep their own licences, and some are non-commercial — see <a href="models.html">Models &amp; licences</a>.</p>
<p class="caveat">Cloud models change often. The October results were measured on 18–19 October 2026 (the September ones on 26–29 September) with the versions named on the <a href="methodology.html">methodology</a> page; treat vendor numbers as a snapshot, not a ranking that will hold.</p>
</div>
"""
    page("index.html", "Translation Open Stack Research",
         body, "What we measured choosing how to hear, translate and voice live speech with open models, October 2026.")


def degrade_means(D):
    c = {(r["recogniser"], r["cond"], r["lang"]): r["cer"] for r in D["degrade"]["runs"]}
    out = {}
    for cond in D["degrade"]["conditions"]:
        out[cond] = tuple(st.mean((c[(rec, cond, l)] - c[(rec, "clean", l)]) * 100 for l in langs)
                          for rec, langs in (("azure", ["en", "ja", "km", "lo"]), ("omni", ["en", "km", "lo", "ht"])))
    return out, c


def degrade_means_only(D):
    return degrade_means(D)[0]


def build_findings(D, S1):
    B = D["bakeoff"]
    runs = {(r["system"], r["lang"]): r for r in B["runs"]}
    live = {(r["system"], r["lang"], r["mode"]): r for r in D["live"]["runs"]}
    base = B["baselines_cer"]
    LANG = {"en": "English", "ja": "Japanese", "km": "Khmer", "lo": "Lao", "fr": "French", "ht": "Haitian Creole"}
    KLEG = [("Live (streaming)", "c1"), ("Batch / per sentence", "c2"), ("Open stack", "c3")]
    sections = []

    # ---- 1. hearing
    stt_charts = ""
    order = ["el-realtime", "el-realtime-vad05", "oai-live", "aai-stream", "el-scribe-v2", "aai-batch",
             "oai__gpt-transcribe", "oai__gpt-4o-transcribe", "oai__gpt-4o-mini-transcribe",
             "gem__gemini-3.1-pro-preview", "gem__gemini-3.8-flash"]
    for lang in ["en", "ja", "km", "lo"]:
        rows = [{"label": L("azure-speech"), "value": base["Azure Speech (live)"][lang], "cls": "c1", "kind": "live",
                 "lat": live[("azure-speech", lang, {"en": "en-US", "ja": "ja-JP", "km": "km-KH", "lo": "lo-LA"}[lang])]["sentence_latency_ms_median"]},
                {"label": L("gemini-3.5-transcribe-live"), "value": base["Google gemini-3.5-transcribe-live (live)"][lang], "cls": "c1", "kind": "live",
                 "lat": next((r["sentence_latency_ms_median"] for k, r in live.items() if k[0] == "gemini-3.5-transcribe-live" and k[1] == lang and k[2] != "auto"),
                             live.get(("gemini-3.5-transcribe-live", lang, "auto"), {}).get("sentence_latency_ms_median")),
                 "extra": "" if lang != "lo" else "auto language (no Lao code)"},
                {"label": SYSTEMS["omni"][0], "value": base["Omnilingual ASR (open stack, live)"][lang], "cls": "c3", "kind": "open",
                 "extra": "earlier sentence cutting (0.3 s : 6 s)", "lat": None}]
        for s in order:
            r = runs.get((s, lang))
            if not r:
                continue
            thai = (r.get("script") or {}).get("thai", 0) > 0.5
            ex = "wrote Thai script" if thai else ""
            if r.get("cer") is None:
                rows.append({"label": L(s), "value": None, "nav": "not offered", "cls": "c2", "kind": r["kind"], "lat": None})
                continue
            rows.append({"label": L(s), "value": r["cer"], "cls": "c1" if r["kind"] == "live" else "c2", "kind": r["kind"], "extra": ex,
                         "lat": r.get("sentence_latency_ms_median") or r.get("request_ms_median")})
        rows.sort(key=lambda r: (r["value"] is None, r["value"] if r["value"] is not None else 0))
        for r in rows:
            r["hl"] = r["label"] == L("azure-speech")
        trows = [[r["label"] + (f' ({r["extra"]})' if r.get("extra") else ""), r["kind"],
                  pct(r["value"]) if r["value"] is not None else r.get("nav", "n/a"),
                  f'{r["lat"] / 1000:.1f}' if r.get("lat") else "–"] for r in rows]
        stt_charts += hbar(f"{LANG[lang]}: character error rate by recogniser",
                           "30 FLEURS sentences read by native speakers. Lower is better. Live = streamed at real-time pace.",
                           rows, maxv=None, cap=0.6, legend=KLEG, vendor_named=True,
                           table_headers=["Recogniser", "Mode", "CER", "Median s (live: after sentence end; batch: request)"],
                           table_rows=trows)
    # French and Haitian Creole
    fr_rows = [{"label": L("gemini-3.5-transcribe-live"), "value": live[("gemini-3.5-transcribe-live", "fr", "fr-FR")]["cer"], "cls": "c1", "extra": "fr-FR"},
               {"label": L("gemini-3.5-transcribe-live"), "value": live[("gemini-3.5-transcribe-live", "fr", "auto")]["cer"], "cls": "c1", "extra": "auto language"},
               {"label": L("azure-speech"), "value": live[("azure-speech", "fr", "fr-FR")]["cer"], "cls": "c1", "extra": "fr-FR", "hl": True}]
    stt_charts += hbar("French: character error rate, live", "30 FLEURS sentences. Lower is better.", fr_rows,
                       maxv=0.1, legend=[("Live (streaming)", "c1")], vendor_named=True)
    href = D["live"]["haitian_reference_cer"]
    ht_rows = [
        {"label": SYSTEMS["omni"][0], "value": href["Meta Omnilingual ASR (open stack, live)"], "cls": "c3", "hl": True},
        {"label": L("ht:gemini-2.5-pro"), "value": href["gemini-2.5-pro (batch, per sentence)"], "cls": "c2"},
        {"label": L("gemini-3.5-transcribe-live"), "value": live[("gemini-3.5-transcribe-live", "ht", "ht-HT")]["cer"], "cls": "c1", "extra": "told ht-HT"},
        {"label": L("gemini-3.5-transcribe-live"), "value": live[("gemini-3.5-transcribe-live", "ht", "auto")]["cer"], "cls": "c1", "extra": "auto language: writes French"},
        {"label": L("ht:gemini-2.5-flash"), "value": href["gemini-2.5-flash (batch, per sentence)"], "cls": "c2"},
        {"label": L("ht:gladia"), "value": href["Gladia Solaria-1 (live)"], "cls": "c1"},
        {"label": L("ht:gemini-live"), "value": href["Gemini Live (its input transcript)"], "cls": "c1"},
        {"label": L("ht:chirp3"), "value": href["Google Chirp 3, auto language (batch, per sentence)"], "cls": "c2"},
        {"label": L("azure-speech"), "value": None, "nav": "no locale", "cls": "c1"},
    ]
    ht_rows.sort(key=lambda r: (r["value"] is None, r["value"] or 0))
    stt_charts += hbar("Haitian Creole: character error rate",
                       "30 sentences from 30 native speakers (CMU Haitian Creole speech). Lower is better.",
                       ht_rows, cap=0.6, legend=KLEG, vendor_named=True)
    sections.append(f"""
<h2 id="hearing">1. Speech recognition by language</h2>
<div class="prose">
<p>Character error rate (CER): the share of reference characters a recogniser got wrong (edits ÷ reference length). Each language is one ~6-minute clip of 30 read sentences. Bold = the live recogniser the selected route uses.</p>
<ul>
<li><strong>Nothing streams Lao well.</strong> The best Lao score is a slow per-sentence LLM ({L('gem__gemini-3.1-pro-preview')}, {pct(runs[('gem__gemini-3.1-pro-preview','lo')]['cer'])} at a median {runs[('gem__gemini-3.1-pro-preview','lo')]['request_ms_median']/1000:.0f} s a sentence). Several recognisers write Lao in Thai script.</li>
<li><strong>Khmer:</strong> the best is batch ({L('el-scribe-v2')}, {pct(runs[('el-scribe-v2','km')]['cer'])}); live, {L('gemini-3.5-transcribe-live')} told <code>km-KH</code> scores {pct(live[('gemini-3.5-transcribe-live','km','km-KH')]['cer'])} against {pct(base['Azure Speech (live)']['km'])}.</li>
<li><strong>Haitian Creole:</strong> the open Omnilingual model is the best live recogniser ({pct(href['Meta Omnilingual ASR (open stack, live)'])}). A cloud recogniser left on automatic language detection writes the speakers down as French ({pct(live[('gemini-3.5-transcribe-live','ht','auto')]['cer'])}); given the code it scores {pct(live[('gemini-3.5-transcribe-live','ht','ht-HT')]['cer'])}.</li>
<li>The Omnilingual numbers for English, Japanese, Khmer and Lao below come from the service's earlier sentence cutting; <a href="#endpointing">section 5</a> shows how much the newer cutting recovers.</li>
</ul>
</div>
{stt_charts}
""")

    # ---- 2. translation
    t_charts = ""
    for g in GROUPS1:
        rows = []
        for s in SYS1:
            v = S1[s].get(g)
            rows.append({"label": L(s), "value": v["score"] if v else None, "nav": "n/a" if not v else "",
                         "cls": kind_cls(s), "extra": f'{v["critical"]} critical' if v else "lacks the language", "hl": s == "hymt2-7b-nf4"})
        rows.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0)))
        t_charts += hbar(g, "Mean score over the directions; critical errors summed. Higher is better.", rows, maxv=1,
                         legend=KIND_LEGEND, vendor_named=True)
    sc = []
    for s in SYS1 + ["stack-route"]:
        if s == "hymt2-7b-nf4":
            continue
        g = S1[s]["All 25 directions"]
        sc.append({"x": S1[s]["latency"], "y": g["score"], "label": L(s), "cls": kind_cls(s), "s": s})
    short = {"madlad-7b-int8": "MADLAD", "translategemma-12b": "TranslateGemma 12B", "azure-translator": L("azure-translator"),
             "gemini-3.5-flash@medium": L("gemini-3.5-flash@medium"), "gemini-3.5-flash": L("gemini-3.5-flash"),
             "foundry-gpt-5.6-sol@low": L("foundry-gpt-5.6-sol@low"), "stack-route": "Open stack route"}
    for p in sc:
        p["short"] = short[p["s"]] if not ANON or not is_cloud(p["s"]) else short[p["s"]]
        if p["s"] == "foundry-gpt-5.6-sol@low":
            p["anchor"] = "end"
        if p["s"] == "gemini-3.5-flash":
            p["dy"] = 12
        if p["s"] == "gemini-3.5-flash@medium":
            p["dy"] = -10
    if not ANON:
        for p in sc:
            p["short"] = {"gemini-3.5-flash@medium": "Flash, medium", "gemini-3.5-flash": "Flash, default",
                          "foundry-gpt-5.6-sol@low": "GPT-5.6-sol", "azure-translator": "Azure Translator"}.get(p["s"], p["short"])
    else:
        for p in sc:
            if is_cloud(p["s"]):
                p["short"] = L(p["s"]).replace(", thinking", ",").replace("reasoning ", "")
    scat = scatter("Quality against speed, 25 directions",
                   "Each translator's score against its median time per sentence (log scale). Up and left is better.",
                   sc, xlabel="Median seconds per sentence", ylabel="Score", xticks=(0.1, 0.3, 1, 3, 10),
                   yticks=(0.5, 0.6, 0.7, 0.8, 0.9), xfmt=lambda v: f"{v:g} s", yfmt=lambda v: pct(v, 0),
                   vendor_named=True, legend=KIND_LEGEND,
                   note="Open models: GPU time on one RTX 6000 Ada, one sentence at a time. Cloud APIs: round trip from a client in the US.")
    hm = D["htmt"]
    keys = ["foundry-gpt-5.6-sol@low", "gemini-3.5-flash@medium", "gemini-3.5-flash", "gpt-5.5@low", "gemini-3.5-flash@low",
            "foundry-gpt-5.6-luna@low", "gpt-5.4-mini@low", "gemma-4-31b", "gpt-4.1", "google-translate",
            "foundry-deepseek-v4.1-flash", "nllb-200-3.3b", "translategemma-27b", "azure-translator",
            "foundry-mistral-large-3", "kreyol-mt"]
    groups = [(L("mt:" + k), [hm[k]["omnilingual"]["mean"], hm[k]["gold"]["mean"]], k == "foundry-gpt-5.6-sol@low") for k in keys if k in hm]
    htc = grouped("Haitian Creole → English: from a live transcript vs from the read text",
                  "30 real-speaker sentences. Mean score, higher is better. One blind grading round.",
                  groups, [("From Omnilingual's live transcript", "c1"), ("From the text the speaker read", "c4")], maxv=1,
                  vendor_named=True)
    r2 = D["shoot2"]
    r2rows = []
    for s, v in r2["overall"].items():
        r2rows.append({"label": L(s), "value": v["score"], "cls": kind_cls(s), "extra": f'{v["critical"]} critical'})
    r2rows.sort(key=lambda r: -r["value"])
    r2lat = r2["latency"]
    r2c = hbar("Round 2: open reasoning LLMs, all 25 directions",
               "A separate blind grading round (scores not comparable with round 1). Higher is better.",
               r2rows, maxv=1, legend=KIND_LEGEND, vendor_named=True,
               table_headers=["Translator", "Score", "Critical", "Median s over directions", "Single stream median s"],
               table_rows=[[L(s), pct(v["score"], 0), v["critical"], r2lat[s]["median_over_directions_s"],
                            r2lat[s].get("single_stream", {}).get("median_s", "–")] for s, v in sorted(r2["overall"].items(), key=lambda kv: -kv[1]["score"])],
               note="Hy-MT2 has no overall score here: it lacks Lao and Haitian Creole. Open models ran on one H100 80 GB with vLLM 0.31.0.")
    sol = S1["foundry-gpt-5.6-sol@low"]
    hy = S1["hymt2-7b-nf4"]
    az = S1["azure-translator"]
    sections.append(f"""
<h2 id="translation">2. Translation quality</h2>
<div class="prose">
<p>Seven translators received <strong>identical sentence text</strong> — the cloud recogniser's transcripts of real and synthetic speech (Omnilingual's for Haitian Creole speakers) — and all 25 directions were graded blind, side by side, in one round. Score = share of 0–3 points per sentence; a <em>critical</em> error is a wrong number, time, dose, negation or who-did-what.</p>
<ul>
<li>Into English, Hy-MT2 scores {pct(hy['Into English (6 directions)']['score'],0)} against {pct(az['Into English (6 directions)']['score'],0)} for {L('azure-translator')}, but the LLMs reach {pct(S1['gemini-3.5-flash@medium']['Into English (6 directions)']['score'],0)}–{pct(sol['Into English (6 directions)']['score'],0)}.</li>
<li>Out of English, Hy-MT2 and {L('azure-translator')} are close ({pct(hy['Out of English (11)']['score'],0)} vs {pct(az['Out of English (11)']['score'],0)}).</li>
<li>For Lao and Haitian Creole only the two LLMs are usable from these transcripts. Hy-MT2 does not cover them; MADLAD stands in.</li>
</ul>
</div>
{t_charts}
{scat}
<div class="prose">
<h3>Haitian Creole: why the LLMs win</h3>
<p>From the clean read text the open models do reasonably; from a live transcript with recognition errors they lose most of it, because they translate the errors literally. The large LLMs repair them from context.</p>
</div>
{htc}
<h3 id="open-llms">Open reasoning LLMs (round 2)</h3>
<div class="prose"><p>Could an open reasoning LLM on the stack's GPU replace Hy-MT2 and MADLAD? Four ran on round 1's inputs and were graded blind beside saved outputs of the cloud LLMs and the stack's translators. None came close; the one that runs fast enough (gpt-oss-120b at low effort, {r2lat['gpt-oss-120b@low']['single_stream']['median_s']} s a sentence) needs more memory than the stack's card.</p></div>
{r2c}
""")

    # ---- 3. model sizes
    runs_s = {r["card"]: r for r in D["sizes"]["runs"]}
    cards = ["omniASR_LLM_300M", "omniASR_LLM_1B", "omniASR_LLM_3B", "omniASR_LLM_7B",
             "omniASR_LLM_300M_v2", "omniASR_LLM_1B_v2", "omniASR_LLM_3B_v2", "omniASR_LLM_7B_v2"]
    lg = [("Haitian Creole", "c1"), ("Khmer", "c2"), ("Lao", "c3")]
    groups = [(c.replace("omniASR_", "").replace("_", " "), [runs_s[c]["cer"][l] for l in ("ht", "km", "lo")], c == "omniASR_LLM_300M") for c in cards]
    sz = grouped("Omnilingual ASR: character error by model card",
                 "Zero-shot, 30 real-voice sentences per language, cut per sentence. Lower is better.",
                 groups, lg, maxv=0.2, vendor_named=False,
                 note=f"{esc(D['sizes']['gpu_note'])}. {esc(D['sizes']['package'])}.")
    allcards = sorted(D["sizes"]["runs"], key=lambda r: (r["card"].split("_")[1], r["params_m"], r["card"]))
    tbl = _table(["Card", "Params (M)", "Peak GB, batch 1", "Real-time factor, batch 1", "ht", "km", "lo"],
                 [[r["card"].replace("omniASR_", ""), f'{r["params_m"]:.0f}', f'{r["mem_peak_batch1_gb"]:.1f}', f'{r["rtf_batch1"]:.4f}',
                   pct(r["cer"]["ht"]), pct(r["cer"]["km"]), pct(r["cer"]["lo"])] for r in allcards])
    l3, l7 = runs_s["omniASR_LLM_300M"], runs_s["omniASR_LLM_7B"]
    sections.append(f"""
<h2 id="sizes">3. Model sizes: 300M vs 7B</h2>
<div class="prose">
<p>Meta's Omnilingual ASR comes in CTC and LLM-decoder cards from 300M to 7B encoders, and a v2 series. The stack ships the LLM 300M card.</p>
<ul>
<li><strong>Haitian Creole:</strong> 7B is no better than 300M ({pct(l7['cer']['ht'])} vs {pct(l3['cer']['ht'])}). The v2 cards drift Haitian Creole towards French spelling.</li>
<li><strong>Lao:</strong> 7B is clearly better ({pct(l7['cer']['lo'])} vs {pct(l3['cer']['lo'])}), but on fragments under about a second it can repeat one syllable many times, so it needs a repetition guard.</li>
<li><strong>Cost:</strong> peak memory {l3['mem_peak_batch1_gb']:.1f} GB (300M) vs {l7['mem_peak_batch1_gb']:.1f} GB (7B) at batch 1; at batch 16 the range is 5.5 to 17.4 GB; all fit a 24 GB L4 beside the language-ID and voice-detection models.</li>
<li><strong>Batching:</strong> decoding the waiting utterances of all connections together, with prompts left-padded so they end together, took one L4 from about 4 to 8–10 fully transcribed streams with the same CER (omni-stt, <a href="{REPO_URL}/pull/18">PR #18</a>).</li>
</ul>
</div>
{sz}
<details class="data"><summary>Every card: size, memory, speed and error</summary>{tbl}<p class="note">Real-time factor = processing seconds per audio second on the measurement GPU (lower is faster). The decoder is the same ~1.3 B parameters in every LLM card; only the encoder grows.</p></details>
""")

    # ---- 4/5. endpointing
    sw = D["sizes"]["endpointing_sweep"]
    lev = next(r for r in sw["runs"] if "levelled" in r["run"] and "300M" in r["card"])
    settings = [(300, 6.0), (300, 15.0), (500, 15.0), (700, 15.0), (800, 25.0)]

    def cell(lang, e, m):
        return next(r for r in lev["rows"] if r["lang"] == lang and r["endpoint_ms"] == e and r["max_s"] == m)
    xc = [f"{e / 1000:g} s : {m:g} s" + ("\n(old)" if (e, m) == (300, 6.0) else "\n(now)" if (e, m) == (700, 15.0) else "") for e, m in settings]
    ser = [(LANG[l], c, [cell(l, e, m)["cer"] for e, m in settings]) for l, c in (("lo", "c3"), ("km", "c2"), ("en", "c4"), ("ht", "c1"))]
    waits = [cell("ht", e, m)["seg_wait_ms_median"] for e, m in settings]
    endc = lines("Live sentence cutting: pause to wait : longest sentence",
                 "Omnilingual LLM 300M through the service's own segmenter, full clips, levelled input. Lower is better.",
                 xc, ser, ylabel="Character error", yticks=(0, 0.1, 0.2, 0.3, 0.4), yfmt=lambda v: pct(v, 0),
                 table_headers=["Setting", "Haitian Creole", "Khmer", "Lao", "English", "Mid-sentence cuts (ht)", "Wait after speech, ms"],
                 table_rows=[[x.replace("\n", " "), pct(cell("ht", e, m)["cer"]), pct(cell("km", e, m)["cer"]), pct(cell("lo", e, m)["cer"]),
                              pct(cell("en", e, m)["cer"]), cell("ht", e, m)["mid_cuts"], w] for x, (e, m), w in zip(xc, settings, waits)],
                 note=f"GPU: {esc(sw['gpu'])}. Wait after speech ends: " + ", ".join(f"{x.split(chr(10))[0]} → {w} ms" for x, w in zip(xc, waits)) + ".")
    sections.append(f"""
<h2 id="endpointing">4. Endpointing: when to cut a sentence</h2>
<div class="prose">
<p>A live recogniser has to decide when a sentence has ended. The service used to cut after a 0.3 s pause and force a cut at 6 s, which chopped many sentences in half. Waiting 0.7 s and allowing up to 15 s cut Lao's error from {pct(cell('lo',300,6.0)['cer'],1)} to {pct(cell('lo',700,15.0)['cer'],1)} and Haitian Creole's from {pct(cell('ht',300,6.0)['cer'],1)} to {pct(cell('ht',700,15.0)['cer'],1)}. The cost is about 0.4 s more wait per turn, and up to 15 s before text if a speaker never pauses.</p>
<p class="note">Very quiet input (peaks below about −30 to −40 dBFS) is never heard by the voice detector and is dropped whole; the chart uses input levelled as a microphone with automatic gain would deliver it.</p>
</div>
{endc}
""")

    # ---- 6. audio quality
    means, c = degrade_means(D)
    conds = D["degrade"]["conditions"]
    order = ["revnoise10", "revnoise10_rnn", "revnoise10_afftdn", "revnoise10_hpnorm", "noise5", "noise10", "reverb",
             "hfp_nb", "opus12", "hfp_wb", "opus24"]
    groups = [(conds[k], [means[k][0], means[k][1]], k == "revnoise10") for k in order]
    dgc = grouped("Added character error by audio condition",
                  "Mean change from clean, in percentage points, over four languages per recogniser. Lower is better.",
                  groups, [(L("azure-speech"), "c1"), ("Omnilingual ASR 300M", "c3")], fmt=lambda v: f"{v:+.1f}",
                  maxv=60, vendor_named=True,
                  note="Negative changes are drawn as zero-length bars. Synthetic room impulse response (RT60 1.5 s) and a seeded HVAC + babble noise mix; one run per cell.")
    sections.append(f"""
<h2 id="audio">5. Audio quality</h2>
<div class="prose">
<p>The same clean clips were put through simulated conditions and streamed in real time. Mostly, whole sentences vanish silently rather than words getting garbled.</p>
<ul>
<li><strong>The room hurts most, the codec least.</strong> A room mic (reverb plus 10 dB noise) adds {means['revnoise10'][0]:.0f} / {means['revnoise10'][1]:.0f} points; Opus at 24 kbit/s adds {means['opus24'][0]:.1f} / {means['opus24'][1]:.1f}.</li>
<li><strong>Cleanup does not rescue a room mic.</strong> Denoisers hurt the cloud recogniser and help Omnilingual a little; gain normalisation is safe.</li>
<li><strong>Bluetooth:</strong> wideband hands-free costs about a point; narrowband (8 kHz) costs {means['hfp_nb'][0]:.0f} / {means['hfp_nb'][1]:.1f}.</li>
<li><strong>Practical advice:</strong> take a sound-board feed or a close mic.</li>
</ul>
</div>
{dgc}
""")

    # ---- selected setup
    sections.append(f"""
<h2 id="selected">6. Selected setup (19 October 2026)</h2>
<div class="prose">
<p>For a live service where privacy terms allowed a cloud route: {L('azure-speech')} (streaming) → {L('foundry-gpt-5.6-sol@low')} → a neural cloud voice for every language except Haitian Creole, which goes Omnilingual 300M → the same LLM → {L('v:gemini-flash')} (see <a href="voices.html">Voices</a>). Lao is the weak spot: no recogniser we can stream does it well yet.</p>
<p>For a fully private deployment, the open stack itself: Whisper or Omnilingual to hear, Hy-MT2 (else MADLAD) to translate, Kokoro, Piper or VoxCPM2 to speak — on one GPU, with no audio leaving the machine.</p>
</div>
""")

    toc = """<ul class="toc"><li><a href="#hearing">Speech recognition</a></li><li><a href="#translation">Translation</a></li><li><a href="#sizes">Model sizes</a></li><li><a href="#endpointing">Endpointing</a></li><li><a href="#audio">Audio quality</a></li><li><a href="#selected">Selected setup</a></li></ul>"""
    body = f"""<div class="prose"><h1>Findings, October 2026</h1>
<p class="lede">Speech recognition by language and provider, translation quality, model size, sentence cutting and audio quality. Every chart has its data table; numbers come from the result files in <a href="{TREE}eval">eval/</a>.</p>
<p class="caveat">Grades come from one blind LLM grader per round and move 5–10 points between rounds: compare numbers inside one chart only. Cloud models change; these are 18–19 October 2026 results.</p>
{toc}</div>""" + "".join(sections)
    page("findings.html", "Findings", body, "Speech recognition, translation, model size, endpointing and audio-quality results, October 2026.")


def build_voices(D):
    sc = D["voices"]
    meta = {"gemini-flash": "Cloud voice", "gemini-lite": "Cloud voice", "oai-coral": "Cloud voice",
            "oai-coral-instr": "Cloud voice, accent instruction", "oai-sage-instr": "Cloud voice, accent instruction",
            "coqui": "Open weights, CC-BY-SA 4.0", "mms": "Open weights, CC-BY-NC 4.0 (non-commercial)"}
    order = sorted(sc, key=lambda k: (-sc[k]["h"], -sc[k]["i"]))
    judged = {}
    for x in D["judge"]:
        judged.setdefault(x["v"], 0)
        if x.get("haitian_score") is not None:
            judged[x["v"]] += 1
    rows_h = [{"label": L("v:" + k), "value": sc[k]["h"], "cls": kind_cls("v:" + k), "hl": k == "gemini-flash"} for k in order]
    rows_i = [{"label": L("v:" + k), "value": sc[k]["i"], "cls": kind_cls("v:" + k), "hl": k == "gemini-flash"} for k in order]
    f1 = lambda v: f"{v:.1f}"
    ch = hbar("Sounds Haitian (1–5)", f"Mean over six sentences, judged blind by {L('grader')} with audio in. 1 = French accent. Higher is better.",
              rows_h, fmt=f1, maxv=5, legend=KIND_LEGEND, vendor_named=True)
    ci = hbar("Clear (1–5)", "Mean intelligibility over the same six sentences. Higher is better.", rows_i, fmt=f1, maxv=5,
              legend=KIND_LEGEND, vendor_named=True)
    # sentences: judge.json texts by index
    texts = {}
    for x in D["judge"]:
        texts.setdefault(x["i"], x["text"])
    sentences = [texts[i] for i in sorted(texts)]
    alias = {k: (f"voice-{n + 1}" if ANON else k) for n, k in enumerate(order)}
    vdata = {"audioBase": "audio/ht-voices/", "sentences": sentences,
             "voices": [{"file": alias[k], "name": L("v:" + k), "meta": meta[k] + f' · sounds Haitian {sc[k]["h"]:.1f}, clear {sc[k]["i"]:.1f}'} for k in order]}
    # copy audio
    dst = os.path.join(OUT, "audio", "ht-voices")
    os.makedirs(dst, exist_ok=True)
    src = os.path.join(ROOT, INPUTS["mp3"])
    for k in order:
        for i in range(len(sentences)):
            fn = f"{k}__{i}.mp3"
            if os.path.exists(os.path.join(src, fn)):
                shutil.copyfile(os.path.join(src, fn), os.path.join(dst, f"{alias[k]}__{i}.mp3"))
    per = _table(["Voice"] + [f"S{i + 1}" for i in range(len(sentences))],
                 [[L("v:" + k)] + [next((f'{x["haitian_score"]} / {x["intelligibility"]}' for x in D["judge"] if x["v"] == k and x["i"] == i and x.get("haitian_score") is not None), "–")
                                   for i in range(len(sentences))] for k in order])
    data_json = json.dumps(vdata, ensure_ascii=False).replace("</", "<\\/")
    body = f"""<div class="prose">
<h1>Haitian Creole voices</h1>
<p class="lede">Which text-to-speech voice sounds most like a native Haitian Creole speaker? Seven voices — cloud and open — read the same six sentences. Listen for yourself; the scores are one AI judge's view.</p>
</div>
<section class="hide-blind">
{ch}
{ci}
<details class="data"><summary>Per-sentence scores (sounds Haitian / clear)</summary>{per}<p class="note">A dash is a sample the judge did not score.</p></details>
</section>
<h2 id="listen">Listen</h2>
<div class="prose"><p>Pick a sentence, then play each voice. <strong>Blind mode</strong> shuffles the voices, hides their names and the scores above — try it before reading the charts.</p></div>
<div class="tools"><label><input type="checkbox" id="blind"> Blind mode</label></div>
<div class="picker" id="picker" role="group" aria-label="Sentence"></div>
<p class="sentence" id="sentence" lang="ht" aria-live="polite"></p>
<div class="vrows" id="vrows"></div>
<script type="application/json" id="voice-data">{data_json}</script>
<div class="prose">
<h2>What it shows</h2>
<ul>
<li>{L('v:gemini-flash')} led ({sc['gemini-flash']['h']:.1f} for sounding Haitian); its lighter sibling sounded more French ({sc['gemini-lite']['h']:.1f}).</li>
<li>The open voices, trained on Haitian Creole readers, were clear ({sc['coqui']['i']:.1f}–{sc['mms']['i']:.1f}) but not judged more Haitian; both drop digits (“600”).</li>
<li>An accent instruction did not help the cloud voice that accepts one.</li>
</ul>
<p class="caveat">Six sentences; a {vendor('google')} model judging, among others, a {vendor('google')} voice; an AI judge is not a Haitian listener. A native listener should confirm with blind mode.</p>
<h2>Sources and licences</h2>
<ul>
<li>Sentence text: CMU Haitian Creole speech data, © 2010 Language Technologies Institute, Carnegie Mellon University, used under its COPYING terms.</li>
<li>Samples from the open voices are output of <a href="https://huggingface.co/facebook/mms-tts-hat">Meta MMS-TTS</a> (CC-BY-NC 4.0, non-commercial) and <a href="https://huggingface.co/multilingual-tts/VITS-OpenBible-Haitian-Creole">Coqui VITS OpenBible</a> (CC-BY-SA 4.0).</li>
<li>Raw scores and scripts: {src_link('eval/2026-10-ht-voices')}.</li>
</ul>
</div>"""
    page("voices.html", "Haitian Creole Voices", body, "Seven Haitian Creole text-to-speech voices, blind-judged, with playable samples.",
         extra_head="<style>body.blind .hide-blind{display:none}</style>\n", scripts='<script src="voices.js"></script>\n')


def build_methodology(D):
    # The dataset's hub page sits under its publisher's organisation; an anonymised build links the paper instead.
    FLEURS_LINK = ('<a href="https://arxiv.org/abs/2205.12446">FLEURS dataset</a>' if ANON
                   else '<a href="https://huggingface.co/datasets/google/fleurs">google/fleurs</a>')
    s1 = D["shoot1"]
    r2 = D["shoot2"]
    sw = D["sizes"]["endpointing_sweep"]
    deg = D["degrade"]
    body = f"""<div class="prose">
<h1>Methodology</h1>
<p class="lede">What was measured, on what audio, how it was scored, and with which exact versions. Raw outputs and scripts are in <a href="{TREE}eval">eval/</a>.</p>

<h2>Datasets (public only)</h2>
<ul>
<li><strong>FLEURS</strong> ({FLEURS_LINK}, CC BY 4.0): native speakers reading the same 30 FLoRes sentences in English, Japanese, Khmer, Lao and French, one recording per sentence, alternating men and women. References are FLoRes's own professional translations. Audio is downloaded at run time and not stored in the repository.</li>
<li><strong>CMU Haitian Creole speech</strong> (speech.cs.cmu.edu/haitian; read by native speakers in 1997–98): 30 sentences from 30 speakers. CMU has no English, so the English references for translation grading were written once by {L('grader-old')} — a model-made reference. © 2010 Language Technologies Institute, Carnegie Mellon University, used under its COPYING terms.</li>
<li><strong>Synthetic set</strong>: 24 short sentences built to catch critical errors (times, doses, negations), read by synthetic voices; used in the translator comparison as the <code>syn:</code> directions.</li>
</ul>
<p>Each language's sentences are trimmed of silence and joined with 0.8 s pauses into one ~6-minute clip, streamed at real-time pace in 100 ms chunks for live systems. This is read speech: real voices and accents, not spontaneous speech or a large hall's echo (the <a href="findings.html#audio">audio-quality</a> test simulates that).</p>

<h2>Scoring</h2>
<ul>
<li><strong>Character error rate (CER)</strong>: edit distance between the joined reference and the joined transcript, divided by the reference length, after Unicode NFKC normalisation. Characters, not words, because Japanese, Khmer and Lao do not separate words with spaces. A sentence a system never returns counts as deleted. Known artefacts (all systems pay them): Latin names kept in the references but written in native script by good transcripts, numerals as words or native digits.</li>
<li><strong>Translation</strong>: 0–3 points per sentence against the English meaning (3 = fully correct and natural, 0 = wrong, garbled or missing), plus a <em>critical</em> flag for a wrong number, time, date, dose, amount, negation or who-did-what. Each direction is graded in one call with every translator's output shuffled under letters (blind, side by side). Score = share of the possible points; a group score is the mean of its directions. Grader: {L('grader')}, model id <code>{esc(s1['grader']) if not ANON else 'withheld'}</code>, rounds 1 and 2 graded separately.</li>
<li><strong>Voices</strong>: the judge model heard each sample (shuffled, names hidden) and scored “sounds Haitian” 1–5 and “clear” 1–5.</li>
<li><strong>Latency</strong>: live recognisers, median time from the end of each sentence's speech (found from the audio) to the first final covering it. Open translators, GPU time per sentence on the pod; cloud APIs, round trip from a client in the US.</li>
</ul>

<h2>Dates and versions</h2>
<div class="table-wrap"><table class="wide"><thead><tr><th>Test</th><th>Date</th><th>Versions and hardware</th></tr></thead><tbody>
<tr><th scope="row">September model evaluation</th><td>2026-09-26 to 09-29</td><td>24 synthetic-set sentences per direction, mostly synthetic speech; FLEURS for round-8 recognition. One RTX PRO 4500 Blackwell 32 GB (Romanian: RTX 6000 Ada). Grader {esc(L('grader-old'))}. See <a href="languages.html">Languages</a>.</td></tr>
<tr><th scope="row">Cloud routes, delay</th><td>2026-10-17</td><td>September's synthetic clips; delay = end of sentence to start of translated audio, median of 24. See <a href="latency.html">Latency</a>.</td></tr>
<tr><th scope="row">Recognition bake-off</th><td>{esc(D['bakeoff']['date'])}</td><td>Model names as on the chart labels. Cloud regions: US.</td></tr>
<tr><th scope="row">Audio conditions</th><td>{esc(deg['date'])}</td><td>{esc(L('azure-speech'))}; Omnilingual LLM 300M on a cloud L4 service. Room impulse response RT60 {deg['audio']['ir']['rt60_T20_s']} s (T20), DRR {deg['audio']['ir']['drr_db']} dB.</td></tr>
<tr><th scope="row">Translator round 1</th><td>2026-10-19</td><td>Hy-MT2 7B at revision <code>9b0eb4e8</code>, bitsandbytes NF4; MADLAD-400 7B at <code>1ff63ce7</code>, CTranslate2 int8, beam 4; TranslateGemma 12B bf16. One RTX 6000 Ada 48 GB. Cloud LLMs at temperature 0 or their reasoning setting as labelled.</td></tr>
<tr><th scope="row">Translator round 2</th><td>2026-10-19</td><td>gpt-oss-120b <code>b5c939de</code>, gpt-oss-20b <code>6cee5e81</code> (MXFP4), Qwen3.8-27B-FP8 <code>017b9c7a</code>; vLLM 0.31.0 on one H100 80 GB.</td></tr>
<tr><th scope="row">Omnilingual sizes</th><td>{esc(D['sizes']['date'])}</td><td>{esc(D['sizes']['package'])}. {esc(D['sizes']['gpu_note'])}.</td></tr>
<tr><th scope="row">Endpointing sweep</th><td>{esc(sw['date'])}</td><td>{esc(sw['service_ref'])}. {esc(sw['gpu'])}. Silero VAD at <code>5cd79456</code> (v6.2.3).</td></tr>
<tr><th scope="row">Haitian Creole voices</th><td>2026-10-19</td><td>Seven voices as labelled; open voices on CPU.</td></tr>
</tbody></table></div>

<h2>Caveats</h2>
<ul>
<li><strong>Snapshot.</strong> Results were measured in October 2026. Cloud models and their defaults change without notice; rerun before relying on a vendor comparison.</li>
<li><strong>One grader per round.</strong> LLM grades move 5–10 points between rounds; compare inside one chart only. The grader is from the same family as some graded systems and may favour them.</li>
<li><strong>Small samples.</strong> 24–30 sentences per direction; six sentences for voices. Single runs; run-to-run noise in CER was about half a point.</li>
<li><strong>Read speech.</strong> Real speakers, but reading. Conversation, crosstalk and halls will be worse (see audio conditions).</li>
<li><strong>Bounded by hearing.</strong> Translation scores for Lao and Khmer speakers are capped by what the recogniser heard, not by the translators alone.</li>
<li><strong>Model-made references</strong> for Haitian Creole → English.</li>
</ul>

<h2>Reproduce</h2>
<p>Some result files carry grader notes and transcripts the site never shows; <code>site/extract_derived.py</code> copies only their scores and delays into <code>site/data/derived.json</code>, which the build reads. Rerun it when those files change.</p>
<p>Each eval folder has a README with the commands and the environment variables it needs (API keys are never committed). Start at {src_link('eval/README.md')}; route summary: {src_link('docs/dev/route-findings-2026-10.md')}.</p>
</div>"""
    page("methodology.html", "Methodology", body, "Datasets, scoring, versions and caveats behind the October 2026 results.")


def build_models(D):
    langs = D["langs"]
    names = {"en": "English", "es": "Spanish", "fr": "French", "pt": "Portuguese", "it": "Italian", "de": "German", "ru": "Russian",
             "uk": "Ukrainian", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "vi": "Vietnamese", "ar": "Arabic", "fa": "Persian",
             "id": "Indonesian", "tr": "Turkish", "bn": "Bengali", "ur": "Urdu", "hi": "Hindi", "sw": "Swahili", "ro": "Romanian",
             "ht": "Haitian Creole", "km": "Khmer", "lo": "Lao", "tl": "Tagalog"}
    rows = []
    for code, v in langs.items():
        if code in ("models", "licence_review") or not isinstance(v, dict) or "asr" not in v:
            continue
        asr = "Omnilingual 300M" if v["asr"].startswith("omni") else "Whisper large-v3"
        tr = {"hymt": "Hy-MT2 7B", "madlad": "MADLAD-400 7B"}.get(v.get("translator"), v.get("translator", ""))
        voices = []
        if v.get("kokoro"): voices.append("Kokoro")
        if v.get("voxcpm"): voices.append("VoxCPM2")
        if v.get("piper"): voices.append(f"Piper ({piper_id(v['piper'])})")
        if v.get("mms"): voices.append("MMS-TTS")
        if v.get("coqui"): voices.append("Coqui OpenBible")
        com = v.get("commercial")
        comv = ""
        if isinstance(com, dict):
            cv = []
            if com.get("kokoro"): cv.append("Kokoro")
            if com.get("voxcpm"): cv.append("VoxCPM2")
            if com.get("piper"): cv.append(f"Piper ({piper_id(com['piper'])})")
            if com.get("espeak"): cv.append("eSpeak NG")
            comv = ", ".join(cv)
        rows.append([f"{names.get(code, code)} ({code})", asr, tr, ", ".join(voices), comv or "see licences.md"])
    lt = _table(["Language", "Hears", "Translates", "Speaks (non-profit edition)", "Commercial-edition voice override"], rows, numeric_from=99)
    comp = [
        ("Silero VAD", "Detect speech and sentence ends", "MIT", "Permissive", "Small, fast, pinned commit; its pauses drive the endpointing measured on the Findings page."),
        ("VoxLingua107 ECAPA", "Which language is spoken", "Apache 2.0", "Permissive", "107 languages in one small model."),
        ("Whisper large-v3 (faster-whisper)", "Recognition, most languages", "MIT", "Permissive", "Strong across the major languages; runs in CTranslate2."),
        ("Omnilingual ASR LLM 300M", "Recognition: Haitian Creole, Khmer, Lao, Swahili, Persian, Bengali, Urdu, Hindi", "Apache 2.0", "Permissive", "Best live Haitian Creole recogniser measured; the 7B card was no better for Haitian Creole at four times the memory."),
        ("Hy-MT2 7B (pinned revision, 4-bit)", "Translation, its 36 languages", "Apache 2.0", "Permissive", "Beat a commercial translation API into English; not under the Hunyuan Community Licence at the pinned revision."),
        ("MADLAD-400 7B (int8)", "Translation where Hy-MT2 has no language (ht, lo, sw, ro)", "Apache 2.0", "Permissive", "Wide coverage; weaker, so used only as the fallback."),
        ("Kokoro-82M", "Voices: en es fr it pt ja zh hi", "Apache 2.0", "Permissive", "Picked over Piper by ear; 24 kHz native, ~98× real time on a GPU."),
        ("VoxCPM2", "Voices: Khmer, Lao, Tagalog (and more in commercial)", "Apache 2.0", "Permissive", "Clearest tested for Khmer and Lao; one voice at a time per GPU, so kept for languages with nothing else."),
        ("Piper voices", "Voices: ~21 languages", "Per voice", "Mixed", "Each voice's training data sets its licence; several are non-commercial or unclear."),
        ("Coqui VITS OpenBible (Haitian Creole)", "Haitian Creole voice, commercial edition", "CC-BY-SA 4.0", "Attribution / share-alike", "Clear; licence-clean alternative to MMS."),
        ("Meta MMS-TTS", "Haitian Creole voice (non-profit); fallback for km lo tl", "CC-BY-NC 4.0", "Non-commercial", "Clearest open Haitian Creole voice; never loaded in the commercial edition."),
    ]
    ct = '<div class="table-wrap"><table class="wide"><thead><tr><th scope="col">Model</th><th scope="col">Used for</th><th scope="col">Licence</th><th scope="col">Class</th><th scope="col">Why it was chosen</th></tr></thead><tbody>'
    for m in comp:
        ct += f'<tr><th scope="row">{esc(m[0])}</th><td>{esc(m[1])}</td><td>{esc(m[2])}</td><td>{esc(m[3])}</td><td>{esc(m[4])}</td></tr>'
    ct += "</tbody></table></div>"
    body = f"""<div class="prose">
<h1>Models &amp; licences</h1>
<p class="lede">The stack's code is Apache 2.0. The models it downloads are not part of it and keep their own licences — some permissive, some with attribution or share-alike duties, and some non-commercial.</p>
<p class="caveat">Not legal advice. An engineering summary of {src_link('docs/licences.md')} (checked 29 September 2026 against the model cards and licence files). Upstream licences change; check the links before relying on this.</p>

<h2>Licence classes</h2>
<div class="table-wrap"><table class="wide"><thead><tr><th scope="col">Class</th><th scope="col">Examples</th><th scope="col">What it means here</th></tr></thead><tbody>
<tr><th scope="row">Permissive</th><td>MIT, Apache 2.0, BSD, CC0</td><td>Commercial use allowed; keep the licence and notices.</td></tr>
<tr><th scope="row">Attribution / share-alike</th><td>CC-BY, CC-BY-SA, MPL-2.0, GPL-3.0</td><td>Commercial use allowed with duties: credit the source; pass the same licence on when you distribute.</td></tr>
<tr><th scope="row">Non-commercial</th><td>CC-BY-NC, CC-BY-NC-SA, research-only datasets</td><td>Not for commercial use.</td></tr>
<tr><th scope="row">Restricted</th><td>Gemma terms, Tencent Hunyuan Community Licence</td><td>Territory exclusions, user caps or use policies. None is in the default stack.</td></tr>
<tr><th scope="row">Unclear</th><td>No licence declared; voices fine-tuned from data whose licence may carry over</td><td>Ask first.</td></tr>
</tbody></table></div>

<h2>Commercial vs non-profit edition</h2>
<p>Recognition and translation are identical in both editions and all permissive. Only the voices differ. <code>EDITION=commercial</code> is enforced in code: the licence of every model and voice is data (<code>server/licences.py</code>), and a commercial stack loads only permissive and attribution/share-alike items — never a non-commercial one, not even as a fallback — and an unclear one only after a recorded review. A language left with no allowed voice is text only. <code>python3 server/stack_config.py check --edition commercial</code> shows the result before anything loads.</p>

<h2>What runs, and why</h2>
</div>
{ct}
<div class="prose">
<h2>Per language</h2>
<p>From {src_link('languages.toml')}, as built into this site.</p>
</div>
{lt}
<div class="prose">
<h2>Evaluated but not deployed</h2>
<ul>
<li><strong>TranslateGemma 12B / 27B</strong> — Gemma Terms of Use (restricted). Close to Hy-MT2 where both run; much weaker in Khmer.</li>
<li><strong>NLLB-200 3.3B</strong> — CC-BY-NC 4.0 (non-commercial). Loops on noisy input and turns names into others.</li>
<li><strong>Omnilingual v2 and larger cards</strong> — Apache 2.0. Not better for Haitian Creole (see <a href="findings.html#sizes">model sizes</a>).</li>
<li><strong>gpt-oss-120b / 20b, Qwen3.8-27B</strong> — open reasoning LLMs; scored below the stack's own translators (<a href="findings.html#open-llms">round 2</a>). Check each model card's licence before use.</li>
<li><strong>Kreyòl-MT</strong> — MIT. Gets the gist of Haitian Creole but drifts in register, drops names, and sometimes loops.</li>
<li><strong>Coqui XTTS-v2, F5-TTS, Fish-Speech</strong> — non-commercial or research licences.</li>
</ul>
<p>Full list with links: {src_link('docs/licences.md')}.</p>
</div>"""
    page("models.html", "Models and Licences", body, "Why each model in the open stack was chosen, and what its licence allows.")


# ---------------------------------------------------------------- September evaluation + latency

LANG_NAMES = {"en": "English", "es": "Spanish", "fr": "French", "pt": "Portuguese", "it": "Italian", "de": "German",
              "ru": "Russian", "uk": "Ukrainian", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "vi": "Vietnamese",
              "ar": "Arabic", "fa": "Persian", "id": "Indonesian", "tr": "Turkish", "bn": "Bengali", "ur": "Urdu",
              "hi": "Hindi", "sw": "Swahili", "ro": "Romanian", "ht": "Haitian Creole", "km": "Khmer", "lo": "Lao",
              "tl": "Tagalog"}
SEPT_ROUND1 = ["es", "fr", "de", "pt", "ru", "uk", "zh", "ja", "km", "ht", "lo"]
SEPT_ROUND8 = ["ar", "hi", "vi", "ko", "tl", "fa", "id", "tr", "bn", "ur", "it", "sw"]
SEPT_ORDER = ["en"] + SEPT_ROUND1 + SEPT_ROUND8 + ["ro"]
PR18 = REPO_URL + "/pull/18"


def _ws(s):
    return re.sub(r"\s+", " ", s)


def cite(D, key, needle):
    """Fail the build if a document no longer says what the site quotes from it."""
    if _ws(needle) not in _ws(D["text"][key]):
        raise SystemExit(f"build: {INPUTS[key]} no longer contains {needle!r}; update site/build.py")
    return needle


def load_more(D):
    D["text"] = {}
    for k in ("sept_doc", "oct_doc", "htv_readme", "azg_readme", "omni_readme"):
        with open(os.path.join(ROOT, INPUTS[k]), encoding="utf-8") as f:
            D["text"][k] = f.read()
    for k in ("derived", "r6lao", "asr300", "nat", "voxspeed", "r8asr", "r8mt", "r8nat"):
        D[k] = J(INPUTS[k])
    p = os.path.join(ROOT, INPUTS["latency"])
    D["latency"] = J(INPUTS["latency"]) if os.path.isfile(p) else None
    # Which voices each edition runs, exactly as the server decides it.
    sys.path.insert(0, os.path.join(ROOT, "server"))
    import stack_config as sc
    toml = os.path.join(ROOT, INPUTS["langs"])
    table, _ = sc.load(toml)
    reviews = sc.load_reviews(toml)
    D["editions"] = {ed: sc.apply_edition(table, ed, reviews, unclear_ok=False)[1] for ed in ("nonprofit", "commercial")}
    D["hymt_langs"] = set(sc.HYMT_LANGS)
    D["table"] = table


def piper_id(value):
    """A Piper voice id, with the speaker part dropped when it names a cloud vendor in an anonymised build."""
    if ANON and "google" in value.lower():
        parts = value.split("-")
        return f"{parts[0]}, {parts[-1]} quality" if len(parts) >= 3 else parts[0]
    return value


def voice_label(name, value):
    if name == "kokoro":
        return f"Kokoro {value.split(':', 1)[1]}"
    if name == "piper":
        if ANON and "google" in value.lower():  # a voice id that names a cloud vendor
            return f"Piper ({value.split('_')[0]})"
        return "Piper " + value.split("-")[1] if value.count("-") >= 2 else f"Piper {value}"
    return {"voxcpm": "VoxCPM2", "mms": "MMS-TTS", "coqui": "Coqui OpenBible", "espeak": "eSpeak NG"}.get(name, name)


def voice_key(name, value):
    """The voice's key in the round-8 result files."""
    if name == "kokoro":
        return "kokoro-" + value.split(":", 1)[1]
    if name == "piper":
        return "piper-" + value
    return name


def sept_doc_clarity(D):
    """Round-trip error of each language's voice, from the table in section 3.4
    of the September document (only the document has these numbers)."""
    doc = D["text"]["sept_doc"]
    sec = doc.split("### 3.4 Voices", 1)[1].split("**VoxCPM2 speed.**", 1)[0]
    byname = {v: k for k, v in LANG_NAMES.items()}
    byname["Mandarin"] = "zh"
    out = {}
    for line in sec.splitlines():
        cells = [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] not in byname:
            continue
        cur = re.findall(r"([A-Za-z]+) (\d+(?:\.\d+)?)%", cells[2])
        vox = re.match(r"(\d+(?:\.\d+)?)%", cells[1])
        out[byname[cells[0]]] = {"voxcpm": float(vox.group(1)) / 100 if vox else None,
                                 "current": {e.lower(): float(p) / 100 for e, p in cur}}
    return out


def _pts(x):
    return x[0] / x[1] if x and x[1] else None


def sept_e2e_summary(D):
    """Round 3 end to end, recomputed from the raw result file: plain mean over every direction."""
    rows = [(d, _pts(v["stack_new"]), _pts(v["gemini_live"])) for d, v in D["derived"]["sept_e2e"].items()]
    return {"n": len(rows), "stack": st.mean(r[1] for r in rows), "gl": st.mean(r[2] for r in rows),
            "wins": sum(r[1] > r[2] for r in rows), "ties": sum(r[1] == r[2] for r in rows),
            "lost": [r[0] for r in rows if r[1] < r[2]]}


def _dir_name(d):
    a, b = d.split("-")
    return f"{LANG_NAMES.get(a, a)} → {LANG_NAMES.get(b, b)}"


def sept_lang_rows(D):
    """One row per stack language: what serves it and what September measured."""
    der, table, hy = D["derived"], D["table"], D["hymt_langs"]
    r4 = der["sept_text"]
    asr300 = D["asr300"]["sets"]
    r8a, r8m, r8n = D["r8asr"], D["r8mt"], D["r8nat"]
    clar_doc = sept_doc_clarity(D)
    nat = {}
    for x in D["nat"]:
        nat.setdefault(x["lang"], {"voxcpm": [], "current": []})
        nat[x["lang"]]["voxcpm"].append(x["voxcpm"])
        nat[x["lang"]]["current"].append(x["current"])
    rows = []
    for code in SEPT_ORDER:
        t = table[code]
        omni = t.get("asr", "whisper").startswith("omni")
        np_voices = [(n, v) for n, v, _ in D["editions"]["nonprofit"][code]["voices"] if n != "espeak"]
        cm = D["editions"]["commercial"][code]
        cm_voices = [(n, v) for n, v, _ in cm["voices"] if n != "espeak"]
        np_lic = {n: li for n, v, li in D["editions"]["nonprofit"][code]["voices"]}
        r = {"code": code, "name": LANG_NAMES[code], "hears": "Omnilingual 300M" if omni else "Whisper large-v3",
             "to_tr": "MADLAD-400 7B" if t.get("translator") == "madlad" else "Hy-MT2 7B",
             "from_tr": "Hy-MT2 7B" if code in hy else "MADLAD-400 7B",
             "voice": voice_label(*np_voices[0]) if np_voices else "eSpeak NG only",
             "voice_nc": bool(np_voices) and np_lic[np_voices[0][0]].cls == "noncommercial",
             "voice_more": [voice_label(n, v) for n, v in np_voices[1:]],
             "commercial": (voice_label(*cm_voices[0]) if cm_voices else
                            ("eSpeak NG only" if cm["voices"] else "text only")),
             "cer": None, "cer_alt": None, "cer_src": "", "to": None, "from": None, "mt_src": "",
             "nat": None, "clar": None, "voice_src": "", "round": ""}
        if code == "en":
            r["round"] = "source and target"
        elif code in SEPT_ROUND1 and code != "lo":
            r["round"] = "round 1 (26–27 Sept)"
            to_sys = "madlad7b" if t.get("translator") == "madlad" else "hymt7b"
            from_sys = "hymt7b" if code in hy else "madlad7b"
            r["to"] = _pts(r4[f"en-{code}"][to_sys])
            r["from"] = _pts(r4[f"{code}-en"][from_sys]) if f"{code}-en" in r4 else None
            r["mt_src"] = "typed text, round 4" + ("; uk→en excluded (bad source set)" if code == "uk" else "")
        elif code == "lo":
            r["round"] = "round 1 (26–27 Sept)"
            lao = D["r6lao"]
            r["to"] = lao["en-lo"]["madlad7b"][0] / 72
            r["from"] = lao["lo-en"]["madlad7b"][0] / 72
            r["mt_src"] = "typed text, round 6"
        elif code in SEPT_ROUND8:
            r["round"] = "round 8 (28 Sept)"
            r["to"] = r8m[f"en-{code}"]["pct"] / 100
            r["from"] = r8m[f"{code}-en"]["pct"] / 100
            r["mt_src"] = "typed text, round 8"
        else:
            r["round"] = "29 Sept"
        # recognition
        if code in r8a["fleurs"]:
            f = r8a["fleurs"][code]
            r["cer"], r["cer_alt"] = (f["omni"], f["whisper"]) if omni else (f["whisper"], f["omni"])
            r["cer_src"] = f"FLEURS, {f['n']} real clips"
        elif code in ("km", "lo", "ht"):
            sets = {k.split("/")[1]: v["cer"] for k, v in asr300.items() if k.startswith(code + "/")}
            r["cer_syn"] = sets
            r["cer_src"] = "synthetic voices (" + ", ".join(f"{voice_label(k, '')}: {pct(v)}" for k, v in sets.items()) + ")"
        elif code == "ro":
            cite(D, "sept_doc", "**7.7% WER** (2.1% CER)")
            r["cer"], r["cer_src"] = 0.021, "FLEURS, 25 real clips (document §3.4c)"
        # voice
        if np_voices:
            n, v = np_voices[0]
            if code in SEPT_ROUND8:
                k = voice_key(n, v)
                r["nat"] = r8n.get(code, {}).get(k)
                c = r8a["clarity"].get(f"{k}/{code}", {})
                r["clar"] = c.get("omni" if omni else "whisper")
                r["voice_src"] = "round 8 files"
            elif code in nat:
                which = "voxcpm" if n == "voxcpm" else "current"
                r["nat"] = st.mean(nat[code][which])
                r["voice_src"] = "naturalness: voice_naturalness.json"
            if code in ("km", "lo", "ht"):
                key = {"voxcpm": "voxcpm", "mms": "mms"}.get(n)
                r["clar"] = asr300.get(f"{code}/{key}", {}).get("cer")
                r["voice_src"] += ("; " if r["voice_src"] else "") + "clarity: Omnilingual round trip"
            elif code in clar_doc and r["clar"] is None:
                eng = {"kokoro": "kokoro", "piper": "piper", "voxcpm": None}.get(n)
                r["clar"] = clar_doc[code]["current"].get(eng) if eng else clar_doc[code]["voxcpm"]
                if r["clar"] is not None:
                    r["voice_src"] += ("; " if r["voice_src"] else "") + "clarity: document §3.4"
            if code == "ro":
                cite(D, "sept_doc", "8.3% WER / 1.9% CER")
                r["clar"], r["voice_src"] = 0.019, "clarity: document §3.4c"
        rows.append(r)
    return rows


def build_languages(D):
    der = D["derived"]
    doc = src_link("docs/dev/model-evaluation.md", "model-evaluation.md")
    E = sept_e2e_summary(D)
    for n in ("| Score | **83%** | 76% |", "| Directions won | **16 of 19** |", "recomputed over all 19 directions",
              "**~0.8 s after the speaker stops**", "~2.8 s after the speaker *starts*; speaks mid-sentence"):
        cite(D, "sept_doc", n)
    gl = L("sept:gemini-live")
    # ---- end to end, per direction
    e2e = der["sept_e2e"]
    groups, wins = [], 0
    for d, s in e2e.items():
        a, b = _pts(s["stack_new"]), _pts(s["gemini_live"])
        wins += a > b
        groups.append((d.replace("-", "→"), [a, b], False))
    m_stack = st.mean(g[1][0] for g in groups)
    m_gl = st.mean(g[1][1] for g in groups)
    e2e_chart = grouped("End to end, per direction: the stack against " + gl,
                        "Same synthetic audio for both; the stack's own recognition through the real server; one blind grading round. Share of 0–3 points per sentence, higher is better.",
                        groups, [(L("sept:stack"), "c3"), (gl, "c1")], maxv=1, vendor_named=True,
                        note=f"Method: averaged over all {len(groups)} directions in round 3's results file (24 sentences each, 0–3 points per sentence; a direction scores its points over 72, the headline is the plain mean of the direction scores): {pct(m_stack, 0)} against {pct(m_gl, 0)}, the stack ahead in {wins}.")
    # ---- translation per language
    rows = sept_lang_rows(D)
    tgroups = [(f'{r["name"]}', [r["to"], r["from"]], False) for r in rows if r["to"] is not None]
    tr_chart = grouped("Translation by language, typed text (September)",
                       "The stack's translator for each direction: Hy-MT2 where it has the language, else MADLAD-400 7B. Higher is better.",
                       tgroups, [("English → language", "c2"), ("Language → English", "c4")], maxv=1,
                       note="Ukrainian → English is missing: its source sentences came back in broken English and were excluded. Lao from round 6; the round-8 languages from round 8; the rest from round 4.")
    # ---- recognition, FLEURS
    fl = D["r8asr"]["fleurs"]
    rgroups = [(LANG_NAMES[c], [fl[c]["whisper"], fl[c]["omni"]], D["table"][c]["asr"].startswith("omni")) for c in fl]
    rgroups.append(("Romanian", [0.021, None], False))
    rec_chart = grouped("Recognition on real speech (FLEURS), September",
                        "Character error rate, 25 clips per language. Lower is better. Bold: the stack hears this language with Omnilingual.",
                        rgroups, [("Whisper large-v3", "c2"), ("Omnilingual 300M", "c3")], maxv=0.4,
                        note="Romanian is from the document (§3.4c, Whisper only). Japanese, Khmer, Lao, French, English and Haitian Creole on real speech are on the <a href=\"findings.html#hearing\">Findings</a> page (October).")
    # ---- voices
    vrows = [{"label": f'{r["name"]}: {r["voice"]}', "value": r["nat"], "cls": "c3"} for r in rows if r["nat"] is not None]
    vrows.sort(key=lambda x: -x["value"])
    voice_chart = hbar("Voice naturalness, the voice each language uses (1–5)",
                       f"Blind A/B by {L('grader-old')}, 4–8 sentences per language. Higher is better.",
                       vrows, fmt=lambda v: f"{v:.1f}", maxv=5, legend=[("Open weights", "c3")], vendor_named=False,
                       note="Each mean is over that language's blind comparisons; different pairings per language, so compare with care.")
    # ---- the big table
    def cer_cell(r):
        if r["cer"] is not None:
            s = pct(r["cer"])
            if r["cer_alt"] is not None:
                s += f' (other: {pct(r["cer_alt"])})'
            return s + f' · {r["cer_src"]}'
        return r["cer_src"] or "not measured in September"

    head = ["Language", "Hears", "Recognition error (CER)", "Translates (to / from English)", "en→ / →en",
            "Voice (non-profit)", "Naturalness", "Clarity", "Commercial edition voice"]
    body = ""
    for r in rows:
        mt = f'{pct(r["to"], 0)} / {pct(r["from"], 0) if r["from"] is not None else "–"}' if r["to"] is not None else "–"
        tr = r["to_tr"] if r["to_tr"] == r["from_tr"] else f'{r["to_tr"]} / {r["from_tr"]}'
        voice = esc(r["voice"]) + (' <small>(non-commercial)</small>' if r["voice_nc"] else "")
        if r["voice_more"]:
            voice += f' <small>then {esc(", ".join(r["voice_more"]))}</small>'
        com = r["commercial"]
        comc = f"<strong>{esc(com)}</strong>" if com in ("eSpeak NG only", "text only") else esc(com)
        body += (f'<tr><th scope="row">{esc(r["name"])} <small>({r["code"]})</small><br><small>{esc(r["round"])}</small></th>'
                 f'<td>{esc(r["hears"])}</td><td>{esc(cer_cell(r))}</td><td>{esc(tr)}</td><td class="num">{esc(mt)}</td>'
                 f'<td>{voice}</td><td class="num">{f"{r["nat"]:.1f}" if r["nat"] is not None else "–"}</td>'
                 f'<td class="num">{pct(r["clar"]) if r["clar"] is not None else "–"}</td><td>{comc}</td></tr>')
    big = (f'<div class="table-wrap"><table class="wide langs"><thead><tr>'
           + "".join(f'<th scope="col">{esc(h)}</th>' for h in head) + f"</tr></thead><tbody>{body}</tbody></table></div>")
    eo = [r["name"] for r in rows if r["commercial"] == "eSpeak NG only"]
    to_only = [r["name"] for r in rows if r["commercial"] == "text only"]
    nc = [r["name"] for r in rows if r["voice_nc"]]
    vox = D["voxspeed"]["T10/km"]
    cite(D, "sept_doc", "Khmer's voice starts ~0.1 s after its text instead of 1.5 s")
    body_html = f"""<div class="prose">
<h1>Languages, September 2026</h1>
<p class="lede">How well the open stack hears, translates and speaks each of its {len(rows)} languages, from the model evaluation of 26–29 September 2026: the first eleven languages, twelve more in round 8, then Romanian. Per language: what serves it, what we measured, and whether the commercial edition can still give it a voice.</p>
<p class="caveat">September numbers are not comparable with the October pages. September used a synthetic test set of 24 short sentences built to catch critical errors, mostly synthetic speech, and {L('grader-old')} as the blind grader; October used real speakers, longer news sentences and {L('grader')}. Compare numbers inside one chart only. Source: {doc}.</p>
</div>
<section class="stats" aria-label="End to end, September">
<div class="stat"><div class="n">{pct(E["stack"], 0)} vs {pct(E["gl"], 0)}</div><div class="t">end-to-end translation score: the open stack against {esc(gl)}, same audio, graded blind, mean over all {E["n"]} directions</div></div>
<div class="stat"><div class="n">{E["wins"]} of {E["n"]}</div><div class="t">directions won by the stack ({esc(gl)} won {esc(", ".join(_dir_name(d) for d in E["lost"]))}{"" if E["ties"] else "; no ties"})</div></div>
<div class="stat"><div class="n">~0.8 s</div><div class="t">to first translated audio after the speaker <strong>stops</strong> (stack), against ~2.8 s after the speaker <strong>starts</strong> for {esc(gl)}, which speaks mid-sentence</div></div>
</section>
<div class="prose">
<h2 id="e2e">End to end: the stack against {esc(gl)}</h2>
<p>The real server, with its own recognition, translation and voices, heard the same synthetic recordings as {esc(gl)}; every output was graded blind. The losses on {esc(gl)}'s side were mostly mishearings — “chicken” heard as “children”, “a quarter to twelve” as 5:15 — not mistranslations. The two speaker-to-English directions for Khmer and Haitian Creole were poor for both. Headline figures from {doc} §3.1; the chart is the per-direction grades.</p>
</div>
{e2e_chart}
<div class="prose">
<h2 id="table">Every language</h2>
<p>Recognition error is the character error rate of the recogniser the stack uses for that language (the other recogniser in brackets where both were tried). Translation is the stack's translator on typed text, graded 0–3 per sentence by {L('grader-old')}. Naturalness is 1–5 from a blind A/B; clarity is the round-trip error when a recogniser transcribes the voice (lower is clearer). Voices are the first in each language's chain; a dash means not measured.</p>
</div>
{big}
<div class="prose">
<ul>
<li><strong>Commercial edition:</strong> recognition and translation are the same; only voices change. {"No language is text only. " if not to_only else "Text only: " + esc(", ".join(to_only)) + ". "}{esc(" and ".join(eo))} fall back to the robotic eSpeak NG voice because their only good voices have unclear licences. Non-commercial voices in the non-profit edition: {esc(", ".join(nc))}. See <a href="models.html">Models &amp; licences</a>.</li>
<li><strong>Swahili is the weakest translation</strong> ({pct(D['r8mt']['en-sw']['pct'] / 100, 0)} / {pct(D['r8mt']['sw-en']['pct'] / 100, 0)}): MADLAD gets times and days wrong (Swahili clocks count from 6 am).</li>
<li><strong>Omnilingual hears Bengali, Hindi, Persian, Urdu and Swahili better than Whisper</strong> (Bengali {pct(fl['bn']['omni'])} vs {pct(fl['bn']['whisper'])}); Whisper is better for Tagalog.</li>
<li><strong>Khmer, Lao and Haitian Creole recognition was measured on synthetic voices only in September</strong>; their real-speaker results are on the <a href="findings.html#hearing">Findings</a> page.</li>
<li><strong>VoxCPM2</strong> speaks Khmer, Lao and Tagalog (and, in the commercial edition, the languages whose Piper voices are not licence-clean). Streamed, its first audio comes about {vox['first_chunk_ms_median']} ms after it starts (median, Khmer); in the full stack Khmer's voice now starts ~0.1 s after its text instead of 1.5 s.</li>
</ul>
</div>
{tr_chart}
{rec_chart}
{voice_chart}
<div class="prose">
<h2>Sources</h2>
<ul>
<li>Write-up: {doc} (§3.1 end to end, §3.2 translation, §3.4 voices, §3.4b twelve more languages, §3.4c Romanian).</li>
<li>Grades and measurements: {src_link('eval/2026-09-model-eval/results')}. The per-direction end-to-end and round-4 scores are summed from that folder's per-sentence grades by <code>site/extract_derived.py</code>.</li>
<li>Which model serves each language and which voices each edition loads: {src_link('languages.toml')}, read through <code>server/stack_config.py</code>.</li>
</ul>
</div>"""
    page("languages.html", "Languages", body_html,
         "Per-language recognition, translation and voice results for the open stack's 25 languages, September 2026.")
    return {"wins": wins}


def _lat_rows_generic(data):
    """Rows of an eval/2026-10-latency/results.json, whatever its exact shape."""
    if isinstance(data, list):
        return data
    for k in ("routes", "results", "rows", "runs"):
        if isinstance(data.get(k), list):
            return data[k]
    return []


def latency_results_section(D):
    data = D["latency"]
    head = '<h2 id="routes">End-to-end comparison of current routes</h2>'
    if data is None:
        return (f'{head}<div class="placeholder" role="note"><p><strong>In progress.</strong> '
                f'A test of the current routes end to end, measured the same way for each, is running. '
                f'Its results will appear here when <code>eval/2026-10-latency/results.json</code> is committed; '
                f'the site renders that file automatically.</p></div>')
    meta = ""
    if isinstance(data, dict):
        for k in ("date", "what", "measures", "audio", "method", "note"):
            if isinstance(data.get(k), str):
                meta += f"<li><strong>{esc(k.capitalize())}:</strong> {esc(anon_text(data[k]))}</li>"
    rows = [r for r in _lat_rows_generic(data) if isinstance(r, dict)]
    if not rows:
        return head + (f"<ul>{meta}</ul>" if meta else "") + f'<p class="note">{src_link(INPUTS["latency"])} has no rows yet.</p>'
    cols = []
    for r in rows:
        for k, v in r.items():
            if k not in cols and not isinstance(v, (dict, list)):
                cols.append(k)
    name_key = next((k for k in ("route", "name", "label", "system") if k in cols), cols[0])
    cols = [name_key] + [c for c in cols if c != name_key]
    trows = [[anon_text(r.get(c, "")) if isinstance(r.get(c), str) else ("–" if r.get(c) is None else r.get(c)) for c in cols] for r in rows]
    chart = ""
    num = next((c for c in cols if c != name_key and all(isinstance(r.get(c), (int, float)) or r.get(c) is None for r in rows)
                and ("ms" in c or c.endswith("_s"))), None)
    if num:
        scale = 1000 if "ms" in num else 1
        bars = [{"label": anon_text(r.get(name_key, "")), "value": (r[num] / scale) if r.get(num) is not None else None,
                 "cls": "c1"} for r in rows]
        chart = hbar(f"Current routes: {num}", "Seconds; lower is better. From " + esc(INPUTS["latency"]) + ".", bars,
                     fmt=lambda v: f"{v:.2f} s", vendor_named=True, table_headers=cols, table_rows=trows)
    return head + (f'<div class="prose"><ul>{meta}</ul></div>' if meta else "") + (chart or _table(cols, trows, numeric_from=1))


def azg(rel="eval/2026-10-azure-stt-gemini", text=None, link=True):
    """The cloud-routes eval folder: its path names two vendors, so an anonymised build does not show it."""
    if ANON:
        return "the cloud-routes eval folder (17 October)" if link else "cloud-routes eval (17 Oct)"
    return src_link(rel, text) if link else rel


def build_latency(D, S1):
    oct_doc = src_link("docs/dev/route-findings-2026-10.md", "route-findings-2026-10.md")
    sept_doc = src_link("docs/dev/model-evaluation.md", "model-evaluation.md")
    gl = L("sept:gemini-live")
    az, gem, gla = VN("microsoft", "Azure", "recogniser"), VN("google", "Gemini Live", "voice model"), VN("gladia", "Gladia", "recogniser")
    cite(D, "oct_doc", "The delay is about 1.3 s after each sentence ends.")
    cite(D, "azg_readme", "Azure's final ~0.8 s, Gemini's first audio ~0.5 s after that")
    cite(D, "oct_doc", "(first audio 0.67 s against 0.95 s)")
    cite(D, "omni_readme", "~0.10-0.12 s at the server for either voice, ~0.14-0.18 s at a client in the US over an open socket")
    cite(D, "oct_doc", "~1.1 s GPU (Khmer 5–8 s)")
    cite(D, "omni_readme", "**One instance** (`--max-instances 1`), up to 4 streams")

    # ---- live recognisers
    live = {(r["system"], r["lang"], r["mode"]): r for r in D["live"]["runs"]}
    runs = {(r["system"], r["lang"]): r for r in D["bakeoff"]["runs"]}
    langs = ["en", "ja", "km", "lo"]
    code = {"en": "en-US", "ja": "ja-JP", "km": "km-KH", "lo": "lo-LA"}
    recs = []
    recs.append((L("azure-speech"), [live[("azure-speech", l, code[l])]["sentence_latency_ms_median"] / 1000 for l in langs], True))
    recs.append((L("gemini-3.5-transcribe-live"),
                 [(live.get(("gemini-3.5-transcribe-live", l, code[l])) or live[("gemini-3.5-transcribe-live", l, "auto")])["sentence_latency_ms_median"] / 1000 for l in langs], False))
    for s in ("oai-live", "aai-stream", "el-realtime-vad05", "el-realtime"):
        vals = []
        for l in langs:
            r = runs.get((s, l))
            v = r.get("sentence_latency_ms_median") if r else None
            vals.append(v / 1000 if v else None)
        recs.append((L(s), vals, False))
    rec_chart = grouped("Live recognisers: time from the end of a sentence to its final transcript",
                        "Median seconds, 30 FLEURS sentences per language streamed at real-time pace (real speakers). Lower is better.",
                        recs, [("English", "c1"), ("Japanese", "c2"), ("Khmer", "c3"), ("Lao", "c4")],
                        fmt=lambda v: f"{v:.1f} s", maxv=None, vendor_named=True,
                        note="Measured at the client in the US, 18–19 October 2026. n/a = the service did not return the language. Recognition only: no translation or voice.")
    # ---- cloud pipelines (synthetic audio)
    oc = D["derived"]["oct_cloud"]
    pg = []
    az_only = []
    for d, s in oc.items():
        vals = []
        for k in ("azure_only", "azure_stt_gemini", "gladia_stt_gemini"):
            x = s.get(k) or {}
            v = x.get("delay_ms_median")
            # left out: a run that returned (almost) nothing, and Azure-only Haitian Creole (captions, no voice)
            if not x.get("score_pct") or (k == "azure_only" and d == "en-ht"):
                v = None
            vals.append(v / 1000 if v else None)
            if k == "azure_only" and v:
                az_only.append(v / 1000)
        if any(v for v in vals):
            pg.append((d.replace("-", "→"), vals, False))
    pipe_chart = grouped("Cloud routes: end of sentence to start of translated audio",
                         "Median seconds over 24 synthetic sentences per direction, 17 October 2026. Lower is better.",
                         pg, [(L("azg:azure_only"), "c1"), (f"{az} → {gem}", "c2"), (f"{gla} → {gem}", "c4")],
                         fmt=lambda v: f"{v:.2f} s", vendor_named=True,
                         note=f"End to end: recognition, translation and the first audio of the voice. {gl} has no comparable figure: it speaks mid-sentence. n/a: the route could not run that direction (quota, no Haitian Creole recogniser), returned almost nothing ({gla}, Khmer), or had no voice ({L('azg:azure_only')}, Haitian Creole: captions only).")
    # ---- translators
    trow = []
    for s in SYS1:
        trow.append({"label": L(s), "value": S1[s]["latency"], "cls": kind_cls(s),
                     "extra": "GPU time, RTX 6000 Ada" if not is_cloud(s) else "round trip from the US"})
    r2 = D["shoot2"]["latency"]
    for s in ("gpt-oss-20b@low", "gpt-oss-120b@low", "gpt-oss-120b@medium", "qwen3.8-27b-fp8@low"):
        trow.append({"label": L(s), "value": r2[s]["single_stream"]["median_s"], "cls": "c3",
                     "extra": "H100, vLLM, one request at a time"})
    trow.sort(key=lambda r: r["value"])
    tr_chart = hbar("Translators: time per sentence (October)",
                    "Median seconds to translate one sentence. Lower is better.", trow,
                    fmt=lambda v: f"{v:.2f} s", legend=KIND_LEGEND, vendor_named=True,
                    note="Translation only. Open models: model time on the GPU, one sentence at a time (round 1: RTX 6000 Ada 48 GB; round 2: H100 80 GB). Cloud: request round trip from a client in the US. Hy-MT2's median hides Khmer at 5–8 s.")
    # ---- endpointing
    sw = D["sizes"]["endpointing_sweep"]
    lev = next(r for r in sw["runs"] if "levelled" in r["run"] and "300M" in r["card"])
    settings = [(300, 6.0), (300, 15.0), (500, 15.0), (700, 15.0), (800, 25.0)]

    def cell(lang, e, m):
        return next(r for r in lev["rows"] if r["lang"] == lang and r["endpoint_ms"] == e and r["max_s"] == m)
    lab = [f"{e / 1000:g} s : {m:g} s" + (" (old)" if (e, m) == (300, 6.0) else " (now)" if (e, m) == (700, 15.0) else "") for e, m in settings]
    eg = [(x, [cell("ht", e, m)["seg_wait_ms_median"] / 1000, cell("ht", e, m)["sent_wait_ms_median"] / 1000], (e, m) == (700, 15.0))
          for x, (e, m) in zip(lab, settings)]
    ep_chart = grouped("Sentence cutting: how long the recogniser waits, and what it buys",
                       "Omnilingual 300M through omni-stt's own segmenter, Haitian Creole real-voice clip (levelled). Median seconds of audio time; lower is quicker.",
                       eg, [("Wait after the pause starts (turn end)", "c1"), ("Per sentence: end of speech to its first text", "c2")],
                       fmt=lambda v: f"{v:.2f} s", vendor_named=False,
                       note="Audio time from the segmenter, not wall-clock: excludes network and the GPU decode (p90 decode per segment in the table).")
    ep_tbl = _table(["Pause : longest", "Turn-end wait", "Per-sentence wait, median", "Per-sentence wait, p90", "GPU decode p90 / segment", "CER ht", "CER lo"],
                    [[x, f'{cell("ht", e, m)["seg_wait_ms_median"]} ms', f'{cell("ht", e, m)["sent_wait_ms_median"]} ms',
                      f'{cell("ht", e, m)["sent_wait_ms_p90"] / 1000:.1f} s', f'{cell("ht", e, m)["decode_s_p90"]:.2f} s',
                      pct(cell("ht", e, m)["cer"]), pct(cell("lo", e, m)["cer"])] for x, (e, m) in zip(lab, settings)])
    # ---- voices
    htv = []
    for line in D["text"]["htv_readme"].splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) == 5 and c[0] not in ("Voice", "---") and not c[0].startswith("-"):
            htv.append((c[0].replace("**", ""), c[1], c[4]))
    vmap = {"Gemini 3.8 Flash TTS": ("v:gemini-flash", "network, streamed"), "Gemini 3.8 Flash Lite TTS": ("v:gemini-lite", "network"),
            "gpt-4o-mini-tts, coral": ("v:oai-coral", "network"), "gpt-4o-mini-tts, coral + accent instruction": ("v:oai-coral-instr", "network"),
            "gpt-4o-mini-tts, sage + accent instruction": ("v:oai-sage-instr", "network")}
    vt = []
    for name, where, first in htv:
        base = re.sub(r"\s*\(voice \w+\)", "", name)
        key = vmap.get(base, (None, ""))[0]
        if key:
            lbl, how = L(key), "request sent → first audio at the client (US)"
        elif base.startswith("Meta MMS"):
            lbl, how = "Meta MMS-TTS", "whole sentence synthesised on CPU, then sent"
        elif base.startswith("Coqui"):
            lbl, how = "Coqui VITS OpenBible", "whole sentence synthesised on CPU, then sent"
        else:
            continue
        if first in ("—", ""):
            continue
        vt.append([lbl, first, how, "voice only", "eval/2026-10-ht-voices"])
    vt.append(["Meta MMS-TTS / Coqui on omni-stt (L4)", "~0.10–0.12 s at the server; ~0.14–0.18 s at a client", "request → first audio, one sentence, warm, open socket", "voice only", "services/omni-stt/README.md"])
    vx = D["voxspeed"]
    vt.append(["VoxCPM2, streamed (10 steps)", f'{vx["T10/km"]["first_chunk_ms_median"]} ms (Khmer), {vx["T10/lo"]["first_chunk_ms_median"]} ms (Lao) median',
               "start of generation → first audio chunk", "voice only (GPU)", "eval/2026-09-model-eval (voxcpm_speed.json)"])
    vt.append(["VoxCPM2 in the full stack (Khmer)", "~0.1 s after its text (was 1.5 s before streaming)", "translated text ready → voice starts", "voice, in the full stack", "model-evaluation.md §3.4"])
    voice_tbl = _table(["Voice", "First audio", "Measured from → to", "Scope", "Source"], vt, numeric_from=99)
    # ---- omni-stt under load
    sizes = {r["card"]: r for r in D["sizes"]["runs"]}
    ld = [["omni-stt on one L4, before batching", "up to 4 streams per instance", "configured limit (README)", "services/omni-stt/README.md"],
          ["omni-stt on one L4, with batching", "~4 → 8–10 fully transcribed streams, same CER", "measured, PR #18", PR18],
          ["Omnilingual LLM 300M, one stream", f'real-time factor {lev["rtf_batch1"]:.2f}', "GPU decode time ÷ audio time, MIG 1g.24gb slice (an L4-class quarter of an RTX PRO 6000)", "eval/2026-10-omni-sizes"],
          ["Omnilingual LLM 300M / 7B, batch 1", f'real-time factor {sizes["omniASR_LLM_300M"]["rtf_batch1"]:.3f} / {sizes["omniASR_LLM_7B"]["rtf_batch1"]:.3f}', "GPU decode only, H200", "eval/2026-10-omni-sizes"]]
    load_tbl = _table(["What", "Result", "What it measures", "Source"], ld, numeric_from=99)
    # ---- summary
    e = cell("ht", 700, 15.0)
    sol = S1["foundry-gpt-5.6-sol@low"]["latency"]
    summary = [
        ["Open stack, end to end (Sept)", "~0.8 s", "speaker stops → first translated audio", "end to end", "synthetic", "model-evaluation.md §3.1"],
        [f"{gl}, end to end (Sept)", "~2.8 s", "speaker <em>starts</em> → first translated audio (it talks mid-sentence)", "end to end", "synthetic", "model-evaluation.md §3.1"],
        [f"{az} STT → {gem} (Oct)", "~1.3 s", "sentence ends → translated audio starts", "end to end", "synthetic", "route-findings §3; " + azg(link=False)],
        [L("azg:azure_only") + " (Oct)", f"{min(az_only):.1f}–{max(az_only):.1f} s", "sentence ends → translated text + voice starts", "end to end", "synthetic", azg(link=False)],
        [L("azure-speech") + ", English", f'{live[("azure-speech", "en", "en-US")]["sentence_latency_ms_median"] / 1000:.1f} s', "sentence ends → final transcript", "recognition only", "real (FLEURS)", "eval/2026-10-real-voices"],
        ["Omnilingual, sentence cutting now (0.7 s : 15 s)", f'{e["seg_wait_ms_median"]} ms / {e["sent_wait_ms_median"]} ms', "pause starts → turn ends / sentence speech ends → first text (audio time)", "segmenter only", "real", "eval/2026-10-omni-sizes"],
        [L("foundry-gpt-5.6-sol@low"), f"{sol:.1f} s", "request → translation (round trip)", "translation only", "text", "eval/2026-10-translator-shootout"],
        ["Hy-MT2 7B, 4-bit", f'{S1["hymt2-7b-nf4"]["latency"]:.1f} s', "sentence in → translation, GPU time", "translation only (GPU)", "text", "eval/2026-10-translator-shootout"],
        [L("v:gemini-flash"), "~0.7–0.95 s", "request → first audio", "voice only", "–", "eval/2026-10-ht-voices"],
    ]
    sum_tbl = ('<div class="table-wrap"><table class="wide"><thead><tr>' + "".join(
        f'<th scope="col">{h}</th>' for h in ("What", "Time", "Measured from → to", "Scope", "Audio", "Source")) + "</tr></thead><tbody>" + "".join(
        f'<tr><th scope="row">{esc(r[0])}</th><td class="num">{esc(r[1])}</td><td>{r[2]}</td><td>{esc(r[3])}</td><td>{esc(r[4])}</td><td><small>{esc(r[5])}</small></td></tr>'
        for r in summary) + "</tbody></table></div>")
    body = f"""<div class="prose">
<h1>Latency</h1>
<p class="lede">Every delay we have measured, with exactly what each one measures. A delay counted from when the speaker <em>stops</em> is not the same as one counted from when they <em>start</em>; GPU time for one stage is not the same as end to end; synthetic speech is not the same as real speakers. Numbers from different rows are not interchangeable.</p>
<p class="caveat">Measured September–October 2026; cloud timings are from a client in the US and change with load and region. Where a figure is quoted from a write-up rather than a result file, the source says so.</p>
</div>
<h2 id="summary">At a glance</h2>
{sum_tbl}
<div class="prose">
<h2 id="e2e">End to end</h2>
<p>In September the open stack's first translated audio came about <strong>0.8 s after the speaker stopped</strong>; {esc(gl)} started talking about <strong>2.8 s after the speaker started</strong>, mid-sentence, before it had heard the end ({sept_doc} §3.1, synthetic audio, real server). In October, {esc(az)}'s live recogniser feeding {esc(gem)} took about <strong>1.3 s after each sentence ended</strong>: {esc(az)}'s final transcript about 0.8 s, then the voice's first audio about 0.5 s later ({oct_doc} §3; {azg('eval/2026-10-azure-stt-gemini/README.md', 'README')}).</p>
</div>
{pipe_chart}
<div class="prose"><h2 id="recognition">Recognition</h2>
<p>How long a live recogniser takes to settle each sentence once it has been spoken. A long default pause (one service waits 1.5 s of silence) shows up directly here.</p></div>
{rec_chart}
<div class="prose"><h2 id="endpointing">Sentence cutting: wait against accuracy</h2>
<p>The open recogniser decides a sentence has ended after a pause. Waiting longer cuts fewer sentences in half — Haitian Creole's error fell from {pct(cell('ht', 300, 6.0)['cer'])} to {pct(e['cer'])} and Lao's from {pct(cell('lo', 300, 6.0)['cer'])} to {pct(cell('lo', 700, 15.0)['cer'])} — for about 0.4 s more at each turn end, and up to 15 s before any text when a speaker never pauses.</p></div>
{ep_chart}
<details class="data"><summary>Waits, decode time and error per setting</summary>{ep_tbl}<p class="note">GPU: {esc(sw['gpu'])}. Per-sentence p90 is long because a sentence that never pauses waits for the forced cut.</p></details>
<div class="prose"><h2 id="translation">Translation</h2></div>
{tr_chart}
<div class="prose"><h2 id="voices">Voices: time to first audio</h2>
<p>A streamed voice starts as soon as its first chunk exists; one that synthesises the whole sentence first adds the full synthesis time. Haitian Creole samples: full {esc(L('v:gemini-flash'))} took about 0.95 s to first audio against 0.67 s for the Lite model ({oct_doc} §12), and was kept because it sounds more Haitian.</p></div>
{voice_tbl}
<div class="prose"><h2 id="load">omni-stt under load</h2>
<p>Batching decodes the waiting utterances of every connection in one GPU call, with prompts left-padded so they finish together (<a href="{PR18}">PR #18</a>).</p></div>
{load_tbl}
{latency_results_section(D)}
<div class="prose">
<h2>Sources</h2>
<ul>
<li>{sept_doc}, {oct_doc}, {src_link('eval/2026-10-ht-voices/README.md')}, {src_link('services/omni-stt/README.md')}, <a href="{PR18}">PR #18</a>.</li>
<li>Result files: {src_link('eval/2026-10-real-voices')}, {src_link('eval/2026-10-translator-shootout')}, {src_link('eval/2026-10-omni-sizes/results.json')}, {azg('eval/2026-10-azure-stt-gemini/results.json')} (delays copied by <code>site/extract_derived.py</code>), {src_link('eval/2026-09-model-eval/results/voxcpm_speed.json')}.</li>
</ul>
</div>"""
    page("latency.html", "Latency", body, "Every latency the open stack project has measured, each labelled with exactly what it measures.")


def main():
    global ANON
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anonymise-vendors", "--anonymize-vendors", action="store_true",
                    help="replace cloud vendor and service names with Vendor A, B, ... (open-weight model names stay)")
    ap.add_argument("--out", default=OUT, help="output directory (default site/_site)")
    ap.add_argument("--list-inputs", action="store_true", help="print the repository files the build reads, and exit")
    a = ap.parse_args()
    if a.list_inputs:
        for rel in INPUTS.values():
            print(rel)
        return
    ANON = a.anonymise_vendors
    globals()["OUT"] = os.path.abspath(a.out)
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    for f in ("style.css", "voices.js"):
        shutil.copyfile(os.path.join(HERE, "src", f), os.path.join(OUT, f))
    with open(os.path.join(OUT, ".nojekyll"), "w") as f:
        f.write("")
    D = load()
    S1 = shootout1(D)
    load_more(D)
    build_home(D, S1)
    build_findings(D, S1)
    build_languages(D)
    build_latency(D, S1)
    build_voices(D)
    build_methodology(D)
    build_models(D)
    n = sum(len(fs) for _, _, fs in os.walk(OUT))
    print(f"built {n} files in {os.path.relpath(OUT, ROOT)}" + (" (vendors anonymised)" if ANON else ""))


if __name__ == "__main__":
    sys.exit(main())
