"""Haitian Creole numbers in words, for the voices (/speak).

Neither Haitian voice says digits: MMS-TTS's and Coqui OpenBible's alphabets are
letters and punctuation only, so "600 moun" comes out as "moun" (heard
2026-10-19). Translators write numbers as digits, so every text is spelled out
here before synthesis.

    words(600)                        -> "si san"
    spell_numbers("Jan 3:16, 600 moun") -> "Jan twa, sèz, si san moun"

Sources (checked 2026-10-19): languagesandnumbers.com "Counting in Haitian
Creole" (formation rules: -eyen for a one after a ten, -t of the tens becoming
-n before a unit except one, eight and nine, hundreds as "<unit> san" with the
unit's final consonant dropped -- "sen san", "si san", "ui san" --, "mil",
"yon milyon", "yon milya"), Wikivoyage's Haitian Creole phrasebook ("de mil",
"senk mil") and Valdman's Haitian Creole-English Bilingual Dictionary for the
70s-90s (swasanndis, swasanteyonz, katreven, katrevenen, katrevendis).

Choices where the sources differ or say nothing (one spelling had to be picked;
the voices read the alternatives alike):
- 1 is "en" (the counting form) alone and in compounds; "youn" is also used.
  "1 milyon" is "yon milyon" (the article), as the sources give it.
- 60 is "swasant" (Valdman, Wikipedia); one source writes "swasann".
- Hundreds are spaced ("de san"; the request's example "sisan" is the same
  sound as "si san"). The unit's last consonant drops before "san", "mil",
  "milyon" and "milya" as it does in speech: sen san, si mil, ui san, di mil.
  Years are read as cardinals: 1804 -> "mil ui san kat", 2026 -> "de mil vennsis".
- Ordinals: 1e/1ye/1er -> "premye"; otherwise the cardinal + "yèm", with the
  stems dezyèm, twazyèm, katriyèm, sizyèm, setyèm, nevyèm, dizyèm, ventyèm, santyèm.
- A decimal is "<whole> pwen <part>" (part read as a number up to two digits,
  else digit by digit); "3,500" (comma, three digits) is three thousand five
  hundred, as is "3 500" (a space before exactly three digits); "3,5" is three
  point five.
- "%" -> "pousan", "$" -> "dola" (after the number). A colon between numbers
  ("Jan 3:16", "10:30") becomes a pause; ":00" is dropped.
- Over 999 999 999 999, or with a leading zero ("0612..."), digit by digit.
"""
import re

UNITS = ["zewo", "en", "de", "twa", "kat", "senk", "sis", "sèt", "uit", "nèf",
         "dis", "onz", "douz", "trèz", "katòz", "kenz", "sèz", "disèt", "dizuit", "diznèf"]
# A ten before "eyen", "uit" and "nèf" (ventuit, tranteyen) and before any other unit (vennde, trannkat).
T_STEM = {2: "vent", 3: "trant", 4: "karant", 5: "senkant", 6: "swasant"}
N_STEM = {2: "venn", 3: "trann", 4: "karann", 5: "senkann", 6: "swasann"}
TENS = {2: "ven", 3: "trant", 4: "karant", 5: "senkant", 6: "swasant"}
# The unit's final consonant is not said before san/mil/milyon/milya.
ELIDED = {"senk": "sen", "sis": "si", "uit": "ui", "dis": "di"}

LIMIT = 10 ** 12


def _below_100(n):
    if n < 20:
        return UNITS[n]
    if n < 70:
        t, u = divmod(n, 10)
        if u == 0:
            return TENS[t]
        if u == 1:
            return T_STEM[t] + "eyen"
        if u in (8, 9):
            return T_STEM[t] + UNITS[u]
        return N_STEM[t] + UNITS[u]
    if n < 80:
        return "swasanteyonz" if n == 71 else "swasann" + UNITS[n - 60]
    return "katreven" + ("" if n == 80 else UNITS[n - 80])


def _multiplier(n):
    """The count before san/mil/milyon/milya, with its last consonant dropped."""
    w = words(n)
    head, _, last = w.rpartition(" ")
    last = ELIDED.get(last, last)
    return f"{head} {last}" if head else last


def words(n):
    """0 <= n < 10**12 in Haitian Creole words."""
    n = int(n)
    if n < 0 or n >= LIMIT:
        raise ValueError(f"out of range: {n}")
    if n < 100:
        return _below_100(n)
    for size, name in ((10 ** 9, "milya"), (10 ** 6, "milyon"), (1000, "mil"), (100, "san")):
        if n >= size:
            q, r = divmod(n, size)
            if q == 1:
                head = "yon " + name if size >= 10 ** 6 else name
            else:
                head = f"{_multiplier(q)} {name}"
            return f"{head} {words(r)}" if r else head
    raise AssertionError(n)


def digits(s):
    return " ".join(UNITS[int(d)] for d in s)


# Ordinal stems: the last word of the cardinal -> what "yèm" attaches to.
ORD_STEM = {"de": "dez", "twa": "twaz", "kat": "katri", "sis": "siz", "sèt": "set",
            "nèf": "nev", "dis": "diz", "ven": "vent", "san": "sant"}


def ordinal(n):
    if n == 1:
        return "premye"
    w = words(n)
    head, _, last = w.rpartition(" ")
    for key in sorted(ORD_STEM, key=len, reverse=True):
        if last.endswith(key):
            last = last[: len(last) - len(key)] + ORD_STEM[key]
            break
    last += "yèm"
    return f"{head} {last}" if head else last


def _cardinal_text(raw):
    """A run of digits (thousands separators already removed) in words."""
    if len(raw) > 1 and raw.startswith("0"):
        return digits(raw)
    n = int(raw)
    return words(n) if n < LIMIT else digits(raw)


def _decimal_text(part):
    if len(part) <= 2 and not part.startswith("0"):
        return words(int(part))
    return digits(part)


# Grouped thousands (1,000 / 1 000, also with a no-break or thin space / 1.000.000), else a plain run, then an
# optional decimal part. Not inside a word or another number.
_GROUP = r"\d{1,3}(?:,\d{3})+(?!\d)|\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)|\d{1,3}(?:\.\d{3}){2,}(?!\d)"
_NUMBER = re.compile(
    r"(?<![\w.,])(?P<cur>\$\s?)?(?P<int>" + _GROUP + r"|\d+)(?:[.,](?P<dec>\d+)(?![.,]?\d))?"
    r"(?P<ord>yèm|yem|ème|èm|ye|er|re|e)?(?![\w])(?P<pct>\s?%)?(?P<cur2>\s?\$)?")
# 3:16, 10:30 (":00" is not said).
_COLON = re.compile(r"(?<=\d):(\d\d?)(?!\d)")


def _replace(m):
    raw = re.sub(r"[,. \u00a0\u202f]", "", m.group("int"))
    dec, ordsuf = m.group("dec"), m.group("ord")
    if ordsuf and not dec and not raw.startswith("0") and int(raw) < LIMIT:
        out = ordinal(int(raw))
    else:
        out = _cardinal_text(raw)
        if dec:
            out += " pwen " + _decimal_text(dec)
        if ordsuf:
            out += ordsuf
    if m.group("pct"):
        out += " pousan"
    if m.group("cur") or m.group("cur2"):
        out += " dola"
    return out


def spell_numbers(text):
    """Every number in `text` in Haitian Creole words; the rest unchanged."""
    if not any(ch.isdigit() for ch in text):
        return text
    text = _COLON.sub(lambda m: "" if m.group(1) == "00" else ", " + m.group(1), text)
    return _NUMBER.sub(_replace, text)
