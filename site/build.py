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
}

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

PAGES = [("index.html", "Home"), ("findings.html", "Findings"), ("voices.html", "Voices"),
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
<footer class="site"><div class="in"><span>Results measured October 2026. Code: <a href="{REPO_URL}">lithsec/translation-open-stack</a> (Apache 2.0). {anon}</span><span>by <a href="https://vortas.io">Vortas</a></span></div></footer>
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
<p class="lede">Translation Open Stack is an open-source server: a client streams microphone audio in and gets back captions and spoken translation for every language its listeners need, in 25 languages, from open-weight models on one GPU. This site publishes what we measured in October 2026 while choosing how to hear, translate and voice live speech — including where the open models fall short.</p>
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
<p class="caveat">Cloud models change often. Everything here was measured on 18–19 October 2026 with the versions named on the <a href="methodology.html">methodology</a> page; treat vendor numbers as a snapshot, not a ranking that will hold.</p>
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
    s1 = D["shoot1"]
    r2 = D["shoot2"]
    sw = D["sizes"]["endpointing_sweep"]
    deg = D["degrade"]
    body = f"""<div class="prose">
<h1>Methodology</h1>
<p class="lede">What was measured, on what audio, how it was scored, and with which exact versions. Raw outputs and scripts are in <a href="{TREE}eval">eval/</a>.</p>

<h2>Datasets (public only)</h2>
<ul>
<li><strong>FLEURS</strong> (<a href="https://huggingface.co/datasets/google/fleurs">google/fleurs</a>, CC BY 4.0): native speakers reading the same 30 FLoRes sentences in English, Japanese, Khmer, Lao and French, one recording per sentence, alternating men and women. References are FLoRes's own professional translations. Audio is downloaded at run time and not stored in the repository.</li>
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
        if v.get("piper"): voices.append(f"Piper ({v['piper']})")
        if v.get("mms"): voices.append("MMS-TTS")
        if v.get("coqui"): voices.append("Coqui OpenBible")
        com = v.get("commercial")
        comv = ""
        if isinstance(com, dict):
            cv = []
            if com.get("kokoro"): cv.append("Kokoro")
            if com.get("voxcpm"): cv.append("VoxCPM2")
            if com.get("piper"): cv.append(f"Piper ({com['piper']})")
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
    build_home(D, S1)
    build_findings(D, S1)
    build_voices(D)
    build_methodology(D)
    build_models(D)
    n = sum(len(fs) for _, _, fs in os.walk(OUT))
    print(f"built {n} files in {os.path.relpath(OUT, ROOT)}" + (" (vendors anonymised)" if ANON else ""))


if __name__ == "__main__":
    sys.exit(main())
